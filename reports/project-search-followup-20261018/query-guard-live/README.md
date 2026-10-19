# 最终查询与标签保护：独立真实补测

这是最终生产代码通过 1422 项后端回归后进行的一次真实补测，单任务 `7ff5313e-1ac3-498d-b0fc-3c9b61f8a440`，服务端 `http://127.0.0.1:18124`，终态 `partial`。只从主运行的请求中取语法、文件路径、matplotlib 柱状图三个原始知识点与相同背景；没有导入旧资源、旧匹配、搜索响应或缓存，也不把本次课程合入主项目。

原始 `submission-plan.json` 证明提交前 projects/jobs/resources/evidence/search_attempts/cache 均为空。服务在实际提交前以 `--resume` 重启以装载最终规则；这是恢复空库，不是复用旧搜索。`final-runtime-checks.json` 核对运行源码和前端构建与最终文件一致，环境配置未变。

| 项目 | 实际结果 |
| --- | --- |
| 真实模型 | 3 次关键词扩展、1 次重排，均 HTTP 200 / JSON；未重新项目分析 |
| 搜索 | 7 条逻辑查询，12 次实际请求；6 条查询成功、1 条上游超时失败 |
| 详情 | 12 次处理；10 个 fetched、2 个 not_found |
| 缓存 | 搜索与详情缓存命中均 0 |
| 真实目录 | 416 条逐字段与来源一致；不等于 416 个相关学习章节 |
| 语法 | 共 6 条部分支持，默认显示 5；不宣称脚本运行完整覆盖 |
| 文件路径 | 1 条部分支持，当次重新发现并抓取同一候选、1 个真实章节 |
| 柱状图 | 共 7 条支持，默认显示 5；支持并不代表已观看验证整课 |

唯一失败查询是 `命令行运行 Python 3 脚本文件 视频教程`。聚合服务 HTTP 200，但视频引擎记录 `timeout` / `upstream_engine_failed`；不能把传输成功当作有效结果。此次仍严格采用单任务 5 点、12 搜索、12 详情、240 秒上限，无来源暂停重置。

查询短语确实变化，语法不再只是重复原词再加“入门”。路径实际第二条是 `Python 本地路径处理：读取 Excel 路径并拼接输出目录 视频教程`，短语在上限内但仍带业务描述；柱状图变体仍带“保存图片”。不能声称模型总能输出最短或最佳表达。匹配始终针对原始知识点，额外扩词不被当作课程支持。

SigmaPlot 在本轮二次查询的原始候选 trace 中确实返回（index 12），但没有进入最终保留的 6 个 URL，因此数据库没有该资源/匹配。不能把“不在结果里”冒称“这次在线最终排序明确拒绝”。对这条新 trace 的离线只读重放得到 `candidate_topic_signal=False`；这是规则复核，与真实搜索结果分开。主项目里已经保存的 SigmaPlot 卡则由正常结果 GET 重新评估后实际移除，见主目录 `post-review-checks.json`。

证据：原始 `job.json`、`results.json`、`live/jobs/` HTTP 审计、`live/model-events.jsonl`；独立只读审计见 [supplemental-audit.json](supplemental-audit.json)，所有结构、预算、来源引用检查通过。具体查询和全量候选相关性另见 [逐项审阅](manual-review.md)。`live-evidence.sqlite3` 为终态只读备份。没有 Mock、固定链接注入或旧课程补齐。

现有章节定位仍可能漏推荐：本次 4 张已抓详情的 Matplotlib 卡有相关目录，但当前前端标题规则没有选出章节；只有路径卡显示了实际推荐章节。另有一个仅搜索发现的抖音聚合入口只在 `other` 平台列表，相关摘要、具体单条视频身份、页面和播放的验证等级不同，不能把它当作已抓详情的课程。以上限制与全部 14 条数据库匹配均在逐项审阅中列明。

本次命令只记录复现方式；已有输出采用独占写入，重复执行会拒绝覆盖，新的网络运行应选择新的输出目录：

```powershell
.venv\Scripts\python.exe -u scripts/run_query_guard_validation.py --source-job reports/project-search-followup-20261018/live-run/06327234-488c-4503-bed4-465dbf6cce3b-job.json --source-job reports/project-search-followup-20261018/live-run/7c564271-24bd-4c3a-a138-c660d0343161-job.json --point-index 0 --point-index 1 --point-index 6 --output reports/project-search-followup-20261018/query-guard-live --base http://127.0.0.1:18124
```
