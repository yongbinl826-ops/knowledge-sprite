# 本轮匹配诊断与保守修复（2026-10-18）

本记录使用上一轮 `reports/project-search-diagnosis-20261018/final-live/live/live.sqlite3` 的真实证据做只读重放，另审阅本轮独立详情探测 `path-candidate-probe/result.json`。重放没有搜索、抓取或修改旧数据库；它不是本轮重新实网验收。新的完整搜课由主代理独立执行。本次未读取密钥、未改变查询额度或平台访问规则。

## 原因与本轮范围

| 知识点 | 上一轮缺口 | 本次证据边界与修复 |
| --- | --- | --- |
| k1：Python 脚本基础语法与运行 | 真实简介/标题明确基础语法，但没有脚本限定；爬虫 p37 的“创建与运行”没有脚本对象，不能支持运行 | 基础语法单列为 supported 核心；脚本基础语法、运行仍 unknown。原泛动作对象绑定保留，未把 p37 加回 |
| k4：pandas DataFrame 列选择与列名处理 | 候选“选择行与列”的中文语序与“列选择”不同；标题只出现 df/Series，不能推断 df 就是 DataFrame；旧候选尚未抓取 | 同一文字对象/动作的倒序可匹配；仅 pandas 上下文时展示列选择核心并明确 DataFrame 类型未确认。列名处理仍 unknown，不把筛选/修改视作同一动作 |
| k5：pandas 数值类型转换与缺失值检查 | 已抓课程讲类型转换和缺失值处理，但泛类型转换不证明数值目标，处理也不证明检查 | 单列类型转换核心；明确“检测与处理缺失值”可支持检查子项。只在同一教学语句且 API 所属明确时，按规范承认 to_numeric、明确数值 dtype 的 astype、isna 的精确操作 |
| k6：pandas 分科平均分、最高分与及格率统计 | 上轮 7 个候选均无足够具体统计教学证据，没有详情抓取 | 保留空缺。规范 mean/max 教学最多支持平均值/最大值计算核心，不能补分科、成绩语义或及格率。旧库实际没有可满足这些边界的课程 |

以上规则由原知识点拆分结果驱动，没有硬编码项目名称、知识点 ID、课程标题或网址；原始知识点和原子项不会被替换成更宽泛的请求。新增核心支持不能使整点升为完整支持；缺失限定继续显示 unknown。原子项的集合覆盖统计仍只统计原始子项。

## 上一轮真实证据只读重放

逐资源完整输出在 `frozen-evidence-replay.json`。下表计数为同一知识点名下、当前规则可匹配的候选资源数，**不是本轮新搜到的数量，也不是前端去重和展示上限后的卡片数**。不同知识点可引用同一资源，不能把各行加总当作唯一课程数。

| 点 | 当前可匹配候选 | 其中旧库已抓取详情 | 支持范围 |
| --- | ---: | ---: | --- |
| k1 | 5 partial | 3 | 仅基础语法核心；没有任何获支持的章节 ID |
| k2 | 1 partial | 0 | 文件路径处理核心；本地限定 unknown |
| k4 | 1 partial | 0 | 列选择核心；DataFrame 类型与列名处理 unknown |
| k5 | 6 partial | 2 | 5 个泛类型转换核心、1 个缺失值检测子项；数值转换均未被这些候选证明 |
| k6 | 0 | 0 | 保持无匹配 |

可核验的代表证据：

- k1 `BV1LEt86SEBN` 的简介 `ev_940bbe5e-b1e7-47e4-bd5a-511e319c71cc` 明确写“包含基础语法、进阶语法…”，只支持基础语法核心。同资源 p37“【爬虫篇】http与https的区别创建与运行”不在 supporting_evidence_ids 中。此次重放该资源的支持 ID 只有原搜索记录 `ev_e78e64ba-2daf-496f-b1e2-c56daddbc9a6` 与该简介，没有章节。
- k4 `BV167YLepEfo` 原搜索记录 `ev_6d02d07c-85e8-4a2d-badf-31125e7aa59c` 标题为“2.Pandas教程_df与Series基础-选择行与列-[Python]”。它证明候选在讲列选择，不证明 df 类型、列名处理或详情抓取成功。
- k5 `BV167YLepE26`、`BV1UT411y7cT` 有真实同题章节，分别讲“类型转换与处理缺失值”“数据类型转换和缺失值…处理”。只给类型转换核心支持；未把处理写成检查，未把通用类型转换写成数值转换。
- k5 `BV17tfoBqEbB` 的原搜索证据 `ev_e763f80f-347c-4774-bc31-184fea601073` 明确“检测与处理缺失值”，只支持检查子项；旧库未抓详情，不补章节。
- k5 两个 astype 相关标题虽提到百分数/千分位数字，本次仍仅给通用类型转换核心，未从“数字”推断精确 dtype 或整个数值转换流程。

## k2 独立详情核对

主代理本轮对 `BV1ED1yY2Eo6` 做了独立详情探测：robots 与课程页共 2 次物理请求均返回 200，解析状态 fetched，得到 1 章；详情标题和章节均为“Python案例技巧51：文件路径处理”，简介为“讲解文件路径相关的处理方法！”。章节证据 `ev_97bdad9d2a93e429c664`。这些数据证实文件路径处理教学线索和真实章节，但没有明确本地路径限定，也没有验证播放。该探测标明 `new_search_performed=false`、`injected_into_search_results=false`、`end_to_end_acceptance=false`，未被导入新的搜课任务冒充新检索结果。

## 规范依据与负例保护

- [pandas.to_numeric](https://pandas.pydata.org/docs/reference/api/pandas.to_numeric.html) 明确定义数值转换；[DataFrame.astype](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.astype.html) 接受指定 dtype，因此 bare astype 不等价于数值转换。本实现只有显式 int/uint/float dtype 才作这一精确判断；任意字符串、category 等保持泛类型转换核心。
- [pandas.isna](https://pandas.pydata.org/docs/reference/api/pandas.isna.html) 检测缺失值；fillna/dropna 不能代替检查证据。
- [DataFrame.mean](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.mean.html) 和 [DataFrame.max](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.max.html) 支持平均值/最大值计算，不能自动证明成绩、分科或及格率。idxmax 不当作 max。
- [DataFrame.rename](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.rename.html) 可重命名行或列。本路径必须看见显式 columns 参数才支持列重命名核心，仍不声称完整列名处理。

新增路径排除先修、否定、旁列 API、顺带提及、另见、弱观察。规范 API 必须是独立教学名称或明确标准 receiver；自定义 helper、statistics、未确认类型的 df 等成员不做标准 API 等价。紧邻教学核心/动作的明确技术标识必须归属于当前上下文，不能把 SQL/HTML/PHP/Lua 的基础语法归给 Python，也不能把 Polars 列选择归给 pandas。未覆盖的措辞或归属保持 unknown。

已把独立审阅复现的 17 个反例纳入测试：相关 API 列表、顺便提及、helper.to_numeric/isna/astype、statistics.mean、max 不是最大值教学、不包括基础语法、外部语言基础语法、Polars 列选择、已弃用不建议使用、本视频不涵盖等全部不生成新增支持。

## 本次实际测试

新增 `tests/test_project_followup_matching.py`：82 项通过。连同原匹配、操作边界、来源证据、修复、平台目录与核心测试，实际执行 **347 passed**（1 条现有 Starlette/httpx 弃用警告）。命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_project_followup_matching.py tests/test_project_matching_diagnosis.py tests/test_topic_operations.py tests/test_evidence_followup.py tests/test_completion_repairs.py tests/test_platform_catalog_integration.py tests/test_core.py
```

测试使用明确标注的 synthetic evidence，仅证明离线规则行为。完整回归和新空库实网联调由主代理另行记录；本报告不替代其验收结论。此文件完成时生产匹配代码已冻结，后续不为增加命中数量扩大规则。

## 页面审阅后的收紧与最终回归

上文为第一次冻结时记录。整项目实际运行后，页面人工检查发现一条 SigmaPlot 视频，搜索摘要通过 `#matplotlib` / `#python` 标签造成错误支持，且详情并未成功抓到。随后仅对搜索观察的评分副本排除独立社交标签；原始 search evidence、课程页和目录记录不被删改，代码中的 C#、预处理行和格式化代码仍保留。新增 16 项正反测试。

该收紧使一条旧真实 SQL 正例暴露了既有分值问题：非标签文字已明确 MySQL 与 ROW_NUMBER，既有 `sql_row_number_is_window_function` 规则也给出支持，但删除标签后旧词面折扣再次拒绝该卡。因此只给**同条已支持证据通过这一既有精确规则**的候选增加与既有规范形规则相同的分值保护；没有恢复标签、增加语义等价、修改原测试期望或放宽全局门槛。新增 7 项覆盖无标签正例、仅 #SQL、Python/NoSQL、错误 RANK 及跨观察借词。

最终该专项文件 **105 项**，含存档正例的关联回归 **392 passed**；完整仓库最终 **1422 passed、26 subtests passed**。最后完整测试之后没有再改生产代码。详见主目录实施记录与原始日志。

主运行的只读 GET 真正移除了已入库的 SigmaPlot 卡，其他卡片/匹配未变；原始终态和 HTTP 证据保留。独立三点新搜索也自然返回该候选，但未进入有限保留集合，不能把这一次未展示当作最终 rank 拒绝；新 trace 的离线规则重放仅确认无正向教学信号，见 `query-guard-live/manual-review.md`。
