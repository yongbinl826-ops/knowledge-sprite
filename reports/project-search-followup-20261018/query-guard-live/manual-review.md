# 查询防线补测人工复核

复核日期：2026-10-18。任务：`7ff5313e-1ac3-498d-b0fc-3c9b61f8a440`。

本记录只读审阅本目录的 `submission-plan.json`、`job.json`、`results.json`、`audit-status.json` 与 `live/live.sqlite3`，以及冻结后的查询、匹配和章节推荐代码。SQLite 以 `mode=ro` 打开；没有调用模型、搜索、页面请求或修改生产代码。本补测独立于主项目，不合并结果或成功计数。

## 结论与范围

- 原始三个知识点均保留，首轮原词查询没有被模型变体替换。最终为 `partial`，不是全部验收成功。
- 计划 18 条查询（每点最多 6 条），实际执行 7 条，消耗 12/12 次搜索请求和 12/12 个详情页预算；没有增加预算。搜索记录均为 `network_attempted=true`、`cache_hit=false`。提交前项目、任务、资源、证据、搜索记录和缓存计数均为 0；`course_imported=false`。
- 末轮防线已应用，但不能据此宣称扩词质量问题全部解决。k1 不再出现原词加“入门”的旧变体；其新变体只覆盖运行部分，且这轮请求失败。k2 旧式 49 字超长变体未再出现，但本次较短变体仍夹带 Excel 项目措辞。模型完整候选数组没有保存，无法证明哪条未被采用的候选更优，也无法对选择分支作完整因果归责。
- 审阅全部 14 条数据库匹配（k1：6 partial，k2：1 partial，柱状图：7 supported），含默认列表以外的平台项及截断项，未发现新增错主题推荐。`supported` 仅指已有文字证据支持主题，不代表完整教学、可播放或免费。14 条的 supporting evidence ID 均存在于各自资源的证据记录中；播放核验均为 false。

## 实际查询逐条核对

以下长度包含空格及教学尾词，不包含未执行的计划查询。

| 次序 | 原知识点 | 实际查询 | 长度 | 结果 | 人工核对 |
| --- | --- | --- | ---: | --- | --- |
| 1 | Python 脚本基础语法与运行 | Python 脚本基础语法与运行 入门 视频教程 | 24 | partial，6 候选 | 保留完整原词首轮；备用来源受额度/超时影响。 |
| 2 | Python 本地文件路径处理 | Python 本地文件路径处理 入门 视频教程 | 23 | partial，6 候选 | 保留完整原词首轮；未用扩词改写知识点。 |
| 3 | matplotlib 柱状图绘制 | matplotlib 柱状图绘制 入门 视频教程 | 24 | completed，6 候选 | 保留完整原词首轮。 |
| 4 | Python 脚本基础语法与运行 | 命令行运行 Python 3 脚本文件 视频教程 | 24 | failed，0 候选 | 独立短变体，保留 Python/脚本/运行对象；仅召回运行子操作，不能替代基础语法。上游超时且后备无候选，不能宣称变体带来有效资源。 |
| 5 | Python 本地文件路径处理 | Python 本地路径处理：读取 Excel 路径并拼接输出目录 视频教程 | 37 | partial，6 候选 | 扩展短语本体 32 字，符合这个知识点当前 40 字的短语上限；旧 49 字短语未在本次已执行查询出现。仍比原词长且带业务对象，本轮不把它描述为理想 API 变体。 |
| 6 | matplotlib 柱状图绘制 | matplotlib绘制柱状图并保存图片 视频教程 | 25 | completed，6 候选 | 保留绘制柱状图，增加了项目背景中的保存图片；搜索词不等于教学证据，匹配仍针对原知识点。 |
| 7 | Python 脚本基础语法与运行 | site:bilibili.com/video Python 脚本基础语法与运行 视频教程 | 45 | completed，6 候选 | 固定平台范围及原词查询；没有把扩展短语拼成更长的课程目标。 |

本次实际记录与 skip-self、教学尾词不计新信息、扩词统一长度/操作符防线相容；真实请求未保存被拒绝的模型候选，因此“被拒超长词不会从两条 legacy 分支重新进入”的全面覆盖来自专项测试，而非对这一次模型输出的猜测。本次没有复现旧 49 字变体，也没有新增查询轮次。

## 全部匹配的相关性检查

默认页面有 11 张卡片：k1 的 5 张 partial、k2 的 1 张 partial、柱状图的 5 张 supported。平台 `other` 另外有 1 条；另有 k1 和柱状图各 1 条因每组上限 5 未进入接口卡片数组。下表覆盖数据库全部 14 条，未把“未显示”误认为“被匹配规则拒绝”。长标题以可辨认的原始片段列出，链接指向对应真实资源。

| 知识点 | 资源与证据 | 已存状态/展示位置 | 人工结论 |
| --- | --- | --- | --- |
| k1 | [Python 零基础全套教程，环境搭建、基础语法](https://www.bilibili.com/video/BV1gLe462ELN/)：本次页面标题明确 Python 与基础语法。 | partial；已抓页面；默认卡 | 只支持 Python 基础语法核心；脚本限定和脚本运行仍 unknown，正确保留。 |
| k1 | [全 500 集 Python 教程](https://www.bilibili.com/video/BV15tMg6VEb3/)：本次页面标题明确“包含基础语法”。 | partial；已抓页面；默认卡 | 同上；标题的就业等宣传不是验收事实。 |
| k1 | [全 400 集 Python 教程](https://www.bilibili.com/video/BV1maM46yE4T/)：标题及页面简介明确 Python 基础语法。 | partial；已抓页面；默认卡 | 同上；没有把其他爬虫/数据分析章节当作脚本运行证据。 |
| k1 | [全套 Python 教程](https://www.bilibili.com/video/BV1LEt86SEBN/)：本次页面简介明确“包含基础语法”。 | partial；已抓页面；默认卡 | 同上；没有承诺完整覆盖。 |
| k1 | [全套 Python 教程](https://www.bilibili.com/video/BV19eeE6hENA/)：搜索摘要明确 Python 基础语法。 | partial；仅搜索发现；默认卡 | 文字相关，页面及教学位置未核验。与上条标题相似但 URL 不同，未凭标题合并。 |
| k1 | [648 集 Python 教程](https://www.bilibili.com/video/BV1wYh76YENF/)：搜索摘要明确“Python 核心基础语法”。 | partial；仅搜索发现；数据库第 6 条，卡片数组截断 | 文字相关；运行仍 unknown，未因截断漏审。 |
| k2 | [Python 案例技巧 51：文件路径处理](https://www.bilibili.com/video/BV1ED1yY2Eo6/)：标题、简介及真实分 P 目录支持文件路径处理。 | partial；已抓页面；默认卡 | 相关。`operation_core=Python 文件路径处理` supported，`本地` unknown；没有把本地限定补成已证实。 |
| 柱状图 | [Matplotlib 全套教程](https://www.bilibili.com/video/BV1UBNy6XEyW/)：页面标题列出柱状图，真实 P7 为“7_绘制柱状图”。 | supported；已抓页面；默认卡 | 同课程标题提供 Matplotlib 上下文，目录支持柱状图主题。 |
| 柱状图 | [其他图形绘制——matplotlib 库柱状图绘制](https://www.bilibili.com/video/BV1UP4y1h7A7/)：页面标题、简介的 `bar(x, y, width, color)` 与 P1“柱状图绘制”。 | supported；已抓页面；默认卡 | 与技术和操作直接相关。 |
| 柱状图 | [绘制柱状图（横向）— Matplotlib](https://www.bilibili.com/video/BV16K4y187qh/)：本次页面标题。 | supported；已抓页面；默认卡 | 横向柱状图属于当前宽泛柱状图目标；未声称专门讲各科均分。 |
| 柱状图 | [绘制柱状图（竖向）— Matplotlib](https://www.bilibili.com/video/BV1ra4y1j7Jm/)：本次页面标题，目录 P1“柱状图2”。 | supported；已抓页面；默认卡 | 直接相关；未将简介中的外链内容当作已抓课程。 |
| 柱状图 | [Python 数据可视化之 Matplotlib 绘图](https://www.bilibili.com/video/BV19z9UBbEmp/)：搜索标题、摘要明确 Matplotlib 柱状图。 | supported；仅搜索发现；默认卡 | 文字相关，页面和实际章节未核验；没有把摘要罗列的目录生成章节记录。 |
| 柱状图 | [19 集 Matplotlib、Seaborn 教程](https://www.bilibili.com/video/BV1yos9zgEz5/)：摘要明确“Matplotlib 基础图表（折线 / 柱状图）绘制”，后半句另讲 Seaborn。 | supported；仅搜索发现；数据库第 6 条 Bilibili，卡片数组截断 | 技术与对象在同一摘要片段明确绑定，未借 Seaborn 覆盖 Matplotlib。 |
| 柱状图 | [怎么用 jupyter 堆叠柱状图](https://www.douyin.com/shipin/7356564617293826075)：搜索摘要明确“用 python 的 matplotlib 工具包绘制散点图和柱状图的代码解析”。 | supported；仅搜索发现；`platform_items.other` | 相关性仅由当前摘要支持；这是一条抖音聚合入口，页面、单条视频身份、章节、播放均未核验，不能当作与 Bilibili 详情同等级的完成验收。 |

## SigmaPlot 的真实返回与规则重放边界

`matplotlib绘制柱状图并保存图片 视频教程` 的原始 provider trace 中，index 12 确实返回了 [sigmaplot 柱状图制作教程](https://www.douyin.com/shipin/7371013377855932455)。摘要是“用bar绘制柱状图 #matplotlib #python教学 #学习使我快乐 #绘图指导 #教程来了”。原始 trace 的 `reason=accepted` 只表示解析接收，不代表主题匹配认可。

本轮数据库没有这个 URL 的 resource 或 match，也不在默认/全部平台结果中。provider 会按正向主题信号排序后取至多 6 个唯一 URL，现有 trace 未记录该项被最终排除的具体阶段，因此不能断言它实际执行了最终排名并被拒绝。

对这条已保存真实标题、摘要和 URL，使用冻结代码作纯本地重放（没有网络，搜索视频类型提示按实际来源设为 `search_template/video`）：`candidate_topic_signal(...) == False`，同形资源输入的 `rank_resource(...) is None`。这证明规则不会用标签里的 Matplotlib 为显式 SigmaPlot 标题背书；它属于“真实返回证据上的离线规则检查”，不冒充额外真实抓取或在线最终排名日志。

## 章节与剩余限制

对接口全部 12 个可达唯一卡片调用当前 `recommendChapters` 作纯本地复核：只有 k2 推荐真实 P1“Python案例技巧51：文件路径处理”，其 ID 是 `ev_97860ed8-c5c3-4bbc-b485-18db373218d4`，同时存在于目录证据、总体 supporting IDs 和 supported 核心子题中。k1 的 5 张 partial 卡均返回空章节，没有把未知的脚本运行、爬虫章节或通用运行词补成推荐章节。

四张已抓详情的 Matplotlib 卡虽然有相关目录，当前前端标题匹配仍全部返回空推荐章节，这是保守漏推荐的限制；目录证据依然保留，不能写成页面已经展示了这些推荐章节。仅搜索发现的条目也没有生成章节。

本任务的 `audit-status.json` 为 `acceptance_valid=true`、`audit_errors=[]`，只说明该审计流程未报完整性错误；不把它提升为教学内容、全部三点覆盖、完整项目流程或播放验证成功。实际仍有预算未执行查询、1 次失败查询、未抓详情条目，以及 k1/k2 的 unknown 要求。继续保留这些状态，不扩大结论。
