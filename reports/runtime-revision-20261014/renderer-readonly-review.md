# 生产渲染桥只读复核（2026-10-14）

范围：只读当前 `backend/app/rendering.py`、`backend/renderer_worker/worker.mjs`、取消测试和既存来源快照。仅执行 `declared_assets` 的本地纯函数复现；没有联网、浏览器运行、源码修改或旧报告覆盖。下列文件行号对应本次读取快照，root 后续修复可能移动行号。

## 需要处理的实际问题

### 1. 排除入口第三方资产需同时处理预检与重放，不能只改 `raise` 为 `continue`

- MIT 的原始页面确有 Appzi：`../adapter-evaluation-20261013/baseline-source-2.html:1890` 为 `https://w.appzi.io/w.js?token=Tgs1d`，标签是 `async script`。本地对该真实 HTML 执行 `declared_assets(..., max_resources=20, asset_hosts=())` 得到 `render_scope_blocked`；没有 HTTP。
- `rendering.py:117` 对不在允许名单的跨源脚本/样式直接抛异常，因而不能继续渲染页面内已许可的课程内容。
- 仅跳过预取仍不够：原 HTML 标签依然存在，`worker.mjs:124` 将脚本 CSP 违规标为 fatal；如果请求到达 route，`:102` 的缺资产检查同样会使脚本 fatal。`:141` 随后返回 `render_dependency_blocked`。
- 建议：将入口实际声明、语法合法但不在资产允许名单内的第三方资产记录为 `excluded_assets`，在单独的**重放副本**中将对应标签变为惰性节点。保留原始 HTML/source hash，另记录 replay document hash 与具体排除清单；不得把改写副本 hash 冒充原响应 hash。该资源没有 HTTP、执行或放行。字段证据仍明确来自受限渲染 DOM，不能声称原站整页功能完备。
- 私网、含凭据、登录/交易路径等安全 URL 异常不应为兼容性转为可抓取；未知运行时脚本及未许可依赖也不能全局忽略。不要为跳过 Appzi 而全局将 `csp_script-*` 或全部缺失脚本变为非致命。

### 2. 保存的 Docsify 页面另有已经观测到的阻塞；不是 Appzi

- `../runtime-revision-20261013/dynamic-course-sources/source-2.txt:12,17-26` 只有 jsDelivr 的 Docsify CSS、Docsify JS，以及一段 `$docsify` 内联配置；没有 Appzi。
- 同一真实入口通过当前纯函数预检，产出 **2 个声明资产、1 个内联脚本 hash**。所以 Appzi 排除修复本身不会改变该入口的预检结果。
- 既存 `../runtime-revision-20261013/dynamic-course-live.json` 的 `$.targets` 只有 3 条：Microsoft robots 404、入口 200/875 字节、jsDelivr robots **400/58 字节**。`dynamic-course-sources/source-3.txt` 原文为 `Invalid URL. The URL structure is /project/version/file.js`。
- 同报告 `$.resource.render_diagnostics.status=robots_unavailable`，`passes=[]`，`manifest` 只有入口文档，`dom_sha256=null`，`$.acceptance.rendered=false`。真实 CSS、JS、README 尚未取得，Node 两轮也尚未开始。
- 当前 Fetcher `_robots_for` 仅将 404/410 作为无 robots；400 走 `robots_unavailable`。因此仍需独立解决该来源的 robots 状态处理契约；不能在 renderer 内绕过 Fetcher 或将旧失败改成成功。本审查不联网验证协议或建议盲目重试。

## 取消已修复；不再是待修问题

- `rendering.py:342-347` 的 `graceful()` 包含 `stdin.write(cancel)`、`await stdin.drain()`、`await process.wait()`，整个协程置于 `wait_for(..., 3)` 中。此前第二次 drain 不受界限的问题已修。
- 3 秒是**优雅退出宽限**，不是总清理时长。后续 taskkill 等待与目标进程等待各有独立的 3 秒上限，不能把完整清理宣传为总共 3 秒。
- `tests/test_rendering.py:255`：不读 stdin 的 Python 进程替身，加 600 KB 输入，验证工作超时、强制树清理请求、Node 替身退出与本隔离例小于 10 秒。
- `tests/test_rendering.py:273`：真实系统 Edge 到 ready 后取消，验证 `CancelledError` 穿透并等待所拥有 Node 退出。
- 既存 `../runtime-revision-20261013/rendering-cleanup-check.xml` 有 **26 tests、0 failures、0 errors**；上述两项分别耗时约 4.461 秒和 2.798 秒。本轮未重跑，不能将昨日结果称为新源码验证。
- 两项均不证明所有 Edge 子进程退出、任意取消时点均已覆盖，或 OS 全出口/UDP 隔离；相应 unknown 边界仍合理。

## 关于 Docsify 的其余判断边界

- 保存入口配置有 `relativePath: true` 和 `routerMode: 'history'`，没有明示 README 请求 URL。当前观察驱动 GET `.md/.json` 两轮策略符合“不猜 API”的约束。
- 未获得真实 Docsify 脚本、实际运行请求和 DOM，因此不能有证据地认定它必然使用 eval、需要第三轮、会请求带 query 的 README，或课程表必然匹配当前适配器。相关结论保持 unknown。
- 已有正例仅是本地构造的 script → content.json → Course + 两章，不应代替该真实 Docsify 课程验收。
- 另一个来源差异：保存 MIT HTML 的 `hideLinksOffline()`（baseline-source-2.html:1896-1912）会在 `navigator.onLine=false` 时移除教师等 `.strip-link-offline` 链接。offline context 可能触发这种页面自带退化逻辑；已有静态字段应保留，不能用受限 DOM 的缺失反证原页没有教师或来源链接。此点不是已观察到的 Docsify 故障。
