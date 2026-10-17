# API 合约

默认模式 `live`；日期为 UTC ISO 8601。错误只含安全的 code/message。

Provider 增量：服务端可选择 `SEARCH_PROVIDER=official_sitemap`（MIT-only），默认仍为 searxng；`OFFICIAL_SITEMAP_FALLBACK=false` 默认关闭，只在主来源正常空结果或无可展示相关链接且域范围允许 MIT 时启用。capabilities 含 `official_discovery` 的 selected/fallback_enabled/scope/children_per_query/cache_ttl_seconds/dns_counter_scope；官方模式其他平台 discovery=out_of_scope。请求正文不增加自由来源 URL 或站点地图地址。

官方来源候选仍为真实检索记录：search evidence.source=official_sitemap，附 `discovery_evidence:{kind:sitemap_loc,source_url,source_sha256,observed_url,observed_at,cache_hit,index_url,index_sha256,robots_url,title_basis:url_path_words,confidence:low}`。URL 路径推得标题不算页面标题或教学覆盖；即使混合普通搜索记录，也不把该来源的 title/snippet 纳入相关性。纯官方候选必须有实际 page/catalog 对原始知识点完整词面的覆盖及独立课程/视频类型依据，才能进入展示结果。

官方发现的 robots/索引/子图/重定向真实 HTTP 计入既有 search_requests；其实际 DoH HTTP 单列 progress.discovery_dns_requests。search_attempts 新增 provider_dns_requests、discovery 及相应 cache_origin 字段；官方回退失败以 source=official_sitemap、error_code 记录独立 warning，不变成主来源的 access_denied，不停止后续主查询。官方模式或启用回退时不使用外层 query cache，只使用带 TTL 的独立来源索引缓存；page cache 边界不变。该模式 fetch_diagnostics.scope 明确包含 XML；它仍不把 DoH 混入目标 HTTP 计数。

`POST /api/search-jobs` 请求：`{knowledge_points: string[] (1..5), student_level: "beginner"|"intermediate"|"advanced"|"any", language: "zh"|"en"|"any", project_context?: string, technical_version?: string, preferred_platforms: ("bilibili"|"icourse163"|"xuetangx")[]}`。所有可选字段有默认值。响应 HTTP 202 `{job_id,status,reused:boolean}`。新任务为 queued/reused:false；相同规范请求已有 queued/running 任务时返回其原 ID 和当前状态/reused:true，不重复加入队列。规范化压缩知识点、项目背景和技术版本中的空白，去除重复平台；保留知识点与平台的有效顺序，不合并不同版本或背景。

可选请求头 `Idempotency-Key`：1–128 个字符，首位为字母或数字，其余允许字母、数字、点、下划线、冒号和连字符。同键与相同规范请求持久关联原任务，任务已终结或服务重启后仍返回原 ID、原状态和 reused:true；同键用于不同请求返回 HTTP 409。客户端首次提交时生成键，超时或响应丢失后重试使用原键；用户明确发起新检索应使用新键。不带该头时，仅合并进行中任务，终态重新提交会创建新任务。幂等键不加入请求正文，不包含密钥等敏感信息。

`POST /api/search-jobs/{job_id}/cancel` 无正文，返回 HTTP 200 `{job_id,status,cancelled:boolean}`。queued/running 任务停止后返回 cancelled/true；运行中取消会先等待搜索与详情子任务清理，再确认终态，队列继续处理后续任务。已取消任务重复调用仍返回 cancelled/true；completed/partial/failed/interrupted 任务不改状态，返回 cancelled:false；不存在返回 404。已保存资源、排序与证据仍可从原 GET 接口读取。

`GET /api/search-jobs/{job_id}` 返回：
```json
{"job_id":"...","status":"running","phase":"searching","created_at":"...","updated_at":"...","request":{},"progress":{"queries_planned":20,"queries_completed":3,"search_requests":3,"search_successes":2,"search_failures":1,"candidates_discovered":12,"resources_discovered":8,"details_attempted":0,"details_completed":0,"cache_hits":0},"budgets":{"max_search_requests":30,"max_detail_pages":40,"deadline_seconds":180},"warnings":[],"errors":[{"code":"search_unavailable","message":"搜索服务暂时不可用"}],"knowledge_points":[{"knowledge_point_id":"...","text":"Python 列表与字典"}]}
```
`status`: queued / running / completed / partial / failed / interrupted / cancelled。`phase`: queued / expanding / searching / fetching / ranking / done。进度全为实际计数，勿换算假百分比。终态均 `phase:done`。cancelled 表示用户主动取消；interrupted 表示服务停止或重启中断。

`GET /api/search-jobs/{job_id}/results` 返回 `{job_id,status,groups:[{knowledge_point_id,text,total_matches,items:[{resource,match,evidence:[]}],platform_items:{平台:[{resource,match,evidence:[]}]}}],warnings:[],search_attempts:[],identity_summary:{}}`。items 与每个平台的 platform_items 分别在原排序基础上优先选择不同已知课程身份，再补同课程条目，最多5项；不是纯分数前5名。在截断前按平台分组，避免全局第6名的合格课程无法筛选。均来自同一已存储结果，不产生额外搜索。空组视 job status 分辨正常无结果与服务失败。

资源另含 `resolved_url`（本次安全抓取的实际响应 URL）、`parent_course_url`（同源显式 Course 父关系）和 `course_identity`。身份结构见 [身份字段契约](../reports/completion-20261013/identity-review.md)。可靠页面 JSON-LD Course 或 MIT 课程主页可独立支持课程准入，即使 `video_evidence_status=none`；普通笔记标题含“课程”加 CSS 目录不足以证明课程。HTTP 重定向来源仅绑定抓取器记录的 resolved_url，不相信页面自行声明的跨站 canonical。

resource 至少含 resource_id,title,url,canonical_url,platform (bilibili/icourse163/xuetangx/other),resource_type (video/course/playlist/unknown),author,author_role,description,language,duration_seconds,published_at,discovered_at,fetched_at,fetch_status,metadata_evidence_level (search/page/catalog),requires_login/requires_payment/requires_enrollment (boolean|null),chapters:[],field_provenance:{},cache:{hit:boolean,cached_at:string|null,stale:boolean},playback_verified:false。未知可空。`fetch_status` 为可扩展字符串；成功 `fetched`，未取 `not_fetched`，其他状态均需展示受阻/未核验。平台策略明确区分 site_policy_blocked（有具体策略来源）与 policy_unreviewed（许可范围待核对）；另有 robots_blocked、robots_unavailable、robots_delay、captcha、login_required、not_found、access_denied、timeout、rate_limited、unsafe_url、javascript_required、error_page 等。推荐可含有视频发现依据的候选、页面视频证据资源，或有真实课程入口格式依据的搜索课程候选；后者视频状态仍为 none。普通 Course/课程大纲不证明视频。`video_evidence_status`: search_discovered / page_verified / none，分别表示搜索发现、页面视频结构已取证、无视频证据；均不证明学生实际可观看。unknown 候选仅保存供补全判断。

`author_role` 是 `"course_instructors" | "video_instructors" | "credited_creator" | null`，分别显示“课程教师”“本讲教师”“来源署名”。author 与 author_role 各有独立字段来源；角色依据必须属于实际采用的署名。MIT 课程教师不能自动用作同页历史录像的讲师，Archive 的机构 creator 仅表示来源署名。无明确角色时为 null，不补猜角色。

目录增量：`catalog_kind` 区分 course_outline / video_playlist / video_chapters；`catalog_fetch_status` 独立记录目录跟随页状态。每条 chapter 含 title、url（可空）、start_seconds/end_seconds（无证据为 null）、可选 duration_seconds、source、evidence_id，可另含 source_url。`duration_seconds` 为来源明确记录的有限正数秒，可含小数；start/end 为有限非负数秒，二者同时存在时 end 不小于 start。未记录的值为 null 或省略，不能把时长改写为结束偏移，不能累加章节时长作为 resource.duration_seconds；集合或课程总时长没有独立来源时仍为 null。

目录证据按行绑定：chapter.evidence_id 必须命中同一资源的 `kind=catalog` 证据，证据 field 必须等于该行的 `chapters.N`（N 从 0 开始），证据 url 必须是有效来源页。text 必须可解析为 JSON 对象，其中 title/url/start_seconds/end_seconds/duration_seconds 与该行逐字段一致，null 与省略均视为未知。其他章节的有效证据不能借给本行；目录总字段的汇总证据也不能代替逐章证据。界面与验收只认通过这些校验的目录行。

目录总字段和每章证据都指向实际来源页。若来源播放列表只暴露媒体文件而没有章节网页入口（如 Archive），chapter.url=null，并保留原页 source_url；访问目录来源使用对应证据页，不把媒体下载 URL 伪装成课程章节链接。解析出视频结构、目录或时长均不构成播放核验。

进度增量：`details_cached` 表示缓存补全次数，`catalog_pages_attempted/completed` 表示公开目录跟随页处理次数。目录页与资源详情共用 max_detail_pages 预算；details_completed 不包含缓存，也不包含另列的目录页。并行阶段 phase 只表示主阶段，具体完成度读实际计数。

match 含 knowledge_point_id,resource_id,ranking_score,recommendation_reason,matched_evidence_ids:[],coverage_basis:[]。分数仅内部排序分。

evidence 含 evidence_id,candidate_id (search evidence),kind (search/page/catalog/page_link/site_policy/access_restriction),source,query,url,title,snippet,observed_at,cache；页面/目录等证据另含 field、text。搜索类型证据另有 source_engines、type_source、resource_type_hint；搜索视频模板不等于页面验证。search_attempts 含 knowledge_point_id,query,domain_filters,provider,status,candidate_count,cached_at,cache_hit,stale,error_code,network_attempted,upstream_warnings,provider_requests,cache_origin_requests,cache_origin_warnings。provider_requests 只记录当前真实请求；缓存原始请求单列，不把缓存旧200覆盖当前401。SearXNG 有结果但部分上游引擎失败时任务 partial；缓存保留该故障证据。

任务结束时可含 `fetch_diagnostics:{available,started_at,finished_at,counts_delta,events:[],truncated,scope}`。来自实际 Fetcher 的计数差和当前任务最近 512 条脱敏事件，任务间不累加；events.at 为 UTC ISO 时间，HTTP 完成事件的 status_code 为真实响应码，网络失败只记录 error_type，不猜 HTTP 状态。URL 去除查询值和锚点，完整 URL 仅保存 SHA-256 供对照。counts_delta 中的 http_started 才是实际发起 HTTP 数；details_attempted、robots/DNS/节流等事件不可代替它。事件超出 512 条时 truncated:true，计数差仍保留。常规 scope 为 `target HTML+robots only; DoH HTTP uncounted`；官方模式或启用官方回退时为 `target HTML/XML+robots only; DoH HTTP separately traced for official discovery`。二者都不把 DoH 服务请求混入目标 HTTP；仅官方发现阶段的 DoH 另在 discovery_dns_requests/provider_dns_requests 记录。无追踪能力的隔离测试适配器会标 available:false；未执行即取消的排队任务可能无该字段。

搜索缓存按 Provider、搜索实例身份、引擎组、查询、语言、版本、域范围和结果上限隔离；页面缓存还按采集启用状态、许可/停采域、DNS 解析策略和解析/载荷版本隔离。页面缓存不保存查询特有的搜索标题、摘要或搜索证据，未知页面字段始终回退到本次候选；真实页面标题、摘要及其独立来源照常保留。目录 budget_limited/not_attempted 不写不完整页面缓存，主页证据仍保存到该任务；其他目录失败即使主页 fetched 也只缓存至多 300 秒，失败过期后重新尝试，不能用 ALLOW_STALE_CACHE 无限延续失败。成功旧页面缓存若明确允许使用，会标明 stale 和原缓存时间。缓存命中不计为新详情/目录 HTTP。

采集请求间隔由服务端 `FETCH_MIN_INTERVAL_MS` 配置，默认 500 毫秒，环境变量读取范围为 100–10000 毫秒。每次初始请求、重试、robots 及重定向请求均经过同主机节流，实际间隔不低于配置值及已知 robots Crawl-delay / Request-rate 换算间隔；超过单次等待预算返回 robots_delay。该配置与搜索 Provider 的请求间隔独立。

429 或携带 Retry-After 的 503 返回 rate_limited，并按秒数或 HTTP 日期暂停同主机；缺失/非法暂停值使用有限默认值，暂停期内不发起新请求。403、页面验证码/明确拒绝访问，或 robots 返回的相应限制，触发当前 Fetcher 实例的同主机隔离；后续资源保留未继续请求的事实。此时 `kind=access_restriction`、`field=fetch_status` 的证据 url 以及 field_provenance.fetch_status.url 指向原始触发请求 URL，而非后续被停止的资源 URL。text JSON 记录 host、trigger_url、status、source、observed_at、scope（fetcher_instance_host）。robots 触发时来源可为 robots.txt；已核对的条款来源使用 site_policy 证据，不混成一次实际页面响应。

`GET /api/capabilities`: `{mode:"live",search:{selected_provider:"searxng",status:"unconfigured"|"configured"|"available"|"fault",message:"...",providers:[{name,status,message}]},llm:{status,message},fetch:{status:"available",message,browser_fallback:false},platforms:[{id,name,discovery:"search",metadata:"public_metadata_when_allowed",playback:"unknown"}],limits:{max_knowledge_points:5,max_results_per_point:5,max_search_requests:30,max_detail_pages:40,global_concurrency:5,per_host_concurrency:1},deployment:{local_only:true,authentication:false}}`。configured 仅代表配置齐全，available 代表最近请求成功，不能互换。

`GET /health`：实际检查 worker 存活与 SQLite 可读性，正常 HTTP 200，退化 HTTP 503。字段包括 `status,mode,single_worker,worker_alive,database_ok,accepting,queue_depth,queue_capacity,oldest_queue_wait_seconds,active_jobs,job_counts,admission_rejections,recent_outcomes,source_cooldown_seconds,source_access_denied,engine_cooldowns`。recent_outcomes 最多 50 条状态/时间，不含学生请求内容；健康正常不等于外部搜索有相关结果。

新任务准入：默认最多等待 20 项、整个实例每分钟最多接收 30 项。满队列或提交过快返回 HTTP 429 `{detail,code}` 与 `Retry-After`；worker 不可用返回 503。相同幂等键或同一进行中任务优先复用，不重复消耗配额。取消等待任务会释放队列名额；出队前若等待超过 300 秒，标记 interrupted / queue_wait_expired，不再发起外部请求。这是单进程本机队列，不支持多个 Uvicorn worker。

链接准入不要求目录或播放核验。通用搜索课程候选须同时有可靠搜索来源、同 URL、明确课程标题、课程根入口格式、教学摘要及原知识点相关性；以 resource_type 的 source=search_title_url 记录，仍为 search 证据级别、video_evidence_status=none。不能据此升级为页面已核验。备用搜索组仅在首组无可展示相关链接时使用；同一 canonical URL 的不同观察保留，但独立 URL 数仍受查询限额约束。

三词以上英文复合知识点要求同一来源观察支持完整目标词面（含有限复数变体）。只在 SQL + ROW_NUMBER、explicit CSS Grid + 轨道定义属性这两项有依据的等价情形补充词面，match.topic_match_rules 记录实际使用的规则；不按 URL 放行。所有既存匹配在读取时通过当前准入规则后，再统一生成默认和平台分栏；原始证据和原匹配记录不被读取动作改写。它不构成完整语义理解或教学覆盖保证。

配置缺失仍允许提交，任务记录会明确 failed/configuration_error；不会生成演示数据。HTTP 422 为输入格式问题，404 为不存在任务。

`capabilities.fetch.stopped_hosts` 为服务端明确停止自动采集的域名列表（例如已观测到 robots 拒绝的来源），不影响搜索入口保留。该列表也进入页面缓存身份，避免旧缓存掩盖新的停采配置。
