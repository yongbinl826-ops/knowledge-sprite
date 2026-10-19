# MOOC 相关性与课程大纲校验

日期：2026-10-19。已为当前简洁发现模式新增免费、确定性的 MOOC 筛选，沿用现有 Tavily 搜索和公开课程页解析。没有增加 LLM 请求、付费服务或课程 URL 种子；B站来源与发现卡片保留。

## 推荐行为

1. 同一知识点、同一课程 URL 的真实搜索标题与摘要决定是否值得读取详情。查询词自身不是证据；宣传课程、明确先修/否定说明及缺少所需技术名的结果不作为正证据。
2. 只按既有采集范围读取公开课程页，不改写 `/learn`、旧 `detail.htm`、带 `outVendor` 的链接来绕过来源限制。
3. 逐条核对本课大纲的来源 URL、章节索引、JSON 原文、来源标识和原始哈希。已过期、截断、损坏或来自另一课程的目录不能通过。技术名可由有证据的本课标题提供，其他章节不能为当前章节补造技术上下文。
4. “Python 列表与字典”等复合知识点必须逐项有目录依据。完整覆盖才进入主推荐；部分覆盖、已读未见、尚未取得目录和入口不支持的结果保留诊断。
5. MOOC 与原详情队列在总预算内轮转，原 B站内部顺序保持。没有相关 MOOC 时，不占其详情名额；来源拒绝或限流不影响另一个搜索来源。

这些判断表示“课程大纲声明包含所选主题”，不是完整教学质量、学生适配或可播放证明。有限术语规则可能漏掉同义表述，缺少证据不等于课程不教授该内容。

## 本轮真实联调

固定四个知识点，未按结果换题。使用真实 `JobService`、原 SearXNG B站入口、Tavily 免费免 Key、真实采集器及全新临时 SQLite。上限 16 次搜索、12 个详情页，搜索和抓取间隔至少 2 秒，零重试、零缓存命中、零 LLM 调用；未向原业务数据库写入测试任务。

| 所选知识点 | 旧展示规则可显示的 MOOC | 新规则大纲确认 MOOC | B站展示结果 |
| --- | ---: | ---: | ---: |
| Python 列表与字典 | 5 | 0 | 9 |
| pandas 数据分组与聚合 | 5 | 1 | 8 |
| SQL 多表连接与分组查询 | 2 | 0 | 7 |
| HTML 表单与网页结构 | 2 | 0 | 8 |
| 合计 | 14 | 1 | 32 |

比较对象是**同一批实际观测**：旧规则只检查课程类型与来源绑定，新规则再要求大纲覆盖。计数单位为知识点/资源对。本轮 32 个 B站展示资源无跨组重复。该表不是独立人工标注的准确率或召回率评估。

通过的课程为 [Python数据处理（南京信息职业技术学院）](https://www.icourse163.org/course/NJCIT-1469574161)。本次成功获取 43 条大纲，其中索引 27 的原文“项目6 使用pandas进行数据分组与聚合”同时支持“数据分组”和“聚合”，有原始证据 ID 和 SHA-256；标题、搜索摘要没有代替此大纲。

30 个 MOOC 原始候选中，1 个目录确认、27 个入口不在现有公开采集范围、2 个缺少所选技术名的搜索依据。**不能把所有未展示课程都叫作不相关**：例如 SQL Server 的追踪链接和部分 `/learn` 课程可能相关，但本轮无法用其自身大纲确认。

实际请求为 B站 8 次全部成功，Tavily 6 次中前 5 次成功、第 6 次 HTTP 429。错误响应要求暂停 600 秒，后续两次 MOOC 查询在本地被拦截，没有再次发 HTTP；未切换身份、来源或付费 Key 重试。任务因此及详情预算耗尽标记为 `partial`。B站仍正常完成 8 次搜索，取得 9 个页面的元信息和分P目录。

证据：[请求前计划](../evidence/mooc-relevance-20261019/live/plan.json)、[总体结果](../evidence/mooc-relevance-20261019/live/summary.json)、[逐课程筛选及目录依据](../evidence/mooc-relevance-20261019/live/quality.json)、[请求状态](../evidence/mooc-relevance-20261019/live/search_attempts.json)、[页面证据](../evidence/mooc-relevance-20261019/live/evidence.json)。本次没有继续请求受限来源。

## 明显无关结果的回归检查

另对上一轮固定 20 题的 89 条真实搜索响应做离线重放，**未联网**。SQL 对应“高等数学”、HTML 对应“结构力学”、HTTP/REST 与 ESP32 对应“MOOC进校园”均不再通过探测/展示门槛。原因分别包括缺少所需技术名、宣传课程，以及入口不支持，逐条保存；没有把重放说成新搜索。[历史响应复核](../evidence/mooc-relevance-20261019/retained-search-audit.json)

离线目录测试另外验证：同一课程中分别出现“列表”“字典”可共同支持课程范围；只有其中一项时必须为部分覆盖；先修、否定、错误技术归属、跨课程证据或改写章节均不能变成已确认。B站卡片与旧发现函数逐项相同；读取不修改原始证据或数据库。

## 接口与实现

- `backend/app/mooc_relevance.py`：纯规则评估，无网络或模型调用。
- `backend/app/service.py`：在 `TEACHING_MATCH_ENABLED=false` 的当前简洁模式接入 MOOC 门槛和详情轮转；保留旧教学评审模式的既有行为。
- `GET /api/search-jobs/{id}/results`：展示项附 `mooc_relevance`；每组的 `mooc_relevance.candidates` 保留资源 ID、状态、原因、子项和目录证据。原始候选仍在数据库中。
- `/api/capabilities.mooc_relevance`：显示规则版本、启用状态、`outline_required` 门槛和零模型调用。

主要状态：`outline_supported`（全部目录支持）、`outline_partial`（部分支持）、`outline_no_match`（本次所读完整大纲未见）、`outline_unavailable`（无法核验）、`search_candidate`（待取目录）、`rejected`（未通过入口/探测门槛）。后五种不进入 MOOC 主推荐。

测试与运行的最终记录见 [最终审计](../evidence/mooc-relevance-20261019/final-audit.json)。`backend-regression.xml` 保留首次回归发现旧展示契约及测试替身兼容问题的记录，最终结果以 [backend-regression-final.xml](../evidence/mooc-relevance-20261019/backend-regression-final.xml) 为准。真实测试后仅调整非 MOOC 分支访问设置的求值顺序，以及已演示误判的否定/术语边界；全部真实证据已在最终规则下离线复核，逐项评估结果与实测时完全一致，限流后未重新联网。[最终规则复核](../evidence/mooc-relevance-20261019/post-live-rule-recheck.json)

## 本地运行

最终全量回归：**4101 passed，26 subtests passed**，无失败。保留了依赖已有的 Starlette/httpx 弃用提示，未为本次筛选改动依赖版本。

刷新 <http://127.0.0.1:8002> 即可使用新规则。已正常停止本任务上轮启动的 8002 预览进程，并在同一个 `data/discovery-tavily-preview-20261019.sqlite3` 数据库上启动新版；没有再创建另一份预览数据。原 8001 实例保留。

新版健康、就绪、能力接口及首页均为 HTTP 200，MOOC 门槛已启用。原库与预览库各 17 张表的行数和内容哈希均未改变。新版启动时恢复了实测中尚未到期的 Tavily 暂停时间（约 94 秒），没有通过重启清掉冷却，也没有在启动时搜索。[运行状态](../evidence/mooc-relevance-20261019/runtime-after-update.json)

## 免费配置与复现

现有 `.env` 继续保留 B站 `searxng`、MOOC `tavily`、`TAVILY_ALLOW_KEYLESS=true` 和空 Tavily Key。免 Key 已真实遇到限流，不能作为生产 SLA。

如需明确的免费月度额度，可在 [Tavily 控制台](https://app.tavily.com/)申请免费账户 Key，保持免费计划、不启用按量付费。官方当前列出每月 1,000 积分，basic 每次 1 积分。[免费额度说明](https://docs.tavily.com/documentation/api-credits)

在本地 `.env` 填入 `TAVILY_API_KEY`，设置 `TAVILY_ALLOW_KEYLESS=false`，正常重启后端生效。不要把 Key 发到聊天或放进前端/Git。本轮未创建账户或消费账户额度。[原配置说明](tavily-mooc-recall-20261019.md)

离线生成固定测试计划：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/verify_mooc_relevance_live.py --output reports/runtime/mooc-quality-plan-new
```

需要另一次真实测试时增加 `--live`、使用新的输出目录，并遵守来源当前暂停时间。脚本明确清空账户 Key、关闭 LLM，不能被本地已有付费凭据意外切换。本次测试完成后没有安排自动复测。
