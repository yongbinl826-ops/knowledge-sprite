# MIT 传输超时：离线诊断与分阶段验证

日期：2026-10-13。此文件是后续独立修复记录，不修改原成功探针、失败修复验证或 held-out 报告。截至本记录编写时，新验证未联网执行。诊断只使用原始 JSON、保存的脚本与当前锁定环境源代码。

## 已知与未知

| 记录 | 可证事实 | 不可据此推出 |
| --- | --- | --- |
| `mit-discovery-probe.json` sitemap | 363036 字节，HTTP 200；从 target 发起到响应头 1.229765 秒，响应头到正文结束 5.165452 秒，总 6.396233 秒；完整 hash 已保存 | 后续请求会有相同响应速度或同样大小 |
| `official-repair-live.json` sitemap | DNS A/AAAA 均完成；目标传输运行 10.009 秒后下层 CancelledError、Fetcher 上层 TimeoutError；整体失败已保留 | 已定位 TCP、TLS、响应头等待或正文读取中的某一阶段 |
| 两个脚本与传输 | 都使用固定公网 IP 连接、原主机 Host/SNI、无代理、无隐式重定向、同一 User-Agent / Accept / identity 编码请求；DNS 有独立期限 | headers 配置差异造成失败、某个 CDN IP 更优 |

失败 runner 的旧 target 记录仅在完整 `HTTPResult` 返回后更新 status/hash/bytes。因此 status_code=null 不证明“未收到响应头”；其初始 truncated=false 也不证明未读过部分正文。失败前已读字节未知，不能当 0。成功首个 IP 为 151.101.194.132，失败首个 IP 为 151.101.66.132；只有各一次记录，不作地址优劣推断，不调换地址或逐 IP 重试。

已确认的实现限制是 `Fetcher._request` 的单个 10 秒 wait_for 覆盖 TCP/TLS、请求、响应头、全部正文。HTTPX 已采用流式读取而非整页自动预加载，并有字节上限；改成“流式”本身不是新修复。原响应迭代使用 16384 字节聚合，现在直接观察实际返回 chunk，减少小于聚合块的正文遥测盲区；不解除字节校验。

## 修复假设与实现

假设：一次总期限可能把各自仍有进度且有界的首响应阶段与正文阶段过早合并取消。该假设仅能解释一种可能性，不证明旧失败发生在正文，也不保证新请求成功。

生产 `FetcherConfig` 新增可关闭选项：

- `phased_timeouts=False` 默认关闭，保持原 whole-response 截止方式。
- `body_idle_timeout_seconds=5.0`。
- `body_min_bytes_per_second=32768.0`。
- `body_timeout_cap_seconds=20.0`；本次单次验证明确设为 10。

启用后，首响应仍受 `timeout_seconds`（本次 10 秒）约束；headers 之后固定正文累计期限为 `min(当前响应字节上限 / 最低速率, body_timeout_cap_seconds)`，每个 chunk 不重置该时钟；每次等待网络 chunk 另有空闲上限。只使用己方字节上限推导时间，不让缺失或虚报 Content-Length 延长期限。外围仍保留首响应加 bodycap 的总 HTTP 护栏，任务总期限和取消优先。

新安全遥测写入 `fetch_diagnostics.events[].http_transport` 对应事件的 `transport` 字段，包含 allowlist 的 httpcore TCP/TLS/发送/headers/body 阶段、UTC 和相对时间、已知 HTTP 状态、部分字节/hash、正文是否完整及 timeout_kind。不会复制底层 info 对象、请求/响应头正文、cookie 或异常文本。取消继续抛出 CancelledError，错误不是重试触发授权；partial body 只留诊断，既不返回提取器也不缓存成成功页面。

为并行开发的受控渲染器提供可选 `NETWORK_OBSERVER.response_byte_limit()`：每次实际 target HTTP 前限制为剩余正整数字节；非正或非法值在 HTTP 前停止。该 hook 不能增加原有 cap，复制并 finally 复原观察器，不影响 DNS/IP/robots/重定向约束。

本轮未修改来源选择、排序、缓存格式或官方失败状态恢复。现有官方 Provider 对 timeout 等失败会在该实例生命周期保持停止；本轮明确不增加自动恢复/重试。新验证构造独立 Provider 和新鲜 SQLite，不把旧报告响应注入缓存。若未来需要跨新任务恢复 transient failure，应单独定义新任务边界、冷却、访问拒绝与 Retry-After 的不同语义；本轮不实施。

## 离线检验

`tests/test_mit_transport_revision.py`：25 passed，报告 `mit-transport-revision-final.xml`。覆盖分阶段成功而原总期限失败、首响应阶段可定位、正文 idle/累计超时区分、持续小块不能滑动延长期限、Content-Length 不放宽 byte cap、取消关闭流并原样传播、非法预算拒绝、renderer 剩余字节 hook，以及新 runner 在正文失败时保留实际 headers HTTP 200 和 partial hash、但不生成完整来源 hash/文件。

相关采集、官方发现、runner、生命周期组合报告为 `mit-transport-integration.xml`：176 个 XML testcase，errors/failures/skipped 均为 0，13.000 秒（含既有 subtests）；该组合在追加最后 1 个 runner 定向测试前执行，新增用例已在上述 25 项中通过。没有借助外网、正式数据库或原失败的重跑。

## 新单次验证草案

范围文件：[mit-transport-revision-scope.json](mit-transport-revision-scope.json)。脚本：[verify_mit_transport_revision.py](../../scripts/verify_mit_transport_revision.py)。由根任务在所有相关源码冻结并明确批准后手动执行一次：

```powershell
.\.venv\Scripts\python.exe scripts/verify_mit_transport_revision.py
```

仅原始知识点 `probability`、最多 1 个匹配子 sitemap；不指定课程 URL。生产仍从 robots 实际声明、根图到子图真实 loc 发现，再获取页面、按原规则检查证据。主题是开发后验证输入，不能称独立 held-out。

硬预算：目标 HTTP 共 6（含 robots/root/child/page/redirect/catalog）、实际 DoH HTTP 共 12、合计 18、并发 1、0 重试、全程 120 秒。XML 路径（含根图）最多 500000 字节；其他目标仍最多 2000000 字节；DoH 65536 字节。首响应 10 秒、body idle 5 秒、bodycap 10 秒、每 target 总最多 20 秒。全局 wrapper 逐 DNS/HTTP 检查 MIT 同源，在访问限制、网络/DNS/大小错误及预算到达后阻止后续请求。

新数据库为 `mit-transport-revision.sqlite3`，输出为 `mit-transport-revision-live.json`，原响应单独放 `mit-transport-revision-sources/`。任一预期输出已存在即拒绝重复执行。报告保存完整任务、证据、实际阶段和 partial 数据，校验旧 probe / repair / held-out 的 hash 不变。旧失败原因仍未知；本次若失败，无替换输入或重试。目录、视频结构与播放验证分别报告，不能用 HTTP 完成或 Course 静态结构宣称三者都通过。
