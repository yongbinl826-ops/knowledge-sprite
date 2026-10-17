# 项目制知识引导小精灵

输入任意 1–5 个知识点，真实搜索公开课程和视频，按知识点返回有来源证据的原平台链接。自动补全允许读取的公开元信息；无法读取、未知和结果不足都明确显示。

本轮仅实现资源发现。没有账号、教师后台、考试、积分、学习路径、视频下载或代理播放；没有预置课程库和静默演示回退。默认且唯一运行模式是 `live`。

2026-10-17 当前本机模式：按用户的本地自用选择，`.env` 已设置 `BILIBILI_PUBLIC_METADATA=true`，仅匿名读取 B站 HTTPS 视频页和 robots；`.env.example` 仍默认 `false`。从当次 HTML 内的 JSON 字面量解析同一 BV 的课程名称、真实封面和分 P 目录，章节链接使用来源给出的 `page` 编号，不调用非公开 API、登录接口或媒体地址。此配置记录本机运行选择，不表示取得平台授权或作出法律判断。实现、真实请求及界面验收记录见 [B站本地读取验收](reports/bilibili-local-use-20261017/README.md)。

前端仅展示课程封面、名称和至多两条相关章节；封面与课程名跳转课程页，有真实直链的章节可跳到对应分 P。完整目录保留在后台用于知识点匹配，不展示播放器或整份目录；“列表与元组”等复合知识点优先选择分别匹配不同子项的章节，没有依据的章节不补造。

2026-10-17 MOOC 修复：匿名公开 `/course/` HTML 已接入后台，直接解析当次响应自带的课程大纲，不执行页面脚本或调用学习接口；不再把许可范围未确认当成明确禁止。修复内嵌大纲遗漏和100项截断，超过500项则明确标注上限，不截断冒充完整目录。真实任务、逐项响应核对和页面截图见 [MOOC公开课程读取验收](reports/mooc-public-read-20261017/README.md)。下面保留的旧阶段报告按各自日期与范围读取，不能代替当前状态。

## 快速启动（Windows / PowerShell）

需要 Python 3.13、[uv](https://docs.astral.sh/uv/)、Node.js 22.12+ 或本次验证的 Node.js 24、Docker Desktop（仅本地 SearXNG 需要）。

```powershell
cd D:\项目制知识引导小精灵
# 先启动 Docker Desktop，然后建立本机私有搜索服务：
.\scripts\setup-searxng.ps1
# 安装锁定依赖、构建前端、启动单进程应用；首次自动复制 .env.example。
.\scripts\start.ps1
```

打开 **http://127.0.0.1:8000**。按 Ctrl+C 停止应用。搜索容器独立运行，可用 `docker compose stop searxng` 停止；数据保留在 `data/` 和 Compose volume。

第二次运行可使用 `scripts/start.ps1 -SkipInstall -NoBuild`。`.env` 只在启动时读取，修改后重启应用。不把 API Key 写进前端或 `VITE_*` 环境变量。

跨平台等效步骤：复制 `.env.example` 到 `.env`；复制 `deploy/searxng/settings.example.yml` 到 `settings.yml` 并用随机值替换 secret；运行 `docker compose up -d searxng`、`uv sync --frozen`、在 `frontend` 运行 `npm ci && npm run build`，最后在根目录运行：

```text
uv run --frozen uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

## 开发启动

```powershell
uv sync --frozen
uv run --frozen uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
# 另开终端：
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Vite 使用 `http://127.0.0.1:5173`，`/api` 代理到 `8000`。生产构建通过 FastAPI 同源提供，无需同时运行 Vite。

## 接入搜索与可选模型

### SearXNG（默认，无需付费 API）

`compose.yaml` 使用官方 GHCR 镜像，固定为本次实际拉取的 digest，只绑定 `127.0.0.1:18780`。Docker Hub 首次拉取遇到镜像校验错误，本次改用官方文档列出的 GHCR 镜像并成功启动，未使用陌生公共搜索实例。

`.env` 设置 `SEARCH_PROVIDER=searxng` 和 `SEARXNG_URL=http://127.0.0.1:18780`；也可填写自己托管的可信服务地址。必须在 SearXNG 配置中开启：

```yaml
search:
  formats: [html, json]
```

执行真实探测：

```powershell
curl.exe --noproxy '*' -G 'http://127.0.0.1:18780/search' --data-urlencode 'q=Python 列表 教程' --data-urlencode 'format=json'
```

HTTP 403 常见于 JSON 未开启或实例访问限制。SearXNG 能启动不代表其上游搜索引擎可用；查看任务的 `search_attempts[].upstream_warnings` 与容器日志。遇到上游限流、验证码或访问拒绝，停止相应路径，等待其暂停期，不配置绕过手段。

可以通过 `SEARXNG_ENGINES` 指定一般网页引擎，通过 `SEARXNG_VIDEO_ENGINES` 指定视频意图查询使用的引擎（包含站点限定查询）；名称必须来自自己实例的 `/config`。空值沿用实例默认设置，不暗中使用公共实例。`SEARXNG_FALLBACK_ENGINES` 是可选的独立备用组，只在主组无可用结果或发生允许回退的故障时尝试一次；配置备用组时必须显式指定主组，重叠引擎不会再次请求。所有请求、重试和备用请求都计入任务预算。该设置不会切换到付费 Provider。

本机最终配置为一般搜索 `bing`、视频搜索 `duckduckgo videos`、备用组 `bing,duckduckgo videos`（自动排除与主组重复的引擎）；之前遇到验证码的一般 DuckDuckGo 引擎不再选用，YouTube/B站直搜引擎已移除；这只是有日期的运行配置，不承诺这些引擎长期可用。视频搜索返回的类型仍属于搜索证据。实例级 401/403 停止后续查询；429 尊重 Retry-After；上游限流、验证码、拒绝访问的引擎会暂停。默认组成员未知时，收到这类限制后保守暂停整组，避免再次请求受限来源。

可选 `OPEN_COURSE_DOMAINS` 最多配置两个课程来源域名，本机为 `ocw.mit.edu,open.edu`。每知识点最多增加一条合并站点查询，保留两条不限站点查询；这是搜索范围，不是预置课程列表或采集授权。OpenLearn 的本轮 robots 请求实际返回 403，已通过 `DENIED_FETCH_HOSTS=open.edu` 停止后续自动采集；搜索服务发现的链接仍可独立保留。

本项目的 SearXNG 模板移除了 `youtube` / `bilibili` 直接抓取引擎；应用也拒绝显式启用这两个引擎，并把用户输入的引擎选择操作符视为普通文字。外部自托管实例的管理员需同样核对并关闭未经许可的直接采集引擎。一般搜索服务发现的原平台链接可以保留，详情采集仍独立遵守站点规则。

每条查询的 `provider_requests` 记录本轮实际 HTTP 状态、耗时、请求引擎、已识别的上游原始原因；缓存来源的历史请求另列，不能把旧 200 当成本次成功。未知异常原因保留 unknown，不输出可能含凭据的异常正文。

### Tavily（可选）

仅在已有 Key 且主动选择后启用：`SEARCH_PROVIDER=tavily`、`TAVILY_API_KEY=你的服务端密钥`。不会创建账号、购买额度或从 SearXNG 自动切换到 Tavily。调用官方 HTTP Search API，统一转换为候选结构；无 Key 返回明确配置错误。本次若未配置 Key，只有离线解析/故障测试，不能称为已联网验证。

### MIT 官方站点地图发现（可选）

默认仍为 SearXNG。设置 `SEARCH_PROVIDER=official_sitemap` 可明确切换为 **仅 MIT OCW** 的官方发现模式；每个原始知识点读取最多 `OFFICIAL_SITEMAP_CHILDREN_PER_QUERY=1` 个匹配子站点地图（可配置上限 2）。也可在常规搜索模式设置 `OFFICIAL_SITEMAP_FALLBACK=true`，只在主来源正常返回空结果或没有可展示相关链接时补充官方发现。MOOC/B站限定查询不会偷偷切到 MIT，主来源拒绝访问或限流不会触发此回退；MIT 自身故障只暂停 MIT 来源并保留警告，后续知识点仍可继续使用主来源。

生产只读取 robots 实际声明的同源 sitemap，课程链接必须来自真实 `<loc>`，不读取 reports 中的快照，不由路径拼造课程 URL。URL 路径词仅作低置信召回，细知识点没有完整词面匹配就返回 0；原始版本要求保留。推荐展示仍须取得真实页面的课程/视频类型与原知识点覆盖证据，静态结构不代表可播放。官方模式不承诺中文翻译、任意细分点召回或其他平台覆盖。

`OFFICIAL_SITEMAP_CACHE_TTL_SECONDS` 默认 21600 秒，上限 86400 秒。官方模式或启用该回退时关闭外层查询结果缓存，避免旧索引产生的新查询结果延长索引寿命；robots 声明、root 与子 sitemap 按来源、安全策略和 TTL 独立缓存。请求数包含实际 robots、索引、子图与重定向；官方发现 DoH 单列为 `discovery_dns_requests`，不等于整个采集器的全部 DNS 请求。实现与修复验证入口见 [官方发现实现报告](reports/completion-20261013/official-sitemap-implementation.md)。

### LLM（可选）

默认 `LLM_PROVIDER=none`，规则查询与排序完整可用。需要时设置 `LLM_PROVIDER=openai_compatible`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，接入支持 JSON Chat Completions 的可信服务。模型仅返回关键词、候选 ID、顺序和已有证据 ID；结构、数量、ID 归属均校验，任何新 URL 或非法结构使本次模型结果失效，并回退规则。网页和摘要通过不可信数据字段传入，不提供执行工具或配置能力。

没有对每一种兼容模型服务做实测；服务的实际模型名、JSON 支持与费用由配置者确认。未配置模型不妨碍真实搜索。

## 采集策略和平台支持程度

| 范围 | 当前实现 | 不能据此推断 |
| --- | --- | --- |
| 常规搜索模式 | 每个知识点包含不限站点查询；通用静态 HTML/JSON-LD/Open Graph 提取器。官方 sitemap 模式另限 MIT 同源 | 覆盖整个互联网、每次都有足够结果；MIT 官方模式覆盖其他平台 |
| B站 | 默认停止后台详情读取；本机显式开启匿名 HTTPS 视频 HTML 模式，从同 BV 的 `videoData.pages` 提取真实分 P、标题、时长及链接，封面来自页面元信息 | 本机选择等于平台授权；仅保留搜索链接的分 P 参数等于已提取目录 |
| 中国大学 MOOC | 读取匿名公开 `/course/` HTML 自带的课程信息与大纲，逐次检查 robots 和访问状态 | 公开大纲等于已选课、可播放或已获广泛数据使用许可 |
| 学堂在线 | 域名识别、定向搜索；保留独立采集策略与依据 | 搜索发现等于后台目录已取得 |
| 其他公开课程网页 | 站点策略、robots、DNS/IP/重定向安全检查后读取，按实际证据补全 | HTTP 200 等于免费、可播放或完整覆盖 |
| 动态网页 | 可选安全 Fetcher + 离线 Edge 补全已实现，默认关闭；已验证隔离流程与取消 | 任意动态网站可采集；本次真实动态目录增益已通过；已使用 Crawl4AI |

平台策略核对与公开来源仍保留。B站协议5.6(3)、1.5的原有记录对应默认配置下的请求前停止；普通 `ALLOWED_RESTRICTED_HOSTS` 不解除该默认策略。本机另以专用 `BILIBILI_PUBLIC_METADATA=true` 开启窄范围读取：只允许 `https://www.bilibili.com` / `https://bilibili.com` 的视频 HTML 与 robots，视频查询参数仅保留真实 `p` 编号；重定向也必须留在该范围，不运行页面脚本、不采集推荐合集或继续遍历 UP 主投稿。此本地选择和平台条款记录分别保留。

YouTube、学堂在线的原有默认限制不变。MOOC 当前使用独立的公开课程 HTML 范围，不把自动聚合许可尚未确认推断成公开课程页不可访问。`ALLOWED_RESTRICTED_HOSTS` 仍用于其他需精确配置的来源，不跳过 robots、访问限制页和 SSRF 检查。robots 是独立的路径规则，不代表数据使用授权。

SSRF 保护限制 HTTP/HTTPS 标准端口，拒绝凭据、非公网地址、本地域名、云元数据地址及隐藏 IPv4 的 IPv6 隧道/转换范围；每次请求和重定向重新解析验证，连接钉住所验证的公网 IP，TLS 仍验证原域名，禁用隐式代理。浏览器子请求未受控，故不提供浏览器抓取入口。

某些本地代理的 Fake-IP DNS 会把公网域名解析为 `198.18.0.0/15` 等非公网范围，此时默认解析器会安全拒绝。可明确选择 `DNS_RESOLVER=cloudflare_doh`：仅使用固定 Cloudflare 公开解析服务和 TLS 主机身份，依然校验全部地址并钉住出口；会向 Cloudflare 发送待解析的课程域名，不发送密钥或知识点正文。此设置不更改操作系统 DNS/代理，也不放宽网站限制。默认值为 `system`，本次本机验收的明确选择见实现报告。

## 状态与证据怎么读

- **completed**：计划查询正常结束，可能没有合适课程。页面受阻会在资源卡片单独标注。
- **partial**：有已保存的有效搜索结果/查询，但部分搜索失败、到达预算或期限。
- **failed**：全部搜索失败或配置缺失。不会显示预置课程。
- **queued / running**：真实队列和执行阶段，页面显示实际查询进度；候选、补全等明细保留在任务数据中，不做假进度动画。
- **interrupted**：服务停止或重启时遗留任务，结果仍保留，可提交相同输入重新执行。
- **cancelled**：用户主动取消排队或运行中的任务；已保存结果仍可查看，取消等待子请求清理后确认，后续队列继续运行。

每组最多 5 条。数量不足不会凑数；按平台筛选还可能减少可见结果。标题/摘要匹配只表示“可能涉及”。`ranking_score` 是内部排序值，不是正确概率、教学质量评分或观看验证。

推荐保留有依据的视频候选，以及明确课程入口的搜索发现候选；后者单独标注是否含视频未核验。普通 JSON-LD Course 和普通课程大纲不足以证明存在视频。文字文档、搜索页及未知类型不会因为含有“教程”关键词就冒充视频课程。类型与视频证据分开记录：`video_evidence_status=search_discovered` 只表示搜索发现，`page_verified` 表示有页面视频结构或真实视频目录，`none` 表示缺少视频证据。搜索类型依据不会升级为页面核验。未知候选仍可在采集预算内读取页面以判断类型。

目录为可选信息，缺失不会阻止有充分搜索身份与相关性依据的链接展示。目录支持真实 JSON-LD、B站公开 HTML 中同 BV 的 `videoData.pages`、MOOC 公开课程大纲、MIT OCW 可见视频目录，以及 Internet Archive 公开 HTML 中的播放列表属性。字段与目录均由统一流程生成来源证据。B站分 P 链接使用 `pages[].page` 生成 `?p=N`，不把 CID 或数组序号当成分 P 编号。Archive 列表若只给出媒体文件地址，会保留章节标题和原页面来源，章节直链/起止时间留空；不会提供媒体下载入口或猜造章节链接。

署名通过 `author_role` 区分：`course_instructors` 显示“课程教师”，`video_instructors` 显示“本讲教师”，`credited_creator` 显示“来源署名”。例如课程页教师与课程引用的历史录像讲师可以不同，机构署名也不等于录像讲师；未知角色保持空值，不按页面位置猜填。

章节 `duration_seconds` 是该条目的时长，允许保留来源明确给出的正数小数秒；`start_seconds/end_seconds` 是来源明确给出的时间轴起止位置。时长不会变成结束时间，也不相加为课程总时长。目录逐行核验 `evidence_id`、`kind=catalog`、`field=chapters.N` 和证据 JSON 中的标题、链接、起止时间、时长；缺少或不一致的证据不会进入推荐章节。前端只显示当前知识点对应的至多两条学习位置。

资源区分 `search` 搜索证据、`page` 页面元信息、`catalog` 真实目录。即使有目录，也未验证完整讲解或实际可观看。登录、收费、选课条件无依据即 `null` / 未知；所有资源的 `playback_verified` 为 false。

资源 `field_provenance` 可追溯字段来源；匹配关系含依据类型和证据 ID。一个资源可以匹配多个知识点。跟踪参数会被移除，`p`、`chapter`、`course`、`term` 等实际入口参数及锚点保留，不把章节入口丢失。

缓存时间、是否命中、是否过期都有记录。默认不使用过期缓存；明确启用 `ALLOW_STALE_CACHE=true` 后，服务失败时可展示标注过期时间的真实历史搜索证据。查询、语言、版本、筛选、搜索服务身份进入缓存键；详情缓存还区分安全策略。

页面缓存只复用页面事实与相应证据，搜索标题/摘要始终使用本次查询的发现记录。主页成功但目录补全超时的结果最多缓存 300 秒；目录预算不足时保留该任务的主页证据，但不写长期不完整缓存，后续预算恢复仍可尝试补全。配置 `DENIED_FETCH_HOSTS` 的停采域会进入缓存身份，并在 capabilities.fetch.stopped_hosts 公开显示。

## 预算与运行边界

默认每任务 5 知识点、30 次真实搜索 HTTP 请求（重试和备用组计数）、40 个详情页、180 秒期限。按知识点轮转分配预算；首轮每个知识点取得候选后，详情补全与余下搜索并行推进，共享最多 5 个网络槽，同一站点并发为 1。任务之间仍串行。`details_cached` 单列缓存补全，避免被误读为本轮新抓取。初始参数不是性能承诺。

当前 `.env.example` 与本机配置采用 `GLOBAL_CONCURRENCY=1`，搜索和详情共用一个网络槽。本机 `.env` 已持久保存每任务 12 次搜索、12 个详情页、240 秒期限，准确生效值以任务 `budgets` 和 `capabilities.limits` 为准；配置支持范围不代表本轮实际并发数。

有连接/读取超时、一次有限重试、字节和重定向预算。`FETCH_MIN_INTERVAL_MS` 默认 **500 毫秒**，约束同一主机相邻请求的发起间隔；初次请求、每次重试、robots 请求和重定向后的请求均经过该约束。实际间隔取配置下限与已知 robots `Crawl-delay` / `Request-rate` 所要求间隔的较大值；间隔超过本次等待预算时停止并标注 `robots_delay`。

429 或带 `Retry-After` 的 503 会暂停相应主机，暂停期内不继续请求。403、验证码或明确拒绝访问会隔离同一主机，在当前采集器实例内停止其后续页面请求。`access_restriction` 证据及 `fetch_status` 来源指向实际触发限制的 URL（可能是 robots URL），后续资源不会被伪装成已经请求并收到相同响应。站点条款限制仍另列为 `site_policy` 证据。

B站“视频不见了”错误页可能返回 HTTP 200；只有同 BV 的页面错误数据与可见错误提示一致时，内容状态才记为 `not_found`，原始 HTTP 200 仍保留在传输记录中。HTTP 成功、目录取得与视频可播放分别记录，不互相替代。

SQLite 持久化任务、知识点、资源、匹配、证据、执行记录和缓存。不要开启多个 Uvicorn worker，不使用 `--reload` 做验收。SQLite 队列面向本机小规模运行。默认等待上限 20、实例每分钟接收上限 30；满额返回带 Retry-After 的 429。出队时等待超过 300 秒的任务直接中断。/health 报告工作进程、数据库、排队和来源冷却状态；不能据此断言外部搜索覆盖率。

默认仅本地运行。对外部署需另行实现鉴权、请求限流、严格 CORS、反向代理与独立网络出口策略；当前版本没有这些生产部署能力。

## 接口

### 可选传输诊断与 JS 补全

`FETCH_PHASED_TIMEOUTS=true` 将首响应、正文空闲及正文总期限分开，记录 TCP/TLS/响应头/正文阶段、部分读取字节及哈希；不把部分 XML 当成功索引。正文从响应头开始只有一个固定期限：取正文硬上限、`空闲额度 + 本次合法 Content-Length（缺失时取字节上限）/最低速率`、请求剩余时间、任务剩余时间的最小值；持续收到数据不会延长该期限。DNS、请求间隔和 HTTP 同受任务绝对期限约束，任务耗尽不会被记成来源永久故障。相关参数见 `.env.example`。

`JS_RENDER_ENABLED=true` 配合 `JS_RENDER_ALLOWED_HOSTS` 与 `JS_RENDER_ASSET_HOSTS` 精确允许名单启用生产补全；默认保持关闭。需要本机 Node、已锁定的 `frontend/node_modules/playwright` 和 Microsoft Edge。入口与其真实声明资产都先通过同一 Fetcher；离线 Edge 只能回放这些字节。第一轮实际观察到的同源无查询参数 `.md/.json` GET，先补取第一个依赖，再进行最后一次离线渲染；后续首轮请求记为延后，避免把离线阻止所触发的备用 404 页面当成核心依赖。第二轮仍缺依赖即为不完整，没有第三轮或在线浏览器回退。保留原 CSP。每次补全有独立资源、目标 HTTP、DoH、字节和时间上限，同时受任务期限及详情页调度约束；这些请求上限不是整个任务的 HTTP 总数。

MIT 已观察到的 Appzi/GTM 反馈统计脚本仅在精确 HTTPS 路径、GET、script 类型时阻止且不计核心依赖失败；没有任何外部请求或字节回放。其他用途、未知路径、原 CSP 限制仍失败。jsDelivr 的 robots 400 仅对原始且无重定向的同源 robots、已核实纯文本路由错误、无重试/认证挑战头作窄范围缺失规则处理；访问拒绝、验证码和站点许可判断不变。

API 返回 `render_diagnostics` 与字段级 `acquisition=offline_rendered_dom`、输入/清单/DOM 哈希；失败保留静态信息，动态访问限制如实标注。普通页面标题或菜单不会因此升级为课程。操作系统全部后台出口、UDP 与全部浏览器子进程退出仍未取得完整证明，不能据此对外开放任意页面渲染服务。

`JS_RENDER_ALLOWED_ENTRIES` 可进一步限定完整 HTTPS 课程入口。配置后入口必须同时符合主机名单和精确 URL；同源数据、脚本、样式及其重定向必须留在该入口目录子树，robots 规则文档单独读取；跨源资产仍须来自入口实际声明且列入资产主机名单。无效非空配置直接报错，不静默放宽。首轮 POST、导航、未知脚本、CSP 或 worker 等关键失败不会被第二轮成功覆盖。

2026-10-14 新验证：MIT 从 robots→索引→子索引→课程主页成功，4 次目标请求、8 次 DoH；该课程没有提取到视频目录。微软 AI 课程直接入口经真实 Fetcher 和两轮离线 Edge，从静态 0 条增至 28 个目录链接，6 次目标请求、12 次 DoH；这是文字课程目录，未证明视频或播放。两个真实 SearXNG 搜索任务未发现该课程，因此动态课程的搜索→任务→结果全链仍未通过；没有将直接入口或回放结果插入正式搜索库。所有先前失败均保留。

`POST /api/search-jobs` 返回 HTTP 202 与 `job_id`；其余接口：

```text
GET /api/search-jobs/{job_id}
GET /api/search-jobs/{job_id}/results
POST /api/search-jobs/{job_id}/cancel
GET /api/capabilities
GET /health
```

字段见 [API 合约](docs/api-contract.md)，可交互文档在本机 `/docs`。capabilities 的 `configured` 只代表配置齐全，`available` 代表最近请求成功；不会返回密钥和内部服务 URL。

相同规范需求的进行中任务会复用原任务，创建响应包含 `reused`。客户端可用 `Idempotency-Key` 请求头避免 POST 超时重试重复检索：同键同请求在终态或重启后也找回原任务，同键不同请求返回 409；明确新检索使用新键。取消和恢复均保留原来源证据。

实际进入执行后结束/取消的任务详情包含 `fetch_diagnostics`：本任务的采集事件计数差、UTC 时间和最近 512 条脱敏事件；排队时即取消的任务可能没有此字段。HTTP 返回码、网络错误类型与 robots 路径可审计，截断单独标记；这些计数只覆盖目标页面与 robots，DoH 请求另属解析基础设施，未计入该字段。详情资源数不能当作实际 HTTP 次数。离线生命周期、幂等、缓存与顺序隔离的测试记录见 [后端生命周期报告](reports/completion-20261013/backend-lifecycle.md)。

## 测试与真实验收

```powershell
uv run --frozen pytest
cd frontend
npm run build
npx playwright install chromium
npm run test:e2e
cd ..
# 应用启动后；真实搜索，不使用 mock；六组限定用例包含指定4知识点、英文、空结果、目录与平台路由。
uv run --frozen python scripts/live_acceptance_revision.py
uv run --frozen python scripts/dependency_inventory.py
```

本机已验证的浏览器路径为 Microsoft Edge：在 frontend 目录执行 `$env:PLAYWRIGHT_CHANNEL='msedge'` 后运行 `npm run test:e2e`，无需再次下载 Chromium。默认浏览器下载中断的记录已保留在前端 QA 报告。

联网脚本输出独立时间戳 JSON，保留查询、任务阶段、预算、真实链接、平台、补全状态、匹配证据和失败，拒绝覆盖旧报告。独立公开页面探测不会插入正式搜索结果。离线 tests/Playwright fixture 与正式 SQLite 数据完全分离。

当前 B站本地模式的入口为 [2026-10-17 B站本地读取验收](reports/bilibili-local-use-20261017/README.md)，MOOC 见 [公开课程读取验收](reports/mooc-public-read-20261017/README.md)。历史 [2026-10-14 原定40主题真实联网验收](reports/link-completion-20261014/final-report.md) 及 [覆盖矩阵](reports/link-completion-20261014/coverage.md) 保留原范围。此前 [8案例链接发现试用](reports/link-trial-20261014/final-report.md)、[真实联网验收与剩余边界](reports/runtime-revision-20261014/final-report.md)、[传输与动态补全实测](reports/runtime-revision-20261013/final-report.md) 与 [补充实现与真实验收报告](reports/completion-20261013/final-report.md) 均按原时间边界读取。固定批次验收脚本 `scripts/live_completion_acceptance.py` 及两个输入组不会覆盖重跑。后端课程身份、取消和缓存修复分别见 [身份复核](reports/completion-20261013/identity-review.md) 与 [任务生命周期](reports/completion-20261013/backend-lifecycle.md)。

历史阶段（2026-10-14）：全套测试计数及冻结哈希见该阶段报告；此前 28 项 Edge 测试记录保留，该阶段另做真实任务结果的界面检查。这些不等于全部平台联网通过。当时 B站样本浏览器可见 15 个分集，MOOC 两个入口的大纲/访问状态不同，两站的应用自动目录尚未取得。随后实现的当前后台读取情况见上方 2026-10-17 报告。目录仍是可选补充，播放不作为资源发现验收条件。本机继续使用 SearXNG，并启用 MIT 官方回退和仅限 `https://microsoft.github.io/AI-For-Beginners/` 的受控 JS 补全；模板仍默认关闭。无该课程搜索命中时，不会注入直接验证结果。历史失败记录仍在 [official-repair-live.json](reports/completion-20261013/official-repair-live.json)。

历史 [来源适配器与固定样本评估报告](reports/adapter-evaluation-20261013/final-report.md) 及 [固定来源字段对照](reports/adapter-evaluation-20261013/extraction-field-ledger.json) 保留。4 份来源文档、41 项目录观察归属 1 个已人工核对的 SICP 课程家族；课程首页、目录、章节及镜像不分别算新增课程。当前自动身份只确认有来源依据的同站课程关系，跨站镜像关系没有证据时为 unknown。已有入口保留、标题清理和章节数增加均不等于独立课程发现增长。

历史验收完整保留：[平台覆盖与播放抽查报告](reports/coverage-followup-20261013.md)、[目录补充验收报告](reports/implementation-revision-report.md)、[首次实现报告](reports/implementation-report.md)。各报告的离线回放、真实联网及播放观测分别读取，不相互替代。第三方说明见 [依赖与许可证](docs/third-party.md)，官方参考见 [文档依据](docs/official-references.md)。

## 目录

```text
backend/app/       配置、API、任务、SQLite、搜索适配、排序、LLM、安全采集和提取
backend/tests/     采集器与安全测试
tests/            核心单元与接口测试
frontend/         React / TypeScript / Vite、界面及流程测试
deploy/searxng/    自托管搜索配置模板（真实 secret 被忽略）
scripts/          启动、联网验收、依赖清单工具
reports/          本次真实测试报告和界面证据
docs/             合约、官方接口依据、第三方说明
data/             本机 SQLite（不入库）
```

历史阶段（2026-10-14、8案例）：保留原始结果及失败；随后使用相同保存证据修复串题与术语误删，该阶段没有追加真实搜索。阶段测试为534项后端及26项子测试通过；前端30项中首次29通过、1项旧文案断言失败，修正后该项通过。记录见 [历史8例报告](reports/link-trial-20261014/final-report.md)。

随后完成原定40主题的真实API路由与外部检索，B站／MOOC均逐题发起定向查询；默认推荐和平台分栏分别计数。H14／H15暴露的相关推荐尾部及技术语境串题经通用规则修复、保存证据回放和有界实网复验，原始失败保留且标为已消费开发样本。最终570项后端及26项子测试通过。链接产出不等于教学质量、页面、目录或播放通过，详见最新40主题报告。

历史阶段（2026-10-17，浏览器目录核验）：实际打开B站视频页与MOOC课程页，新增目录适配器并逐项核对15个分P、84项课程大纲。MOOC当时学期关闭的提示保留；当时后台自动采集策略仍有限制。真实页面、修复前后对照、运行方法与测试见 [平台目录核验报告](reports/platform-catalog-20261017/README.md)，不能将该阶段保存DOM复核理解为全平台自动采集已经打通。

历史阶段（2026-10-17，公开 HTML 接入前）：实际从双知识点输入完成12次真实搜索，发现B站21条、MOOC11条候选，无旧缓存命中；进入详情流程的9条B站、3条MOOC均在请求前因当时的条款/许可范围判断停止，新取得目录0条，**该阶段后台目录链路未通过**。修复了动态失败长缓存、条款变更缓存失效、重定向证据范围及审计错误处理；原文截图、真实任务与运行方式见 [后台联网验收](reports/platform-live-chain-20261017/README.md)。该历史结论不代替后续 MOOC 公开课程读取及 B站本地自用模式的当前结果。
