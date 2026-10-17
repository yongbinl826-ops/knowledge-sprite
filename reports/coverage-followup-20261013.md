# 平台覆盖诊断、真实目录与播放抽查

2026-10-13，北京时间。此报告补充并更新 `implementation-revision-report.md` 的最终状态；前序失败报告全部保留。范围仍为本机知识点→真实搜索→允许页面/目录→证据排序→原平台入口。未新增付费服务、账号、凭据或预置课程答案。

## 结论与边界

现在已真实验证一个应用搜索发现的 Archive SICP 课程集合的目录：**20 讲加 1 个旧版条目，共 21 项**，不是 21 门课程，也不是 21 个已实测播放成功的视频。逐项有页面 JSON 目录证据；章节直链与起止时间未知，未编造。

本轮单独在原站正常点击 Play，抽查首项 `Lecture 10A: Compilation (old quarter screen original)`：先出现“无法播放媒体”，点击后进入加载并出现真实讲授画面，媒体状态从播放中 39.703309 秒前进到 48.7121 秒，随后主动暂停，readyState=4、error=null。未下载完整视频、未登录、未付费。这只证明**这一条在本次浏览器环境短时可播**；没有把整个课程或其他资源的 `playback_verified` 改为 true。证据：[单条播放记录](browser-playback-sample-20261013.json)、[暂停画面](frontend/archive-playback-paused-20261013.jpg)。

最新限定联网回归通过搜索发现、页面视频结构及目录链路要求；**学堂在线仍未命中，MOOC 详情/目录自动采集未完成，完整课程可观看性未知**。自动验收脚本未播放视频，其“观看未实测”描述仅限脚本本身；上述手工浏览器抽查单独报告。

## MOOC 为何先前没有结果，修复了什么

先前的站点限定视频查询因为带 `domain_filters` 被路由到一般 Bing 索引。对照探测表明 Bing 收到完整 site 查询，却返回全部外域结果；不是域名过滤器误删了有效课程。固定官方镜像的查询构造和跳转 URL 解码也已检查，不能进一步断定 Bing 服务端原因。

相同两组主题改走已经配置的独立 `duckduckgo videos` 索引，MOOC 返回 60/2 条域内候选，学堂均为 0；详细原始 URL、标题、查询、HTTP 与过滤理由见 [路由诊断](mooc-route-probe-20261013T090956Z/findings.md)。这只是诊断候选数量，不是全部相关、可播放或已展示课程数量。

最小修复是让带站点限定的视频意图查询也走配置的视频索引，仍保留域名过滤及原有访问停止、限流和预算规则。未对知识点或课程 URL 编写答案。每次搜索请求新增有界脱敏的 `filter_counts` / `candidate_trace` / `candidate_trace_omitted`，可定位过滤阶段。provider 缓存版本 4，页面/策略缓存版本 5，旧证据未删除。

另修复两项：平台筛选在截断前取各平台前五项，使全局第六名以后的课程仍可被平台筛选找到；合法 B站视频入口的 uid 跟踪参数不再制造重复身份，不同分 P 仍独立，原始直链和所有搜索证据仍保存。

## 真实应用回归

[完整联网 JSON](live-coverage-final-20261013.json)，2026-10-13 17:19–17:21（准确时间见 JSON），6 组任务全部 completed。**50 次实际搜索 HTTP、0 搜索缓存命中**；页面缓存与实际采集分别列示。代码哈希在整轮开始/结束一致。

| 输入组 | 默认展示项数 | 状态 |
| --- | --- | --- |
| Python 列表与字典 / HTML 表单校验 / SQL 多表连接 / 地图投影与坐标系 | 5 / 4 / 5 / 5 | completed |
| D3.js 数据连接 enter update exit | 2 | completed |
| Scheme higher-order procedures / Eigenvalues and eigenvectors（含重复输入） | 5 / 5 | completed，重复输入合并 |
| 随机无意义知识点 | 0 | completed，未填入替代课程 |
| D3.js enter update exit / Structure and Interpretation of Computer Programs | 3 / 5 | completed，后者含 21 项真实目录 |
| Python / linear algebra，优先 MOOC 与学堂 | 5 / 5 | completed，平台筛选各显示 1 条 MOOC |

默认视图按资源身份去重为 48 个，加上平台筛选可达项为 **52 个资源身份**：B站 29、其他网站 21、MOOC 2。这里不是 52 门课程或已去除所有跨站镜像的 52 个独立视频。50 个视频类型、2 个课程类型；页面视频结构与目录证实仅 1 个资源，其他保持搜索证据级别。48 个页面采集因明确策略停止、2 个 MOOC 许可待核对、1 个需 JavaScript、1 个允许页面采集成功。

本轮仍未命中学堂。四个指定中文细分知识点的 MOOC 候选未通过完整主题匹配，不声称已覆盖这些知识点；新增 Python / linear algebra 是用于验证通用平台路由的宽主题输入。

真实浏览器读取修复后 API 任务 `ff870c31-34f9-4c17-9694-3fceb5d4b847`，选择“中国大学 MOOC”，显示：

- `https://www.icourse163.org/course/WHUT-1206307812`：数据结构与算法Python版。
- `https://www.icourse163.org/course/NWPU-1207119809`：Linear Algebra。

这次浏览器流程为真实任务结果渲染和筛选核验；任务由联网脚本提交，不写成浏览器重新提交。界面证据：[MOOC 筛选截图](frontend/live-mooc-filter-20261013.jpg)、[完整候选卡片](frontend/live-mooc-filter-cards-20261013.jpg)。此前无替身浏览器表单提交及目录展开证据仍见 `browser-live-delivery-20261013.json`。

普通浏览器打开第一条实际搜索链接时首次导航等待超时，随后读取已经创建的页签，课程正文成功显示。页面确认北京大学课程和公开大纲，但显示“当前开课已结束”“老师已关闭该学期，无法查看”。**入口可达不等于课程可观看**；未继续登录、选课或媒体请求，未将这一人工观察写入生产元信息。[入口抽查记录](browser-mooc-entry-20261013.json)、[原页面截图](frontend/mooc-source-closed-term-20261013.jpg)。第二条 MOOC 的详情和播放仍未知。

## 平台政策与导航核对

[政策和导航报告](platform-coverage-policy-20261013-final.json)：每平台 4 个顶层页面尝试，原始 HTML、可见条款片段、来源与哈希均保存，未写正式 SQLite。

- MOOC：robots 为 404，这本身不是访问拒绝；官方协议和首页 HTTP 200，首页静态 HTML 未给出可见课程直链。协议 3.1 允许浏览课程信息，5.2.7 的接入范围仍需区分；保留 `policy_unreviewed`，不能称整站禁止访问。[官方协议](https://www.icourse163.org/topics/mooc_privacy_service/)
- 学堂：官方首页存在搜索/课程导航，课程索引可见，但 django 子域本次 DNS 失败，不能冒称页面拒绝访问。随后通过首页实际协议链接发现“网络行为准则”明确要求不抓取和批量下载，条款日期 2021-01-05；停止直接页面采集，更新为 `explicit_scraping_prohibition` / `site_policy_blocked`。这与搜索索引未命中是两项不同事实。[官方协议](https://www.xuetangx.com/app/protocol)
- 未重新请求已遇验证码/拒绝的一般 DDG、Qwant、Google 或失败的 Sogou 路径，未扩大允许列表或绕过安全验证。

## 离线回归与保留的失败

- 后端 **141 passed，26 subtests passed**：[JUnit](backend-tests-coverage-final-20261013.xml)。依赖侧 1 个 TestClient 弃用提醒保留。
- 前端 **15/15 passed**：[测试 JSON](frontend/e2e-results-coverage-final-20261013.json)。包含平台第六名课程可筛选、目录证据、移动端与异常状态；生产构建通过。
- 首次新增平台 fixture 缺少 canonical_url、前端标题断言未排除隐藏外链箭头、旧 capabilities 测试仍预期学堂 policy_unreviewed，均在修复测试后通过。初次后端及前端失败报告留存，不把它们当成功记录。
- 本轮未进行生产部署验收，也未声称跨账号、长期或全平台可观看。
