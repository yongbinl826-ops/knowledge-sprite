# 来源适配、候选工具比较与真实验收

日期：2026-10-13。应用已在 `http://127.0.0.1:8000` 运行本轮构建。结论：保留 FastAPI/httpx/BeautifulSoup/SQLite + React 技术栈，模块化改进 MIT OCW 和 Internet Archive 的公开静态元信息提取，增加有证据的作者角色和章节时长，修复请求节流、拒绝隔离及目录证据绑定。生产依赖未增加。已完成新的真实搜索、允许页面联网、API 和浏览器验收；受限平台的目录仍未验证，动态采集仍关闭。

本轮改进没有增加独立课程发现数，也没有证明全平台目录可取或所有视频可播放。完整日志、原失败、原 HTML 与源码基线均保留。

## 1. 目录到底提取了什么

本轮新浏览器任务 [4501fb77-18be-4702-8e06-84f996c05c25](http://127.0.0.1:8000/?job=4501fb77-18be-4702-8e06-84f996c05c25) 输入 `Structure and Interpretation of Computer Programs video lectures`，英语、无平台限定。北京时间 19:10:21–19:10:32 完成：2 次真实搜索 HTTP，搜索缓存 0，详情缓存 0，12 个搜索候选合并为 8 个资源记录，默认显示前 5 项。6 次详情处理不是 6 次原始网络请求，其中包含按策略直接停止的结果。

搜索实际发现 [Archive SICP 原页](https://archive.org/details/MIT_Structure_of_Computer_Programs_1986)，本轮采集时刻为 19:10:31。应用返回并在浏览器展开显示 **21 项真实目录、21 个单节时长**，来源署名为 MIT，角色为 credited_creator。每章都有独立证据 ID、正确的 `chapters.N` 索引以及标题/URL/起止/时长 JSON 一致性检查；审计确认 21 项全部匹配。

例如首两项是来源本身保留的旧版与普通版 Lecture 10A，均显示时长 45:43；Lecture 1A 为 72:55。没有把这 21 项说成 21 门课程。章节网页直链、起止时间、课程总时长继续为 unknown/null，没有将媒体文件 URL 作为下载入口，也没有累加时长伪造总时长。

- [新浏览器任务完整 API 记录](browser-fresh-search.json)
- [逐资源/逐章独立审计](browser-evidence-audit.json)
- [真实结果界面](browser-fresh-result.png)、[章节时长界面](browser-catalog-duration.png)
- [浏览器 DOM、构建资产与控制台记录](browser-ui-evidence.json)：21 个可见目录行，无横向溢出，无可见弹窗，无 warn/error 日志。

同一搜索也返回 3 个 YouTube 章节入口，详情按已有策略停止；MIT downloads 页面成功读取，但仍只有搜索发现的视频类型依据，未升级成页面视频核验。所有资源 `playback_verified=false`。

## 2. 冻结输入上的提取变化

基线于 18:49:15 冻结，见 [源码清单](baseline-source-manifest.json)、[源码 ZIP](baseline-source.zip)、[HTML 样本清单](sample-manifest.json)。4 份原始 HTML 来自 2 个站点，属于 **1 个明确 SICP 课程家族**：MIT 课程首页、目录、章节，以及 Archive 镜像集合。MIT Spring 2005 是课程页面上下文；1986 是录像时间，教师角色不能混用。MIT 章节 HTML 的明确 Archive 链接证明镜像关系，详见 [来源审查](extraction-review.md)。

同字节静态对照排除了页面变化与联网波动，未发网络请求。固定测试时钟 `2026-10-13T00:00:00Z` 只为可重复提取，不是实际抓取时刻；[逐字段 ledger](extraction-field-ledger.json) 另列原始 HTTP 时间和复跑时间。

| 字段 | 旧版 → 本轮 | 分母及限制 |
|---|---|---|
| 正确标题 | 4/4 → 4/4 | 正文标题更清晰，未增加标题覆盖 |
| 完整、与页面相关的简介 | 1/4 → 4/4 | 旧版另有 1 个截断正文、2 个站点模板；不是教学覆盖率 |
| 课程教师 | 0/2 → 2/2 | 同课程首页与目录的同 3 位教师，不是 6 位 |
| 本讲教师 | 0/1 → 1/1 | MIT 1A 正文明确标注的 Hal Abelson / Gerald Jay Sussman |
| 来源署名 | 0/1 → 1/1 | Archive creator 为 MIT，不能称视频讲师 |
| 作者角色 | 0/4 → 4/4 | 来源结构支持，JSON-LD 作者优先时不会套用另一人的角色 |
| 目录标题 | 41/41 → 41/41 | MIT 20 + Archive 21 个来源条目观察；不是 41 个独立视频/课程 |
| 章节网页直链 | 20/41 → 20/41 | 仅 MIT 20 项有真实 href；可恢复字段 20/20 |
| 单节时长 | 0/21 → 21/21 | 来源可恢复的 21 项全部提取；总体是 21/41，MIT 20 项 unknown |
| 总时长、起止偏移 | unknown → unknown | 无可恢复字段，正确率分母 0，应为 N/A |
| 输入原站入口 | 4/4 → 4/4 | 调用者保留的 URL，不算新增提取字段/播放入口 |

独立课程发现增量 **0**。来源适配负责静态语义，Fetcher 仍单独控制许可、robots、URL/DNS/IP、TLS、重定向及预算。详情缓存版本由 5 升为 6，使旧空字段缓存不会遮蔽新提取结果；搜索缓存版本未变。

## 3. 开源工具确实研究和试用了哪些

官方来源与固定发布源码核对见 [初始研究](tool-research.md)、[官方元数据](official-metadata-summary.json)、[源码哈希](source-snapshot-manifest.json)。研究快照与后续实测分开保存。

- **Scrapling 0.4.15**：已在独立 Python 3.13.5 临时环境安装纯解析依赖，4 份固定 HTML、同一组 CSS/属性规则、预热后每组 7 次。所有输出稳定且相同，新增字段 **0**；解析微基准约快 6.22–7.28 倍，但没有端到端、网络或课程覆盖率收益证明。因此不加入生产依赖。[实测](selector-experiment.md)、[完整数据](selector-comparison.json)、[采用决定](selector-decision.json)、[依赖哈希锁](selector-requirements.lock)。
- **Crawlee Python 1.10.4 / JS 3.18.2**：核对了官方接口和发布源码，未安装、未做运行验收。Python 默认客户端/robots/blocked 重试行为不能直接替代当前安全传输；其 HttpxHttpClient 不接受传入 transport/mounts 的预期接管方式，需要独立完整实现与验证。现有有界队列已满足本轮工作，不进行框架迁移。
- 未启用 stealth、浏览器指纹、代理轮换、验证码处理或私有接口。隔离 Selector 实验只证明本机固定 HTML 的纯解析能力，不能证明第三方联网组件安全。

生产 `pyproject.toml`、`uv.lock`、`frontend/package.json`、`frontend/package-lock.json` 的哈希均与基线相同，见 [最终源码及验证清单](final-source-and-validation.json)。字段收益来自来源适配规则，不能归功于替换解析器。

## 4. 同一组页面的真实联网对照

[旧版请求记录](baseline-network.json) 与 [新版请求记录](current-network.json) 使用相同 4 个 URL、1 MB 页面上限、3 跳重定向、8 秒 DNS/HTTP 各阶段超时、0 次重试、最多 10 次目标页/robots HTTP、120 秒总期限。每个页面独立提取；未启用目录自动跟随，也未写搜索库或应用数据库。新版增加默认 500 ms 主机间隔。所有失败保留，没有更换样本或重跑失败来提高比例。

| 指标 | 旧版 18:54:52–18:55:21 | 新版 19:07:35–19:08:09 |
|---|---|---|
| MIT 首页 | fetched | fetched |
| MIT 目录页 | timeout | timeout |
| MIT 1A 章节页 | fetched | fetched |
| Archive 集合页 | fetched，21 项目录 | fetched，21 项目录及21个时长 |
| 目标页面 + robots HTTP | 6 | 6 |
| enrich 总墙钟时间 | 28.624 秒 | 33.835 秒 |

**该样本访问成功率未提高，墙钟耗时未改善。** 墙钟包含 DNS、网络、超时和节流，不是解析器性能。MIT 两个成功页在两次捕获中 HTML 哈希相同；Archive 两次页面字节不同，不能仅凭这组联网输出做解析器因果比较，字段改进结论取自上一节同字节对照。

`actual_http_requests` 只统计目标页面和 robots。固定 Cloudflare DoH 的外部 HTTP 未由该 Recorder 计数，全部出站 HTTP 总数是 unknown。基线原 JSON 的 `total_http_requests` 命名不够精确，保留原文件，在此更正口径；新版 JSON 已显式说明。一般详情页进度也不能当原始网络请求数。

MIT 20 项目录在此前已成功捕获的原 HTML 上可重现，并有先前真实成功记录；**这次配对联网没有重新取得 MIT 目录**。不能将旧成功伪称为本轮成功。

## 5. 完整应用回归与失败边界

新版六组应用回归于 19:11:07–19:11:51 运行，原始 [live-final.json](live-final.json) 保留请求、任务、来源、缓存与检查结果。43 条查询全部使用有效历史搜索缓存，本轮实际搜索 HTTP 为 **0**；不能将它称作再次完成 43 次联网搜索。新的 2 次零缓存搜索是第 1 节单独的浏览器任务。此前同类用例的 50 次真实搜索 HTTP 与失败记录仍保留在 [上一轮联网报告](../live-coverage-final-20261013.json)。

| 用例 | 默认各组候选数 | 结果 |
|---|---|---|
| Python 列表与字典、HTML 表单校验、SQL 多表连接、地图投影与坐标系 | 5 / 4 / 5 / 5 | 四中文知识点均有真实历史发现来源 |
| D3.js 数据连接 enter update exit | 2 | 返回；不足不凑数 |
| Scheme higher-order procedures、Eigenvalues and eigenvectors、重复 Scheme 输入 | 5 / 5 | 输入去重 |
| qzxvkb7391unfindablecourse | 0 | completed 且没有伪造推荐 |
| 原浏览器 D3.js / SICP 用例 | 3 / 5 | 目录及证据关联通过 |
| Python / linear algebra 平台路由 | 5 / 5 | MOOC 筛选入口仍保留 |

默认区 48 个不同资源 ID，加各平台筛选共 52 个 ID（B站29、其他21、MOOC2），**不是52门独立课程**。其中 51 个搜索视频发现、1 个页面视频结构与目录；48 个按站点策略停止，2 个 MOOC policy_unreviewed、1 个 javascript_required、1 个 fetched。目录所在 Archive 在六组回归中命中刚才真实浏览器任务生成的新版详情缓存，时间有记录；不能算又抓取一次目录。

学堂在线没有发现结果，`xuetangx_discovered=false` 原样保留，未调词补跑或删除检查。B站/YouTube 事先许可要求、学堂明确停采、MOOC自动聚合许可范围未确认，均未通过本轮工具研究解除。本轮受限平台对照沿用既有来源与策略，没有新发受限详情/robots/浏览器请求。MOOC先前人工浏览能看到部分大纲不等于已接入生产提取器。

动态渲染未启用：固定允许样本所需字段已存在静态 HTML；没有证明其缺失字段必须运行 JavaScript。同时项目尚无经验证的浏览器所有子请求/协议/后台流量出口隔离。只换浏览器库不能保持现有逐跳安全保证。[网络审查](network-review.md) 明确了当前能力与未来需要验证的条件，`browser_fallback=false` 保持真实。

## 6. 网络和证据校验修复及测试

- 所有请求及重试遵守 `FETCH_MIN_INTERVAL_MS=500` 和已知 robots 间隔的较大值，同主机不同 origin 不会降低延迟。
- 503 Retry-After 与 429 均暂停主机；HTTP403、明确 robots 拒绝、已识别验证码/拒绝页在当前 Fetcher 实例停止该精确 hostname。401、404、普通503、超时不被误写成永久拒绝。后续被停止的候选引用真实触发页的 `access_restriction` 证据，不假称该候选也返回403。
- robots 多星通配原本可触发正则回溯；本地原失败保留，改为字面分段匹配并验证 raw/decoded、最长规则、同长Allow、末尾锚定语义。
- 章节只能使用属于该索引且字段一致的独立 JSON 证据。不同章节的同一时长、篡改标题/URL/起止/时长、字符串/布尔/负数/零/无穷时长都会被拒绝。时长与起点分开显示。

验证结果：

- 后端与审计：**213 passed、26 subtests passed**，[JUnit](backend-final.xml)。仅有 Starlette TestClient 的 httpx 弃用提示；未为该提示改动生产依赖。
- Microsoft Edge 浏览器 E2E：**16/16 passed**，0 skipped、0 unexpected、0 flaky，[JSON报告](frontend-e2e.json)。桌面1536×1024及移动390×844，包含目录、字段篡改、转义、安全外链、筛选与未知状态；这些隔离 fixture 不替代真实搜索证明。
- `npm run build` 通过，运行资产 `index-B3p1UZL3.js`；CUA 实际加载资产与最终 SHA 清单对应。
- 新浏览器任务实际点选与目录展开验证通过，21项逐章证据审计通过；控制台无 warn/error，页面无横向溢出。
- 六组应用回归除学堂发现检查外，其余检查通过；学堂发现检查仍为 false。独立真实连接失败用例正确失败而没有伪数据；执行期间源码哈希未变。

本轮未播放视频。之前只对 Archive 一个条目做过人工浏览器播放抽样，见 [原播放记录](../browser-playback-sample-20261013.json)；不代表其余条目、受限平台或当前未来时刻可播放，也不提升本轮 API 状态。

## 7. 复现与后续工作边界

启动与字段说明见 [README](../../README.md)、[API 合约](../../docs/api-contract.md)。可在实际应用中直接打开第1节任务查看已保存来源，也可输入新的知识点执行真实检索。已有报告不可用成功重跑覆盖；比较脚本在目标 JSON 已存在时拒绝执行，复现实验应另存目录并保留失败。

尚未完成：学堂在线搜索覆盖、B站/MOOC/学堂的自动目录提取、被允许动态页面的完整隔离渲染、多课程家族泛化评估、所有视频播放验收、Tavily/LLM未配置服务的真实调用、面向公网的生产部署。对这些范围仍按 unknown/未验证处理。
