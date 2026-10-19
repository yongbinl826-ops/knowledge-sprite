# 共享课程库、按缺口补搜与 Serper 对照（2026-10-19）

已实现并完成真实调用验证。当前本机仍使用 SearXNG 搜 B站、Tavily 搜 MOOC；Serper 已接入、配置并独立测试，可显式切换。没有注册付费方案、充值、开启自动续费或自动切换搜索来源。

后续三点缺口已各补齐 1 门、后台刷新与导入完成，见 [三点补齐与后台更新](mooc-gap-refresh-20261019.md)。下方对照、冷暖测试和运行状态是该后续修复之前的历史记录，按各自实验边界读取。

## 当前行为

- 新任务先查询同一服务数据库中的共享 MOOC 库。库中仅保存来源绑定的公开课程字段、原始页面与大纲证据，不保存项目、用户知识点、搜索 query 或先前的相关性结论。
- 每次复用都对当前知识点重新执行完整大纲校验。课程标题、搜索摘要、先修要求或部分覆盖不能代替完整覆盖；原 URL 和学期保持不变。
- 以原始抓取时间计算到期时间，默认 7 天；读取、搜索查询和搜索摘要不续期，新的有效公开页面与目录观测才可更新课程证据。撤销、更新、到期、缩短 TTL、关闭共享库或采集策略变化会使旧库副本停止显示和计入覆盖数。已有非库任务的历史证据保留。
- 默认每点目标为 **3 门不同 MOOC**。不足时补搜；达到目标后跳过后续 MOOC 查询，但启用刷新且已到期时，下次实际检索的首轮仍最多使用 1 个原查询槽查找新课程。根域/www 和尾斜杠不重复计数，学期区别仍保留。已开始的大纲校验最多等待 20 秒，不占网络并发槽。
- 查询触发刷新默认间隔 24 小时。距同一知识点与当前策略最近一次无来源警告的真实成功 MOOC 查询达到间隔后，即使已有 3 门课程，也最多安排 1 次刷新查询；它绕过查询缓存、计入原搜索预算，不增加查询槽。没有实际检索时不运行后台定时任务，读取结果、订阅 SSE 或刷新浏览器均不会触发查询。
- 刷新使用 5 分钟持久化租约，避免相邻任务重复请求。只有没有来源警告的真实成功查询更新成功时钟；缓存、失败、部分完成和取消不更新。宽泛课程词与具体知识点词随成功轮次轮换，新候选仍须取得自身大纲并支持全部所选子项，不能用搜索成功替代覆盖校验。
- B站保留原轮数、来源、详情校验与展示规则。课程库命中和后续新增课程沿用 SSE 推送；项目主界面仍只展示封面，手动界面沿用原卡片。共享库及刷新配置只在后台管理，两种界面均不显式显示共享库、库命中或刷新配置等技术标签。
- 计划槽数和真实请求数分开：`queries_completed` 包括已处理的跳过槽；`queries_skipped` / `gap_queries_skipped` 记录节省；`search_requests`、`provider_requests` 记录真实搜索请求。

这是一个实例内、跨任务复用的 SQLite 课程库，不是已经收齐全网课程的目录。仍需持续取得有效的公开大纲，不能承诺所有知识点有足量课程。

实现入口：[共享课程库](../backend/app/course_library.py)、[刷新时钟与租约](../backend/app/mooc_refresh.py)、[查询调度](../backend/app/platform_search.py)、[完整大纲门槛](../backend/app/mooc_relevance.py)。下方真实对照、冷/热实验和验证计数保留为原阶段记录，不代表新增刷新机制的真实验收。

## 配置

两份 Key 已写入本机根目录 `.env`，该文件被 Git 忽略。不要把 Key 写入 `VITE_*`、前端、报告或 Git。

```dotenv
SEARCH_PROVIDER=searxng
BILIBILI_SEARCH_PROVIDER=searxng
MOOC_SEARCH_PROVIDER=tavily
TAVILY_ALLOW_KEYLESS=false
TAVILY_API_KEY=你的TavilyKey
SERPER_API_KEY=你的SerperKey
SHARED_COURSE_LIBRARY_ENABLED=true
SHARED_COURSE_LIBRARY_TTL_SECONDS=604800
SHARED_COURSE_LIBRARY_MAX_CANDIDATES=100
MOOC_GAP_SEARCH_ENABLED=true
MOOC_TARGET_COURSES_PER_POINT=3
MOOC_GAP_CHECK_WAIT_SECONDS=20
MOOC_REFRESH_ENABLED=true
MOOC_REFRESH_INTERVAL_SECONDS=86400
```

以上为本机配置；分发模板 `.env.example` 中 `MOOC_REFRESH_ENABLED=false`，刷新间隔同为 `86400` 秒。共享库和缺口补搜仍使用各自启用开关。修改服务端 `.env` 后重启后端；前端没有对应配置入口。课程证据的 `SHARED_COURSE_LIBRARY_TTL_SECONDS=604800` 与发现查询的 24 小时刷新间隔分别计时，刷新查询不会延长旧证据的有效期。

要显式改用 Serper，只修改 `MOOC_SEARCH_PROVIDER=serper` 并重启后端，B站配置保持原值。Serper 每次最多取 10 条普通搜索结果；不会自动升级结果数量或请求分页。Key 失效、限流或额度错误会停止对应来源，不自动切回另一家。免费试用入口：[Serper](https://serper.dev/)、[Tavily](https://app.tavily.com/)。套餐和余额以账户后台为准；应用不会修改计费设置。

本机现有召回上限仍为 B站每点 3 轮、MOOC 每点 5 轮，每次最多 12 候选（Serper 自身上限 10）、每任务最多 80 搜索请求和 60 详情页；缺口机制可提前结束 MOOC 搜索，到期刷新也只占其中已有查询槽，不突破这些上限。

## 真实召回对照

固定知识点：Python 列表与字典、pandas 数据分组与聚合、SQL 多表连接与分组查询、HTML 表单与网页结构。两来源均使用 2 轮、每查询 10 候选、最多 8 搜索请求、12 详情页、250 秒；独立空数据库，不导入已知课程，不启用共享库/缺口优化，不调用模型。仅检索 MOOC，避免 B站变量干扰对照。

| 指标 | Tavily | Serper |
| --- | ---: | ---: |
| 真实搜索请求 | 8 | 8 |
| 搜索 HTTP 200 | 8 | 8 |
| 跨查询原始候选（含重复） | 58 | 46 |
| 不同 MOOC URL | 53 | 38 |
| 支持的原生课程入口 | 6 | 8 |
| 完整大纲支持并实际显示的课程 | 2 | 2 |
| 响应明确报告的 credits | 8 | 8 |

两者实际显示相同的 2 门 Python 课程；pandas、SQL、HTML 在这个两轮对照中均为 0。未支持的入口、目录部分覆盖或技术语境不符的候选均没有填充推荐区。该小样本没有证明 Serper 相关性优于 Tavily；可作为显式替代来源。没有人工金标准，precision/recall 均为 `unknown`，大纲声明也不证明播放或教学深度。

过程中暂停过一次 Serper 段，以修正测试脚本跨来源保留站点暂停状态的问题。中断段保留了 6 次成功响应及 6 credits，另 1 次在途结果/额度 `unknown`，不纳入上表；Tavily 已完成结果保留，没有重复调用。恢复后的 Serper 使用原知识点与相同预算重新完成。前后保存的课程站点观察未见访问拒绝或限流；修复后的脚本也有 403/429 跨来源停止测试及取消导出测试。

## 真实冷搜与复用

另用空数据库固定测试 `pandas 数据分组与聚合`，本实验每点目标为 **1 门**（本机正式配置仍为 3），B站 2 轮、MOOC 3 轮、最多 5 搜索请求和 8 详情页。第二轮使用同一个库、新任务，未复用旧任务 ID。

| 指标 | 首次冷搜 | 第二次复用 |
| --- | ---: | ---: |
| MOOC 真实搜索请求 | 3 | 0 |
| MOOC 完整大纲课程 | 1 | 1 |
| 直接复用库课程 | 0 | 1 |
| 跳过 MOOC 查询槽 | 0 | 3 |
| B站真实搜索请求 | 2 | 2 |
| B站最终显示链接 | 0 | 14 |
| 首次出现已校验课程 | 约 26.1 秒 | 约 0.4 秒 |

真实课程为 `Python数据处理`（NJCIT-1469574161）。冷搜的 B站来源两次查询未完成，热搜两次成功；热搜详情预算不足以处理全部候选，两任务均如实保留 `partial`。MOOC 复用仍成功，B站搜索和已有结果不受影响。

首卡时间来自生产 `result_events` 生成器的进程内 SSE 观测，不是浏览器端延迟测量。热任务结束前已经收到库卡片；未出现缺少完整大纲却显示的 MOOC。此次节省 3 次 MOOC 搜索，不据此推算生产流量或月成本。共享库备份、冷/热全部原始证据均保留在独立验收目录，未用测试数据库覆盖用户数据库。

本轮已明确观察的 Tavily 搜索消耗共 11 credits；Serper 共 14 credits，另有中断时 1 次在途消耗 `unknown`。Tavily 调用前经只读 `/usage` 确认 Researcher 免费计划、免费余额覆盖测试上限、已付费消耗为 0；未修改任何计费设置。usage 接口与逐响应 credits 可能存在刷新时差，不能把旧余额当作最终余额。

## 验证和运行

最终后端全量 **4,309 passed，26 subtests passed**；前端构建通过，浏览器流式/封面/版本切换 **12 passed**，真实本地服务三种屏宽 **3 passed**。存在一条原有 Starlette TestClient 的 httpx 弃用提示，不影响本轮结果。扫描仓库非忽略文件及本轮产物共 6,285 个路径，未发现本机已知凭据。原数据库各旧表行内容哈希不变，预览库仅新增 `shared_mooc_courses` 和 `shared_mooc_terms`，旧表不变。

完整回归、构建及浏览器记录存放在验收目录：

`C:/Users/xiaoer/.codex/visualizations/2026/10/19/01a15377-c9da-7fe2-adfd-2bf11716a2d0/shared-course-library/`

- `provider-comparison-live/summary.json`：召回对照、实际额度及中断段说明。
- `library-cold-warm-live/summary.json`、`library.sqlite3`：真实复用和可复核库备份。
- `browser-results.json`：12 项浏览器流式/封面/版本切换测试；模拟来源，不消耗真实搜索额度。
- `real-ui-results.json`、`real-ui/`：3 种屏宽真实本地服务只读联调与截图。
- `backend-final.xml`：最终后端全量测试结果。

首次把受控跨端口 SSE 测试放在生产服务上运行时，5 项被生产 CSP 的同源连接策略阻止；随后使用测试所需 Vite 环境，12 项全部通过。未放宽生产 CSP。真实服务联调使用同源接口，3 项全部通过。

本轮已重启自己启动的 `http://127.0.0.1:8002` 预览服务，使用已有预览数据副本并增加共享库表。原 `8001` 进程及原用户数据库保留。验收库与预览库分开，预览库将从后续实际查询自动积累当前策略下的公开课程；不把测试任务混入用户项目。

可复现命令（输出必须是仓库外的新目录；不带 `--live` 为无网络计划）：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/compare_mooc_providers_live.py --live --confirm-serper-free-trial --output C:/temp/mooc-compare-new
.venv/Scripts/python.exe -X utf8 scripts/verify_course_library_live.py --live --output C:/temp/mooc-library-new
```

对照脚本要求两份 Key，Tavily 免费余额覆盖固定请求上限，以及明确确认 Serper 免费试用额度。这里不提供自动开通、充值或绕过限流路径。
