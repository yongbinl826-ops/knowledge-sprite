# 静态来源适配器审查与固定样本比较口径

审查日期：2026-10-13。本报告只读取已有代码、真实采集报告及保存的 HTML，并在本地解析。未新增外网请求、未播放或下载媒体、未修改旧验收报告。随后按 root 的明确任务实施了最小适配器重构；真实网络验收由 root 单独管理。

## 样本及身份边界

比较固定使用以下 4 份原始 HTML。已逐份重新计算 SHA-256，均与原采集报告一致；不采用更早/更新的页面替代，不从失败来源补样本。

| 页级样本 | 原文件 | SHA-256 |
|---|---|---|
| MIT 课程首页 | `reports/catalog-probe-mit-final-revision-20261013-source-1.html` | `9c1858679bee19f7ccb41d57c6c0b10bf74313deba084afd9b0326f7d280229e` |
| MIT 同课程视频目录 | `reports/catalog-probe-mit-final-revision-20261013-source-2.html` | `c153754a1ee84eaefaf000c77f6df7a540fd6e3d0f9cc74d8f5bb57933e8e819` |
| MIT 同课程第 1A 章 | `reports/catalog-probe-mit-final-revision-20261013-source-3.html` | `f23fd0175dcd1caeb8e9be1478faed97bec7629ec5b23fded4da7bb5d8cd3c14` |
| Archive SICP 镜像播放列表 | `reports/catalog-probe-archive-20261013-after-source.html` | `03f179ccf513e358348cf114557e0f1352513f273fc7c4cd5efc003cdb2bc9a8` |

URL、真实 HTTP 200、采集时间及来源策略依据分别沿用 `catalog-probe-mit-final-revision-20261013.json` 与 `catalog-probe-archive-20261013-after.json`。本地复跑的时间不替代这些原始采集时间。`extraction-field-ledger.json` 逐文档单列原 HTTP 抓取时刻与本次 `replayed_at`；`2026-10-13T00:00:00Z` 只是 baseline/new 共同的固定测试时钟，不是午夜发生过真实抓取的声明。

固定计数：4 个来源文档、2 个来源站点、1 个明确 SICP 课程家族。MIT 首页、目录和章节共享 `/courses/6-001-structure-and-interpretation-of-computer-programs-spring-2005/`；三个 HTML 的 canonical 与课程导航可核对。第 1A 章 HTML 第 1449 行还明确给出 `http://www.archive.org/download/MIT_Structure_of_Computer_Programs_1986/lec1a.mp4`，与 Archive 页面 identifier 和条目对应，是镜像关联的直接证据，不是根据相似标题猜测。

MIT 页面课程上下文为 Spring 2005，录像说明明确为 July 1986；两种年份/授课角色必须保留，不能相互覆盖。评估将这一镜像与 MIT 归为同一课程家族，不把 Archive 算成第二门独立课程；该人工核对的评估身份不自动注入产品的资源 URL 去重逻辑。没有明确父课程路径或镜像证据的其他候选，单列 `course_identity=unknown`。

MIT 目录 20 项，Archive 播放列表 21 项，其中包括 `Lecture 10A: Compilation (old quarter screen original)` 与 `Lecture 10A: Compilation` 两个记录。41 是两份目录中的条目观察数，不能称 41 门课程，也不能称 41 个独立讲解。保留原始顺序与旧版条目，不凭标题删掉内容，不把用户评论当成重复内容的证明。

## 现有提取遗漏的具体证据

以下代码行号对应本轮冻结的 baseline `baseline-src/backend/app/extractor.py`，而非重构后的行号。

1. **Archive 章节时长被丢弃。** HTML 第 2750 行 `play-av[args][playlist]` 的 21 项全部含有限正数 `duration`，其中既有整数也有数值字符串，例如第 1A 讲为 `"4375.02"`。baseline 第 125–126 行只输出 title/url/source_url/start/end；第 194 行证据白名单同样不包含 duration。时长是独立媒体的长度，不能改成 `end_seconds` 或求和成为课程总时长。
2. **MIT 章节简介与讲师漏提。** 第 1A 章 HTML 第 1432–1435 行 `.video-page .description` 明确包含主题及 `<strong>Instructors:</strong> Hal Abelson and Gerald Jay Sussman`。baseline 第 213 行只处理 JSON-LD author/instructor/creator；第 252–257 行先接收通用 OG 简介，`put()` 第 180–188 行不再覆盖已填字段，故最终 author 为空、description 是 MIT 全站介绍。
3. **MIT 课程教师与录像教师需要分角色。** 课程首页第 567、575、583 行 `.course-info-instructor` 分别为 Eric Grimson、Peter Szolovits、Trevor Darrell，移动/桌面布局重复出现。目录页也保留这些课程教师；第 1A 章必须使用章节正文标注的两位录像讲师，不能抓全页 course-info 后误贴。两套署名均有真实依据，但适用对象不同。
4. **MIT 目录正文被站点介绍遮盖。** 目录 HTML 第 1405–1407 行 `main#course-content-section > p` 说明录像讲师、1986 年录制背景及教材版本，而 baseline description 使用第 34 行通用 `og:description`。正文描述能改善证据，不代表目录关联到每个任意知识点都成立。
5. **Archive 可见元信息比 OG 完整。** HTML 第 2932 行 `[itemprop=name]` 为干净标题；第 2937 行 `[itemprop=creator]` 是 `MIT`；第 2992–2996 行 `#descript[itemprop=description]` 为完整简介。baseline title 混入站点操作文案、description 截断、author 为空。这里 MIT 的身份是 creator/机构，不能把它计入视频讲师的命中数。
6. **原站入口已有，不能把适配器增益虚报为新入口发现。** 调用者保存搜索发现的原始 `resource.url`，并保留 resolved_url/HTTP 来源记录。MIT 有 20 个实际章节页 href；Archive 只有媒体文件，章节 url 必须继续为 null、来源链接回原 details 页面。MIT 章节的下载/YouTube 嵌入地址可作为镜像关联证据，不在本轮生成播放地址或发请求。

## 最小模块化实现

新增 `backend/app/source_adapters/base.py` 的 `SourceAdapter` Protocol、`FieldFact` 与 `SourceFacts`，以及显式注册表。MIT/Archive 各自处理站点与路径匹配、DOM 选择器和静态结构，不执行脚本、联网或决定访问策略。限制仍包括 JSON 长度、至多 100 个条目、实际同站链接与 Archive identifier/视频源匹配。

`extractor.py` 继续负责访问错误识别、JSON-LD、不可见节点清理、通用 fallback、字段及每章证据 ID。站点正文 title/description/author 在 OG fallback 前进入统一 `put()`；明确 JSON-LD 仍保留既有优先级。原目录 source 名称及 `_catalog_followup` 的同课程导航约束保持。每章 `duration_seconds` 与 title/url/start/end 一起进入其独立 catalog JSON 证据；不触碰页面级 duration。

MIT 首页/目录的 author 使用 `html.mit_ocw.course_instructors`，仅章节使用 `html.mit_ocw.video_instructors`。Archive author 使用 `html.archive.creator`。另返回独立有证据的 `author_role=course_instructors / video_instructors / credited_creator`，对应原始标签/DOM 结构与署名。角色只在适配器 author 实际被采用时赋值；若更高优先级 JSON-LD author 生效，不能套用另一位 DOM 作者的角色。这些来源角色应由界面/验收读取，不可将通用 author 非空率写成“讲师核验率”。

本次未添加 course_identity 模型字段或跨站自动合并：`Resource` 的 extra=ignore 会丢弃未声明字段，service 又会重映射证据 ID；仅在提取器塞新字段不能构成 API 全链路功能。若以后实现身份字段，应同时定义身份依据、父课程与镜像关系、模型/服务/界面契约，并保留原始资源及全部来源证据。

## 固定 baseline/new 比较方法

- baseline 使用 root 冻结的 `baseline-source.zip` / `baseline-src`；new 使用本轮适配器文件。两侧源码与样本哈希分别记录。
- 直接提取层：同样 4 个 `(原HTML, 原URL, 固定fetched_at)`、同样解析顺序、每侧 4 次解析；外网请求预算为 0，不执行跟随，不重试、替换或补充样本。
- API/服务回放层：只能以同一冻结 Candidate/搜索证据输入和同一原 HTML 响应映射回放。保留每侧同样的 3 个初始页（MIT home、MIT chapter、Archive details）和 1 个目录跟随页预算，总共 4 个公开页面槽；robots/策略使用原快照并单独计数。新版本不能多读一页后声称提取器更好。
- 目录首页不混算：直接 extract 的 MIT home 仍只有 `_catalog_followup`、0 个章节、video_evidence_status=none；Fetcher 完成允许的同课程目录跟随后才有 20 项与 page_verified。页级与跟随后级别分别报告。
- 排序回放固定原 `SearchRequest`、候选、排序阈值和输出 K；仅比较同来源字段变化的影响。本次解析提升不是新搜索覆盖率、课程数或排序正确率的证明。
- B站沿用 `catalog-probe-policy-review-20261013.json` 的受限依据；MOOC/学堂使用更新的 `platform-coverage-policy-20261013-final.json`。MOOC 为 policy_unreviewed，学堂明确停止采集，保留历史搜索证据；3 个平台观察记录是受限对照，不新发详情、robots、浏览器或代理请求。失败/受限不从报告删除，也不计作“提取器可恢复字段”分母。

## 字段分母与本地观察

完整性至少同时给出：`非空/全部槽位`、`有来源可恢复/全部槽位`、`正确且带字段证据/可恢复槽位`。适用但无来源是 unknown；不适用是 N/A；不能把两者塞入成功分母或填 0。来源 DOM 的正确性与实际教学覆盖/可播放性独立。

| 指标 | 固定分母与基线 | 本轮本地观察 |
|---|---|---|
| 文档标题 | 4 个页面槽；baseline 4/4 非空 | 4/4；MIT home 与 Archive 使用更具体正文标题。去后缀是质量改进，不是新增覆盖 |
| 页面相关简介 | 4 个页面槽；baseline 4/4 非空，但 MIT gallery/chapter 的 2 个是全站模板 | new 4/4 为相应正文/课程简介；Archive 从截断 OG 换为完整正文。是否覆盖知识点另审 |
| 完整页面相关简介 | 严格 ledger 口径要求完整来源块（上限 4000 字符）；baseline 1/4，另有 Archive 部分截断 | new 4/4；与上行“非空/非模板”口径分开 |
| 课程教师字段 | MIT home/gallery 2 个角色槽；baseline 0/2 | 2/2，均是同课程的同 3 位教师，不能算 6 位独立教师 |
| 章节讲师字段 | MIT chapter 1 个结构化 Instructors 槽；baseline 0/1 | 1/1；绝不回退到课程教师。Archive 描述中的人名仍不作为独立讲师字段增益 |
| Archive creator 字段 | 1 个明确机构 creator 槽；baseline 0/1 | 1/1，MIT；与讲师分开 |
| 署名角色字段 | 4 个带可核对结构的角色槽；baseline 0/4 | new 4/4，2 个 course_instructors、1 个 video_instructors、1 个 credited_creator |
| 目录标题证据 | MIT gallery 20 + Archive 21 = 41 个来源条目槽；baseline 41/41 | 保持 41/41；同时标注 2 个目录文档、1 个课程家族 |
| 章节原站页直链 | 41 个目录槽；有原 href 的仅 MIT 20；baseline 20/41 | 保持 20/41，recoverable=20/20；Archive 21 个 null 不造链，使用 source_url |
| 章节时长 | 41 个目录槽；原来源明确时长21；baseline 0/21 可恢复字段 | new 21/21（总体21/41），均有 per-chapter catalog JSON 证据；MIT 20 条仍 unknown |
| 页面/课程总时长 | 4 个页面槽；无明确总体时长 | 两侧均 unknown；可恢复分母0应写 N/A，不写0%或100%，不累加重复/旧版条目 |
| start/end 时间偏移 | 41 个目录槽；本样本无明确 offset | 41 项均 null；duration 不改写成 end |
| 原页面入口 | 4 个输入 URL；原报告有相应公开HTML响应记录 | 保持原入口；不是当前可达或播放验证 |
| 播放 | 独立观测，不从 HTML/video标签推断 | 本轮未播放；API playback_verified 不由解析提升为 true |

四页在本地复跑后的独立 video_evidence_status：MIT home=none、MIT gallery=page_verified、MIT chapter=page_verified、Archive=page_verified。MIT 首页的目录跟随成功属于上一层 Fetcher/服务证据，不能伪装成首页自身有 player。

## 服务及排名对接提醒

baseline service `_page_cache` 第 341 行的 extractor_version 必须随提取逻辑变更递增，否则旧空 author/时长缓存会遮蔽新适配器。新字段进入每章 dict 后，现有 service 会重映射 chapter.evidence_id；界面仍需核对 duration_seconds 等于该章证据 JSON 中的值。

baseline ranking 第 177–188 行会使用页面 description 与章节标题影响相关性，原有站点 boilerplate 也曾参与匹配。本轮正文替换可改变排序，不能把更长简介直接当更高准确率。按固定输入回放，保留先修项排除、类型证明、搜索发现/page_verified/播放三层边界；不通过放松阈值制造字段提升后的命中。

`extraction-field-ledger.json` 冻结了 4 个文档的 title/description/author/author_role/chapters/duration/learning_entry 各字段 `applicable/source_present/correct_extracted`，另列 41 个目录条目，其中 21 个有原始 duration。unknown 与 N/A 的 correct_extracted 使用 null。learning_entry 明确属于调用者保留的输入 URL + 原 HTTP 来源记录，不虚报为本次从 DOM 新发现的播放地址。没有独立课程发现增量。

本 agent 的改动范围为 `extractor.py`、`source_adapters/*`、新的 `backend/tests/test_source_adapters.py` 及本目录两份审查/ledger报告；未改 models/fetcher/service/ranking/front/scripts。追加角色证据后的联合离线验证结果：`78 passed, 26 subtests passed`（新适配器测试与完整 test_fetcher）。原 HTML 文件哈希再次核对不变。此处结果是静态提取与回归验证，不能替代 root 的完整 API/浏览器验收。
