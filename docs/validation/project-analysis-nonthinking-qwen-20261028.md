# 项目分析非思考模式与千问对比

日期：2026-10-28。项目 `1db14b6f-e5c5-4d57-93e8-236cff20d419`。

## 已实现的范围

- 项目专属 `PROJECT_ANALYSIS_THINKING_MODE=disabled`，独立克隆请求配置；全局视频检索的模型、密钥、思考模式和搜索配置不变。
- 千问仅在识别到官方百炼地址和明确支持的模型时发送 `enable_thinking=false`；DeepSeek 使用 `thinking.type=disabled`。切换供应商必须同时提供项目专属端点和凭据，防止跨供应商借用密钥。
- 保持 `project-analysis-v9-textbook-single-generation` 原提示词：教材式概念名称，项目用途放说明，不预置本项目知识点，不凑数。
- 一次生成，不增加名称/内容判断、提示或修正。只保留已有 JSON 结构、数量及敏感内容边界；输出上限 16000、知识点上限 30、含排队的总超时 60 秒。
- 后台新增 HTTP 阶段耗时、可用时的推理 token 记录；前端 UI 投影移除分析时间、尝试记录和失败诊断。原始后台审计和旧版本完整保留。

百炼官方文档截至本次查询列出 `qwen3.8-max` 为最新 Max 系列，支持关闭思考。用用户提供的凭据只读查询模型列表，HTTP 200 且列表包含该模型，然后进行一次真实生成。来源：[模型选择](https://www.alibabacloud.com/help/zh/model-studio/models)、[思考模式](https://www.alibabacloud.com/help/zh/model-studio/deep-thinking)。

## 相同需求的真实结果

三版保存的项目输入完全相同：用 Python 做接球小游戏，方向键移动挡板，接住下落小球记录分数，漏接后能够重新开始。输入没有指定图形库。v7 是原有记录；本次仅新建 v8、v9，各一次模型请求，无重试，无视频搜索。

| 版本 | 请求模型 / 模式 | 知识点 | 总耗时 | 模型请求耗时 | 输入 token | 输出 token | 总 token |
|---|---|---:|---:|---:|---:|---:|---:|
| v7 | deepseek-flash / low 思考 | 15 | 51.262757 秒 | 51.253444 秒 | 1958 | 7727 | 9685 |
| v8 | deepseek-flash / 关闭思考 | 18 | 14.935057 秒 | 14.928357 秒 | 1933 | 1556 | 3489 |
| v9 | qwen3.8-max / 关闭思考 | 11 | 21.179298 秒 | 21.173459 秒 | 1932 | 820 | 2752 |

v8 比 v7 缩短约 71%，v9 比 v7 缩短约 59%；本次两版都在 30 秒内。各一个样本，不能保证后续全部项目都在 30 秒内。60 秒硬超时未降低。输入文本相同，但不同模型/模式的供应商计数不必相同。

两次新响应没有报告独立的 reasoning_tokens，保存为 unknown/null，不记成零；输出 token 是供应商报告值，不能拆算成“思考节省量”。HTTP 头部/正文接收耗时不是首 token 时间，也不能区分供应商排队、推理和生成。统计仅保存在后台与本报告。

## 人工文本质量对比

此表为测试完成后的人工阅读，不是应用新增的判断阶段；没有改写任何模型原稿，也没有调用模型评分。

| 维度 | v7 | v8 | v9 |
|---|---|---|---|
| 教材式命名 | 概念最稳定，二维坐标系、矩形包围盒、有限状态机等较明确 | 基础更显性，但“计分与整数累加”“主循环启动”等夹杂任务动作 | 简洁，但“Rect对象”“游戏状态管理”等仍偏 API 或功能分类 |
| 必要覆盖 | 输入、更新、碰撞、边界、计分、漏接、重开、绘制形成闭环 | 核心闭环完整，变量、分支、函数、参数与回调更明确 | 漏了挡板边界、接球后复位/移走小球、必要初始化说明 |
| 准确性 | “随机落点每次不同”不准确；dt 与整数 Rect 之间的位置表示未交代 | 两处碰撞规则不一致；函数修改模块级坐标却没解释作用域 | 每帧固定增量同时声称 tick(60) 确保不同硬件速度一致，错误；技术方案“重力”与固定速度正文不一致 |
| 粒度 | 大体合理，“累加器”可并入变量/状态说明 | 输入事件与键盘控制重复偏多 | 数量少本身不是问题，缺失机制比条目少更关键 |

人工综合结论：**本样本 v7 的整体知识点质量更稳；限定 30 秒内，v8 优于 v9。千问这次没有带来质量提升。**v8 自行选择 tkinter，v7/v9 选择 pygame，因此不是固定实现路线的严格对照实验，不能把质量差异全部归因于思考开关，也不能据此给模型作总体排名。

细节依据：Pygame 的 [Clock.tick](https://www.pygame.org/docs/ref/time.html#pygame.time.Clock.tick) 只限制最大帧率，不能保证实际帧率；[Rect](https://www.pygame.org/docs/ref/rect.html) 使用整数坐标；Python 的 [randint](https://docs.python.org/3/library/random.html#random.randint) 不保证连续调用不重复。v8 没有随机数条目不算必然遗漏，因为需求没有指定随机落点；单循环实现也不必为了凑数单列函数。

## 验证与数据保留

- 外网连接守卫下，与 v7 相同的分析回归范围加新增测试：**2368 项通过**。覆盖配置隔离、两家请求参数、单次调用、旧稿回放、超时/数量边界、后台 token 和前端隐藏。
- 原数据库完整备份；先以 DeepSeek 非思考配置启动 8000，完成 v8 后，确认服务空闲再切到千问。两次启动前后所有数据库表的行摘要相同。
- 原有 **90** 个历史版本逐条摘要一致；最终 **92** 个，仅新增 v8、v9。v7/v8/v9 都与各自保存的结果一致。
- 最终服务健康、无待运行任务，继续使用 `D:\项目制知识引导小精灵\data\discovery.sqlite3`。当前项目分析模型为 `qwen3.8-max`，关闭思考；视频检索配置未变。
- 浏览器已实际打开 v9，显示 11 个知识点；页面不显示分析阶段耗时或 token。没有点击“查找视频”。
- 凭据只存在本地被 Git 忽略的配置文件，未写入报告、代码差异、能力接口或模型结果。

全库扩展回归为 **8800 项通过、75 项失败**（另有 26 个 subtests）。用修改前 HEAD `bfeb3d7f` 的四个生产模块，在临时导入隔离环境中重跑相同 75 个失败项，75 项全部复现，失败集合一致；可提取的 63 条首要错误信息也一致。74 项涉及旧判断/修正契约，另 1 项本地恢复测试的 `restart_analysis_interrupted_no_auto_model` 断言也在修改前代码复现。未为了测试恢复用户已停用的流程，未改动这些旧测试。此结果证明这些已观察失败在基线也存在，不能把分析范围的 2368 项通过描述为全库全绿。

## 本地证据

目录：`C:\Users\xiaoer\AppData\Local\Temp\analysis-nonthinking-qwen-20261028-51e_kodv`。

- `analysis-regression.xml` / `analysis-regression.log`：定向离线回归。
- `offline-suite.log`：扩展全库测试原始记录。
- `baseline-head-failed-only/baseline-report.json` / `baseline-comparison.md`：75 个失败项的修改前基线复现、模块摘要与实际导入路径。
- `discovery-before.sqlite3` / `baseline.json`：数据库备份和原有 90 个版本摘要。
- `deepseek-service-receipt.json` / `qwen-service-receipt.json`：启动及数据库不变核验。
- `deepseek-post-attempted.json` / `qwen-post-attempted.json`：仅一次提交标记。
- `v7.json` / `v8.json` / `v9.json`：保存的三份完整原稿。
- `deepseek-live-report.json` / `qwen-live-report.json` / `final-verification.json`：耗时、用量、原输入相同、历史保留及最终运行配置。
- `v9-browser.png`：实际页面截图。

[查看 v7](http://127.0.0.1:8000/?project=1db14b6f-e5c5-4d57-93e8-236cff20d419&version=7) · [查看 v8](http://127.0.0.1:8000/?project=1db14b6f-e5c5-4d57-93e8-236cff20d419&version=8) · [查看 v9](http://127.0.0.1:8000/?project=1db14b6f-e5c5-4d57-93e8-236cff20d419&version=9)

## 后续选择：采用 v8 方案

用户随后选择使用 v8。项目分析已切回 `deepseek-flash`、`PROJECT_ANALYSIS_THINKING_MODE=disabled`，8000 重启生效；其余调用次数、提示词、16000/30/60 限制及视频检索设置不变。此次没有调用模型或新建版本，全部 92 个历史版本及所有数据库表记录在重启前后相同。浏览器打开 v8 历史结果供查看；未将历史 v8 设为可编辑的当前版本，项目最新保存版本仍是 v9。切换核验与数据库备份位于 `C:\Users\xiaoer\AppData\Local\Temp\use-v8-20261028-upxsqcm5`。
