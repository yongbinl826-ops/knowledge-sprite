# robots 400 分类与真实发现链只读复核

2026-10-14。只读现有保存响应、Fetcher、查询/Provider/JobService、微软适配器和直接入口验证脚本。未联网、未运行测试、未修改源码。RFC 9309 在本次作为任务指定的处理框架；本轮没有重新在线核对官方文档。

## 已保存响应的实际含义

`dynamic-course-live.json` 与 `dynamic-course-sources/source-3.txt` 记录：

- URL：`https://cdn.jsdelivr.net/robots.txt`
- HTTP 400；Content-Type `text/plain; charset=utf-8`；完整正文 58 字节。
- 正文：`Invalid URL. The URL structure is /project/version/file.js`
- SHA-256：`c693c9a1ed5a4eb5dc7cb0da280fe755efa3a0c0353788ad2873a3d7324c33aa`。
- TLS/响应传输完成，未截断；此次脚本尚未取得，Edge 尚未启动。

这是应用在说明支持的 URL 路由形式。此记录没有登录、授权、验证码、限流、robots Disallow 或禁止抓取文字，不能据此称为“网站明确拒绝访问”。`text/plain` 本身也不能证明许可；结论依赖状态、完整正文及限制信号合看。

当前 `_request` 原样返回 400 与有界正文，`_robots_for` 只把 404/410 作为无 robots 规则，对 400 统一 `robots_unavailable`。所以旧验证停止是实现的保守分类边界，不是 403/验证码类事实。

## 最小建议

保留普通页面 400 的失败语义，只在 `_robots_for` 做 robots 分类。RFC unavailable 4xx 允许实现选择继续，不要求忽略站点策略或明确拒绝；项目可以采用比通用 4xx 规则更窄的允许条件。

本次最窄可审计例外为：400、完整有界 plain-text 正文、明确路由格式错误，并且没有任何限制信号。先检查拒绝/认证/验证码/限流，再识别上述路由错误，最后生成空 robots 规则。规则分类应记录 `unavailable_4xx_route_error`、原 HTTP 状态、URL、观察时间、正文 hash 与缓存期限，不把空规则写成“robots 明确允许”或“已核验网站条款许可”。

不建议把 `400 <= status < 500` 全部一律放行，也不按 CDN 主机硬编码跳过 robots。无法判定的 400、HTML 壳、JSON 错误体、编码/截断异常继续停；401/403/429、402/407/451、5xx、Retry-After、CAPTCHA、明确 denial 与现有政策限制继续停。政策检查仍在每跳之前，允许空 robots 不绕过 SSRF、DNS/IP、TLS、预算与节流。

## 建议的离线负例

| 输入 | 期望 |
| --- | --- |
| 保存的 400 plain-text 路由错误 | robots 分类可为 unavailable；随后仅请求原先批准的真实脚本，保留 400 证据。 |
| 400 同正文后追加 Access denied / CAPTCHA / 登录提示 | 拒绝优先，不读取目标资产。 |
| 400 + Retry-After / 认证 header | 不按路由错误放行。 |
| 400 + HTML challenge/form、未知 HTML、空正文或未知 plain-text 错误 | 保留未知/拒绝，停止目标请求。 |
| 400 正文出现 User-agent/Disallow 指令 | 不能被空规则覆盖；保守停止或按明确禁止处理。 |
| 401/403/429/503 Retry-After，或普通 5xx | 原限制/暂停行为保持，零后续资产请求。 |
| 非 robots 页面返回完全相同的 400 正文 | 仍是页面 HTTP 失败，不能误判为内容成功。 |
| robots 重定向到私网/凭据地址/策略禁止来源 | 原逐跳 guard 在目标请求之前拒绝。 |
| 400 路由错误正文超字节/时间限制或读取未完成 | 不将部分字符串当作允许依据。 |

原 404/410 路径在 PinnedHTTPClient 中不读正文，现有实现因此不能声称检查过这些响应里的 CAPTCHA。若本次只加入 400 窄例外，应明确这一既有边界，不能把“保留 400 的拒绝检查”扩大表述成“所有 4xx 正文均已核验”。

## 完整生产发现链

`scripts/verify_dynamic_course.py` 构造 JobService 后，直接调用 `fetcher.enrich(scope.entry)`；未创建/执行搜索任务，也未使用 API 搜索和 UI 任务结果。因此其 `search_discovery=not_tested_direct_entry_scope` 口径正确，不能把该记录当成搜索发现成功。

现有生产代码已有一条无需 seed provider 的可执行路线：

1. 保持真正 `SearXNGProvider`，服务端设置 `open_course_domains=("microsoft.github.io",)`，原知识点保留真实学习主题，`preferred_platforms=[]`。
2. `generate_queries` 在两条普通查询之后，追加真实 `(site:microsoft.github.io) <原知识点> course lesson` 查询。Site 限制不是把微软入口 URL 注入候选。
3. 由实际搜索响应中的 title/url/content 创建 Candidate，并保留真实查询、source engines、候选过滤记录和搜索证据。结果未出现、被过滤或无教学相关性都应保留失败，不能补入已知入口。
4. 未知类型候选只有在真实标题/摘要与知识点匹配并含教学语义时，才通过 `_detail_queues(require_type=False)` 进入有限详情；微软适配器仍须在实际 DOM 中确认课程标题、介绍和编号 Lesson Link 表，才能形成 Course 和章节证据。
5. 从真实 POST 创建 job，经原队列/SQLite/GET results/UI 展示；读取同次 `render_diagnostics` 与逐章来源证明增益，不能只看全局 completed 或 renderer 的 rendered。

可考虑固定 3 个搜索请求、每查询最多 1 个候选、3 个详情页，从而给第三条 site 查询留出详情容量；这只是有限验收调度建议。主/备用引擎一次 search 可能消耗多个 HTTP，必须按实际请求预算重新核定，不能把 3 个 query 等同 3 个 HTTP。`global_concurrency=1`、任务 deadline 和已有总出站包装继续生效。若普通查询先占满预算，记录原失败，不扩预算或换知识点补成功。

当前 `OPEN_COURSE_DOMAINS` 文件配置仍是 MIT/OpenLearn，不能默认已有微软定向发现。将微软纳入显式验证配置后仍不能保证搜索引擎实际返回该入口；本次未进行该网络验证。

另一设想“MIT 页指向微软”目前没有保存的实际 href 证据，生产目录跟随也只支持 MIT 同课程的一次导航。不能构造这条跨站发现路径，更不能把已有 probe URL 当作 MIT 页面发现结果。
