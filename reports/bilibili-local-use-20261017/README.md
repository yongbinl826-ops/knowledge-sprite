# B站本地读取与章节推荐验收（2026-10-17）

本机已启用 `BILIBILI_PUBLIC_METADATA=true`。B站公开 HTTPS 视频页不再仅因许可状态而在请求前停止；读取当次匿名 HTML 中同 BV 的视频元数据和 `videoData.pages`，不依赖第三方课程库或非公开接口。模板默认保持关闭。MOOC 本轮未改，公开课程页读取继续沿用已有实现。

## 最终真实链路

- 页面手动输入：`Python 列表和元组`，初学者、中文，优先平台仅 B站。
- 最终任务：[打开应用结果](http://127.0.0.1:18102/?job=2d4b4ef1-f94d-49cf-8d33-378e1b861afa)。服务只绑定本机，运行中可继续提交新知识点。
- 全新数据库；没有候选注入、保存页面回放或搜索/详情缓存命中。4 条逻辑查询、8 次搜索 HTTP 请求、9 个实际新读取的 B站视频详情页。
- 8 个有效视频，共 18 条目录记录：7 个单 P 视频与 1 门 11 P 教程。另 1 个视频已不可见，正确标为 `not_found`。
- 该教程的列表介绍是 **P2**，元组是 **P9**。从应用真实点击元组链接后，B站显示标题“08 Python基础数据类型 元组”和“视频选集（9/11）”。点击封面也实际打开了同一课程原页面。
- 页面显示 5 条推荐，封面均加载，单卡最多两条匹配章节；没有内嵌视频、iframe 或完整目录，未发现横向溢出与浏览器控制台错误。

最终状态为 `partial`：一次 Bing 上游搜索超时，备用 DuckDuckGo Videos 返回结果。SearXNG 本身返回 HTTP 200 不代表所有上游成功；该状态不表示 B站目录读取失败，也不承诺发现了所有相关课程。

## 修复内容

1. 增加本地匿名视频 HTML 模式，缓存键隔离该选择；保留实际 robots、登录、验证码、访问拒绝、请求预算和 TLS/SSRF 检查。仅允许 B站视频页及 robots，重定向不能扩展到其他接口。
2. 实际服务器即使收到 `Accept-Encoding: identity` 仍返回 gzip。补全有压缩前后字节上限、CRC/完整性验证和固定期限的 gzip/deflate 读取，避免 HTTP 200 后仍因正文编码失败而丢失目录。
3. 静态解析同 BV 的 `window.__INITIAL_STATE__` JSON 字面量，不执行脚本；使用真实 `page` 编号生成 `?p=N`，逐行保留标题、时长、来源与证据。后续脚本读取同一变量不会再误判为重复赋值。
4. 复合知识点优先覆盖不同子项：“列表和元组”从原先两个列表章节，修复为列表 P2 与元组 P9。
5. 识别失效视频的 HTTP 200 错误页：需同 BV 的明确错误负载和可见错误面板一致，且无有效视频元数据。HTTP 状态与内容状态分别保留。

具体失效视频为 `BV1Dit1zYEJQ`：本次 HTTP 200，页面负载 `error.code=404`、`trueCode=62002`、`message=稿件不可见`，可见提示“啊叻？视频不见了？”。不能把 404 负载说成 HTTP 404，也不能把搜索标题当作仍可观看的证据。

## 证据与验证

- [最终统计与响应哈希](final-live-run/acceptance-summary.json)、[运行配置与27个源码哈希](final-live-run/run.json)：当前源码全部一致。
- [保留真实分 P 参数的目录账本](final-live-run/chapter-ledger.json)：18 条记录的标题、时长、页码和 URL 均与各自目录证据一致。旧通用审计导出会去掉 URL 查询参数，此账本从实际数据库只读导出并保留经过校验的数字 `p`。
- [真实请求事件](final-live-run/jobs/2d4b4ef1-f94d-49cf-8d33-378e1b861afa/events.jsonl)、[任务记录](final-live-run/jobs/2d4b4ef1-f94d-49cf-8d33-378e1b861afa/job.json)、[审计有效且无错误](final-live-run/jobs/2d4b4ef1-f94d-49cf-8d33-378e1b861afa/audit-status.json)。
- [应用 DOM 检查](final-live-run/ui-dom-check.json)、[控制台错误记录](final-live-run/ui-console-errors.json)、[分 P 跳转记录](final-live-run/chapter-destination.json)、[封面跳转记录](final-live-run/cover-destination.json)。
- [失效页独立新抓取证据](unavailable-page/after-fix-result.json)。早期 `live-run/`、编码修复前后探测分别保留，不用早期结果冒充最终复验。
- 修复中完整后端套件曾通过 982 项及 26 个子测试；最后新增失效页识别后，相关解析、访问范围和压缩传输共 **155 项通过**。前端单元测试 **34 项通过**，TypeScript/Vite 构建通过。浏览器端使用实际页面交互验收，未把未执行的 Playwright E2E 套件记作通过。

目录和跳转已核实，完整视频播放、教学质量与全站覆盖未核实。后台未请求媒体；原平台浏览器页自行加载其播放器，不属于后台采集链路。

![精简课程卡片与列表/元组章节](final-live-run/final-ui.png)

![实际点击后B站选中第9P](final-live-run/chapter-destination.png)
