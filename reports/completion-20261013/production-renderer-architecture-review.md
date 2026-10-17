# 受控生产 JS 桥：架构与证据只读审查

日期：2026-10-13。只读现有 `experiments/controlled-renderer`、`backend/app/fetcher.py`、`service.py`、`extractor.py` 与模型；没有启动浏览器、外网请求、运行测试或修改生产源码。以下是实现前建议，不是新实现通过验收的结论。

## 可实施的最小链路

允许源的真实候选 → 同一安全 Fetcher 获取成功公开 HTML → 先运行现有静态提取器 → 从这份 HTML 的真实公开资源引用生成有界 manifest → 同一 Fetcher 串行预取允许资源 → 匿名离线 Edge 仅 fulfill 已取得字节 → 保存实际 DOM → 同一提取器处理 DOM → 按证据增益合并。

这一桥可以实施。操作系统全部出口隔离仍为 unknown，并不要求为了这一边界先证明整个 OS 的所有网络通道；产品声明应准确限定为页面 HTTP 离线预审字节回放。它也不使任意来源、任意远端脚本或受限页面自动获得采集许可。

## 当前实验能复用什么，不能直接复用什么

- 可以复用匿名 context、创建页面前设置 route、offline、阻止 Service Worker、WebSocket route、CSP、禁止媒体/框架/下载/新导航、有限 DOM 输出与关闭浏览器的结构。浏览器端只能 fulfill 或 abort，无 `route.fetch` / `route.continue`，不能缺项自动联网。
- 当前 `validate` 只信任固定 fixture 的逐字节内容。生产不能简单删除此校验后接受用户上传任意字节包；包必须由服务器从本任务的真实 Fetcher 响应生成，并与允许源、请求证据和预算绑定。用户检索请求不提供脚本、浏览器启动参数、执行代码或回放 manifest。
- 当前 fixture 用 `window.__fixtureDone` 判断完成。真实源不得注入伪造完成标记或补造课程 JSON-LD；以有界 DOM 稳定观察或来源实际可见结构为完成条件，超时保留真实失败。
- Node 内 finally 的 close 没有独立 watchdog，旧测试驱动才有通信超时与拥有进程树清理。生产 Python 适配层必须承担有界清理，不能仅把旧 Node 正常取消结果当作任意取消时刻已验证。

## 资源来源与执行边界

1. 先检查成功 HTML 的政策、robots 和访问状态。policy_unreviewed、site_policy_blocked、captcha、login gate、403/429、Retry-After 等不能触发 JS 回退。B站、学堂、YouTube 明确限制和 MOOC 未确认许可范围均沿用现有决策。
2. 最小第一版只支持原始 HTML 中实际存在的同源 `script[src]`，必要的 inline 脚本若支持应保存原字节/hash 并按 hash 限定 CSP。JSON-LD 是数据，无需作为可执行脚本处理。CDN、模块递归依赖、XHR/API、worker 或浏览器动态发现的依赖不因 URL 看似合理就自动获取。
3. 所有支持的资源都由现有 Fetcher 走政策、每源 robots、逐跳 URL/公网 DNS 验证、固定验证 IP、原域名 TLS/SNI、限速、字节和超时。资源发生重定向时记录实际 request/final URL；回放匹配使用实际观察到的精确 URL，不靠去 query、补目录或拼 API 猜测别名。
4. 可以把浏览器未预审请求作为失败诊断保存。仅观察到动态请求不等于获得私有 API 访问授权，不能转为无限的发现—补抓循环。缺依赖时返回 unsupported/missing dependency 并保留静态结果。
5. 不播放或下载媒体、不读取用户 profile/cookie/storage state、不向页面暴露 Node/Python 函数。回放 MIME 只允许相应支持类型；既有源 CSP 与新增约束应共同生效，不能为了让脚本运行解除原有明确限制。unsafe-eval、宽泛 connect-src 或开放第三方资源不应作为默认兼容补丁。

## 预算、串行与取消

`service._enrich_one` 已在 `state.network_slots` 内调用 `Fetcher.enrich`；最小桥应作为同一调用的子阶段，资源预取串行执行，保持全局并发 1 时搜索和预取也串行。不能启动脱离任务的预取或渲染 Task。

现有 `max_detail_pages` 只预留资源详情和一次目录页，不能把 JS 预取悄悄藏在一个详情计数中。需要明确的渲染资源预留/计数，同时受当前任务总出站上限约束；目标 HTTP 的 robots、重定向也须计数，DoH A/AAAA 每次实际请求另计。浏览器 fulfill 次数与累计字节有本地独立上限，不能误报为外网次数。复用缓存也要保留原观察时间与 hash，不能算本轮真实请求。

Python 适配层须把剩余 job deadline 同时约束启动、通信、DOM 收集与清理；`CancelledError` 不得转成普通成功、超时或重试。清理只处理本次拥有的 Node/Edge 进程；正常关闭失败时有界终止拥有的进程树并记录不确定项，不关闭用户浏览器。取消接口原本等待任务和网络清理，加入桥之后应保持这一语义。stdout/stderr、输入包、DOM 和审计列表都需要长度上限，不能无界 `communicate()` 等待任意输出。

最有价值的离线用例是：策略拒绝在浏览器启动前零出站；真实引用以外的依赖请求被拒绝；主脚本或跳转到私网/他源被拒绝；资源请求共享预算；预取期间、Edge 启动中、执行中取消；Node 无回应后的有界清理；不同 job 的计数和产物不会串用。

## JS 必要性与字段证据

脚本存在、HTTP 200、静态字段缺失或页面显示加载动画，都不足以证明 JS 必需。应对同一份真实源快照保存：静态提取输出、输入 HTML/hash、每个实际执行资源的 URL/hash、实际 DOM/hash、渲染状态、静态与 DOM 提取字段差异。只有实际 DOM 新增且可逐字段绑定的课程信息/目录，才支持此次 JS 补全产生增益。

现有 MIT 主页和视频目录可从静态 HTML 提取；重复渲染它们不构成 JS 必要性正例。若限定预算内没有取得真实动态增益样本，允许如实交付已实现桥，并将真实 JS 增益标为未验证；不能用 fixture、客户端注入教学数据或保存报告替代生产源。

建议保留现有 extractor 的语义 `source`（例如 `jsonld.@type`），另加 `acquisition=offline_rendered_dom`、render id、manifest hash、DOM hash，避免偷偷把 DOM 当原 HTML，又不因随意替换 source 前缀破坏已有 Course 证据白名单。每章 title/url/start/end 继续绑定章节证据；没有时间仍为 null，课程结构不等于视频，视频结构不等于可播放。

渲染失败或无增益不能清空先前可靠静态字段。缓存键需纳入 renderer 开关/版本、支持源策略及 manifest 依赖；失败与成功分别使用适当 TTL，不能让旧 static cache 永久遮住新桥或把过期 DOM 当本次观察。面向用户的状态应区分静态取得、离线 JS 补全、缺依赖、取消、超时和未启用，避免用全局任务 completed 代替该页完成。

## 待实现后复核

后续代码审查只核对以上实际连接点及证据口径：来源许可与入口、真实资源引用、每跳安全与共同预算、浏览器无在线回退、取消回收、DOM 来源标记及真实增益。当前没有运行新的 JS 实验，不能据本文声称生产渲染、MIT 动态目录或真实网页播放已经通过。
