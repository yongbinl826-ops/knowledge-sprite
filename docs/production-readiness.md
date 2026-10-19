# 运行边界与生产就绪证据

本应用的可交付架构是**本机单用户、单 Python 进程、SQLite 持久化**。本次没有部署外网、购买接口、创建凭据或推送 Git。下面的保护改善本地运行安全；它们不提供多用户身份认证。外网产品上线仍需要真实供应商验收、受认证的入口、HTTPS 与持久化运维安排。

**2026-10-19 当前发布状态：本地候选，核心内容效用未通过生产验收。** 新版本把具体教学技能与原项目练习分开，所有支持均绑定本课原文、全文哈希和当前技能；目录线索保持零覆盖。八案例独立复核、四次有限真实回归、最终构建/原工程回归/恢复/浏览器证据统一以 [本轮交付验收](delivery-acceptance.md) 为准。以下 r9/r9c 的计数、PID和恢复耗时均为上一阶段历史，不能用于给新版本验收。

## 当前候选与回滚配对

最终8000是PID5196，使用新文件`data/preview-phase3.sqlite3`。44后端+3dist运行SHA与工作区/stage/D原工程一致；两个pyproject测试目录共3718测试及26子测试通过，104浏览器/109Node及构建通过。最终实际四案例三步三宽无写回，详见[源码绑定](../evidence/phase3-release/final-source-verification-auxiliary.json)、[浏览器绑定](../evidence/browser/phase3-auxiliary-final-runtime/summary.json)。57前端文件与3dist冻结；隔离QA仅Vite缓存目录名不同，最终产物相同。

本轮新库恢复证据是[phase3 verification](../evidence/recovery-phase3-auxiliary-final-128-reads/verification.json)：14项目、64历史版本，两独立进程各128历史API读取200、源历史不变、WAL包含已提交而排除未提交行、78条旧归属迁移、完整性ok、外键错误0、第二次重启幂等；0真实外部调用。先前30秒脚本等待上限失败保留，最后只放宽离线子进程等待到120秒，实际43.153/44.647秒，全部断言和产品源码不变。[预算说明](../evidence/recovery-phase3-auxiliary-final-128-reads/harness-budget.json)。标准恢复脚本默认仍为30秒，大历史集演练需要单独设置测试等待；这不是调整线上API或供应商超时。

回滚配对是`evidence/phase3-release/rollback-r9c/`内上一版源代码/前端构建及保留的旧`data/preview.sqlite3`。先核对当前进程身份和空闲并停止；恢复已核SHA的旧源/构建，再将旧库一致备份成新文件名启动单worker。**不要把旧代码直接指向包含新技能JSON的新库**。保留新库和失败证据；D原学生库、原凭据与Git均不参与此回滚。没有实际执行回滚或外网部署。

`/health/live`、`/health`和`/health/ready`在最终本机均200、待处理数0；ready仍仅配置与最近观察，不探测上游或证明播放。实际外部调用、静态计划认可、模型判断与人工内容效用必须分开：[真实调用账本](../evidence/phase3-audit/r4-final-source-and-call-ledger.md)。新分析quality失败、有限推荐和Scoring逐对失败阶段未知仍是开放阻碍，不能以运行检查通过解除。

## 启动和配置

在项目根目录完成依赖安装与前端构建后启动：

```powershell
uv sync --frozen
Set-Location frontend
npm ci
npm run build
Set-Location ..
uv run --frozen uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

访问 `http://127.0.0.1:8000/`。开发模式可另行使用前端 Vite 预览（5173）；默认来源列表允许 `http://127.0.0.1:5173` 与 `http://localhost:5173`。前端资源未构建时根地址没有页面；这不影响独立 API 健康检查。

服务端配置来自环境变量和项目根目录 `.env`；密钥不得写入前端环境、构建产物、文档或测试报告。项目请求的严格 schema 禁止用户覆盖模型地址、API key、数据库位置与其他运行配置。`SEARXNG_URL` 和 `LLM_BASE_URL` 是操作者信任的地址，可以有意指向本地服务；它们不是可由学生传入的抓取目标。

| 设置 | 默认值 | 行为 |
| --- | --- | --- |
| `LOCAL_ONLY` | `true` | 按实际 ASGI 客户端 IP 限制为 loopback；应用不读取请求中的 `X-Forwarded-For` 来放行 |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | 精确 Host 白名单，防止 DNS rebinding；不支持通配符、端口或 URL |
| `CORS_ORIGINS` | 上述两个 Vite 来源 | 精确 HTTP(S) Origin；拒绝未知 Origin、`null` 和跨站 Fetch Metadata |
| `MAX_REQUEST_BODY_BYTES` | `512000` | 在 JSON 解析前同时限制声明长度和分块实际长度 |
| `REQUEST_BODY_TIMEOUT_SECONDS` | `10` | 接收整个请求体的总时限；返回可重试的 408 |
| `API_WRITE_LIMIT_PER_MINUTE` | `60` | 全进程 API 写入限额；429 带 `Retry-After`，取消和读取始终可用 |
| `MAX_PENDING_ANALYSES` | `8` | 正在执行及等待分析任务总数；分析执行并发仍为 2 |
| `MAX_PENDING_PROJECT_SEARCHES` | `20` | 项目检索调度任务总数；实际检索继续使用 JobService 预算与队列 |
| `PROJECT_ANALYSIS_TIMEOUT_SECONDS` | `90` | 单次模型分析调用总时限；包含接收响应，不只是空闲读取 |
| `PROJECT_ANALYSIS_TOTAL_TIMEOUT_SECONDS` | `120` | 生成、内容复核及可能的一次修正共用的总预算，不能小于单次预算 |
| `PROJECT_SEMANTIC_REVIEW_ENABLED` | `true` | 独立模型调用核对原始需求、行为、数值含等号边界与先修一致性；复核不等于正确性证明。错误/超时保留输入，不伪造通过；无效布尔配置启动失败 |
| `LLM_MAX_OUTPUT_TOKENS` | `6000` | 每次模型请求实际发送 `max_tokens`；上下界 256–16000，错误配置启动失败 |
| `TEACHING_MATCH_MAX_CALLS_PER_JOB` | `2` | 项目明确技能模式只允许0–2次判断，另最多一次正向声明复核；错误配置启动失败。0关闭业务模型判断，历史读取始终零模型调用 |
| `LLM_REASONING_EFFORT` | `auto` | 仅官方 DeepSeek 已知模型且未关闭 thinking 时自动发送 `low`；`provider_default` 不发送，显式 `low/medium/high/max` 需与 thinking 配置相容 |
| `LLM_THINKING_MODE` | `auto` | 仅官方 DeepSeek 已知模型的有限 JSON 调用自动发送 `thinking={"type":"disabled"}`；`provider_default` 不发送，管理员可显式 `enabled/disabled` |

DeepSeek 官方 [Thinking Mode 文档](https://api-docs.deepseek.com/guides/thinking_mode/) 说明默认开启思考且强度为 `high`，支持 `thinking.type=disabled` 关闭，也可用 `reasoning_effort` 调整强度，`medium` 在该服务上映射到 `high`。本产品的模型调用只生成有限 JSON；`LLM_THINKING_MODE=auto` 只在 HTTPS、精确主机 `api.deepseek.com`、标准 443 端口、模型名 `deepseek-flash` 或 `deepseek-v4-pro` 时发送 `thinking={"type":"disabled"}`，同时不发送自动 `reasoning_effort=low`。未知模型、第三方兼容网关、子域名及伪装后缀都不添加这些自动参数。管理员可显式选择 `enabled/disabled` 或 `provider_default`；若要保留全部供应商默认，两个设置都选 `provider_default`。关闭 thinking（含在官方模型上生效的 auto）与显式推理强度互相冲突，配置启动前拒绝；需要显式强度时先选择 thinking 的 `enabled` 或 `provider_default`。6000 token、字节、时间与质量校验边界保持不变。

选择默认关闭而不是只降低强度，来自真实失败记录 [model-events.jsonl](../evidence/browser/real-project-reasoning-final/model-events.jsonl)：小游戏请求 HTTP 200、耗时约 33.444 秒，completion 6000 tokens 中 reasoning 占 4443，最终正文仅 3607 字符，仍为 `finish_reason=length`。这证明该次调用在有限正文生成前耗尽供应商输出额度，不能据此认定项目范围过大。旧失败证据保留；关闭 thinking 后是否满足真实学生流程，由新的 E2E 证据独立判断，不用离线 payload 测试代替。

安全配置错误在启动前报错，错误信息只列配置项，不回显密钥或地址值。CORS 使用精确来源，API 有内容时只接受 `application/json`；这同时阻止恶意网页使用表单向本地写入。允许来源具有读取和修改本机项目的权限，因此只添加自己控制的前端来源。

不要用 `--workers 2` 或多个进程指向同一数据库。任务队列、限流计数、缓存读取协调和任务归属均由单进程维护；SQLite WAL 不会把它们变成分布式队列。生产验收也不要使用 `--reload`。

结果读取的排序缓存也限定在服务实例内：最多1024项、序列化输出总量8MiB，完整输入超过1MiB时跳过缓存。键包括当前单元、确认概念、来源元数据、原始证据、可用性证据和请求设置；任何一项变化都会重新排序。输出深拷贝，异常不缓存，写入侧排序不使用该缓存。一次排序内另缓存最多4096项纯URL规范化/分词结果，调用结束即清除，不缓存DNS解析或网络权限判断。同一项目读取中的终态批次结果只在本次请求内复用，批次状态仍实时读取。这些边界避免旧覆盖结论跨版本复用；离线数据回放的提速不等于实际服务延迟承诺，真实运行另行记录。

若以后提供受认证的反向代理入口，需要显式配置 `LOCAL_ONLY=false`、准确 Host 与 Origin；在外部认证和权限测试完成前不得放开。Uvicorn 可在代理头处理后改变 ASGI 客户端地址，部署者必须限制可信代理范围并在实际代理路径复测，不能依靠客户端自报的头作为身份。

## 已实现的安全与成本边界

锁定依赖也完成了公告查询：`evidence/dependency-advisories.json`记录本次生产Python锁文件的OSV批量查询，0条版本匹配；`evidence/frontend-dependency-advisories.json`记录包含开发依赖的npm锁文件只读`npm audit`查询，完成且0条公告匹配。没有自动升级或运行包安装脚本。此结果对应当次锁文件与公告库时间，不能替代后续发布时的复查。

* HTTP 层在访问、Host、Origin、长度和接收总时限检查通过后才将内容交给 FastAPI。拒绝压缩请求，避免压缩膨胀的不确定边界；拒绝非法或不一致 Content-Length。
* 所有响应含请求编号、禁止 MIME 猜测、禁止 iframe 嵌入、无 Referer、关闭相机/麦克风/定位能力和 CSP。API、健康检查及错误响应均 `Cache-Control: no-store`。CSP 禁止任意脚本和对象；允许 React 必要的内联样式及 HTTPS 图片。
* 参数化 SQLite 查询避免把项目 ID 或需求拼成 SQL。Pydantic 约束需求长度、知识点数量、枚举、额外字段和先修关系；HTTP 校验错误只返回字段位置、错误类型和说明，不回显原始输入。
* 项目同一时间只能有一个分析版本在运行；重复当前请求可复用。新版本不会排队绕过限制。项目分析和调度入口上限不会截断已有需求或静默删掉学习单元。
* JobService 已有限额：默认等待队列 20、实际新任务每分钟 30、排队时限 300 秒、单批总时限 180 秒、搜索预算 30、详情预算 40、最多 5 个并发网络请求、单主机并发 1。项目先核算所有批次的总预算；超预算要求学生缩小或分阶段提交。
* 搜索超时、有限重试、节流、缓存 TTL、上游冷却和部分结果保留沿用现有实现；模型分析有 schema 校验、总时限与有限结构修复，服务异常不能伪造成功结果。测试注入的分析器和搜索器不能用来证明真实外部可用性。
* 模型 HTTP 传输使用 `stream` 和固定 16 KiB 的 `aiter_bytes`，按解压后的字节累计检查上限，超限立即关闭响应；一般调用最多累计 250000 字节，项目分析最多 720000 字节。整个请求和接收受 `asyncio.timeout` 约束，慢速持续发送也不能绕过总时限。借用客户端保留自身 HTTP 超时和跳转配置，自建客户端退出时关闭。运行验收观察器使用独立、有界的元数据副本；完整且有界的错误响应可记录哈希，超限或中断响应标明未完整读取，不保存响应正文。
* Fetcher 在 URL 规范化、DNS 解析和实际连接阶段校验公开地址，控制跳转、端口、响应体、robots 与站点策略；渲染默认关闭，开启时仍受服务器白名单与资源预算约束。统一 URL 规范化现在也拒绝浏览器的缩写/八进制/十六进制 IPv4 形式，防止危险链接成为学生跳转地址。普通公网课程地址和已观察到的章节参数保留。

付费、登录、验证码、地区限制和站点抓取限制不等于无效视频链接；结果应如实展示访问与证据状态。当前产品提供平台跳转，不保证自动验证播放。

模型费用边界按实际调用结构计算：每次项目分析至多2次生成、各自至多1次内容复核，最多4次请求，共用默认120秒。复核输出限 `min(LLM_MAX_OUTPUT_TOKENS,1500)`；读/写/响应超时不自动重试，生成前连接失败只能占用原两个生成机会。项目明确技能检索不做关键词扩展或旧候选重排：每批最多5单元、每单元4个候选、每任务20对，至多2次15秒/3000输出token的技能判断及1次15秒/1500输出token的正向声明复核。每对最多8条自身来源观察、6000字符；输入与引用另有硬上限。来源阶段在原任务总时限中预留 `min((判断次数+1)×15秒, 总时限/4)`，不延长任务。最多24单元、5批的单个项目生命周期，默认保守输出上限为 `2×6000 + 2×1500 + 5×(2×3000+1500) = 52500 token`。

直接知识点搜索的旧模式仍有每单元1次关键词扩展和1次重排（最多15候选、标题/说明各1000字）的独立边界；旧的24单元生命周期保守303000输出token估算只适用于该调用结构，不能套给新技能模式。实际超时、无候选、缓存和结构拒绝通常降低上限。输入token、缓存折扣、币种和价格由供应商决定，这不是金额保证；显式重新分析/检索的新版本重新消耗配额，部署账号需配置费用和速率上限。真实元数据记录具体usage，未捕获的旧用量不补编。

v2.6 在 schema 和图关系校验后增加独立内容复核：以原输入与整份分析作不可信数据，核对需求遗漏、相互矛盾的操作、学生阶段及数值/单位边界；最多八条短问题，只把中/高问题用于一次受限修正。复核不能执行、搜课或输出链接，报告严格校验、拒绝密钥/凭据与矛盾结论；报告不可用时返回专用错误。该机制来自新项目中真实发现的“允许零分钟，却要求正值”缺陷，并非针对某个项目写死输出。它仍可能漏错或误报，代表性真实验收和学生确认仍不可替代。

r8 对检索取证顺序作有限调整：只有已经通过原工具/类型/视频准入的候选，才能按学生确认的具体 API 标识符标题提前取证；查询和摘要不能因此成为教学证据，初始2个加缺口补充2个详情额度不变。Tech With Tim 仅从实际公开分类页进入，最多再读2个已观察到的系列，共3个索引、6个候选、每单元2个独立详情探测；仅首系列的真实课标题完全无匹配信号时考虑第二系列。全部索引仍共享1,550,000字节上限，含robots最多4次目标HTTP，遇robots/登录/验证码/访问限制停止，无绕过。freeCodeCamp仍最多2个索引。准确的站点字面线索只影响召回顺序，不证明教学覆盖。

已声明单一技术的学习单元以该技术作为检索前缀。旧版本若保存了其他工具范围的结果，仅在脱离数据库的读取投影中隐藏课程和覆盖，并显示“检索范围需重试”；原历史数据不写回。组合技术字段保留既有合同，不推测单一归属。来源本人说明音频有问题或将来可能提供完整版时，只有自有页面与URL身份已绑定才显示事实提醒，不把它改成失效链接，也不声称验证过播放。

只读排名缓存的容量变更来自两组真实结果快照的回放：305个工作键在256项时反复淘汰，1024项在相同8MiB边界内得到610次暖命中、0淘汰；18个完整结果JSON SHA保持相同。该离线观察不能代替当前运行态的延迟测量；实际证据另列。缓存仍不参与写入/准入，不改变来源、权限或教学覆盖结论。

## 健康检查、诊断与隐私

* `GET /health/live`：进程能否响应；200 不代表第三方可用。
* `GET /health`：队列 worker、SQLite、队列深度、任务状态和项目待处理数；基础设施异常返回 503。
* `GET /health/ready`：基础设施、检索配置/最近观察和项目分析配置是否齐备，缺失返回 503；`upstream_check=configuration_and_last_observation_only` 明确说明没有进行实时上游探针。200 也不是实时集成或视频播放证明。
* `GET /api/capabilities`：模型、检索、站点政策、数据证据和预算状态；不返回 API key。

`knowledge_sprite.http` 日志只记录随机请求编号、HTTP 方法、路由模板、状态码、耗时和异常类型；不记录需求、标题、原始地址/查询字符串、客户端 IP、请求头或异常原文。响应编号可以与日志对应。用 `--no-access-log` 启动以避免 Uvicorn 默认访问日志记录含用户内容的 URL；反向代理也要采用同样的脱敏规则。不要开启会输出请求体或供应商 Authorization 头的调试日志。

需求、项目历史、分析文本、视频 URL、证据、抓取诊断与缓存会保存在 SQLite。学生输入也会发送给操作者配置的模型/搜索服务。上线前应确认隐私告知、供应商数据条款、备份访问控制、磁盘容量和保留期限。当前历史不会自动删除；应由实际产品的保留政策决定清理方案，不能把隐式删除当作安全修复。

## 数据迁移、备份与回滚

Store 与 ProjectStore 使用增量 `CREATE TABLE IF NOT EXISTS`、索引和兼容迁移；启动会将遗留运行状态恢复为明确的中断/可恢复状态。新 HTTP 保护不改变数据库 schema。数据库路径是服务端配置，默认 `data/discovery.sqlite3`；生产应设置为可持久化且有磁盘监测的位置。

1. 发布前记录当前源码版本、锁文件、前端构建和全部非敏感配置；密钥在受控环境中单独保留。停止接受新任务，等待或取消现有任务。
2. 使用 SQLite backup API 建立一致快照；不要只复制运行中的 `.sqlite3` 而漏掉 WAL。下面脚本的两个路径必须换成实际受控路径：

   ```python
   import sqlite3
   from contextlib import closing
   from pathlib import Path
   source = Path("data/discovery.sqlite3").resolve()
   target = Path("backups/discovery-before-release.sqlite3").resolve()
   target.parent.mkdir(parents=True, exist_ok=True)
   if target.exists():
       raise RuntimeError("Choose a new backup filename")
   with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(target)) as dst:
       src.backup(dst)
       assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
   ```

3. 对快照副本启动候选版本，验证迁移、旧项目读取、旧版本结果、取消与中断恢复，再执行代表性产品验收。
4. 回滚时停止应用，恢复上一版源码与对应前端构建；将备份复制成一个**新的数据库文件名**，用 `DATABASE_PATH` 指向它后启动单 worker。保留失败版本数据库及其 WAL 作为取证，避免新旧文件混用。
5. 复测 `/health`、`/health/ready`、项目读取与一条真实分析/检索链路。新版本发布后新增的数据不在发布前备份中，回滚前必须明确数据损失范围。

### 本轮实际恢复演练

运行 `python scripts/verify_backup_restore.py --source data/preview.sqlite3 --output evidence/recovery-新名称`，输出目录必须是工作区 `evidence/` 或 `tmp/` 下的新目录，脚本拒绝覆盖既有证据。源文件以 `mode=ro` 打开，用一次读事务建立一致快照；不使用会忽略 WAL 的 `immutable=1`，也不复制活动中的数据库或 WAL 文件。

上一阶段完整恢复演练在r9数据库范围完成，证据为 [r9 verification.json](../evidence/recovery-phase2-r9-final/verification.json)：10个本地验收项目、37个版本，两次独立子进程分别74次历史API读取200，原输入/分析/确认历史指纹保持；只读在线备份1.003秒、还原0.995秒。活动WAL已提交行恢复、未提交行排除；44条legacy归属迁移；所有阶段完整性ok、外键错误0、第二次重启幂等。真实外部调用0，首轮恢复调度仅1次离线搜索夹具；离线未配置供应商时ready按预期503。所有迁移/合成写入只在证据副本，未操作8000服务或原学生库。r9c只改变Pygame精确匹配函数与测试，数据库/恢复源码未变；该演练标为r9实际执行，不伪称r9c重新执行。旧r6b、r3范围保留。

第一阶段证据为 [r3 verification.json](../evidence/recovery-20261018-r3-process/verification.json)，下表保留当时范围，备份、还原、迁移与恢复写入均在该证据目录内：

| 演练项目 | 实际观察 |
| --- | --- |
| 工作区 preview 数据的一致备份、还原 | 源读快照与备份全部表 schema/行数/内容哈希相同，还原再次匹配 |
| 活动 WAL 一致性 | 合成 writer 保持连接且存在未提交事务；备份含已提交 WAL 行，排除未提交行 |
| 旧项目与旧版本读取 | 原有 1 个项目、2 个历史版本；两轮各 4 个历史版本/结果 API 返回 200；原始输入、分析与确认快照哈希保持一致 |
| 真正进程重启 | 两个独立 Python 子进程，Windows 隐藏控制台，顺序运行并自然退出；未操作现有预览服务 |
| 中断恢复 | 合成 queued/running 搜索任务变为 interrupted；待分析项目变为 analysis_failed，错误码 interrupted |
| 项目检索恢复与预算 | 合成调度继续执行，单次搜索预算仍生效，诚实返回 partial 与预算告警；第一轮使用 1 次离线搜索夹具，第二轮 0 次 |
| 第二次重启 | 所有表指纹不再改变，重复恢复幂等 |
| 旧 consumer schema 增量迁移 | 仅在合成副本删除旧表来重现迁移前状态，恢复 3 条 legacy 归属；其余旧表不变 |
| 数据完整性 | 所有阶段 `integrity_check=ok`，外键错误 0 |

初次演练记录保留在 `evidence/recovery-20261018-verified/verification.json`：合成场景错误地预期预算只有 1 次时仍返回完整无结果；实际应用按预算返回 partial。更正验收条件后重跑通过，最终报告采用独立进程的 r3 版本。合成恢复场景和真实旧项目读取已分别标注；整个演练真实外部调用为 0，不证明供应商可用性。

## 验证范围和剩余上线条件

上一阶段历史完整后端回归为r9c：工作区与D原工程各3024项测试及26项子测试通过，0失败/错误/跳过，73.75/72.94秒；144个Python文件起止及两目录逐文件SHA一致，树SHA为`da47762bb51042092297d4a5b685b765f720a41c15bcf9b73046e32d225d18de`。见 [工作区r9c](../evidence/phase2/backend-final-r9c.xml)、[原工程r9c](../evidence/phase2/d-original-r9c.xml)、[冻结汇总](../evidence/phase2/final-r9c-dual-regression.json)。原配置、数据和Git HEAD/index哈希不变。仅1条既有Starlette/httpx弃用提醒。旧r6/r7/r8、首轮r9合成媒体身份夹具合同失败、r9c定向开发失败和环境收集错误保留；以下历史定向报告不与最终计数相加，也不代表真实推荐质量。

上一阶段前端88浏览器用例、58 Node测试及TypeScript/Vite构建通过，3个明确opt-in live用例单独跳过；49文件冻结，服务JS为`index-BQdT_Xnf.js`。真实五例及历史scope均经实际Edge三宽只读观察，最终r9c定点闭环见[前端验收](frontend-qa-phase2.md)。上一阶段服务PID34988（该实例已由最终集成替换，见主验收），三项健康检查200，ready仍只表示配置与最近观察。r9c五例冷读最大2.538秒，九次顺序暖读最大0.114075秒，全部200；这是单机观察，未做并发负载SLA，证据在`evidence/phase2/performance-final-r9c-data-maze.json`。

教学与媒体身份分别判断：搜索模板无法证明已抓网页含本课视频，缺少own/native身份时转review并清空覆盖；保留原raw字段与证据，不能倒推视频不存在或付费/登录链接无效。同页原拼写API使用核心可作partial，但不证明别名、参数、数值或项目行为，也不进入原目标分母；全源否定约束同样适用。精确`pygame.font`需自己的模块文字或已绑定代码流，泛“显示文字”不足。API标题级有限线索与前端正文/目录学习清单是两层合同；CSV标题线索不计UI原目标完成数。

上一阶段只重读同一r8已完成五例：28张partial、2张review；API13/31单元有有限线索，UI12/31有正文/目录部分依据，两者完整单元均0。真实供应商已调用，不能用没有密钥解释剩余19个UI内容缺口。原任务分母、参数未知及旧失败保持，当前不通过推荐生产内容门槛；详见[主验收与精确缺口](delivery-acceptance.md)。

`tests/test_production_security.py` 为纯离线边界测试：本机/远程/Host/Origin、响应头、声明及流式 body 上限、接收总时限、JSON 类型、全局写入限流、取消通道、分析等待与版本上限、项目调度限额、错误/日志脱敏、健康状态、配置失败和浏览器数字 IPv4。测试数据库和报告放工作区 `tmp/`，不写原项目数据库。

2026-10-18 历史定向回归：`test_production_security.py`（38 例）、`test_core.py`、`test_job_lifecycle.py`、`test_link_trial.py`、`test_mooc_public_live_harness.py` 与 `test_render_configuration.py` 合计 **173 passed，7.15 秒**；JUnit 证据：`tmp/backend-security-results.xml`。唯一 warning 为既有 Starlette TestClient 对 httpx 的弃用提示。Windows 沙箱会阻塞 asyncio 创建本机 socketpair，最终测试经自动审查允许该本机能力后完成，未调用外网服务。

后续新增的流式读取、解压后超限、慢响应、响应/客户端关闭、观察器完整性、模型参数与共享分析预算回归：`test_production_security.py`、`test_project_model_observer.py`、`test_project_analysis.py` 共 **140 passed，3.58 秒**，证据 [backend-security-streaming.xml](../evidence/backend-security-streaming.xml)。这是修复后的定向结果；全后端回归由集成负责人单独记录，不能把上轮历史 XML 或旧计数当作最终验收。

随后针对真实小项目曾被供应商思考预算截断的问题新增 `LLM_REASONING_EFFORT`：上述三个测试文件合计 **166 passed，3.08 秒**，证据 [backend-reasoning-auto.xml](../evidence/backend-reasoning-auto.xml)。新增 26 例覆盖实际请求载荷、已知/未知模型、精确官方主机、伪装域名、端口、显式覆盖与环境校验。此处仍是离线回归，真实 `finish_reason`、usage 和学生项目结果需查最终 E2E 证据。

模型错误语义最终回归包含上述三个文件及 `test_learning_units.py`，共 **214 passed，3.74 秒**，证据 [backend-output-errors.xml](../evidence/backend-output-errors.xml)。`finish_reason=length` 使用专用异常并映射 `output_truncated`，提示稍后重试或检查服务端生成额度；字节/字符安全上限映射 `response_too_large`，提示联系管理员检查配置。二者均保留原始需求，不把服务端限制归咎于学生项目范围。只有模型明确返回 `status=too_large` 或功能/学习单元数量超过 12/24 才保留项目范围 `too_large`。新增的公开 API 回归验证简单小游戏在两种供应商限制下原始输入不丢失、不保存不完整分析且不重复调用模型。

真实 `low` 复验仍截断后，新增默认关闭 thinking 与互斥配置回归，上述四个文件共 **251 passed，3.91 秒**，证据 [backend-thinking-auto.xml](../evidence/backend-thinking-auto.xml)。新增 37 例包含环境/非法配置、8 种关闭 thinking 与显式推理强度冲突，以及 21 种实际请求载荷组合；验证域名伪装不触发自动参数、管理员可选择供应商默认或显式开关、关闭时不发送自动推理强度，6000 token 上限保持。真实效果仍需最终 E2E 复验。

本文件的测试通过只证明这些边界，不证明模型输出质量、真实视频推荐相关性或真实第三方可用性。对应产品验收应在主验收矩阵中独立列明真实调用、mock、离线夹具和未通过样例，不能沿用旧版本测试计数。

外网上线前置：真实配置和网络路径上的两个核心功能验收；实际代理认证与权限验证；HTTPS、备份恢复演练和磁盘/保留政策；明确外部模型费用/配额；依赖与镜像在目标环境安装；真实浏览器的成功、加载、空结果、错误与移动端回归。当前没有授权进行外网发布。
