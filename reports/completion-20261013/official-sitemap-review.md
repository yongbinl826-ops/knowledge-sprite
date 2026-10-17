# OfficialSitemapProvider 只读审查 · 2026-10-13

本审查只读生产源码、验收脚本、既有测试与报告；没有外网请求、正式数据库写入、测试执行或前端修改。发现的生产正确性问题已发送实现代理，下面记录最终读取版本中的处理及准确边界。独立 transport/resolver 预算与最终 fallback 故障隔离修复均已核对；本审查不代替尚需实际执行的修复验证。

## 已关闭的问题

1. **XML 编码绕过声明检查**：初稿对原始 bytes 扫 DTD/ENTITY，UTF-16 可绕过。冻结版先严格 UTF-8/UTF-8-BOM 解码，拒绝 NUL、DTD/ENTITY，再交给 ElementTree；1,000,000 字节、10,000 个直接条目上限保留。边界测试覆盖 UTF-16 三种编码、DTD/实体、错 namespace/层级/重复 loc。
2. **失败后的后续路径**：初稿 401 与 XML 错误未停止后续查询。冻结版将 401/403/429 明确视为拒绝，FetchStopped 和 SearchError 均记录 `_stopped_code`，同 provider 生命周期不再请求新入口；官方请求将共享 Fetcher 的重试上限收紧为 0。共享 Fetcher 的已拒绝 host 在缓存发现前也检查。
3. **缓存延长旧索引有效期**：仅将 query TTL 取最小值仍会把接近到期的旧 index 再延长一轮。冻结版在官方模式或启用官方 fallback 时关闭外层 query cache（包括 stale 回退），只保留各 robots/index/child 来源自身 TTL。索引 cache key 包含来源 URL、解析版本、TTL、DNS、采集启用与允许/禁止 host；外层 key 仍保留 source identity、原知识点与配置，但该模式不读写它。
4. **混合来源重新引入 URL 词作为教学覆盖**：初稿仅在所有 search 都是 sitemap 时剔除 URL 衍生标题。冻结版最终 rule rank 与 LLM 输入始终排除 official_sitemap 的搜索标题/摘要；它只能参与有限的待采集页面选择。与普通搜索混合时普通搜索的独立证据仍可使用。
5. **MIT 单源的能力范围**：官方模式新增可见任务警告与 provider 说明，B站/MOOC/学堂 discovery 为 out_of_scope；不再把当前 MIT 单源称为三平台均支持搜索发现。旧前端对非 search 的发现状态保守显示“当前未确认”。
6. **可选来源拒绝错误地中止主来源后续知识点**：根代理独立审计确认初稿 `_discover` 将官方 fallback 的 access_denied/configuration_error 传播为主搜索错误。最终版仅捕获 fallback 的 SearchError，保存 `official_source_failed`、原始 reason_code、请求 trace 和 discovery failure，返回原主来源的正常空结果；下一知识点继续原主来源，已停止的 MIT provider 不新增网络请求。主来源自身 SearchError 仍在该 catch 之外；BudgetReached、CancelledError 也不在其中，预算与取消仍终止相应执行。新增测试同时覆盖官方 403、官方配置错误后主来源第二知识点有结果，以及主来源拒绝时不进入官方 fallback。

## 冻结实现的链路与边界

| 项目 | 只读核查结论 |
| --- | --- |
| 入口与数据来源 | 固定官方源为 HTTPS ocw.mit.edu。只从实际 robots `Sitemap:` 声明取入口，然后读取 sitemapindex 的真实直接 `<sitemap><loc>` 与子 urlset 的真实直接 `<url><loc>`；不读取 reports 当生产课程库，不构造课程主页答案，不使用私有 API 或浏览器。当前保守只选第一个可接受声明。 |
| 同域及跳转 | `official_url` 要求相同主机、HTTPS、默认/443 端口、无 query，复用 URL 凭据/私网检查；provider 的 before_resolve 对每个 robots/目标/重定向实际请求执行同域检查。真实传输仍用 DNS 全地址验证、已验证 IP 连接及原域名 TLS/SNI。 |
| domain_filters | 非空过滤范围不包含 MIT 时返回空且不出站。B站、MOOC、学堂定向查询不能静默转 MIT；同时包含 MIT 和其他源的 OR 范围允许 MIT 子集。原 provider 抛错不会进入 fallback，只有正常空结果可进入显式启用的 fallback。 |
| 候选预算 | 原始知识点（含版本）完整词项覆盖才打开实际 child。默认每查询 1 个 child，可配至 2；每个 child 最多取 1 个实际 loc。robots/index/child/重定向目标 HTTP 都走搜索请求预留；DoH A/AAAA 分别计 `discovery_dns_requests`，有独立 2×搜索上限。详情/一次可见目录跟随仍走原详情预算。 |
| 缓存与观测 | 来源 cache 保存 URL、SHA-256、观察时间与 loc；当前请求 trace 与 cache_origin 分开。缓存命中不能伪装为本轮 HTTP。生产 API 不返回 raw HTML/XML 正文。 |
| 最终准入 | 纯 sitemap 候选必须有成功页面中由 field_provenance 关联的 title/description/逐章 catalog 内容覆盖原知识点及版本，之后还须通过原有真实课程或视频类型与反先修等排序门槛。URL 推得的标题不证明实际页面标题或教学内容。普通 Course 仍不证明视频，视频结构仍不证明可播放。 |
| UI 兼容 | 新 discovery_evidence 是附加结构字段，既有 UI 忽略它而不破坏渲染；可读 snippet 已明确来源 sitemap URL、低置信路径标题与未核验覆盖。React 文本渲染不会执行 HTML。该 UI 尚未逐字段展示 index/robots SHA；完整结构保存在 API/evidence 中，不能声称已实现新的来源审计面板。 |

## ContextVar 与总预算必须区分

生产 `NETWORK_OBSERVER` 是任务内替换式观察器：provider 进入时设置自身计数/trace，finally reset。详情调度 Task 在它之前创建并保留自己的 context，因此不会将并行详情计入该搜索 provider；取消/预算异常也会 reset。

它**不组合父 observer**：若调用方只在外层 ContextVar 安装总验收 recorder，官方 search 执行期间该 recorder 会被替换，不能据此记录或限制总出站。已报告此事实；root 明确采用独立 transport/resolver 包装统一限制总验收的 12 target / 24 DoH，不为诊断用途扩展生产回调组合。此选择不会使替换式 ContextVar 自动变成可嵌套的总预算接口。

## 修复验收脚本的独立边界

已只读核对 `scripts/verify_official_discovery.py` 与 `official-repair-scope.json`，没有运行真实验证。

- `AuditedHTTP` 直接包装同一个 PinnedHTTPClient；每次目标请求前预留独立记录，最多 12 次。搜索中的 robots、robots 跳转、索引和 child，以及详情、详情跳转、可见目录跟随，均通过这一共享传输层；不是靠外层 ContextVar 推算总请求数。
- `AuditedDNS` 在每次实际 resolver 调用中读取当时 provider 已安装的 context，再组合 `before_dns_http` 与 `dns_trace`，finally reset。每个实际 A/AAAA DoH HTTP 单独计数，最多 24 次；失败只发 A 时不会虚报两次。两项上限合计 36 次，不包含虚构的缓存请求。
- 初稿仅 provider 搜索范围限制 MIT，详情重定向可能离开验收同源。最终版在 DNS 解析前和目标 HTTP 前均要求 `official_url` 的 HTTPS/ocw.mit.edu/默认端口/无 query 规则；超出批准源在 DNS 前拒绝并置 run-wide stop。
- 目标 401/403/429、503 带 Retry-After，以及目标传输/解析异常设置 run-wide stop，保留原响应或异常记录后阻止后续目标与 DoH；共有 Fetcher 的 robots、站点策略、captcha/403 host 拒绝机制仍保留。正常目标并发上限 1、重试 0；目标正文最多 2,000,000 字节，sitemap 还受更小的 1,000,000 字节上限。
- DoH 仍只连接固定 1.1.1.1、使用 cloudflare-dns.com Host/TLS SNI、trust_env=False、identity 编码，正文单独上限 65,536 字节；该大小限制不取代 response 问题名、状态和公共 IP 验证。原域名请求仍钉住所验证 IP。
- 脚本使用新的隔离 SQLite、真实 JobService 队列和同一生产 provider/fetcher/extractor，拒绝已存在输出或数据库。保存目标原始正文/hash、独立请求记录、逐资源课程/视频/目录审计，以及运行前后源码和旧 held-out 报告 hash；实际运行终态及 source_unchanged 必须由最终报告判断。
- 180 秒任务截止后只有 10 秒等待清理的外层余量。三个知识点明确是开发后选取的 repair verification；退出成功、HTTP 200 或有 loc 都不等于最终课程准入、独立 held-out 成功或播放已验证。代码保持 `playback_verified=False`。

## 既有测试证据与源码快照

审查读取而未重跑的报告：`official-sitemap-source-isolation.xml` 为 61 tests、0 failures/errors/skipped（22:25:09）；`official-repair-runner-final.xml` 为 7 tests、0 failures/errors/skipped（22:23:57）。此前 `official-sitemap-production-frozen.xml` 为 51 tests、`official-sitemap-integration.xml` 为 203 tests、`official-sitemap-boundaries-final.xml` 为 43 tests，均 0 failures/errors/skipped。这些报告保留各自时间快照，不相加成独立测试总数；均为固定内存网络/隔离 SQLite 测试，不能算真实 MIT 发现验收。

最终读取版本 SHA-256：

- `backend/app/official_sitemap.py`: `53950a55197be1c4988a63d88db84a2393e8a6b4ba79e3f90cdaa6a5f9001408`
- `backend/app/fetcher.py`: `cd53544f33ebc3ecf48adef92009fe9f33d216ec7185c7c67914a74e21ba2fb5`
- `backend/app/service.py`: `bdebee537e3bed95a3922747fa60949b2c5660b48b510f76cc49c3ddbe99461b`
- `scripts/verify_official_discovery.py`: `0e473952fb8f2dd945f8e1ac5d613dc90a1e10fa329f22900f75c1bee56c05d5`
- `tests/test_official_repair_runner.py`: `705268ef8c33c66a3070ba62980421d00a1eb910b5009538b26b80041dee2ee8`
- `reports/completion-20261013/official-repair-scope.json`: `364c03e76fae7f3579cb8748b37772fa1cf63cf2c131ed9c1982bb47aab0f420`

本源只覆盖词项能在有限官方索引与页面中确认的 MIT 候选。没发现、细粒度词项不符、版本不符或停止采集，应保持无结果/未知；不得扩大到通用主题、换源补数，或把有限词项匹配声称为完整教学覆盖。
