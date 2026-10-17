# 补充实现与真实验收

2026-10-13，Asia/Shanghai；机器记录均保留 UTC 时间。此报告区分代码完成、隔离测试、真实搜索、页面观察和播放，不将其中一种替代另一种。

## 当前结论

此前的交付没有充分区分搜索发现、自动采集策略与普通浏览器验收，B站目录和另一门 MOOC 的页面检查也未补齐。这是验收与说明的缺口，不能用其他站点的成功样本代替。本轮已补普通浏览器实查：**B站样本公开显示 15 个分 P 及各自时长；MOOC 两个入口的观察不同，一门有大纲但学期关闭，另一门显示介绍和大纲标题却未出现条目。均未验证成功播放。**这些是浏览器观察，没有写入正式自动目录字段。

应用的取消、持久幂等、刷新恢复、缓存隔离、按知识点匹配、同来源课程身份和诊断已实现。真实固定批次发出 **17 次搜索 HTTP，0 搜索缓存命中**；二分查找展示 5 条 B站资源，三个跨学科英文知识点均为 0 个合格结果。**本轮课程覆盖扩展未通过；B站/MOOC 自动目录和播放未验收通过。**没有补假结果，也没有重新执行失败批次。

本机应用已重启到最终代码，运行于 [127.0.0.1:8000](http://127.0.0.1:8000)，单工作进程、全局并发 1。每任务最多 12 次搜索、12 个详情/目录页、240 秒期限，已保存在本机 `.env`。正式实例继续使用 SearXNG，新增官方 sitemap 来源为可选实现，`OFFICIAL_SITEMAP_FALLBACK=false`，没有将本轮失败的新来源默认启用。

## 实现内容与测试

| 已完成 | 实际验证范围 |
|---|---|
| queued/running 取消、保留已有结果、队列继续工作 | 独立任务取消等待子任务清理；隔离 HTTP 等待/取消、重复取消、后续任务、期限测试 |
| 相同进行中请求合并、Idempotency-Key 持久恢复 | 同键同请求跨终态/重启恢复，冲突 409；本次两个真实终态均同键返回原 job ID，没有新增搜索 |
| POST 响应丢失后的刷新恢复 | sessionStorage 仅保存未确认 body/key，页面显示原需求并提供继续入口；收到有效 job ID 即清除；隔离浏览器验证 |
| 目录失败缓存与查询摘要隔离 | 不把预算不足目录长时间缓存；失败目录最多短缓存并允许重新尝试；页面缓存剥离旧搜索回退字段与证据 |
| 普通课程准入、重定向与身份 | 可靠 Course 可作为课程，但不冒充视频；普通“课程笔记”CSS目录不能升级课程；实际安全响应 URL 可绑定证据，页面 canonical 不能冒充跳转 |
| 知识点匹配与课程分散展示 | 后续查询标题参与对应知识点排序；同课程首页/目录/讲次保留原记录，优先不同已知同来源课程；跨站镜像和未知归属不猜并 |
| 小预算来源查询、请求上限与诊断 | 可配置两个来源域名，仍保留全网查询；搜索响应流式字节限制，503 Retry-After 暂停；每任务脱敏 HTTP/robots 轨迹独立保存 |

最终后端全量 **372 项 + 26 子测试通过，18.29 秒**：[JUnit](backend-all-final-after-fallback.xml)。包含实际 Fetcher 重定向→提取→课程准入、官方 sitemap 集成/边界、备用来源失败隔离和独立联网预算包装测试。此前 310/362 项全量、11/51/61 项定向回归及 7 项 runner 回归是重叠测试集，不重复累加；362 项记录早于最终来源隔离修复，不能代表最终代码。现有 Starlette/httpx 弃用提醒保留。

前端最终 **28/28 Edge E2E 通过**，生产 build 通过，未捕获页面异常与未匹配 API/外部请求均为 0。6 条 console 错误来自主动注入的 503/断网 fixture。桌面 1536×1024、手机 390×844 已看图核对。这些测试没有连接真实课程站点：[前端报告](frontend-qa.md)、[最终测试](frontend-e2e-frozen.json)、[冻结哈希](frontend-freeze-manifest.json)。

详细实现依据：[后端生命周期](backend-lifecycle.md)、[身份/准入](identity-review.md)、[只读复核](read-only-review.md)。首轮后端 9 项失败、缺 Chromium、Edge fixture 与 StrictMode 假设不一致等原始失败记录保留，未覆盖。

## 固定真实搜索批次

输入与预算预先保存在 [scope-and-budget.json](scope-and-budget.json)。没有用这些英文主题开发来源适配器，没有替换失败样本，没有再次运行同批次。

| 输入 | 实际搜索 HTTP / 搜索缓存 | 进入任务候选 / 去重资源 | 展示 | 终态 |
|---|---:|---:|---:|---|
| Bayes theorem conditional probability；plate tectonics；supply demand elasticity | 12 / 0 | 36 / 25 | 0 / 0 / 0 | partial |
| 二分查找；偏好 B站、MOOC | 5 / 0 | 23 / 20 | B站 5；MOOC 0 | completed |

时间：`13:42:32.130249Z` 至 `13:43:12`，两个任务轮询耗时 26.418 秒、14.335 秒。真实任务 ID 分别为 `4682587d-f925-4219-8448-b3175c91937e` 与 `a75c3934-622c-4333-bc8b-ccc448f0add4`。

英文组的三个视频查询分别记录上游 timeout / unknown / timeout，备用 Bing 返回词典、购物、论坛等无关候选。三个限定 MIT/OpenLearn 的查询均收到 HTTP 200，但各 10 个返回链接都是外域，域名过滤后 0；这说明本次来源索引路径没有带来候选，不能推断这些课程网站没有内容，也不能仅凭 200 说搜索质量通过。

中文组的 MOOC 定向查询真实返回 5 个课程入口，保存在 provider candidate trace，未通过该细分知识点的相关性准入，因此没有以宽泛课程凑数。B站有 9 个匹配资源，默认/平台视图均取 5 个。它们有视频入口依据，但课程族、开课版本和讲次身份仍未知；**5 个资源记录不是 5 门独立课程**。

这两任务的实际目标页面/robots HTTP 均为 **0**，采集诊断 events 为空。中文任务 `details_completed=9` 指完成 9 次元信息处理，其中策略检查即停止；不能把它读成抓取了 9 个网页。没有新增已核验目录，播放标志均 false。另行 OpenLearn 探针有 1 个 robots HTTP，见下节；不要混入此批次计数。

[完整实时记录](held-out-live.json) 保存每条查询、原始引擎警告、响应过滤轨迹、任务快照、幂等重放及起止源码哈希；源码在该批次不变。[独立证据审计](held-out-audit.json) 确认展示链接来自保存的搜索证据、匹配证据 ID 存在、没有无依据播放宣称。目录为 0，因此目录逐行校验通过只是空集合一致性，**不表示有目录采集成功**。

原始 runner 的 `completed_cases=2` 表示两个任务有终态记录，含 partial；退出码 0 表示记录程序无异常，均不等于内容验收全通过。`displayed_catalog_rows` 是原始保存条目数，本次恰为 0；严格计数以独立审计为准。已保留 [实际执行脚本](live_completion_acceptance.executed.py)，当前维护脚本将字段改名以避免误读，未覆盖或重跑原始结果。

浏览器随后读取这两个真实 API 任务，操作 B站筛选、展开来源依据和异常记录，核对 unknown 身份、目录无证据提示和英文空结果；不是再次表单提交。[浏览器记录](live-browser-check.json)、[实际B站结果](live-bilibili-results.png)、[实际无结果状态](live-heldout-empty.png)。

## B站、MOOC 与其他来源诊断

精确 URL、UTC 时间、工具、HTTP/页面特征、分类和继续条件见 [platform-diagnostics.json](platform-diagnostics.json)。没有观测 HTTP 状态的浏览器操作保留 null，未把导航等待超时等同于页面不可达。

| 来源 | 本次实际观察 | 自动采集/未完成边界 |
|---|---|---|
| [B站样本](https://www.bilibili.com/video/BV1VZ4y1G7YB/?uid=425631565A34793147375942) | `13:24:51Z` 普通浏览器最终显示课程标题与“视频选集（1/15）”；15 项分 P 与时长可见。播放器出现“无法播放媒体”，未观察到推进的播放进度 | 自动获取许可未取得，正式路径按策略停止；未将人工目录灌入生产。不是“源站没有目录”。[记录](bilibili-browser-check.json) / [截图](bilibili-public-page.png) |
| [MOOC Linear Algebra](https://www.icourse163.org/course/NWPU-1207119809) | `13:26:45Z` 介绍、目标、先修要求可见；“课程大纲”标题下 0 条目，无可见播放入口 | 原因 unknown，不能推断源站无目录或必定需要登录/JS。自动采集范围待核对、平台目录适配器未完成。[记录](mooc-browser-check.json) / [大纲截图](mooc-outline-empty.png) |
| [MOOC 数据结构与算法Python版](https://www.icourse163.org/course/WHUT-1206307812) | 先前同日 `09:22:12Z` 浏览器已有可见大纲，显示“当前开课已结束”“老师已关闭该学期，无法查看” | 本轮未重访；没有登录、选课或播放。[历史记录](../browser-mooc-entry-20261013.json) |
| [OpenLearn robots](https://www.open.edu/robots.txt) | `13:21:30Z` 真实 HTTP 403，0 字节；目标 full-catalogue 页未发请求 | 停止路径，加入本机 `DENIED_FETCH_HOSTS=open.edu`，不重试拒绝路径。不是 HTML 解析失败。[探针](openlearn-probe.json) |
| [学堂在线协议](https://www.xuetangx.com/app/protocol) | 先前已读官方明确抓取限制；本次两个 held-out 任务未专门查询学堂 | 不新增直接遍历；历史搜索未命中与条款停止分别记录，不称整站不可浏览。[既有来源](../platform-coverage-policy-20261013-final.json) |
| MIT / Archive | 既有报告有允许页面和真实目录取证；本次固定搜索未新增这些来源结果 | 旧 4 文档、41 次目录观察属人工核对的 1 个 SICP 课程家族，不能当作本次新增独立课程。[旧报告](../adapter-evaluation-20261013/final-report.md) |

搜索无合格结果、网络错误/上游 unknown、许可未确认、明确拒绝、未实现适配器、未测试和解析失败各自记录。没有把“换抓取框架”当作权限、登录或访问限制的解决办法。

收尾复核纠正了两个表述：[勘误](evidence-errata.json)。36/23 是经 provider 过滤和限额后进入任务的候选，上游原始行计数分别为 87/142；B站保存截图实际显示 Python 课程封面及“正在缓冲…”，原 JSON 的 `black Bilibili placeholder` 描述不准确。AX 中“无法播放媒体”是另一观察，不是截图文字；没有观察到推进的播放进度，仍未通过播放验收。原始 JSON 和截图保留不覆盖。

## 动态页面实验边界

新增 [controlled-renderer](../../experiments/controlled-renderer/README.md) 为独立实验：现有 Fetcher 在隔离传输下预审资源，Node/Playwright 临时匿名 Edge context 仅离线 fulfill 与固定可审核 fixture 一致的 HTML/JS。路由先于页面安装，无 `route.fetch/continue`；不在清单中的资源、非 GET、媒体、任意导航等拒绝。remote 模式在启动浏览器之前拒绝，未接入生产，也未执行真实网站脚本。

最终 **18 项本地测试通过，60.10 秒**：[JUnit](controlled-renderer-final.xml)、[独立摘要](controlled-renderer-summary.json)。覆盖 JS 生成 Course 与 2 章、缺资源、私网/重定向、robots/策略、字节/资源/渲染阶段时间预算、POST、导航、frame、worker/WS/popup/WebRTC guard、取消、大输入以及驱动超时/坏 JSON 的异常留存。摘要包含实际合成 Course 名称、两章字段与证据绑定断言。历史失败轮次保存在 [追加式实验记录](controlled-renderer-offline.json)，attempt 数不等于 pytest 测试数。200ms 是页面渲染阶段预算，不含 Edge 启动与清理；取消仅验证 ready 后立即取消。这些是合成结构验证，不能计入真实课程或目录成果。

Node 退出与启动过的 Edge **主进程**退出有观察；操作系统级全进程外联、浏览器背景通道、WebRTC UDP 与所有子进程隔离仍 unknown。offline 加路由不构成全出口隔离证明。没有修改系统防火墙或降低浏览器安全设置，任意第三方脚本的生产渲染仍 fail-closed。真实且允许、确需 JS 的来源渲染链路尚未验证。

先前 Scrapling 0.4.15 仅对保存的 HTML 使用 Selector 做解析对照，未采用其网络/反风控能力，未加入生产；Crawlee 只是官方资料研究。这些工具研究不代表 B站/MOOC 自动获取已通过。

## 后续独立发现探针

MIT 官方 `/search/` 与 robots 实际声明的 sitemap 已完成独立小预算验证：[预注册范围](mit-discovery-probe-scope.json)、[原始结果](mit-discovery-probe.json)。`13:51:55Z` 开始，共 21.707 秒；目标 HTTP 3 次、DoH 6 次，总计 9 次，全 200，无重试、无重定向、无截断。搜索页 9,835 字节，没有课程链接或 GET 表单，仅可见 JS search mount；没有猜 API 或请求脚本。robots 声明的 `https://ocw.mit.edu/sitemap.xml` 返回 363,036 字节，包含 2,588 个 loc：2,587 个课程版本分 sitemap 和 1 个全站 sitemap。探针按预注册没有递归访问子图，也没有请求课程页。

据此已实现可选 `OfficialSitemapProvider`：按 robots 的真实声明读取根索引，每个原知识点默认最多 1 个匹配的子索引，只接纳其实际 `<loc>`；不把路径词当页面标题或教学覆盖。完整知识点与版本约束、真实页面类型与内容证据仍需分别通过。官方源失败保留独立 trace/warning，不会连带停止正常主搜索的后续知识点；主搜索自身拒绝仍停止。索引按来源/策略/TTL 缓存，官方模式或启用该回退时不再外包查询结果缓存，避免延长旧索引寿命。实现和只读审查见 [实现说明](official-sitemap-implementation.md)、[审查报告](official-sitemap-review.md)。

**唯一修复后实网验证仍未通过。**[预定范围](official-repair-scope.json) 使用开发后选择的 `probability / geology / microeconomics`，属于修复验证，不是独立 held-out。真实生产 JobService/Provider/Fetcher/提取器使用全新隔离 SQLite，未读取旧 XML 作为候选；独立传输/解析包装限制 12 次目标 HTTP、24 次 DoH、并发 1、零重试，逐次检查 MIT 同源，失败后停止出站。

实际 `14:29:54.828275Z` 至 `14:30:12.957273Z`，18.109 秒：robots 200、64 字节；随后 sitemap 请求 10.009 秒超时，HTTP 状态未知。目标 HTTP **2 次**、DoH **4 次**、合计 **6 次**，所有预算未越界。底层记录为被超时取消的 `CancelledError`，Fetcher 上层明确为 `TimeoutError/search_timeout`；不是用户取消。之后两个知识点仅返回来源已停止的失败状态，各 0 次新出站。3 次查询调用不等于 3 次联网尝试，`network_attempted=true` 只表示进入 provider 调用，实际 HTTP 以 request trace 为准。

终态 `failed`，0 候选、0 课程身份、0 目录、0 缓存命中，未到达任何子 sitemap 或课程页。runner `errors=[]` 和退出码 0 仅表示记录程序正常完成，不代表内容验证成功。[完整原始记录](official-repair-live.json) 与隔离数据库均保留；源码前后哈希一致，旧 held-out 文件哈希不变。没有重试、延长超时或换样本。此前索引探针成功不能覆盖此处失败；新来源真实“索引→课程页→目录”链路仍未通过。

用临时本机 8001 服务读取该真实任务并在现有 UI 展开失败原因，确认“检索失败”、三个知识点 0 结果、来源范围与超时提示，console error/warn 为 0：[浏览器记录](official-repair-browser.json)、[截图](live-official-repair-failed.png)。没有再次提交查询，临时页与服务已关闭。

原 held-out 不变，不再请求原失败的 DDG/Bing 查询，不重试 OpenLearn 403，不将保存的 XML fixture 作为生产候选库。

## 未完成范围

- 新跨学科知识点稳定覆盖没有通过本轮真实检索；官方 sitemap 实现通过离线回归，但修复实网在根索引超时，真实课程页/目录链路未到达。
- B站/MOOC 的自动目录、全课程播放、学堂课程发现没有取得新的通过证据。
- 动态渲染仅固定本地 fixture 实验，真实站生产桥和全部出口隔离未完成。
- Tavily、可选 LLM 没有本次凭据/联网验收；仍使用既有 SearXNG 与规则排序。
- 当前是本机单进程应用，没有公网部署、鉴权、长期稳定性或跨账号播放承诺。

依赖锁、前端冻结包、旧批次哈希、最终代码与运行参数见 [final-validation.json](final-validation.json)。前序所有失败/成功报告保留，未清除正式数据库，也未改动其他文献工作目录。

## 运行方式补充核验

原 [final-runtime.json](final-runtime.json) 是 `14:35:33Z` 的瞬时观察，不是长期运行证明，文件保留不覆盖。后续关于旧 PID 不存在的观察，在本任务 `14:39:32Z` 的独立进程/端口检查和 `14:40:16Z` 的 localhost HTTP 检查中未复现：旧 PID 64780 当时仍在运行，健康接口正常，见 [迁移前复查](runtime-recheck-20261013.json)。

确认正式库没有 queued/running 检索后，为脱离工具启动会话进行了计划迁移：停止已核实身份的旧服务，使用 Windows `Start-Process -WindowStyle Hidden` 启动后台进程，输出重定向到项目内日志，启动命令正常退出。没有修改配置或发起课程检索。[后台启动记录](background-launch.json) 与启动命令退出后的 [独立复查](background-runtime-check-1.json) 分别保存时间、进程身份、监听和接口证据。`14:42:08Z`（北京时间 22:42:08）确认实际服务 PID 11204、父进程 50196、仅绑定 `127.0.0.1:8000`，health 为 ok，SearXNG、官方回退关闭、并发 1 和 12/12 预算均保持原值。这是当前跨调用核验，不是重启或长期稳定性保证。

`14:43:44Z`（北京时间 22:43:44）的 [第二次独立复查](background-runtime-check-2.json) 再次确认同一 PID 11204、health ok，以及 8000/8001 中只有一个监听：`127.0.0.1:8000`。旧 PID 此时已因上述计划迁移退出。监督侧与目标运行环境的早期观察视图不一致，原因未确认；本次是后台启动方式调整，不能倒推此前停服已获证实。未创建计划任务、开机启动项或系统服务，也未扩大网络绑定范围。
