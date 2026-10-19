# 项目需求分析与知识点确认 v1

项目与检索任务分别持久化。原来的四个 `/api/search-jobs` 接口、抓取器、来源访问边界和结果证据契约不变。新增入口只负责项目分析、学生确认、预算检查、批次编排和版本映射。

## 配置和启动

沿用 `scripts/start.ps1` 或 `uv run --frozen uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1`。在前端选择“从项目开始”。不要开多个 Uvicorn worker。

分析使用服务端 `LLM_PROVIDER=openai_compatible`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`；前端不接收密钥。没有完整配置时，项目输入仍保存，分析明确失败，直接知识点搜索继续可用。独立提示词版本为 `project-analysis-v1`，分析不会调用工具，也不生成课程 URL、章节或课程证据。课程关键词扩展和重排保持原来的提示词语义，只共享 JSON HTTP 传输。

DeepSeek 可直接使用现有 OpenAI-compatible 接口。本机于 2026-10-17 通过官方 `/models` 认证检查后选择 `deepseek-flash`，配置如下（密钥仅写入被 Git 忽略的 `.env`，示例不含密钥）：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
LLM_API_KEY=<仅在本机服务端填写>
```

模型名以自己账号实际可用列表为准。[官方 JSON 输出说明](https://api-docs.deepseek.com/guides/json_mode/)支持当前的 `response_format=json_object` 调用。服务只在启动时读取配置；已启动的旧进程不会热更新。共享传输拒绝明确截断和非正常结束的响应，并拦截配置密钥回显；后者不会进入扩词搜索。没有扩大课程来源范围或改变已有搜索预算。

分析输入：名称 1–160 字符，功能需求 1–8000 字符，保留原始空格与换行。输出上限为 12 个功能和 24 个知识点；超限须缩小范围或分阶段分析。一次初始模型调用，结构错误最多修正一次；单次模型请求超时 60 秒。模糊需求返回 `needs_clarification`，不能以固定样例回退。

| 服务端环境变量 | 默认值 | 含义 |
| --- | ---: | --- |
| `PROJECT_MAX_BATCHES` | 6 | 每个确认版本最多批次数 |
| `PROJECT_MAX_SEARCH_REQUESTS` | 180 | 项目搜索请求总预留上限 |
| `PROJECT_MAX_DETAIL_PAGES` | 240 | 项目详情页总预留上限 |
| `PROJECT_DEADLINE_SECONDS` | 1800 | 项目调度期限，同时约束预留任务执行秒数总和 |

实际能力通过 `/api/capabilities` 的 `project_analysis`、`project_search` 和原 `limits` 公布。单批容量为 `min(5, MAX_KNOWLEDGE_POINTS)`。确认时按每批完整的单任务预算预留，不依赖“某批可能少用”来接纳更多知识点；预算不足时整个计划拒绝，没有批次悄悄执行或知识点静默丢弃。任务仍经过原全局队列、限流与来源暂停。

## 接口

`ProjectInput`：`name`、`requirements`，以及沿用旧检索支持的 `student_level`、`language`、`project_context`、`technical_version`、`preferred_platforms`。

项目输入界面按用户最新要求仅提供“学习语言”和平台偏好，不再展示学生基础、技术版本、补充项目背景三个控件。底层字段继续兼容已有数据与默认值；直接知识点搜索表单保持原样。

`AnalysisDocument`：`scope`、可修改的 `technical_plan`、`assumptions`、`functions`、`knowledge_points`。功能含 `id/name/original_requirement/acceptance_criteria/no_new_learning_reason`。知识点含 `id/name/description/function_ids/why_needed/learning_goal/necessity/prerequisite_ids/learning_order/selection`。`necessity` 为 `required/extension`；`selection` 为 `learn/mastered/skip`。

| 方法与路径 | 请求 | 结果/用途 |
| --- | --- | --- |
| `POST /api/projects` | `ProjectInput` | 创建并保存原始输入 |
| `GET /api/projects` | 无 | `{projects:[…]}`，最近项目列表 |
| `GET /api/projects/{id}?version=N` | 可省略版本 | 项目及指定版本，默认当前版本 |
| `POST /api/projects/{id}/analyze` | `{expected_version, input?}` | 创建新分析版本，后台执行模型分析 |
| `POST /api/projects/{id}/edit` | `{expected_version, analysis, input?}` | 保存学生修改为新版本，清除新版本确认与资源映射 |
| `POST /api/projects/{id}/confirm` | `{version, acknowledged_skipped_prerequisites:[]}` | 校验关系、选择和预算，保存确认快照 |
| `POST /api/projects/{id}/search` | `{version}` | 服务端检查确认后调度；重复调用复用本版本计划 |
| `POST /api/projects/{id}/cancel` | `{version}` | 停止后续批次，取消独占任务，共享任务保留 |
| `GET /api/projects/{id}/results?version=N` | 可省略版本 | 项目视图加每个项目知识点的原检索结果组 |

变更接口和项目读取返回 `ProjectView`，主要字段为 `project_id`、`original_input`、`input`、`current_version`、`versions`、`version`。版本保存 `input/analysis/model/prompt_version/origin/status/confirmation/batches/budgets/error/warnings`。分析响应为 `analyzing` 时轮询项目接口；HTTP 已接受不代表分析通过。

结果的 `points[]` 含 `project_knowledge_point_id/selection/status/batch_id/job_id/knowledge_point_id/result`。`result` 直接来自原 `JobService.results` 的单知识点组，课程封面、原链接、章节和证据由原组件显示。前端不能用标题匹配把其他版本结果放进当前项目。

## 确认、依赖与版本

同一知识点跨功能使用同一 ID 与选择状态。只有 `learn` 进入检索；`mastered/skip` 保存但不检索。待学点依赖 `skip` 前置时，服务端拒绝确认，直到学生调整选择或在 `acknowledged_skipped_prerequisites` 中明确确认影响。没有任何待学点时允许保存确认，不创建空任务。

当前界面按用户最新要求简化为“想学习”复选框：勾选映射 `learn`，取消勾选映射 `skip`；不再提供“已经掌握”“暂时跳过”两个选项。按钮只为勾选的知识点查找推荐视频，全部未勾选时只保存选择。旧 `mastered` 数据继续兼容，已确认版本不被自动修改；必要的未勾选前置提醒仍保留，并允许明确接受影响。接口三态仅用于兼容存储，不要求学生理解这些内部状态。

ID 在同一版本内稳定。重新分析、保存知识点或技术方案修改都会产生新版本；重新分析不凭相同名称继承掌握状态。确认快照不可被后续编辑覆盖，旧版本检索可继续并保留其版本标记。`expected_version` 防止另一标签页或迟到请求覆盖较新的内容。

刷新页面从项目 ID/版本恢复。已经启动的同一确认版本不重复创建任务；已有失败、无结果或中断均保留，不隐式重新联网。取消会先持久化停止调度，再释放本项目批次对任务的使用关系；只有能够证明没有其他使用者的任务才调用原取消逻辑。其他项目、手动入口或迁移前未知使用者仍关联的任务继续运行，已有结果保留。`job_consumers` 在任务新建、复用及取消时更新，不仅靠前端判断共享。

检索背景传入原接口的 1000 字符字段，优先包含项目名、确认后的技术方案与补充背景；超长时明确记录摘要截取说明，完整原文保留在项目版本内。任务实际请求数与详情页数分别聚合展示，详情页包括公开目录跟随页。调度前检查剩余期限是否容得下完整单任务期限；如果期间排队造成延期，已提交共享任务继续受自己的任务期限约束，不为项目取消其他使用者。

## 数据库兼容

在原 SQLite 连接上添加 `projects`、`project_versions`、`project_functions`、`project_knowledge_points`、`project_prerequisites`、`project_batches`、`project_point_job_mappings` 和 `job_consumers`。初始化使用 `CREATE TABLE IF NOT EXISTS`，不删除或重建原 `jobs/knowledge_points/resources/matches/evidence/cache` 表。项目知识点以 `(project_id,version,id)` 标识，与检索任务知识点分开保存。迁移前已有任务登记 `legacy` 使用关系，防止错误推断它们归新增项目独占。

分析结构校验检查严格字段类型、长度和数量，唯一 ID/名称、引用存在、自引用、循环、功能覆盖及前置用途。结构通过只表明数据可处理，教学相关性、遗漏和过度设计仍需人工核对。
