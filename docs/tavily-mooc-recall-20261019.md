# MOOC 免费召回与双平台来源拆分验收

日期：2026-10-19。已复用现有 Tavily 适配器完成真实联网召回，B站保留原 SearXNG 搜索；中国大学 MOOC 单独使用 Tavily。当前本地配置采用官方免费免 Key 模式，无需先申请 API Key。

## 实测结果

### 固定 20 个知识点的 MOOC 搜索

测试先执行 2 个知识点，再执行同一固定语料剩余 18 个；没有根据结果替换题目、注入已知课程或读取缓存。每题一次 basic 搜索、最多 5 个候选、间隔至少 2 秒、零重试；没有调用 LLM，也没有在这个搜索实验中抓课程详情。

| 指标 | 实际结果 | 含义 |
| --- | --- | --- |
| 搜索请求成功 | 20 / 20 | 本次 HTTP 请求均成功；不能推断长期可用率 |
| 返回候选 | 89 条 | 跨查询包含重复链接 |
| 含 `/course/` 链接的查询 | 13 / 20（65%） | 仅 URL 形态命中率，不是相关性或教学覆盖率 |
| 去重后的 `/course/` URL | 15 个 | 不等于 15 门已验证适合学习的课程 |
| API 报告的积分计量 | 20 | 请求未携带账户 Key；这是免 Key 模式计量，不是账户扣费证据 |
| 单次请求耗时中位数 | 3.36 秒 | 仅限本轮环境和样本 |
| 限流、验证码、请求失败 | 本轮未出现 | 免费来源仍可能在其他时段限流 |

相关性审查发现：SQL 查询出现高等数学课程，HTML 查询出现结构力学课程，HTTP/REST、ESP32 查询出现“MOOC进校园”。Python 摘要中的列表、字典也可能只是预备知识。另一方面，`/learn/` 下有课程候选，这些不计入上述 `/course/` 指标。因此，本轮证明发现通道已通，尚未证明细粒度知识点推荐准确率达到生产标准。

证据：[汇总](../evidence/tavily-platform-routing-20261019/recall-summary.json)、[前 2 题](../evidence/tavily-platform-routing-20261019/keyless-pilot/summary.json)、[其余 18 题](../evidence/tavily-platform-routing-20261019/keyless-remaining/summary.json)。各目录保留请求前计划、逐题结果和来源追踪。

### 真实 JobService 双平台联调

使用真实 `JobService`、现有本地 SearXNG 和真实页面采集器，查询“Python 列表与字典”“pandas 数据分组与聚合”。使用空白临时 SQLite，未注入候选或缓存，关闭 LLM、站点地图补充、公开目录补充和 JS 渲染，零重试。预算为 8 次搜索、6 个详情页。

| 指标 | B站 | 中国大学 MOOC |
| --- | --- | --- |
| 搜索来源 | 原 SearXNG | Tavily 免费免 Key |
| 实际搜索请求 / 成功数 | 4 / 4 | 4 / 4 |
| 可展示发现候选（按资源去重） | 18 | 11 |
| 已存储候选资源 | 18 | 20 |
| 成功取得页面元信息 | 5 | 1 |
| 提取到的大纲/分P条目 | 220 | 43 |

搜索合计 8 / 8 成功，错误列表为空，缓存命中为 0。任务状态为 `partial`：详情预算 6 已用完，不能把剩余候选当成已核验课程。MOOC 存储候选与展示候选不同，是现有展示条件筛选的结果。

真实取得大纲的 MOOC 为 [Python数据处理](https://www.icourse163.org/course/NJCIT-1469574161)，其公开页面响应中的 `termDto.outLineDto.outLineStructureDtos` 提取出 43 条大纲，包含“项目6 使用pandas进行数据分组与聚合”“任务1 数据分组与聚合运算”“任务2 分组级apply和transform运算”。这证明页面大纲出现相关内容；学生实际播放、课程学习适配性和长期生产稳定性仍为 `unknown`。

证据：[双平台汇总](../evidence/tavily-platform-routing-20261019/split-live/summary.json)、[任务和预算](../evidence/tavily-platform-routing-20261019/split-live/job.json)、[课程与大纲](../evidence/tavily-platform-routing-20261019/split-live/resources.json)、[页面证据](../evidence/tavily-platform-routing-20261019/split-live/evidence.json)。联调记录导出后临时数据库移除，没有向原业务库写入测试任务。

## 实现与兼容性

- `BILIBILI_SEARCH_PROVIDER`、`MOOC_SEARCH_PROVIDER` 分别覆盖平台来源，空值继承原 `SEARCH_PROVIDER`；已有全局配置继续可用。
- 顺序和并行搜索都按平台选择来源。每个来源独立记录错误、冷却状态、请求追踪和缓存标识；MOOC 的拒绝、限流或额度问题不会终止 B站搜索，也不会重试已停止的旧来源。
- Tavily 固定 basic 搜索，关闭自动参数、生成答案和原文提取；API 和本地同时做域名限制。免 Key 需要显式开启，未配置时给出明确错误。
- 账户 Key 与免 Key 请求头互斥。429 遵守冷却提示，权限或额度错误停止该来源，队列中后续请求也会重新检查额度状态。
- 健康及能力接口显示各平台实际来源和认证模式。配置就绪与真实请求成功分别记录。

后端完整回归：**4001 passed，26 subtests passed**；之后新增的联调脚本测试另跑 **3 passed**。覆盖来源隔离、原配置兼容、认证头、免费模式、预算、限流、额度耗尽及测试脚本的无网络默认行为。没有把模拟响应当成联网召回证据。

测试证据：[最终回归](../evidence/tavily-platform-routing-20261019/backend-regression-final.xml)、[联调脚本测试](../evidence/tavily-platform-routing-20261019/split-harness-tests.xml)。目录中的 `backend-regression.xml` 是修复兼容问题前的历史失败记录，最终结果以带 `final` 的文件为准。

## 当前配置与本地入口

本地 `.env` 已设置以下来源拆分，原 B站引擎和其他配置保留：

```dotenv
SEARCH_PROVIDER=searxng
BILIBILI_SEARCH_PROVIDER=searxng
MOOC_SEARCH_PROVIDER=tavily
TAVILY_ALLOW_KEYLESS=true
TAVILY_API_KEY=
```

新版入口：<http://127.0.0.1:8002>。`/health`、`/health/ready`、`/api/capabilities` 和首页均返回 200，能力接口确认 B站为 `searxng`、MOOC 为 `tavily/keyless`。

新版使用现有数据的独立快照 `data/discovery-tavily-preview-20261019.sqlite3`，在新版产生的数据写入该快照库，不会自动合并进原库。原 8001 实例仍运行原先加载的代码；以后正常重启时才会读取新代码和 `.env`。本轮对原数据库与快照的 17 张表逐表比较行数和内容哈希，均与启动前一致。记录见 [运行状态](../evidence/tavily-platform-routing-20261019/runtime-after.json)。

自动审批策略在执行前拒绝了“停止并重启原 8001 进程”，仅返回 `blocked by policy`，所以没有停止原进程，而是另开 8002 进行验证。

## 如需免费账户 API Key

目前不需要 Key。官方提供限量免 Key 搜索，但未承诺固定请求额度或生产 SLA；达到限制时会明确停止该来源，继续保留 B站结果。[官方免 Key 文档](https://docs.tavily.com/documentation/keyless)

如果免 Key 额度不够，可在 [Tavily 控制台](https://app.tavily.com/)注册免费账户、创建 API Key，保留免费计划并不启用按量付费。官方当前列出免费账户每月 1,000 积分、basic 搜索每次 1 积分，不需要信用卡；实际剩余额度以账户显示为准。[官方额度说明](https://docs.tavily.com/documentation/api-credits)

只在本地服务端 `.env` 修改：

```dotenv
TAVILY_API_KEY=在这里填自己的Key
TAVILY_ALLOW_KEYLESS=false
```

正常重启后端后生效。不要把 Key 发到聊天、放进前端或提交 Git。项目不会创建账户、购买额度或自动升级套餐。如果 Key 和免 Key 开关同时存在，将优先使用 Key 的账户额度。

## 复现实验

在仓库根目录运行，输出目录必须是新的。以下命令默认只生成计划，不联网：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/test_tavily_mooc_recall.py --keyless --limit 2 --output reports/runtime/mooc-plan-new
.venv/Scripts/python.exe -X utf8 scripts/verify_split_provider_live.py --output reports/runtime/split-plan-new
```

需要真实执行时增加 `--live` 并换一个新输出目录。MOOC 脚本默认最多 2 题，可显式设置 `--limit 20` 完整运行固定题集；双平台脚本固定 8 次搜索与 6 个详情页预算。两者的免 Key 实验都显式清空账户 Key，不会消耗配置中的账户额度。

目前可用于本地试用。后续生产验收应单独测量主题相关性、目录覆盖、细粒度技能匹配和持续可用性；本次 20 次成功或 65% URL 命中都不能代替这些指标。
