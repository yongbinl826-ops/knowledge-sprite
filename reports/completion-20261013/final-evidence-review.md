# 最后交付证据只读核对

2026-10-13。核对范围为读取时的 `final-report.md`、`platform-diagnostics.json`、`held-out-live.json`、B站/MOOC 浏览器记录，以及对应截图、历史 MOOC 记录、OpenLearn/MIT 探针、held-out 审计和 JUnit。没有联网、重跑真实请求，未修改生产代码或既有报告。官方发现修复的开发中状态和待生成的 `final-validation.json` 不作为错误。

纠正处理：主任务已确认下面两项，按保留原始记录的方式处理——表头改为“进入任务候选”，既有 B站 JSON 不覆盖，另用 `evidence-errata.json` 和最终报告明确更正截图状态，AX 错误标签保留为独立观察。下面记录的是纠正前读取到的问题；本审查不据此重写历史证据。

## 必须修正的两处事实口径

### 1. 任务候选被标为“原始候选”

位置：`final-report.md` 读取时第 35 行表头“原始候选 / 去重资源”。表中 36、23 来自 `held-out-live.json` 的 `jobs[*].final_job.progress.candidates_discovered`，等于各 `results.search_attempts[*].candidate_count` 之和，是 provider 过滤和单查询上限之后交给任务的候选，不是上游原始响应条目数。

| 任务 | provider_requests[*].raw_candidate_count 求和 | 进入任务候选 | 去重资源 |
| --- | ---: | ---: | ---: |
| 三个英文知识点 | 87 | 36 | 25 |
| 二分查找 | 142 | 23 | 20 |

最小修正：表头改为“进入任务候选 / 去重资源”，保留现有 `36 / 25`、`23 / 20`。如果另列原始响应条目，应使用 87 和 142，并注明是按搜索 HTTP 响应累计，仍包含跨查询重复条目。不能将它们解释成独立资源或课程数。

### 2. B站记录对已保存截图的描述不符

位置：`bilibili-browser-check.json` 第 32 行、JSON 路径 `$.player.screenshot_state`，当前为 `black Bilibili placeholder`。

直接查看 `bilibili-public-page.png`，播放器区域实际显示 Python 编程语言基础“第五章 列表、元组和字典”的课程封面和“正在缓冲…”字样，并非黑色 Bilibili 占位图。应将该截图说明改成与此 PNG 相符的状态，或者明确另一个观察的时间及对应图像。建议“课程封面与正在缓冲提示；未观察到推进的播放进度”。

`$.player.ax_error` 的“无法播放媒体”可保留为 AX 观察；不应因为截图有封面而推翻该观察，也不能将封面或缓冲状态认定为播放成功。`playback_verified=false` 仍准确。

## 已核对一致的关键边界

- 固定两个任务的搜索 HTTP 分别为 12、5，合计 17，搜索缓存均为 0。英文三个组均无展示；中文 9 个匹配资源、默认及 B站筛选各展示相同的 5 个资源，已识别课程族数为 0。
- 英文 `candidates_discovered=36 / resources_discovered=25`、中文 `23 / 20` 与原记录一致，只需纠正上述列名，不应改写原任务计数。
- 两任务 `final_job.fetch_diagnostics.counts_delta={}`、`events=[]`，实际目标页面/robots HTTP 为 0。中文 `details_attempted=details_completed=9` 是处理次数，不能解释为成功抓取 9 页。现正文已经说明这一点。
- 展示资源目录总计 0、播放标志 false；目录绑定检查是空集合一致性，不是目录提取成功。原 runner 的两个终态包含 partial，退出码不是内容覆盖验收结果。
- B站选集总数 15 来自已记录的 `1/15` 标签；本次审查没有从单张截图重新证明全部 15 个时长，也没有补写正式目录。两个 MOOC 的身份、入口和不同大纲/学期观察与各自保存的记录相符；没有按 URL 机构前缀猜改可见机构名称。
- OpenLearn 记录为 1 次 robots HTTP 403、0 字节，full-catalogue 目标页未请求。不能把该请求混入 held-out 两任务的页面计数。
- MIT 独立探针 target 3 + DoH 6 = 9，耗时 21.707 秒；sitemap 2,588 个 loc，其中 2,587 个课程版本子图与 1 个全站图。此探针没有递归课程子图或采集课程页，不能算新增课程发现通过。
- `backend-all-first.xml` 共 336 个 JUnit case，与正文“310 项 + 26 子测试”相容；补充 `discovery-tests.xml` 为 11 项，不应重复累计。前端冻结结果 expected=28、unexpected=0、skipped=0、flaky=0；renderer 最终 JUnit 为 18 项、0 failures/errors/skipped。
- renderer 的正例是固定合成 Course + 2 章；主进程退出观察、200ms 渲染阶段 deadline、ready 后立即取消、全子进程/网络隔离 unknown 在现报告中已分开，不应升级为真实站运行通过。
- 原 held-out 起止源码哈希一致性是该批次的边界；后续正在开发的官方发现来源不是该旧批次重跑，也不能将其未来结果追写为旧批次通过。

除上面两处外，在本次限定只读范围内未发现必须纠正的新数字、课程身份或处理/实际抓取混淆。此结论不涵盖尚未运行的官方来源修复验证及后续总验收。
