# 后端任务生命周期与缓存修复记录

时间：2026-10-13 21:36（Asia/Shanghai）。本轮源码已冻结，验证范围为离线单元、接口及现有核心/身份集成回归；未访问外部课程站点，未重启运行服务，未运行全量前端 E2E。真实联网结果由主任务另行留存，不能由本报告替代。

## 实际缺口与修复

原实现每次提交均创建任务，没有取消接口；worker 直接执行任务，取消该执行路径会同时取消队列。任务进入执行保护之前的异常也可能使队列退出。现改为独立任务执行：排队任务可直接取消，运行中任务取消搜索、详情及目录子任务并等待清理，确认 `cancelled` 后返回；保留此前提交到 SQLite 的资源、匹配和来源证据。worker 区分用户取消与服务停止，继续处理后续队列。前置任务异常由 worker 捕获，以安全错误信息结束该任务，不输出异常中的地址或凭据。任务和知识点的初始写入使用同一 SQLite 事务。

相同规范请求的 queued/running 任务只入队一次，返回原任务及 `reused:true`。知识点/项目背景/版本空白规范化，重复平台去重，有效知识点与平台顺序仍保留。无幂等键时终态重提会创建新任务。

新增可选 `Idempotency-Key` 请求头及 SQLite 关联表。同键同请求跨终态、跨服务重启仍找回原任务；同键不同规范请求返回 409。这样即使首次 POST 响应丢失、服务器任务已完成，客户端重试仍不会重复搜索。键长度及字符有界，CORS 已允许此头。前端约定：一次明确的新检索生成新键，状态未确认的重试使用原键。

规则排序和每项资源已逐步持久化，因此详情或模型重排超时后保留规则结果；无需期限外继续运行模型。此次新增交换两知识点顺序的服务层测试，规则相关性与 LLM 的搜索标题/摘要均按知识点隔离，共享资源的类型资格仍使用全来源凭据；不会因首个知识点的标题决定另一个知识点的匹配。取消/期限中断时，进行中的搜索尝试另存 `cancelled` 或 `interrupted`，已有 Provider 请求轨迹保留。

## 接口

- `POST /api/search-jobs`：HTTP 202 `{job_id,status,reused}`。新建为 queued；复用为原任务当前状态。
- `POST /api/search-jobs/{id}/cancel`：无正文，HTTP 200 `{job_id,status,cancelled}`；queued/running 最终为 cancelled/true。重复取消已取消任务仍为 true；其他终态保持原状态并返回 false。不存在返回 404。
- `GET /api/search-jobs/{id}` / `/results`：既有结构保留，增加 cancelled 终态；已保存结果仍可读取。
- `Idempotency-Key`：首字符字母数字，其余为字母数字及 `._:-`，总长度 1–128；无效头返回 422，同键不同请求返回 409。
- `/results.identity_summary`：只统计默认和平台筛选实际返回资源的来源身份，按 resource_id 去重；不把首页、目录、讲次记录数声称为全球独立课程数。已识别课程家族优先分散展示，但数据库中原资源、URL、讲次和证据不删除。

## 缓存与配置隔离

两个已确认的缓存问题均已修复：

1. 主页 fetched 但目录失败，原来会进入长达一天的成功页面缓存。现在目录 `budget_limited/not_attempted` 不缓存该不完整包，主页事实仍保存到任务；其他目录失败最多缓存 300 秒。过期失败即使启用 stale，也必须再次尝试，避免预算或网络恢复后仍被旧失败遮住。
2. Fetcher 返回包包含搜索回退标题、摘要及搜索证据。现在页面缓存剥离这些查询特有内容，当前任务使用本次发现作为回退；页面实际提取的标题/描述及独立 page/catalog 依据仍保留。缓存重放重新映射证据 ID。`extractor_version=7`、`payload_version=2` 令旧包自然失效，不删除任何历史记录。

搜索缓存继续区分 Provider、实例身份、引擎组、查询、语言、版本、域和结果上限。页面缓存增加明确停采域 `denied_fetch_hosts`，并保留 DNS、安全许可、采集启用等隔离条件。FetcherConfig 收到 `denied_hosts`；`capabilities.fetch.stopped_hosts` 公开本地停采域。配置的 `open_course_domains` 传入现有公平查询生成器，仍受请求预算限制。

## 可审计采集诊断

每个实际执行任务结束、取消或异常清理时保存 `fetch_diagnostics`：

- `available` 区分真实 Fetcher 追踪能力与无追踪的隔离测试适配器。
- `started_at/finished_at` 是任务追踪边界的 UTC ISO 时间。
- `counts_delta` 是该任务前后计数差；`http_started` 为真实发起目标 HTTP 的次数，详情资源数不能代替它。
- `events` 直接保留本任务最新最多 512 条 Fetcher 脱敏事件，包括原事件 UTC `at`、host、去查询/锚点的 URL 及完整 URL 哈希。`http_completed.status_code` 是实际响应码；网络失败记录实际异常类型，不猜 HTTP 状态。
- `truncated` 明示事件窗口截断；计数差仍保留。
- `scope='target HTML+robots only; DoH HTTP uncounted'` 明确不包含解析基础设施的 DoH HTTP。

Fetcher 的事件本身已过滤查询值与异常消息；service 不恢复敏感原始内容。每任务只取开始后的事件，且队列串行，缓存命中不会复制前一任务轨迹。排队未执行即取消的任务可能没有此字段。

## 验证记录

所有测试使用隔离 SQLite 和明确标注的合成适配器。HTTP 取消回归使用 httpx MockTransport 中真实等待的异步请求路径，未访问外部网络。新增 `tests/test_job_lifecycle.py` 共 17 项用例，覆盖：排队/运行取消、两个详情子任务和 HTTP 清理、后续 worker 存活、重复取消、不同终态、规范请求复用、持久幂等/409、服务停止恢复、global_concurrency=1、LLM 期限取消、失败缓存恢复、跨查询搜索回退隔离、缓存来源/策略隔离、课程身份摘要/分散展示、配置课程域、跨任务诊断截断及知识点顺序隔离。

| 留存报告 | 结果与时间边界 |
|---|---|
| `backend-lifecycle-initial.xml` | 65 passed / 9 failed；保留集成初探失败。8 项来自正在对齐的 point-scope 资格/旧来源边界，1 项是旧用例仍期望预算不足目录被缓存。 |
| `backend-lifecycle-revision.xml` | 97 passed；资格与相关性分离、旧缓存期望对齐后的相关回归。 |
| `backend-lifecycle-final.xml` | 98 passed；增加服务层规则与 LLM 交换顺序闭环测试。 |
| `backend-lifecycle-frozen.xml` | **102 passed，0 failed / 0 errors / 0 skipped**；身份/课程准入模块最终冻结后运行，2026-10-13 21:36，pytest 输出 3.77 秒。 |

最终命令：

```powershell
uv run --frozen pytest tests/test_job_lifecycle.py tests/test_core.py tests/test_course_identity.py -q --junitxml=reports/completion-20261013/backend-lifecycle-frozen.xml
```

唯一警告为现有 Starlette TestClient 的 httpx 弃用提示，未为此更换依赖。未覆盖旧失败 XML 或此前 213 + 26 subtests / 16 E2E 验收报告。主任务另行执行的全量后端结果不重复计入本轮相关回归数量。

## 冻结文件与哈希

拥有文件：`backend/app/service.py`、`backend/app/db.py`、`backend/app/main.py`、新增 `tests/test_job_lifecycle.py`。随后经主任务明确授权，只更新 `tests/test_core.py` 中预算不足目录第二次不命中缓存的期望。文档更新为 `README.md` 与 `docs/api-contract.md` 的取消、幂等、缓存和诊断字段说明。未修改本轮其他代理拥有的 models/config/ranking/identity/提取器或前端文件。

| 文件 | SHA-256 |
|---|---|
| `backend/app/service.py` | `ac3298b92dc43f9d2732da53fcf7a6a0098eb8e9dee9aea8321bed24d5649804` |
| `backend/app/db.py` | `08609e3ddcc6f52c78a570c28808ca325ee0d4dfa1badf2041321b9c29ab5e0e` |
| `backend/app/main.py` | `de20321660752cdf6a30a2e248591d6da0963cac1e96b79eb7b5659d12431fe5` |
| `tests/test_job_lifecycle.py` | `ad981f3f80c65472f164e197be438d44d0cc299022380daeed36897c8c00a175` |
| `tests/test_core.py` | `3901a6565582f358f9e880d683658f4589a40f574d941e0f88bbe3a55ab4c10b` |

当前持久化幂等与队列仍是本机单进程设计；没有引入跨进程调度、鉴权或分布式任务承诺。
