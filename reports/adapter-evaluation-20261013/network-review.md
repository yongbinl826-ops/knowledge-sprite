# 采集网络与动态渲染审查

日期：2026-10-13。初始阶段只读核对冻结基线，随后按主任务的明确授权修复已确认的限速、失败隔离与 robots 匹配问题。当前网络实现仍为静态 HTTP；没有启动外网浏览器，没有访问受限来源，也没有写应用 SQLite。报告中的模拟不是网络访问成功验收。

本次结论：保留现有 DNS/IP 钉住连接和逐跳保护，采用小范围原生采集器修复。当前项目没有经验证的完整浏览器出口隔离，不能安全启用按需 JavaScript 渲染。第三方抓取库的可用性或 Playwright 能启动都不能替代这一条件。

## 基线与已完成修复

基线原文件及哈希由主任务保存在 `baseline-source.zip`、`baseline-source-manifest.json`。本审查的第一组模拟核对了 fetcher、service、db、URL、config、原采集测试文件，与冻结基线全部一致。具体输入、虚拟时间、状态和请求序列见 [network-baseline-observations.json](network-baseline-observations.json)。初次模拟的 socket 守卫阻止了 Windows asyncio 自管道初始化；改为先初始化事件循环、再安装禁止 DNS/连接的守卫后才运行模拟。该次初始化失败没有发起页面请求。

| 已确认问题 | 冻结基线的具体行为 | 本轮处理 |
| --- | --- | --- |
| 无普通主机最小间隔 | 同主机 robots、页面一、页面二在同一虚拟时刻开始 | `FetcherConfig.min_interval_seconds=0.5`，每次网络尝试前执行；主任务已接入 `FETCH_MIN_INTERVAL_MS` |
| 重试忽略 robots 延迟 | Crawl-delay 5 秒时，页面在 1005.0 发起，失败后于 1005.25 重试 | 每次重试重新计算等待，修复后该例重试在 1010.0 发起；DNS 每次重新验证 |
| 同主机不同 origin 降低延迟 | HTTP robots 无延迟覆盖 HTTPS 的 5 秒，后续 HTTPS 请求无等待 | 取该主机各 origin 已知 robots 延迟与最低间隔的最大值；某 origin 只有成功刷新自己的规则后才替换旧值 |
| 503 Retry-After 未暂停 | 503 携带 120 秒后仍立即请求同主机另一页 | 与 429 共用主机暂停；不立即重试；暂停期不进行该主机 DNS/HTTP，其他主机继续 |
| 非有限 Retry-After | NaN 退化成零暂停，Infinity 成无限暂停 | 非有限、无效、负值使用有限的 60 秒缺省值；支持有效秒值与 HTTP 日期 |
| 明确拒绝后重复请求 | robots 403 在两个候选上重复请求同一 robots | HTTP 403、已识别页面验证码/拒绝、robots 明确拒绝将精确 hostname 在当前 Fetcher 实例中停止；保留触发来源证据 |
| robots 多星通配正则回溯 | 25 个星号构造规则对 50 个 a 路径匹配，本地子进程 2 秒未结束，被 timeout 终止 | 不再把规则生成正则；按 `startswith`、顺序 `find`、末尾 `endswith` 匹配字面片段 |

robots 回溯的原失败与相同输入修复后结果见 [robots-wildcard-review.json](robots-wildcard-review.json)。修复后同一负匹配加一个正匹配合计约 0.000068 秒；这是本次小样本观测，不是全输入性能上限证明。仍保留 raw/percent-decoded 两种路径与规则、最长匹配、同长 Allow 优先、`*` 和仅末尾 `$` 的语义。

拒绝隔离不会自动把 401、404、普通 503 或传输超时都解释为该主机禁止访问。403 属于本项目保守停采边界：单页观察到明确拒绝后，当前采集器不再尝试该主机其他页。它不是该域名所有资源永久不可访问的事实声明。主机状态不扩展到父域或别的子域，也不跨进程永久保存。

`access_restriction` 证据保存 `trigger_url`、具体来源（例如 `http.status.403`）、观察时间、状态和 `fetcher_instance_host` 作用范围；后续未请求的候选关联这个触发证据，不把后续候选本身伪称为已返回 403。原搜索发现证据保留。已有明确平台条款与普通允许列表之间的优先关系没有改变。

## 仍生效的安全边界

- URL 仅 HTTP/HTTPS、标准端口；拒绝凭据、控制字符、本地主机、元数据地址及非公网 IP。A/AAAA 返回中任意非公网地址都会拒绝，不从混合答案中只挑公网地址继续。
- 采集每次请求重新解析并验证全部地址，实际 TCP 连接使用已验证数字 IP，Host 与 TLS SNI 保留原域名。已读取安装的 httpcore 1.0.9 TLS 连接源码与 httpx 0.28.1 SSL 默认配置；未禁用证书验证。`trust_env=False`，无隐式代理、Cookie 登录或自动重定向。
- 可选 DoH 仅固定可信 1.1.1.1 出口、cloudflare-dns.com Host/SNI、A/AAAA、有限响应；用户请求不能替换解析服务。没有失败回退至其他出口。
- 页面和 robots 的每次重定向都重新经过 URL、平台策略、DNS/IP 与主机锁。页面跨站跳转还检查目标 origin 的 robots。robots 自身的跳转不递归查询目标 robots，避免递归依赖；仍检查目标平台策略与 SSRF。
- 每个 Fetcher 最多 5 个并发采集，实际 HTTP/DNS 使用同 hostname 锁；锁覆盖每一跳。主任务队列单进程串行，各任务另有网络槽位与总期限。异站重定向合流到拒绝主机的离线测试确认该目标只请求一次。
- 响应字节预算、无压缩读取、每次 DNS/HTTP 的超时、最多一次传输重试、最多三次重定向均保留。目录跟随仍限一次、由服务端先预留详情预算，不播放或下载媒体。
- 对明确条款限制来源不启用渲染：Bilibili/YouTube 需事先许可，学堂在线明确限制抓取；MOOC 自动聚合许可范围尚未确认。MOOC 的 robots 404 或动态页面壳本身不是禁止证据，也不是渲染授权。此前官方证据及日期见 `../platform-coverage-policy-20261013-final.json` 与代码 policy review，当前没有重新外访这些路径。

## 缓存与失败隔离的具体边界

1. robots 按 origin 缓存默认 3600 秒，成功规则和 404/410 的空规则缓存。HTML 壳、未确认错误不会转成允许；403/明确拒绝现在有实例级主机停止状态。普通 robots 网络失败/401/HTML 壳仍没有短期负缓存，会在不同候选上再次检查；建议未来仅短期缓存不确定失败，不永久判定禁止。
2. 页面缓存由 service/SQLite 管理：成功与平台策略结果默认 86400 秒，其他失败最多 300 秒；过期缓存默认关闭，启用时有缓存时间与 stale 标识。缓存 key 包括规范 URL、提取器版本、采集开关、受限域配置和 DNS 模式。主任务本轮将版本 5 升为 6；没有覆盖原缓存。本轮没有写正式数据库。
3. 缓存命中代表历史事实读取，不进行新的 DNS/HTTP，也不是重新确认访问许可。当前 policy 更新依赖版本升级使旧缓存失效；未来可单独加入 policy version/hash，降低人工遗漏风险。
4. 同主机连续传输失败目前没有额外短期熔断：每个 URL 最多一次重试，别的 URL 仍可尝试。全局任务期限会取消未完成采集。若后续需要，建议独立短暂停状态，仅统计耗尽重试的 transport failure；不要混同 robots/条款拒绝、DNS 安全拒绝或普通 404。本轮没有加入这一扩展。
5. DNS 与 HTTP 各自有超时，单次尝试并非合计只耗一个 timeout；例如上限 8 秒时，两阶段可能合计约 16 秒。服务总期限仍有效。源码误称 HTTP deadline 同时包括 DNS 的注释已纠正；未来可用共享剩余时限进一步缩紧延迟。
6. 详情预算按资源页/目录页预留，并非 robots、重定向、DNS 及重试的原始网络次数上限。本轮新增有界 trace 帮助分别审计，未改动 service 进度计数。主机锁、robots 状态等字典仍随访问过的主机数增长；长时运行可考虑安全的 TTL/LRU 清理，不能删除正在使用的锁。
7. 恶意畸形重定向 Location（例如不闭合 IPv6 方括号）在 `urljoin` 阶段仍可能上抛 ValueError，由 service 统一显示 fetch_error；未发生目标请求。其分类可进一步细化，但不是 SSRF 放行，本轮没有扩大修改。

## 有界执行记录与测试

`list(fetcher.request_trace)` 保留最近 512 个事件；`dict(fetcher.trace_counts)` 保留累计计数。包括 DNS/HTTP 开始、完成/失败/取消、重试、等待、主机暂停/停止。每个事件有 `kind`（page/robots）、attempt、时间、hostname、去除 query/fragment 的 URL 和完整 URL 的 SHA-256。不会记录认证头、响应全文或异常消息；它是操作记录，不自动升级为页面内容证据。512 之前事件会被淘汰，累计计数仍保留，不应称为无限完整审计日志。

最终相关回归命令：

```text
uv run --frozen pytest backend/tests/test_fetcher.py backend/tests/test_fetcher_pacing.py -q
89 passed, 26 subtests passed in 10.78s
```

新增测试覆盖每次重试间隔、不同 origin 延迟不降级、503 暂停恢复与跨主机隔离、异常 Retry-After、HTTP/robots 明确拒绝与触发证据、401/404 边界、重定向合流、取消释放主机锁、trace 上限/脱敏、通配规则语义与已复现的多星模式。原 DNS 重绑定、混合私网答案、数字 IP+原 TLS SNI、逐跳平台停止、字节预算、真实 HTML 目录证据回归仍通过。

本次 fetcher SHA-256：`9e91407f9c322175c3e8f10840ec05bcbfdc783a62cd1b52bbf3de22946965d0`。新增测试 SHA-256：`a93392203201267c9fb32170c9a5955c5aecaad8de7ca06b5e50cb0ad95c5baa`。service/config 的授权集成由主任务维护；不以这些单测宣称真实搜索或前端链路已验收。

## JavaScript 渲染：当前不能安全启用

项目 Python 运行环境未安装 Playwright、Crawl4AI、Crawlee、Scrapling；前端已有 Playwright 测试依赖，配置用于本地 UI 测试。现有 Compose 仅部署 SearXNG，没有浏览器沙箱、网络命名空间或受控出站代理的验证。没有对主机的所有外部安全设施做普遍断言；结论限于本项目可复现配置与已验证运行路径。

仅校验主文档后交给浏览器、只拦截 page.route、禁用图片、换 User-Agent/fingerprint/proxy 或使用 stealth 抓取器，都不足以承诺完整 SSRF/TLS 控制。子请求包括 iframe、JS/CSS/font/image、fetch/XHR、重定向、worker/service worker、WebSocket、WebRTC/UDP、预连接/DNS、下载及浏览器后台请求。任何未覆盖路径都必须默认不能出站；浏览器不得自己再次解析原域名绕过已验证 IP。

若未来单独授权实现，最小可评估设计应同时满足：

- 浏览器进程在可证明的 OS/容器无直接网络出口环境，含 IPv4/IPv6、UDP/DNS、localhost/宿主机/元数据；仅通过独立控制管道接收审核后的字节。不能依赖浏览器参数作为唯一防线。
- 每一个获准子请求必须经过统一 broker 的平台许可、robots、方法/来源白名单、逐跳 URL/DNS/IP/TLS、节流与总时间/字节/请求次数预算；只允许明确授权的公开资源，不使用私有接口、登录态、隐藏 token、下载或播放媒体。不能验证就停止渲染并保留未知。
- 主页面 policy_unreviewed 或明确禁止时，启动前零 DNS/HTTP/浏览器请求。子资源若指向受限平台，也不能借主页面许可继续读取。不能以 challenge/captcha/403 触发更强绕过。
- 先用完全本地恶意测试页验证：私网/混合 DNS/重绑定、跨站重定向、证书不匹配、iframe/worker/WebSocket/WebRTC/后台流量、压缩/慢响应/无限 JS、总预算取消后孤儿进程。必须验证操作系统实际零出站和所有 broker 连接的数字 IP/TLS；mock route 事件不能作为完整证明。

当前可执行的是继续使用已安全获取的静态 HTML、JSON-LD 和可见 playlist 结构；按需浏览器网络路径保持关闭，`javascript_required` 明确保留。动态渲染的完整隔离尚未实施、尚未验收。
