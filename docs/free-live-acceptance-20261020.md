# 免费实网补验与最小验收预算（2026-10-20）

本轮已执行并返回结果，仍未完成视频闭环：既有两项目材料保持 **19/20 知识点有相关视频材料**，缺少 Streamlit CSV 下载视频。这个数字是旧材料核验结果，不能当作本轮自动发现或全新项目实网通过。

## 实际执行结果

| 项目 | 本轮结果 | 验收范围 |
| --- | --- | --- |
| Streamlit CSV 下载视频 | 未补齐 | 共 8 条有界公开内容搜索查询；产品原生 freeCodeCamp 目录实际联网。Streamlit 标签页 HTTP 200，得到 1 篇多用户 AI 应用文章候选，未得到合格的 CSV 下载视频；后续目录/正文读取超时后停止该源。 |
| 第一次隔离 API 冷启动 | 失败，发网前结束 | 故意未配置主搜索源，原生目录兜底未到达。生产 ASGI API 返回了真实失败结果，不能计作成功。 |
| 新知识点免费目录检索 | 部分完成 | 全新临时空库、手工新输入 `pygame sprite animation`，通过真实生产 ASGI 路由及已有 `TechWithTimCatalogProvider` 检索，无候选或查询缓存种子。真实目录观察到 6 个候选，返回 0 个可展示视频推荐。 |
| 视频详情补全 | 未发送 | 目录出现一次正文超时，随后本轮预设累计 32 次传输预算（含 DNS）在第一个详情 GET 发出前触发；未重发该请求。 |
| 默认不限域+B站/MOOC并行实网 | 未运行 | 现有默认 MOOC 使用 Tavily 账户密钥，当前禁止付费请求；此前匿名搜索失败来源保持停止。免费目录隔离配置 `parallel=False`，不能替代默认路径验收。 |
| 新实网材料进入共享库后按缺口复用 | 未运行 | 新候选尚无已核验视频详情；且 TWT/FCC 属于 `platform=other`，当前公共事实快照只接纳 B站或 MOOC 的合格来源事实。未将私人项目或查询写入公共库。 |
| 新项目 AI 分析到视频全流程 | 未运行 | 没有新模型授权；本轮新知识点由手工给入，不是新 AI 分析结果。 |

未用普通 `st.download_button` 文档、Pandas CSV 单课、已知坏音频视频或不相关 AI 文章填满最后一个知识点；未把目录链接当作已核验视频或播放成功。

本轮原生公开目录共实际发出 **32 次传输**，含 DNS 和目标元数据 GET。未发 Tavily、Serper、模型或现有生产任务 POST；生产数据库未写入，现有服务未重启。外部站点限制、验证码和已停止来源未绕过。

### 需要保留的原始记录说明

- `cold-twt-receipt.json` 的旧字段 `actual_paid_or_primary_provider_requests=3` 按配置的查询标签分组，字段名不准确。这三条内层 HTTP trace 实际都是 `techwithtim_catalog`；传输白名单及 `network.json` 证明实际 Tavily/Serper/SearxNG 请求为 **0**。准确解释见 `verified-outcome.json`，原始回执保留。
- 目录抓取临时工具使用 URL 派生文件名，同一分类页第二次响应覆盖了第一次正文。`pages.json` 保留两次响应 SHA，分类页磁盘文件仅保留最后一次正文；Streamlit 与 TWT 系列页正文保留各自对应 SHA。未声称所有历史正文均可从磁盘重放。
- 唯一被阻止的详情动作：匿名 GET `https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/pygame-animation`；原因是本地隔离工具的累计传输预算，状态为 **发出前阻止，未重试**。不是网站拒绝，也不是自动审批拒绝。不存在仍在等待或结果不确定的执行。

## 默认检索提供商及预算

只读核对 8001、8017 的公开 `/api/capabilities`：B站为 SearxNG，不限域沿用全局 SearxNG，MOOC 为 Tavily（`auth_mode=api_key`）；Serper 已配置但没有被这些默认分支选中；未配置 SearxNG 付费故障切换。公开免费目录兜底在当前生产配置中关闭，本轮只在临时实例显式启用和使用。

Tavily 代码固定 `search_depth=basic`、`auto_parameters=false`，不请求 answer/raw content。公开价格为 Basic **1 credit/次**，PAYG **$0.008/credit**；公开免费档每月 1000 credits。这些资料**不能证明现有账户仍有免费余额**。本轮未读取密钥、账户套餐、账单或剩余额度，也未新建账户或改变付费设置。

价格来源：[官方 credits 说明](https://docs.tavily.com/documentation/api-credits)、[官方价格页](https://www.tavily.com/pricing)，本轮已核对。

| 隔离验收配置 | 首轮分支总请求上限 | Tavily Basic 请求上限 | 公开 PAYG 参考费用 |
| --- | ---: | ---: | ---: |
| 1 个知识点，三分支各一轮，无重试 | 3 | 1 credit | $0.008 |
| 2 个知识点，三分支各一轮，无重试 | 6 | 2 credits | $0.016 |

以上配置已通过本地 `platform_budget` 预检，没有发网。2 点是可观察多知识点公平首轮的最小规模；1 点只能作三分支连通冒烟。它们不能证明缺口补搜完整、所有 20 点找到视频或新 AI 项目全流程。

实际执行必须使用独立临时库及显式 Settings，将 B站/MOOC 轮数都设为 1、总搜索上限设为 `3×点数`、重试设为 0，保留三分支并行及不限域，禁止模型/其他付费端点/故障切换，并在实际 Tavily POST 发出前再计数。现有生产 `SearchRequest` 不接收单次预算覆盖参数，不能向当前生产 API 普通 POST 就声称只有 1 credit 上限。当前普通单点计划是 B站3+MOOC10+不限域1，最多 10 次实际 MOOC 搜索，公开 PAYG 参考 $0.080。

**仍缺授权/依据：** 当前禁止新增付费搜索。执行单点最小方案需另行允许至多 1 次 Tavily Basic 请求（或 2 点公平性方案至多 2 次），或先有可独立证实的当前免费余额并获准使用。可按实际请求数限制 credit 消耗；未知账户具体套餐、计费及美元硬限制，不能保证账户特定美元账单上限。Tavily 授权也不会自动解除此前匿名默认搜索来源的停止状态。

## 最终代码和运行核对

本轮未改产品代码。已重新计算上轮交付的 **88 个公开文件 SHA-256，全部一致**；因此上轮最终代码测试结果仍适用于当前交付版本，但本轮未重跑整套测试。上轮后端最终 JUnit 5983 项、失败 0、错误 0；前端类型检查、构建及浏览器结果详见先前收尾报告。

本轮只读健康核对：8001、8017 均 `status=ok`、运行任务 0、队列 0；先前服务 PID 3796、75808、10388 的命令及创建时间未变。未启动/停止现有服务，8002 未操作。没有安装、打包、push、发布、新凭据或私人数据复制。

## 证据目录

`C:\Users\xiaoer\AppData\Local\Temp\knowledge-sprite-free-live-20261020`

- `verified-outcome.json`：准确的阶段结论、失败/未运行/阻止状态及回执字段更正。
- `minimal-default-acceptance-budget.json`：公开价格、实际提供商、零网络预算预检、缺少的授权及限制。
- `prior-delivery-hash-check.json`：88 个交付文件逐项 SHA 核对。
- `current-capabilities.json`：本轮现有服务健康和公开能力快照。
- `catalog-probe.json`、`probe-receipt.json`：Streamlit 等公开目录的原生联网记录。
- `cold-*.json`：第一次隔离 API 失败回执；`cold-twt-*.json`：第二次真实目录 API 回执、候选与证据。
- `network.json`、`blocked.json`、`pages.json`、`page-*.html`：实际传输、被阻止请求与保留的公开 HTML。

所有本轮进程已返回，不存在待确认写入。接下来仍需补齐 CSV 下载视频、默认三分支实网、合格新材料的共享库复用和新项目全链路验收。
