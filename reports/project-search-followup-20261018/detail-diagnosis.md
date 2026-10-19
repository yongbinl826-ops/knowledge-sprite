# 详情准入与排序诊断（2026-10-18）

结论：k2 的唯一可显示 partial 候选在首轮就已发现，但旧详情队列优先词面分数，使 3 条没有明确主题支持的候选先占用了详情机会。k4、k6 则是没有通过既有准入；仅改变队列顺序不能解决这两个点，也不应把泛系列强行送进队列。

本诊断只读 `../project-search-diagnosis-20261018/final-live/live` SQLite 和该轮原始导出，以资源自己的搜索证据重建抓取前候选，未请求课程网络、未读密钥、未修改原数据库或旧证据。逐条数据、时间戳和源哈希保存于 `detail-candidates-before.json`。重建使用诊断时的匹配版本；其他代理随后修改的语义匹配不属于这份原始排序快照。

## k2 的具体排序原因

知识点：`Python 本地文件路径处理`。该轮有 10 个去重候选，7 个通过已有 relaxed 准入，3 个实际抓取。以下为最终候选集合按旧队列规则的前 4 名；分数基于各候选真实搜索标题/摘要，未使用抓取后目录补证据。

| 旧次序 | 候选资源 | 标题 | 词面综合分 | 明确主题证据 | 原轮抓取 |
| --- | --- | --- | --- | --- | --- |
| 1 | `res_787dfd1a26763ec64d9d4b6e` | python教程-读取本地文件并打印-绝对路径-相对路径 | 53.75 | unknown | fetched |
| 2 | `res_cd7fb5982692de7e3fef090d` | Python教程：Pathlib--处理文件路径的现代方法 | 53.75 | unknown | fetched |
| 3 | `res_f395348b44b14c0ec4cf97c4` | Python教程Pathlib - 处理文件路径的现代方法 | 53.75 | unknown | fetched |
| 4 | `res_464422ad1a4e95dd67c47154` | Python案例技巧51：文件路径处理 | 48.75 | partial，搜索证据 ID 存在 | not_fetched |

partial 候选首次发现于 `2026-10-18T12:20:41.187304+00:00`；上述实际抓取分别启动于 `12:20:58.789628`、`12:21:29.818847`、`12:22:00.559257`（均 UTC）。因此它没有详情不是因为发现太晚，而是相同学习证据等级下的词面分数优先压住了明确 partial。这里的 3 次是该轮轮转与全局 12 页额度实际分配结果，并非新增的每知识点固定上限。

`path-candidate-probe/result.json` 是主代理另行执行的独立真实详情探测，不属于原项目结果，也不导入下一次搜索或缓存。该探测与这里的只读诊断必须分别报告。

## k4、k6 的边界

- k4：12 个去重候选、0 个准入、0 个抓取。部分标题明确提及“选择行与列”“指定列名筛选”，但原匹配契约没有为请求里的技术/操作组合提供可审计支持。需要先由语义匹配模块验证核心操作及仍 unknown 的限定项；详情队列不负责创造匹配。
- k6：7 个去重候选、0 个准入、0 个抓取。候选主要是全套 Pandas 系列，不能仅凭技术词推断覆盖分科平均分、最高分、及格率。没有明确统计证据时保持空结果。

## 实施的最小通用改动

只改 `backend/app/service.py::_detail_queues` 的排序键：已通过原 provisional 准入的候选，如果其 `topic_evidence_status` 是 supported/partial，且非空 `supporting_evidence_ids` 全部存在于当前资源、本点可用的真实 search/page/catalog 证据中，则先于纯词面分数候选取得详情验证机会；同组继续使用原学习证据、分数、稳定资源 ID 排序。缺失证据、其他资源证据和非当前知识点搜索证据不能获得该优先级。

原准入调用、官方 sitemap 限定入口、知识点轮转、已启动去重、host 并发、全局请求数、详情预留、来源暂停、缓存与最终卡片匹配标准均未改变。没有 URL/标题特例，没有提高默认 12 次详情额度。排序不保证页面可访问或能补足主题证据；抓取失败、访问策略和 partial/unknown 必须保留原状态。

## 已执行的离线验证

新增 `tests/test_followup_detail_admission.py`，10 个测试全部通过，使用明确的合成 URL/响应，不访问网络。其中覆盖低分但有真实证据的 partial 优先、只有 1 次详情预算时选择该候选、访问策略状态不升级、泛系列不新增准入、既有词面候选不变成最终匹配、已启动不重复，以及空/悬空/其他资源证据 ID 不能获得优先级。

联合预算保留、公平请求、任务生命周期、项目确认/分批/取消等回归共 **180 passed**；只有现有 Starlette/httpx 弃用提示。结果见 `detail-admission-regression.xml`。

命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_followup_detail_admission.py tests/test_search_budget_preservation.py tests/test_discovery_completion.py tests/test_completion_repairs.py tests/test_core.py tests/test_job_lifecycle.py tests/test_projects.py tests/test_project_boundaries.py -q --junitxml=reports/project-search-followup-20261018/detail-admission-regression.xml
```

本报告不宣称这次排序已完成新的真实搜课验收；后续新空库、相同 12/12 预算的运行由主代理独立采集。
