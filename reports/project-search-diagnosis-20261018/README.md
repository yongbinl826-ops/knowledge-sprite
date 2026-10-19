# 七个知识点缺课诊断与真实搜索复验

本轮针对 2026-10-17 的真实项目 `df08803b-9bea-4ac7-92d1-59a1874c1695`。旧报告和数据库保持原样；下文诊断来自旧证据，新的搜索结果另行记录，不能混作同一轮成功。

## 原因定位

前端并未隐藏课程：旧后端返回的 9 条 supported、3 条 partial 在前端全部保留；7 个无课程点的后端结果原本就为空。[显示层核查](baseline-display-audit.json)

| 项目知识点 | 已发现候选 / 已抓取 | 主要问题 |
| --- | --- | --- |
| k1 Python 脚本基础语法与运行 | 6 / 3 | 有基础语法课程和章节，但严格完整措辞及章节技术上下文限制阻止匹配；另有候选未轮到详情预算。 |
| k2 Python 本地文件路径处理 | 6 / 3 | 已取得“文件路径处理”“Pathlib”课程，因“本地”这一限定未逐字出现而被整体拒绝。 |
| k4 pandas DataFrame 列选择与列名处理 | 6 / 0 | 候选中有列选择、列名筛选、列索引调整，但搜索证据的组合匹配未过门槛，未进入详情队列。 |
| k5 pandas 数值类型转换与缺失值检查 | 6 / 3 | 有“类型转换与处理缺失值”来源；“数值”“检查”等限定及完整子项条件未获证明。 |
| k6 pandas 分科平均分、最高分与及格率统计 | 12 / 0 | 搜索词偏业务描述，返回泛课程和不相关网页；“及格率”的“及”还被当成连词错误拆分。 |
| k9 matplotlib 图表保存为图片 | 6 / 1 | 已抓到保存图片课程，但“图表”“为”等完整措辞条件导致拒绝。 |
| k10 pandas 统计结果导出 Excel | 6 / 1 | 已抓到导出 Excel 课程，未逐字证明“统计结果”，被整体拒绝。 |

以上“发现”不等于教学相关，“抓取成功”不等于播放或完整教学验证。每点均完成首轮查询，不能说后面几个知识点完全没搜。每批上限 12 次物理请求，主引擎、备用引擎、官方发现共用预算，两批各只完成约一轮长搜索词，平台定向词未执行。另发现预算异常会丢弃同一查询已经返回的候选，这是独立的结果保存缺陷。

## 本轮改动

- 首轮保留完整原词，第二轮加入经过技术名和安全检查的简洁模型检索词。最终匹配仍检查原知识点，扩展词不成为课程证据。
- 搜索预算中止时保存已完成响应中的真实候选，并标为部分完成；不增加请求、来源范围或访问权限，不缓存为完整成功查询。
- 物理请求预算优先分配到各知识点：预算足够时保护前两轮，预算较少时先保护首轮；可选备用来源达到本条份额后保存已返回候选并继续后面的知识点。全局上限始终先检查。
- 修复中文连词错误拆分；课程章节只可继承同一页面有来源证据的技术上下文，并同时引用章节和页面证据，不补造章节动作或跨章节拼成完整教学。
- 对明确证明操作但未证明项目限定的来源，采用受限的“部分匹配”，保留未知项；不降低全局相关性门槛，不把部分证据升级为完整支持。

## 验证范围

基线实际执行：后端 **1124 passed + 26 subtests**，0 失败；[基线摘要](baseline-summary.json)。离线测试与旧证据只读回放不算本轮真实搜索。

真实复验固定原项目已确认的 10 个知识点，沿用原输入、语言、平台偏好、技术版本和项目背景。新数据库仅恢复真实输入与分析作为未确认草稿，不导入旧确认、任务、候选、课程、章节或缓存。经正常确认和搜索接口发起 5+5 两批，每批仍最多 12 搜索请求、12 详情、240 秒。本轮不重新做项目分析，真实模型仅用于正常搜索关键词扩展及排序。

## 保留的中间真实试验

第一轮（本目录根部 JSON 和 `live/`）尝试将紧凑词放在首轮。真实返回 k1、k9、k10 各 1 条 partial，k7 有 1 条 supported；但 k3、k8 原有覆盖消失，不能据此宣称整体改善。因此最终代码恢复原词优先，并为原词和变体分配预算。[第一轮实测摘要](first-attempt-summary.json)。第一批实际完成 5 个知识点查询；“3 点后已耗 10/12”的中间观察揭示预算风险，不是发生遗漏的证据。

第二轮位于 `verified-rerun/`，使用最终查询顺序和预算分配。第一批 10 条逻辑查询全部执行，12 次物理请求；视频搜索源连续返回 timeout / unknown，主要备用结果为文字网页，因此没有视频抓取。这一上游状态单独保留，不能归因为词面规则，也不能把第一轮资源复制过来冒充该轮的新结果。

第二轮终态为 9 张卡片、4 个知识点有结果：k7 supported 4，k8 partial 3，k9/k10 各 partial 1。共 24 次搜索请求、12 次详情处理、10 条 fetched 资源、20 条章节。缓存命中为 0。容器源码与记录中的原因哈希确认，部分 unknown 实为 `Suspended: timeout`；不将其解释为封禁，也没有清除暂停或重启搜索服务。[第二轮对照](verified-rerun/comparison.json)、[来源故障证据](source-failure-diagnosis.json)。

第三轮位于 `final-live/`，在第二批视频源自然恢复之后，进行最后一次同配置、同代码、同预算的独立复测。项目 `fe4ca7d2-1674-475e-b20d-ac262e4269c6`，v1，正常确认后执行 5+5 两批。共 **24 次搜索请求、24 次详情处理、24 条 fetched 资源、331 条来源章节**；98 条资源记录包含尚未抓取的候选，不能当作 98 门课程。搜索/详情缓存命中均为 0；两批各 10 条逻辑查询，原词和变体均覆盖所有点，未记录上游失败。10 次扩词、2 次重排均为真实模型调用并成功；本轮没有再次调用项目分析。[原始对照](final-live/comparison.json)、[逐章核对](final-live/chapter-ledger.json)、[数据库备份校验](final-live/backup-manifest.json)。

第三轮原始导出显示 17 张卡片，其中 k1 的 1 张 partial 在人工抽查时发现误报：章节《【爬虫篇】http与https的区别创建与运行》并未明确讲授脚本运行，不能只凭“运行”二字成立。原始导出保持不变。复核后收紧规则，仅在同一观察明确绑定原目标对象时认可泛动作；另修复操作匹配借用后续“导入到”的方向、跨分句技术名以及空白绕过对象限定的问题。新的显示结果使用本轮刚抓取的同一批证据重新计算，单独保存，不代表第四轮搜索，也不导入前两轮或旧验收结果。

## 最终结果与未解决项

[打开最终项目页面](http://127.0.0.1:18122/?project=fe4ca7d2-1674-475e-b20d-ac262e4269c6&version=1)。最终有 **6/10 个知识点显示推荐**；按知识点与资源计有 16 条推荐（10 条 supported、6 条 partial），其中 **13 条已抓取、3 条仅有搜索证据**。同一知识点在多个功能下重复展示不增加此计数，也不把卡片数当成独立课程数。原 7 个空点中，k9/k10 新有已抓取的视频部分匹配，k2 新有尚未抓取详情的搜索候选；其余 4 点继续为空。

| 原空点 | 最终结果 | 本轮证据与剩余问题 |
| --- | --- | --- |
| k1 Python 脚本基础语法与运行 | 0 | 10 个候选、3 条已抓取；剔除仅凭爬虫章节“运行”的误报。当前取得的证据未确认原脚本目标，不能借泛系列标题补足。 |
| k2 Python 本地文件路径处理 | partial 1 | 《Python案例技巧51：文件路径处理》来自本轮真实搜索；该卡 `not_fetched/search_discovered`、0 章。“本地”限定未知。该点另有 3 条已抓取资源，但它们没有通过匹配，不能拿来替这张卡背书。 |
| k4 pandas DataFrame 列选择与列名处理 | 0 | 12 个候选，0 条抓取。标题涉及列筛选/索引等，但当前组合匹配未通过详情准入；仍存在检索用语与匹配召回不足。 |
| k5 pandas 数值类型转换与缺失值检查 | 0 | 10 个候选、3 条已抓取。标题证明类型转换/缺失值处理，尚未明确证明数值转换与检查；包含具体 astype 操作的部分候选未抓取，保留缺口。 |
| k6 pandas 分科平均分、最高分与及格率统计 | 0 | 7 个候选、0 条抓取；原词与变体仍主要返回泛 Pandas 系列，没有具体分科统计教学证据。“及格率”拆词缺陷已修，但修复不等于搜索一定有结果。 |
| k9 matplotlib 图表保存为图片 | partial 1 | 《AI Study … Matplotlib … 保存图片》已抓取，1 条真实章节；支持保存图片，原“图表”限定仍未知。 |
| k10 pandas 统计结果导出 Excel | partial 1 | 《Pandas多种方式导出数据到EXCEL》已抓取，1 条真实章节；支持导出 Excel，原“统计结果”限定仍未知。 |

原有 k3（读取 Excel）显示 5 条 supported、k7（柱状图）5 条 supported、k8（中文标签/坐标轴）3 条 partial。k3 中 2 张仅有搜索证据；k8 仍只证明坐标轴，不能从“P1/02-zimu”等章节名推断中文标签。331 条章节来自所有本轮已抓取资源，并非 331 条相关章节推荐；未匹配的章节不展示为推荐。

最终结果：[post-review-results.json](final-live/post-review-results.json)；独立核对：[post-review-checks.json](final-live/post-review-checks.json)；逐卡证据状态：[post-review-visible-card-ledger.json](final-live/post-review-visible-card-ledger.json)。39 项核查通过：同项目/版本/输入/选择/任务映射未变，原资源与证据逐字段未变，数据库全表逻辑摘要和 30 个原始 JSON、HTTP、模型审计文件摘要前后相同。仅删除 k1 的 1 条误匹配，新增 0 条，其他匹配未变。这是本轮真实抓取后的保守重算，不是额外真实搜索成功。

页面实际刷新恢复成功，版本、两批“部分完成”、真实封面、部分匹配卡片及空结果均已核对，浏览器控制台无 error/warn。[界面记录](final-live/ui-verification.json)、[页面文本](final-live/ui-final-ax.txt)、[截图](final-live/ui-export-result.png)。未测试视频播放，未宣称完整教学覆盖，未使用固定课程链接或旧结果补空。

人工逐卡相关性审查见 [最终证据审阅](final-live-evidence-review.md)。[交付检查](completion-checks.json) 确认本地配置及原验收 JSON/数据库哈希未变，本轮产物未发现服务端密钥，报告相对链接均存在；`git diff --check` 通过。前两轮临时服务已停止，18122 保留最终页面。

## 离线回归

- 修改前：1124 个后端测试及 26 个子测试通过，0 失败。第一次 PowerShell 参数格式错误未执行测试，日志保留；上述数字来自正确重跑。
- 预算修复阶段：1247 个后端测试及 26 个子测试通过，0 失败，68.66 秒。[阶段日志](backend-final-fair.log)、[JUnit](backend-final-fair.xml)。
- **最终代码：1276 个后端测试及 26 个子测试通过**，0 失败，65.31 秒；存在 1 条已有 Starlette 弃用警告。[最终完整日志](backend-final-reviewed.log)、[JUnit](backend-final-reviewed.xml)。
- 前端逻辑：**34/34 通过**。[日志](frontend-node.log)。本轮未改前端源码，未重新执行前端构建或完整浏览器 E2E；终态页面另做真实结果显示核对。
- 定向测试均包含在完整测试中，不重复计数。覆盖紧凑词顺序/边界、预算异常保留、逐点预算分配、旧数据库及空库导入、中文连词、章节证据绑定、操作方向及否定词等；Mock 只用于离线测试。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test frontend/tests/*.test.mjs
```

## 本轮文件与运行方式

本轮没有新增业务 API 或数据库表，不要求迁移/删除原库。此前项目分析、确认、分批和前端复选框等未提交工作保留。

| 文件 | 用途 |
| --- | --- |
| `backend/app/queries.py`、`backend/app/llm.py` | 原词与简洁变体的查询顺序及模型扩词要求 |
| `backend/app/providers.py`、`backend/app/service.py` | 预算中断保留候选、逐点请求预算分配 |
| `backend/app/ranking.py`、`backend/app/topic_operations.py` | 中文复合知识点、同页章节上下文与受限部分匹配 |
| `tests/test_compact_queries.py`、`tests/test_search_budget_preservation.py` | 查询和预算回归 |
| `tests/test_project_matching_diagnosis.py`、`tests/test_topic_operations.py`、`tests/test_platform_catalog_integration.py` | 匹配与证据边界回归 |
| `tests/test_project_search_revision_import.py` | 空库恢复草稿、确认门禁与事务回滚 |
| `scripts/validate_project_search_revision.py`、`scripts/run_project_search_revision.py` | 仅恢复真实输入/分析并通过正常 API 确认、真实搜索 |
| `scripts/summarize_project_search_revision.py`、`scripts/summarize_project_model_live.py` | 只读对照、证据及逐章核查；旧汇总增加不写文件选项 |
| `scripts/review_project_search_revision.py` | 同批真实证据在收紧后规则下的独立 GET 复核，防止原证据改写或结果混合 |
| `README.md`、本报告目录 | 使用说明、全部试验和验收证据 |

正常使用仍按根目录 README 启动既有服务。保留的最终验收页面使用下列命令恢复（端口已有服务时不重复启动）：

```powershell
.\.venv\Scripts\python.exe scripts/serve_project_acceptance.py --resume --port 18122 --output reports/project-search-diagnosis-20261018/final-live/live
```

复测新项目必须使用新的空输出目录，先启动不带 `--resume` 的验收服务，再运行 `validate_project_search_revision.py`，最后使用它输出的新项目 ID 运行 `run_project_search_revision.py`。不允许对已有结果目录重复导入或覆盖。具体参数见 [导入与正常 API 使用说明](revision-import-usage.md)。配置沿用服务端 `.env`；密钥不会进入浏览器或报告。
