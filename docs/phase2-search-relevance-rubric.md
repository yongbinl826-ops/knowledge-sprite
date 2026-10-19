# 四项目真实检索的独立相关性判据

`evidence/phase2/search-independent/four-project-search-rubric.json` 固定 25 个已接受学习单元的原概念、任务、练习、学生背景和逐单元判断标准。它不修改原分析，不指定期望视频，不增加搜索或模型请求，也不使用暂存语义原型。所有推荐都必须根据最终保存的本课页面、说明或目录逐条审阅。

有正确工具和明确项目操作的真实视频，可是有用的部分匹配。例如 pandas 读取 CSV、分组计数或 Matplotlib 条形图，并不要求课程也使用骑行数据。它们也不能证明原单元的具体参数、计数口径、数值边界或所有学习目标。只有泛 Python 基础、工具名、广告、作者简介、其他相关视频或错误库，不能代替项目学习单元。

学生阶段必须结合已有经验：骑行学生会 Python/统计，但第一次使用 pandas 和 Matplotlib，相关的库入门可以适合；不应强迫重上通用 Python 课，也不能机械认为所有入门库课低于其阶段。来源未说明门槛时保留未知，不能从相关视频中的“零基础”“中级”推断本课阶段。页面语言也不等于实际授课语言。

逐单元重点包括：番茄钟的绝对截止时间与暂停/继续、切阶段后等待开始；骑行的严格 `end < start` 与相等零分钟有效、小时计数与可复核输出；Arduino 的 LOW 有效、机械去抖稳定条件、非阻塞抢按与实际亮灯起计时；迷宫的二维地图、单次 KEYDOWN、胜利后事件仍活着和真实时间差。泛循环、框架状态或相邻 API 不能跨工具、边界或作用范围替代这些要求。付费、登录或地区条件按访问限制记录，不等于无效链接；本次不声称验证播放。

## data v4 已保存终态审核

`evidence/phase2/search-independent/data-v4-final-review.json` 已绑定原分析 SHA 和终态结果文件 SHA。其 7 个单元、10 条展示视频均已只读审阅：CSV 读取、去重、分组计数、条形图四个单元有项目相关部分线索，时间解析、时长计算、导出复核三个单元无结果；28 项原确认概念目前仍均为 unknown，完整单元教学为 0。不能把四个通用操作的支持算成 28 个具体技能已教。

发现两处中优先级来源归属错误：本课 meta description 中的“相关视频”尾巴分别造成入门和进阶阶段误归属。原 r6b 失败证据保留；后续暂存修复或回放不能改写这一真实结果。

另一个 Matplotlib 视频原文自述为“自学分享而非教程”。它确是相关条图项目示例，应保留价值；建议卡片明确来源自述与部分匹配，不假称系统教学。第四条零基础 Matplotlib 课程的本课标题和条图目录则是真实依据，适合该学生第一次接触库 API，不因 advanced 标签直接剔除。

迷宫 v4 随后在 453.748648 秒进入 `partial`，独立逐单元记录为 `evidence/phase2/search-independent/maze-v4-final-review.json`。六个单元均无展示候选，24 项确认概念均为 unknown。保存的诊断包括 42 次搜索、17 次详情、本轮预算/期限限制及一次搜索超时和查询扩展失败；不能据此声称全网没有合适视频。零错误卡片与推荐可用性通过是两回事，空集合的 safe URL 指标也不代表验证过真实推荐链接。留存 TWT/FCC 或语义原型没有补入这次结果。

网页、Arduino 终态已分别只读审核，见 `web-v3-final-review.json`、`arduino-v3-final-review.json`。网页 7 单元、5 张部分卡片，3 个单元有部分支持，4 个无结果，耗时 408.568672 秒；Arduino 5 单元全无结果，耗时 133.249833 秒。四例汇总为 25 单元、15 张部分卡片、7 个单元有部分结果、18 个无结果，完整单元支持为 0，见 `four-project-terminal-review-summary.json`。这些数据不构成四例或 APP 生产验收通过。

`web-arduino-source-rejection-audit.json` 保存实际来源字段、SHA 和查询片段。网页 HTML 卡片把本课“语义化”与相关视频尾巴的“按钮”拼成“语义化按钮”支持，是来源范围错误。Flex 课真实目录明确从单行到多行及 `flex-wrap`，而确认目标“flex 布局与换行”仍未知；另一本课已验证的 `focus-visible` CSS 单课可作焦点样式的局部材料，却未展示。以上不能扩大到 viewport、相对单位或原生按钮键盘激活。

Arduino 的已确认工具名与中文标题紧邻，检索适配保留这一形式，后续详情探测却要求工具名后有空格。实际已发现、未取详情的 `digitalRead` 和 `input_pullup` 候选因此不能通过门槛；离线仅改变分隔符即可复现两种探测结果的差异。报告明确这只证明门槛信息丢失，空配额反事实不重建实际调度时序，也不把未取详情候选算作教学证据。实际 `INPUT_PULLUP` 单独标题缺少本课 Arduino 归属时，仍不能借搜索 query 补证。

严格未知也应保留：网页泛倒计时说明没有证明 `Date.now()` 绝对截止时间或后台节流；Arduino 去抖对比演示没有证明稳定时间窗口，随机数课没有证明 `random(2000, 5001)`，ArControl 无代码图形工具不能替代确认的 Arduino 代码路线。零卡片不能证明全网无视频，已有目录漏召回也不应通过降低覆盖证据门槛解决。

此次来源审核使用 `current-final-copy.sqlite3` 只读快照：2026-10-18 18:54:16 UTC 从实际 `data/preview.sqlite3` 以 SQLite `mode=ro`、`query_only` 及 backup API 建立，保留 WAL 一致性；快照 SHA 为 `a7a8cec9b8cdef7ebca4bc4fe7700f8d09cd369b6cdfe8fa8d5a9cfc1797bf12`。未使用 Store、未写源库、未执行新 HTTP/模型请求；暂存修复或离线反事实不改写历史搜索结果。

## 补齐真正的数据看板类型

原骑行案例明确不做仪表盘，不能声称覆盖了“数据分析看板”。新增事前案例在 `evidence/phase2-dashboard-plan/case.json`，为会 Python/pandas、首次使用 Streamlit 的中级学生设计本地校园自习室 CSV 看板，包含六条独立要求，学习单元上限六个，不添加账号、云、数据库或预测。

合成 CSV 与 `expected-results.json` 提供独立口径反例：9 行中 5 行有效、4 行无效；全选为 48 到访人次、1800 占用座位分钟、4200 容量座位分钟，加权使用率为 42.9%，逐行百分比平均 45.0% 是错误答案。有效零到访行必须保留；日期两端包含，空房间选择明确无结果，空指标显示“—”。

第五例已完成真实分析（24.260997 秒）及独立六条要求静态精读：`evidence/phase2-dashboard-analysis/manual-review.json`。6 单元保持既有 Python/pandas、首次 Streamlit 的背景，保留 0、日期含等号、空房间与加权口径；独立 CSV oracle 反例通过。`approved-search-plan.json` 已通过现有 search runner 的输入检查，允许根线程后续搜课。本结论是学习计划静态验收，不声称运行了看板成品，也不计入上述四例搜索覆盖。

原 harness 只统计了生成任务，不能当本例总模型成本。完整 observer 显示生成 1 次、语义复核 1 次，合计 2 次模型调用、2430 completion tokens、9965 total tokens；独立审核保存了两个 call ID、事件子集与 SHA，并保留原 generation-only 报告。没有将模型复核 pass 自动当作人工质量 pass。

## r7 新终态独立审阅：骑行 data v5

`evidence/phase2/search-independent/data-v5-final-review.json` 保存本轮真实终态、逐单元和来源字段。输入和分析 SHA 与原接受的 v2 分析一致；搜课版本是 v5，没有新模型分析。115.917644 秒完成，首条部分结果上界 17.988 秒、首条 page-verified 结果上界 41.265 秒。7 单元中 5 个有部分结果、2 个无结果、0 完整支持；展示 12 条部分卡片和 1 条单独待核实的 TikTok 页面外壳。28 个确认概念仍全部为 unknown，待核实卡片不计入覆盖。

本轮三个 r6 来源范围问题在实际推荐文案中关闭：CSV 读取课的相关视频“零基础”、分组计数课的 UiBot“中级”不再成为本课门槛；raw 尾巴保留。Matplotlib 自学分享课仍作为有用示例保留，明确提示“分享或项目示例，非系统教程”。首次 pandas/Matplotlib 的高级学生可使用库入门章节，不必重上通用 Python，也不能从阶段标签推断库熟练程度。

CSV 写出新增部分结果有本课已验证目录 `Python Pandas Tutorial 4 - Read Write Excel CSV File` 佐证，只接受 CSV 写出主题的有限操作核心。`DataFrame.to_csv(index=False)`、计数链、文件名、输出目录、清洗汇总口径和日志仍未知。上传者说明中原始标题写成 Tutorial 3/DataFrame，与本页及本课目录 Tutorial 4/Read Write 不一致，不能借此推断实现细节；当前服务支持指针仍指向搜索标题，独立审阅使用同卡片的 own 目录作旁证，建议后续归属优先指向该 own 字段。

时间解析并非仅仅“搜得少”：实际缺项查询 `pandas pd.to_datetime errors 视频教程` 首项是真实 `Python pandas.to_datetime函数方法的使用`，已持久化为 `res_5659617259cfc15963a12d97`，但终态未取详情。只读核查与匹配运行态哈希的离线复现表明，该 API 候选现已能通过 namespace 探测；旧长业务标题 relevance 给它 0，而两个泛 Pandas 语法错误/数据框网页为 1/9，并实际被探测后分别 access_denied/robots_blocked。已有两个初始泛工具探测、剩余有界 gap 槽和现有排序共同形成具体候选被泛项挤占的问题。报告没有声称重建了每个时刻的瞬态配额，也没有把未抓到的 API 页面变成已证明的教学内容。

改进提案只在已通过工具/类型/视频门槛的 non-public 探测候选内，按当前确认目标的字面 API 标识优先，再使用原 relevance 和稳定 tie；保持原 2 initial + 2 gap、详情总预算和教学标准。暂存离线测试不构成生产修复或真实复测，r6 和本轮 r7 终态均保留。尚有这一可修探测排序缺陷及时间解析/时长教学缺口，因此本轮推荐验收仍未通过；本次审阅新增 HTTP/模型请求为 0，源代码、测试主树和数据库未修改。

## r7 新终态独立审阅：网页 v4

`evidence/phase2/search-independent/web-v4-final-review.json` 已逐单元核对实际终态。122.705852 秒，首条部分/本页验证结果上界分别 15.587/28.621 秒；7 单元中 2 个有部分结果、5 个无结果，4 条部分卡片、0 完整覆盖。22 项确认概念中 2 项有支持、20 项未知：CSS Flex 换行和 JS 状态对象表示。后者只是对象数据组织的针对性前置，不能据此宣称教会了计时器状态机、阶段常量、毫秒换算或 DOM 更新。

HTML 语义化课借相关视频尾巴证明按钮的旧卡片已撤除，旧 false-button 支持关闭；不是因为移除卡片就把无结果算作质量通过。Flex 的 own 目录“从单行到多行：理解 flex-wrap 与 align-content”本轮正确支持确认的换行目标，r6 的具体目录漏判关闭；viewport、相对单位与媒体查询的复合要求仍未知。

焦点单元仍有确定的发现顺序缺口。真实 `focus-visible` 同课在缺项查询首项，已存为 `res_57acffef3d77072ee934505e`，但当前任务未取详情；owner 门槛在空配额回放中通过。两条初始泛 CSS 缓存卡在 19:35:03 发现，Tab 缺项又取两门泛 CSS 课，在 19:35:25/32 完成；具体焦点课到 19:35:35 才发现。保留的行和时间戳说明仅在候选队列里优先不能收回已消耗槽位，报告没有把瞬态配额推断冒称完整调度日志。

同一个暂存包另提供 `queries-only.patch`：原文完全匹配确认目标、且含具体 dotted/调用/underscore/camel/kebab-case 标识的缺项先查询；其余相对顺序不变，在 `safe_part` 去标点之前排序，保持原 8 个待处理项、4 子项、6 查询上限与 URL/引擎过滤。`focus-visible` 只是一般标识形状，不是新增硬编码知识表，更不能证明 Tab/Enter。独立 helper/队列/查询及既有回归共 92 项离线通过（29 新增、63 既有），主树仍冻结，本轮真实结果未被暂存回放替换。
## r8 新终态独立审阅：骑行 data v6 与网页 v5

`evidence/phase2/search-independent/data-v6-final-review.json` 保存 r8 骑行真实终态、7 单元逐项及每张卡片的来源判断。107.295604 秒，首条部分结果上界 15.367 秒、首条 page-verified 结果上界 33.677 秒；仍为 5 单元有部分结果、2 单元无结果、0 完整支持，12 条部分卡片及 1 条不计覆盖的待核实页面。28 项确认概念全部未知。实际 50 次搜索、7 次新增详情；缓存命中不冒称新增抓取。r6 的相关视频阶段尾巴与“分享而非教程”范围问题继续关闭，原高级学生首次 pandas/Matplotlib 的背景保持不变，CSV 写出的有限核心仍不证明 `index=False`、文件位置或项目汇总口径。

本轮确实关闭了 to_datetime 候选被泛标题挤占的详情探测缺陷：相同真实 `res_5659617259cfc15963a12d97` / BV1eL4y1g7qY 已再次召回，并新取详情 HTTP 200、155906 字节、非缓存，本页视频身份与 own 标题 `Python pandas.to_datetime函数方法的使用` 均已取证。因此剩余空结果不能再归因于未 fetch、owner 或配额。原 `pd.to_datetime(errors)` 仍须未知，不能把 source 的 `pandas.to_datetime` 改成别名或推断参数；但可存在本课明确讲授的原拼写 API 使用局部核心。该有限关联候选仅在 `tmp/phase2-confirmed-api-core/` 离线隔离回放，不改写 r8 实际终态，也不宣称主树已修复。

`evidence/phase2/search-independent/web-v5-final-review.json` 保存网页本轮真实终态。126.118485 秒，首条部分结果上界 17.916 秒、首条本页验证结果上界 33.241 秒；7 单元中 3 个有部分结果、4 个无结果、6 条部分卡片、0 完整覆盖。22 项确认概念中 3 项有支持、19 项未知。具体 `focus-visible` 查询已从 r7 的第三缺项前移至第一缺项，真实同一 B站视频已取得缓存 own 页面证据并展示；只支持焦点样式，Tab/Enter/Space 激活仍未知。HTML 假按钮撤除与 Flex 换行的 own 目录支持继续成立。

其中 1 张 Tuts+ 部分卡片是新的明确分类问题：`res_3edb2cd182f41415c02bd469` 的 own 标题/简介能够说明相关 CSS 内容，但 `resource_type=video` 和 `video_evidence_status=search_discovered` 只来自 `search_template`；留存 5 条证据没有本课 video/embed 身份。不能把它计入已验证真实视频，也不能仅据这些元数据反向断言页面绝无视频。本轮应记为 5 张本页已验证视频及 1 张身份未确认的相关网页；完整 source/provenance/evidence 定位和 SHA 已保存，交由根线程独立修复分类。未发新请求来补证。

以上是 r8 已终态两例的独立只读观察，仍不是五类推荐生产验收通过。API-core 暂存回放使用真实来源派生数据和正常 `JobService.results` 的只读内存 facade：该单一候选可成为 1 条 partial，原 collection 的 8 项 ID/原文和 0/8 未知状态完全保留，4 条确认概念仍全部未知。补充 API 行不进入学习路线分母；前端零支持文案需要明确指“这些学习目标”，不能因存在局部材料就声称已完成原目标。此回放与 231 项离线测试都不替代后续统一集成、全量回归或真实读取验收。本轮独立审阅/暂存新增 HTTP、模型及数据库读写为 0，生产源代码与测试主树未修改。



## 最终r9c闭环与剩余内容缺口

统一集成的r9/r9c使用r8既有终态只读重投影，0新增检索、模型调用或平台播放。最终28张普通partial均有页面视频身份，2张review不计覆盖；31原单元API13some/18none，UI正文/目录12some/19none，0full。CSV标题线索解释了两个口径的差1，不能将它写成有正文/目录支持；原四个确认概念全部unknown。详见`evidence/phase2/data-csv-source-layer-review.json`和`final-content-gaps.json`。

API-core revision2已集成，保持来源原拼写，只支持使用核心，不证明别名、参数或原项目限定、不进入原分母；全源否定已在补充路径关闭。Tuts网页因仅搜索类型、没有本课视频身份转review。pygame.font精确目标所需的TWT本课SysFont/render/blit绑定通过；B站仅“显示文字”标题不足，r9c已撤除。独立闭环`evidence/phase2/final-r9c-independent-closure.json`逐字段证明其余30张保留卡无变化、另四例整JSON相同、31原(id,text)分母和原参数unknown不变；仅本轮差异与已审8卡范围未发现新增高中问题，不能推广为整体内容验收通过。

最终代码双目录各3024测试+26子测试通过、前端88浏览器/58Node及构建通过，这些是技术回归。内容门槛仍失败，已有来源不能覆盖原项目要求。按最终限制不继续新增搜索或业务模型调用；精确缺口逐单元保留，不能通过削减目标、改写分母或将测试数字当推荐质量来宣称生产通过。
