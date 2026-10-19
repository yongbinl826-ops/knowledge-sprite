# 本轮真实第二批结果审阅

审阅任务 `7c564271-24bd-4c3a-a138-c660d0343161`，终态 `partial`。本报告只读取本轮 `live-run/project-results.json` 对应批次，以及 `live-run/live/jobs/7c564271-24bd-4c3a-a138-c660d0343161/{results,job}.json` 和新 `live-run/live/live.sqlite3`。SQLite 以 `mode=ro` 打开；没有补搜、联网、修改生产代码或混入旧结果。

第二批 `results.json` SHA-256：`da3dfbdfb91131e73ee03b2d428b248eb4f877188ab8732cea972b077992562f`。本审阅由代理核对真实来源文字和结构化证据，不代表用户本人逐项确认或视频观看验证。

## 结论

k6 的无结果由**本轮已返回候选过于宽泛、第二条查询遇到上游故障，以及剩余搜索能力受预算限制**共同造成，不是遗漏了 k6，也不是 k6 课程页抓取失败。k8 的唯一部分支持卡边界合理；k9、k10 本轮无有效卡，不能用之前运行中的课程补充本轮成绩。审阅范围内未发现新增的支持误判；保留 `partial` 和上述缺口。

## k6 两条实际查询

知识点：`pandas 分科平均分、最高分与及格率统计`；本轮知识点 ID `142db8d9-03aa-4a86-b6c3-a48bddb06c2d`。

| 时间（UTC） | 实际查询 | 上游与返回 | 预算影响 |
| --- | --- | --- | --- |
| 2026-10-18 13:11:58 | `pandas 分科平均分、最高分与及格率统计 入门 视频教程` | SearXNG 的 duckduckgo videos 请求 HTTP 200，56 条原始候选，保留 6 条入库，`topic_signal_count=0`、`no_topic_signal` | 本条 `priority_request_limit=1`，继续备用来源时触发 `query_budget_exhausted`；已返回的 6 条被保存，未被错误算作整点成功 |
| 2026-10-18 13:12:15 | `pandas 按科目分组统计平均分、最高分和及格率 视频教程` | 请求确实发出，SearXNG HTTP 200，但上游返回 0 候选及 `upstream_engine_failed` | 同样只有 1 次优先请求额度；没有把原词的复合查询拆成更多任务来绕过额度 |

第二条来源警告的结构化 `reason_code`、`reason` 都是 `unknown`，原文未保留，仅有 SHA-256：`6c90b1014a9eabe5143c08002e6186b5aba390f3a48fb460c186e520be6071c2`。本地计算已核对它与字符串 **`Suspended: timeout`** 的 SHA-256 完全一致，因此“视频搜索源因超时暂停”是有哈希比对依据的解释；本报告不把结构化字段改写成已直接记录的 `suspended`。同批其它查询另外明确记录了 `timeout`，SearXNG 的 HTTP 200 不代表其内部搜索引擎查询成功。

第二批总计计划 30 条逻辑查询、执行 10 条，消耗 **12/12 次搜索请求**；详情处理 **9/12**，不是 12 次详情额度已全部用尽。k6 的全部 6 个持久化候选都为 `not_fetched`，没有课程页面抓取或解析失败事件可归因于 k6。它们在初始证据阶段未提供需要的具体教学线索，因而没有变成详情抓取的有支持候选。本次未通过提高额度或放宽类型/匹配门槛强行补结果。

原始响应 56 条不等于 56 门已逐条保存课程：候选审计只保留前 20 条 trace，另外 36 条明确标为 omitted。以下逐条审阅覆盖**全部 6 个实际入库的 k6 候选**，不声称阅读了未保留的 36 条原文。

## k6 全部入库候选

以下 6 条都有搜索模板提供的视频类型依据，但仅有搜索标题/摘要；没有实际目录，也没有本轮详情抓取。

| 课程 ID / 本轮搜索证据 ID | 标题与摘要提供的信息 | 为什么不推荐给完整 k6 或其核心统计子项 |
| --- | --- | --- |
| `BV1bPtP6PEC8` / `ev_d6f047ec-411a-4275-b7e1-99a47fe80399` | “【全42集】Pandas数据分析从入门到实战”；摘要列安装、Series 创建、DataFrame 创建 | 没有平均分、最大值、及格率或可确认的 mean/max 教学证据 |
| `BV1yLcDzMEfi` / `ev_031cc3a6-ae7b-453c-b088-380afadc5fa4` | “Pandas 零基础入门到精通教程（全44集）”；摘要列 Anaconda、Jupyter 启动和单元格状态 | 环境与工具入门不证明统计计算 |
| `BV1tzTs6MEqY` / `ev_adef7490-41a2-4647-b501-3da3ce7a3406` | “【全57集】Pandas数据分析入门到实战教程”；摘要列安装、Series、DataFrame 创建 | 泛数据分析标签不证明成绩统计或明确聚合操作 |
| `BV1qU7U61EZw` / `ev_ed11e8bc-9abd-4039-b3f3-363c1836a2dc` | “【全92集】Pandas数据分析入门到实战教程”；摘要只有零基础学习宣传 | 缺少任何具体 k6 教学线索 |
| `BV1dn7C6bE3Y` / `ev_a3e1dc33-9940-4769-8a95-e13ad1fff7cc` | “【全60集】Pandas数据分析零基础入门到实战教程…”；摘要列安装、Series、DataFrame 创建 | 不能借课程总集数或“实战”宣传补全均分、最高分、及格率 |
| `BV1LhwazuEi8` / `ev_17754268-e1f5-4cd0-9ab1-102bfcc9143d` | “2026年最佳Pandas数据分析教程，一口气学会Pandas全部用法”；摘要列 Anaconda/Jupyter | “全部用法”不是每个具体统计动作已经被证明的证据 |

因此 k6 的 `total_matches=0`、`total_partial_matches=0`、三项原始子题均 unknown，符合本轮实际可见证据。不能进一步断言这些课程实际视频里完全不讲统计，只能断言本轮尚未取得足够证据。

## k8 / k9 / k10 复核

**k8：matplotlib 中文标签与坐标轴设置。** 本轮只有 `BV1tC4y1t7Et` 一条 partial 卡，fetched。标题为“【python-matplotlib-2】论文绘图利器入门2//折线图-时间类坐标轴标签设置”，页面标题证据 `ev_cac4e38a-25f0-4272-aced-89e0246a2c4f`，搜索证据 `ev_678725f0-d526-47c5-998b-5366f7b2c3fd`。它明确支持坐标轴标签设置；没有证明中文字体/标签，中文标签仍 unknown，符合边界。唯一真实目录标题为 `02-zimu`，ID `ev_31ff85de-c55f-49af-a36f-b68d0c42af7d`，不在支持 ID 中；没有用“zimu”推断中文教学或补造章节定位。

**k9：matplotlib 图表保存为图片。** 本轮 0 supported、0 partial。原词查询遇到视频源 timeout；第二条“matplotlib 保存图表为图片文件 视频教程”同样视频源 timeout，后续 Bing 返回 6 个保留候选：Matplotlib 官方首页、菜鸟教程、官方文档、入门指南、安装/简单使用博客、PyPI。它们没有具体保存图片教学信号，也没有本轮课程/视频类型证据，全部 unknown 类型、not_fetched。拒绝把这些文档首页当课程合理；不能沿用上轮有“保存图片”的那张卡。

**k10：pandas 统计结果导出 Excel。** 本轮 0 supported、0 partial。原词查询的来源警告哈希同样对应 `Suspended: timeout`；第二条“pandas 将统计结果导出为 Excel 视频教程”视频源 timeout，备用 Bing 留下 pandas 官方首页、文档、W3Schools、GeeksforGeeks，以及明显同词异义的 PANDAS syndrome 和 giant panda 页面。这 6 条均为 unknown 类型、not_fetched，没有实际导出 Excel 教学证据，未显示为课程。未把 pandas 库名、动物或疾病同名条目误判为知识点支持，也未沿用上轮的导出 Excel 课程。

本轮这些空缺应如实保留。仅新增匹配规则无法修复未获得具体教学候选或上游不可用的问题；本次审阅没有提出继续无限搜索或通过降低证据标准增加卡片数量。
