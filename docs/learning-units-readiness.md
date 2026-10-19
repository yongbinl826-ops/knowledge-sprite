# 学习单元生成验收

本记录验收“项目名称与需求 → 可审阅学习单元”。不能用本记录的测试数替代视频检索、真实链接、页面交互或整个 APP 的生产验收。

## 实现与边界

当前提示词版本为 `project-analysis-v2.4-explicit-technology`。新分析保留功能映射、学习目标、必要先修、顺序、必要性与学生选择，并要求每单元包含：

| 字段 | 学生看到的用途 |
| --- | --- |
| `project_task` | 本单元要完成的具体项目子任务 |
| `technology` | 本单元采用的语言、工具或框架，供学生调整检索目标；不是视频覆盖证据 |
| `concepts` | 合作完成任务的具体概念或技能，新生成 2–6 项 |
| `practice_check` | 学完后可动手观察或核对的结果 |
| `learner_profile` | 明示学习阶段、已有知识假设及调整方式 |

阶段缺省为 beginner；假设可以修改，不替学生认定已掌握。新生成入口严格检查这些字段；历史 v1 记录缺字段时仍能加载，保持 `None` / 空数组，不伪造旧数据。生成校验覆盖引用、无环先修、顺序、功能映射、重复项、分析不得含课程 URL 等边界，并拦截明确泛学科标题、语法碎片、复制标题代替解释和阶段不符。

单次模型调用默认 90 秒，整次分析含修复默认 120 秒。最多两次请求，仅结构或质量不合格可修复一次；修复只使用总预算剩余时间，超时与传输失败不自动重发。单次配置范围 1–120 秒，整体 1–180 秒，整体不得小于单次。最终共享模型传输发送配置的 `max_tokens`（默认 6000）；截断输出明确失败，即使其中 JSON 恰好完整，也不能当作完整分析保存。

质量检查是保守防线，不能仅凭关键词证明所有项目语义正确。测试夹具、真实调用、静态精读和实际学生代码/硬件执行必须分开。

## 标准与合成验收

五项逐例精读标准：①功能覆盖与原需求对应；②粒度围绕一个连贯子任务，目标与练习可执行；③先修必要且顺序合理；④无无关功能或泛课替代；⑤具体技术满足行为约束。

四类项目分别覆盖游戏事件循环/输入/碰撞/重开、看板读入清洗/筛选/聚合/图表/导出、网站交互/状态/持久化/响应式与键盘、硬件接线/校准/阈值/持续响应。`evidence/learning_units_offline.json` 为四类 × beginner/intermediate 共 8 个明确标为合成的样本，自动契约检查 8/8 通过，0 次提供商请求。它证明验收工具和契约，不能证明真实模型全部 8 种组合均已通过。

## 独立代表性验收的 7 次请求

这是该验收脚本的请求数，不是整个项目及后续浏览器联调的模型调用总数。浏览器同一输入回归另列于下节。

| 证据文件（均在 evidence/） | 项目 / 阶段 | 观察结果 | 耗时 | 请求 |
| --- | --- | --- | --- | --- |
| `learning_units_live.json` | 游戏 / beginner | 6 单元，覆盖通过 | 42.383 秒 | 1 |
| 同上 | 看板 / beginner | 9 单元，覆盖通过 | 39.133 秒 | 1 |
| 同上 | 网站 / beginner | 原 60 秒预算超时，无伪造结果 | 60.012 秒 | 1 |
| 同上 | 硬件 / beginner | 原 60 秒预算超时，无伪造结果 | 60.014 秒 | 1 |
| `learning_units_live_revision.json` | 网站 / beginner | 短句提示和新预算后，8 单元 | 19.107 秒 | 1 |
| 同上 | 硬件 / beginner | 6 单元；自动命中通过，人工精读发现阻塞矛盾 | 58.930 秒 | 1 |
| `learning_units_live_arduino_intermediate_revision.json` | 硬件 / intermediate | v2.2，7 单元，逐字符输入方案通过 | 26.548 秒 | 1 |

最后一条曾因执行环境断连而状态未知。恢复后直接读取已落盘的 `run_complete=true`、`provider_requests=1` 及完整分析确认成功，没有重复调用。此轮恢复工作新增真实模型请求 **0 次**。这些旧证据没有采集提供商 token usage 或金额，不能声称已测得实际货币成本。

`evidence/learning_units_recheck.json` 使用当时 v2.2 guard 对原始 7 条记录重审，新增请求 0 次。整体 `automated_passed=false` 是预期：保留了 2 次历史 timeout，且检查拦截了旧 beginner 硬件输出；其余已完成样本通过该轮自动检查。历史失败没有被改写成成功。

## 浏览器同一原始输入回归：v3 / v4 / v5 / v6

精确输入来自 `evidence/live-e2e-data-boundary.json`，并与 `evidence/recovered-browser-analysis.json` 中的 input 一致：本机 Python 图形接球游戏，方向键移动挡板，接球计分，漏接结束，按空格重开，不需要登录或联网；阶段 beginner。该输入是本任务编写的合成教育示例，分析由真实服务生成，不能混同为模拟模型响应。

| 项目分析版本 | 证据 | 结果与提供商观测 |
| --- | --- | --- |
| v3 | `browser/real-project-final/report.json` | 真实分析失败，报告 `too_large`；未记录 provider 元数据，不能补编 token、HTTP 次数或模型时长 |
| v4 | `browser/real-project-reasoning-final/report.json` 与 `model-events.jsonl` | `output_truncated`；HTTP 200，33.444032 秒，finish_reason=length；completion 6000，其中 reasoning 4443；输出没有当作完整分析保存 |
| v5（提示词 v2.2） | `browser/real-project-thinking-final/report.json` 与 `model-events.jsonl` | root 启用 thinking.disabled 配置后返回并显示 6 个真实单元；第一调用 HTTP 200/stop，但 JSONDecodeError，10.534714 秒、1640 completion；受控修复调用 HTTP 200/stop，11.270286 秒、1986 completion。两次模型调用合计 21.805 秒，不能把 11.270 秒称作整次分析总时长 |
| v6（提示词 v2.3） | `browser/real-project-final-v23/report.json` 与 `model-events.jsonl` | 单次 project_analysis，HTTP 200，13.110203 秒，completion 2253、prompt 2600、total 4853，finish_reason=stop；返回 7 单元。analysis_input 与 API 保存的 original_input 及原始输入证据逐字段一致 |

v5 原独立精读已归档为 `evidence/learning_units_browser_v5_review.json`。该版本名义上覆盖全部需求，6 单元粒度与先修图合理，没有无关账号/联网功能；但 **v5 整体精读未通过**：`functions[f5].acceptance_criteria` 要求“停止游戏循环”，与 k6 结束状态仍接收空格事件重开的要求冲突。若学生按该条验收退出整个循环，重开与关闭事件将不再处理。k1–k5 的练习可观察，k6 的练习必须先消除该冲突。

正确说明应为：停止进行中状态的物理更新与计分，继续处理事件和绘制结束画面；空格重置分数、球和挡板。原始 v5 输出保持不变，没有把建议修正文案冒充模型原文。背景说明另有非阻断措辞问题：一处称未假设已有技能，learner_profile 又列出变量、函数及容器基础，应统一为“无项目经验，明确假设基础语法”。

v2.3 提示词和有界 guard 已修复此类遗漏：在明确按键重开场景，检查功能验收、技术方案和学习说明中的退出整个循环指令；允许只暂停物理/计分、正确状态暂停、否定/风险讲解及明确保留外层事件循环的方案，不限定变量名。真实六功能/六单元形状的负例、正确状态方案和一次受控修复均已回归。

**v6 真实输出现已独立静态精读通过**，最新记录为 `evidence/learning_units_final_browser_review.json`。f5 明确“物理与计分暂停……程序仍运行”；技术计划与 k6 一致要求事件/绘制继续，k7 在空格时复位分数、小球与挡板。旧主循环矛盾已在新模型原文中修正，不是手动改写旧结果；当前 guard 检查无问题。7 单元先修为 k1→k2→k3→k4→k5→k6→k7，覆盖完整、顺序可执行；未发现新的阻断语义缺陷。

第一单元“Python 变量与坐标数值基础”是适度的项目前置：任务是建立挡板/球的初始位置、宽高及分数数据，概念把命名、x/y 坐标、整数/浮点和算术组合使用；练习是打印并改变数值、预测位置，不需要先完成 pygame 窗口。命名只是这个连贯任务的一项技能，而非单独变量名碎片；后续六单元覆盖实际游戏功能，没有用一门“Python 基础课”代替项目学习。学习背景仍明确假设可运行脚本、知道 if 与函数基本写法；这不是完整零编程课程，已有基础者可标为已掌握。

v6 另有低优先级措辞备注：assumptions 中“技术栈未指定”宜准确称为“图形库未指定”，因为输入已指定 Python；实际技术计划遵循 Python，并未偏离技术路线。这不构成阻断项。

生产源码保持冻结。本次 v6 精读只读取原有真实证据，新增模型请求 0 次，也未执行学生游戏。课程检索/播放与该静态学习计划结论分开验收。

## 真实精读矩阵

“通过”均为计划静态审阅，不是学生代码运行、传感器接线或视频教学效果验证。

| 组合 | 功能覆盖 | 粒度 | 先修 | 无关项 | 技术正确性 / 证据 |
| --- | --- | --- | --- | --- | --- |
| 游戏 / beginner | 通过：窗口、控制、下落、碰撞、计分、结束/重开齐全 | 最新浏览器 v6 为 7 单元，含具体坐标数据前置；早期独立案例为 6 单元 | 坐标→主循环→移动→碰撞→计分→结束→重开 | 无账号、联网或部署 | 最新 v6 静态通过；旧 v5 失败仍保留 |
| 游戏 / intermediate | 合成夹具通过 | 合成夹具通过 | 合成夹具通过 | 无 | 未真实调用，不能外推模型阶段适配 |
| 看板 / beginner | 通过：清洗、筛选、汇总、两类图、导出齐全 | 9 个单元，处于小项目范围上端；可合并相邻清洗项 | 清洗先于筛选，聚合先于图表，导出依赖筛选 | 无登录、数据库或云部署 | 静态通过，真实生成 |
| 看板 / intermediate | 合成夹具通过 | 合成夹具通过 | 合成夹具通过 | 无 | 未真实调用 |
| 网站 / beginner | 通过：增删、完成、筛选、保存、手机/键盘齐全 | 8 个连贯任务 | 数据模型先于增删筛选/持久化 | 无框架或后端扩张 | 静态通过，有下述措辞备注；真实生成 |
| 网站 / intermediate | 合成夹具通过 | 合成夹具通过 | 合成夹具通过 | 无 | 未真实调用 |
| 硬件 / beginner | 通过：接线、读取、校准、阈值、持续响应均有对应项 | 6 个连贯任务 | 接线→读取→校准→输出/输入 | 无水泵、市电、云端 | **原输出不通过**：默认串口解析与响应约束矛盾；当前 guard 已拦截，未伪造该阶段重测通过 |
| 硬件 / intermediate | 通过：6 项功能均对应学习单元 | 7 个任务，聚焦调试、定时、行解析与联调 | 接线/标定先行；定时与串口调试先于输入解析，最后整合 LED | 无水泵、市电或云端功能 | 静态通过并保留下述学习说明备注；真实 v2.2，26.548 秒 |

说明备注：网站技术计划有一句把已指定技术栈称为“未指定”，部分旧调整说明暴露字段名；v2.2 已明确禁止这类措辞。最终硬件计划正确采用字符缓冲，但数值解析应教学生先验证完整数字串与缓冲边界，再转换并检查范围；不能仅靠 `atoi` 的结果判断输入有效。AVR-LibC 文档说明 `atoi` 转换数字前缀且不检测溢出，完整输入校验需额外实现，见 [AVR-LibC stdlib 文档](https://avrdudes.github.io/avr-libc/avr-libc-user-manual/group__avr__stdlib.html)。干湿端点映射得到的是相对校准刻度，不应直接理解为经过计量验证的绝对含水率。最终硬件接线单元的读数检查可在下一读取单元完成后复核。上述计划未提供完整固件，不把这些说明当成执行正确性的证明。

## 官方源码核实的已修缺陷

旧 beginner 输出建议 `Serial.parseInt`，同时承诺采样期间即时响应，没有解释输入等待或缓解措施。官方 AVR 实现中，`parseInt` 经由 `peekNextDigit` / `timedPeek` 等待输入，`Stream` 默认超时 1000 毫秒。因此，仅把采样改成 `millis` 不保证整个循环持续响应。

来源：[ArduinoCore-avr Stream.cpp](https://raw.githubusercontent.com/arduino/ArduinoCore-avr/master/cores/arduino/Stream.cpp)（解析等待路径）；[ArduinoCore-avr Stream.h](https://raw.githubusercontent.com/arduino/ArduinoCore-avr/master/cores/arduino/Stream.h)（默认超时）。这是静态源码核实，不是硬件实测。

v2.2 要求持续响应场景采用逐字符读取、行缓冲和非法输入处理。guard 仅在用户明确提出这种约束时，拦截缺少缓解说明的 `Serial.parseInt` / `readString`；解释缓冲替代方案或明确有界超时的内容仍可通过，普通串口实验不被无关拒绝。第 7 条真实结果已经改为 `Serial.available()/read()` 缓冲至换行，含范围与非法输入提示；millis 单元也覆盖无符号时间差与回绕。

## 复现与收尾条件

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2'
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' -m pytest tests/test_learning_units.py tests/test_project_analysis.py tests/test_projects.py tests/test_project_boundaries.py -q
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/accept_learning_units.py
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/accept_learning_units.py --replay evidence/learning_units_live.json --replay evidence/learning_units_live_revision.json --replay evidence/learning_units_live_arduino_intermediate_revision.json
```

最后一条命令是历史重审，因上述已保存失败而返回非零，不能理解为发起了新的模型调用。普通离线样本不需要 `--live`。真实调用必须显式指定 `--live`、最大请求数和输出路径，使用已有配置，密钥与原始提供商错误不会打印；每例 checkpoint 落盘。Windows async 测试需要本机 socketpair，受限沙箱下此次使用获准的测试执行环境，没有更改业务代码绕过网络策略。

基础集成回归为 **159 passed / 7.16 秒**，详见 `evidence/learning_units_regression.json`。包括最终 `max_tokens` 配置进入模型载荷、即使完整 JSON 也拒绝截断完成、结构/语义修复预算、历史兼容、串口边界和零请求历史重审。新增重开循环语义修复后，同一相关测试集为 **173 passed / 7.12 秒**，记录于最终与 v5 归档审阅文件。v2.3 的 v6 真实生成及独立静态精读现已通过。早期七例精读判断另存 `evidence/learning_units_manual_review.json`。这组证据支撑当前已测学习生成流程与失败恢复边界；未真实调用阶段、实际学生代码/固件/硬件执行以及模型在所有项目上的语义正确性仍不能据此宣称完成。


## v2.4 explicit technology contract

Each newly generated unit must explicitly include a technology string of at most 80 characters. The prompt asks for the tool relevant to that subtask rather than copying the entire project stack. An explicit empty string is permitted for a general concept. Persisted older analyses retain an empty default; fresh raw model JSON missing the key instead receives one bounded structural repair. Empty defaults are not treated as evidence that the model provided a field. Whitespace-only values, wrong JSON types, oversized values and URLs are rejected. The field is an editable retrieval target and does not establish what a real video covers. Python remains a specified language when only the graphics library is unspecified; any library choice must be marked as an adjustable assumption.

The v2.4 offline checks passed: learning-unit and analysis tests 159 passed / 0.80 seconds; project-boundary tests 15 passed / 0.87 seconds. Evidence: `evidence/learning_units_v24_contract_regression.json`. These are two separate test commands, not a replacement for the parent integration suite. The contract-change subtask made zero provider requests. The v6 real-model review above remains evidence for prompt v2.3; it is not re-labelled as a live v2.4 result.

## v2.4 最终真实输出的独立静态复核

父任务随后从本地页面提交同一合成接球项目输入，生成真实 v8 / `project-analysis-v2.4-explicit-technology`。`evidence/browser/real-project-final-v24/report.json` 直接保存的 `analysis_input`、`original_input` 与最初 `evidence/live-e2e-data-boundary.json` 中的输入一致。本次分析事件只有一次调用：HTTP 200、完整读入、`finish_reason=stop`，10.873103 秒，prompt 2777 / completion 1990 / total 4767 tokens；这些数量仅对应这一分析调用，不包括之后的视频检索。

独立审阅保存在 `evidence/learning_units_final_v24_review.json`，以分析对象的规范化 SHA-256 固定审阅内容，避免仍在检索的浏览器报告发生变化。6 个单元均显式包含 `technology`：k1 为 Python，k2–k6 为 pygame；新生成结构校验与当前语义 guard 通过。计划正确区分“已指定 Python”和“未指定图形库，暂选 pygame 的可改假设”。工具字段只表明检索目标，不能证明任何视频实际覆盖该工具。

人工逐项结论为静态通过，无已知高/中优先级语义缺陷：窗口与退出、方向键与边界、下落/碰撞、加分/复位、漏接结束、空格重开均有具体任务与可观察练习；数值状态→事件循环→移动→碰撞→计分→结束/重开的先修顺序合理。k1 虽以变量和数值更新为题，实际练习是维护挡板/球坐标与分数的小脚本，组合了类型、更新和检查，属于适度项目先修，不是变量名单行碎片。背景明确采用 beginner、零项目经验，同时将 while/if 与运行脚本列为可调假设，因此不声称适合完全零代码学生的完整入门课程。

游戏结束/重开的既有缺陷在本次输出中继续修复：只暂停物理和计分，事件处理与结束画面绘制继续，功能验收及 k6 均明确主循环不退出，空格重置分数与位置后恢复游戏。低优先级教学备注为按帧固定位移应在学生实际编写代码时配合帧率限制或时间步说明，并在目标机器实测；该备注未被隐去，也不被当作游戏已执行验证。此次独立复核使用零网络请求、零模型请求，未修改生产代码；视频检索与界面验收仍由父任务分别记录。
