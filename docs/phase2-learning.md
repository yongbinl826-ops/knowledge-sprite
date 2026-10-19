# 阶段 2：未见项目与学生阶段验收

本阶段独立于此前 1756 项回归及阶段 1 真实证据。目标是观察四个新项目上的学习分析，不复用接球小游戏，不以关键词数量或测试总数代替人工语义验收。所有输入为合成学习需求，无敏感个人数据。

最终独立审阅的学习分析快照为：网页/Arduino v3（v2.6.1）加骑行/迷宫 v2（v2.6），覆盖三种学生阶段，24/24 项需求静态通过、25 个单元已精读，无已知高/中优先级学习语义缺陷。它是明确选定的混合版本快照，不是单版本一次成功率 100% 的声明；v2.4–v2.6 的失败、有限修复与实际调用用量均保留。下文按阶段记录证据，页面、学生项目执行和视频质量另行验收。

## 案例与事前标准

四例已获集成负责人确认：beginner 的 HTML/CSS/JavaScript 离线番茄钟、advanced 的 pandas/Matplotlib 骑行 CSV 报告、beginner 的 Arduino 按钮反应时间游戏、intermediate 的 pygame 8×8 固定迷宫。advanced 案例明确会 Python/统计但首次使用 pandas 分析出行数据，不将高级标签等同熟悉所有库。完整输入、功能观察点和人工技术检查清单保存于 `evidence/phase2-learning/plan.json`。

验收要求如下：

| 维度 | 事前标准 |
| --- | --- |
| 需求覆盖 | 每项明确行为有具体学习单元或必要先修，不只在 scope 中提及 |
| 粒度 | 一个可练习的项目子任务，不能用整门语言课或单行语法代替；4–8 单元为软观察区间，已有基础时允许更少并说明 |
| 先修 | 引用有效、无环、顺序正确，同时人工判断真实必要性 |
| 相关性 | 按单元使用恰当工具，无无关必修与项目外功能；工具字段不是视频覆盖证据 |
| 技术正确性 | 无未处理高/中优先级行为矛盾；硬件仅静态审查，不当成上板执行 |
| 学生阶段 | 保留指定阶段，尊重具体已有经验，不擅自认定掌握未接触的库 |
| 延迟 | 客户端分析墙钟目标 60 秒以内；超过 90 秒为延迟不通过，p95 上限 90 秒。观察最多 150 秒，超出后不自动重复提交 |

关键词仅为人工审查提示。最终质量通过需要每例逐项人工判定，不能因为命中词或结构有效就判定语义通过。真实链接和视频相关性由集成负责人统一检索，避免并发消耗上游配额。

## 执行边界

`scripts/phase2_acceptance.py` 默认只写计划，零网络；`--live` 必须指定已确认的 loopback 服务地址和预期提示词版本。本阶段只对父任务指定的 `http://127.0.0.1:8000`（确认运行 PID 39688、v2.4）顺序提交最多 4 个项目分析，不确认或发起搜课，不读取密钥，不直连模型。程序内部结构修复仍最多一次，所以四次分析最多可能对应八次 provider 请求；实际次数从脱敏 model events 记录，不猜测。

每次变更前 checkpoint 落盘。创建/分析响应不确定时不会自动重发；已知 project_id 时只读恢复观察。该脚本不会停止服务、发送 Ctrl+C 或改共享生产配置。观测事件源由父任务指定为公开证据目录 `evidence/browser/real-project-final-ui-v24/model-events.jsonl`，本阶段顺序分析独占；仅复制本次 `task=project_analysis` 事件到阶段 2 目录，不修改原证据。

## 首轮与单独恢复结果

首轮严格只提交 4 次：3 次生成完成，迷宫例发生 provider `ConnectTimeout`，没有 HTTP 响应或 usage。其客户端等待 5.281946 秒，provider 连接尝试 5.27231 秒。该失败保存在首轮 `run.json` 和 `pygame_maze_intermediate.json`，没有改成首轮通过。

集成负责人随后明确授权一次同项目、同输入的新版本恢复。迷宫项目 v1 已确认 failed 后，以 `expected_version=1` 提交 v2，不重建项目，恢复客户端等待 12.269101 秒；证据独立保存于 `maze-recovery/recovery.json`。本阶段至此合计 5 次分析 API 提交、5 个完成的 provider 事件，只有 4 次返回完整分析。

| 案例 / 阶段 | 项目 ID / 版本 | 单元数 | 客户端墙钟 | 人工静态复核 |
| --- | --- | --- | --- | --- |
| 番茄钟 / beginner | `6d967d65-a25c-479b-b9d1-30ad5dbad637` / v1 | 6 | 13.355728 秒 | 6/6 行为覆盖；通过，有低优先级教学备注 |
| 骑行 CSV / advanced | `79e8b3a3-54bf-484a-9a70-b6449bdf7239` / v1 | 5 | 12.339395 秒 | 6/6 行为覆盖；通过，有低优先级口径备注 |
| 按钮反应游戏 / beginner | `c180bfcd-e9d0-4d95-8aa0-1d59997039ee` / v1 | 6 | 13.330949 秒 | **未通过**：去抖存在中优先级技术矛盾，5/6 行为可确认 |
| 固定迷宫 / intermediate | `d3640200-66c5-42b6-8d3b-5289b1e290d8` / v2 恢复 | 5 | 12.269101 秒 | 5/5 行为覆盖；通过；首轮连接失败仍保留 |

人工复核不是沿用自动关键词结论。每个单元的相关性与粒度、每项需求的单元/功能映射、先修、阶段、技术理由都存于 `manual-review.json`，修复前快照另存 `manual-review-before-arduino-fix.json`。当前 22 个单元的项目相关性和粒度均通过，必要先修关系与阶段适配通过，但 Arduino 的明确去抖矛盾使整体语义验收为 false。不能用 22/22 粒度、所有关键词命中或 guard 为零掩盖这一失败。

技术字段实际值为：番茄钟 `HTML`、四个 `JavaScript`、`CSS`；骑行报告四个 `pandas`、`Matplotlib`；Arduino 为两个 `Arduino Uno`，以及 `Arduino C++ (millis)`、`Arduino C++ (millis, random)`、`Arduino Serial`、`Arduino C++ 状态机`；迷宫五个 `pygame`。它们属于拟学习工具，不是视频实际覆盖证据。

## 必须修复的真实失败

Arduino v1 的 `analysis.assumptions[2]` 原句为“假设按钮去抖既可用 millis 时间窗也可用状态比较，二选一即可；随机等待必须非阻塞。”技术计划及 k3 描述也重复了这一替代关系。仅比较当前/前次原始电平或检测下降沿，无法独立过滤机械抖动；短暂跳变可能成为多次按下、抢按或轮次转换。正确学习路径应在动作边沿前有稳定时间窗、多次稳定采样、明确依据的硬件去抖或专门去抖库。状态比较与稳定机制结合的方案应被允许，不能仅按“状态/边沿”字面误拒。

该问题已报告集成负责人修复；本分支未修改模型/分析生产代码，也未擅自调用 Arduino 第二次。下一次真实回归须在修复版本重载并获明确安排后单独记录，保留本条 v1 失败。此前 Pygame 接球、硬件采样等旧失败与 1756 项回归证据不作覆盖。

## 度量与证据边界

`scripts/phase2_acceptance_metrics.py` 只读保存证据，零网络；缺少人工复核、单元映射不存在或分析哈希不一致时均不能给语义通过。脚本可单独合并明确恢复记录，始终报告首轮与恢复数量。当前命令及结果为：

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2'
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/phase2_acceptance_metrics.py --recovery evidence/phase2-learning/maze-recovery/recovery.json
```

输出 `metrics.json`，当前因 Arduino 语义未通过而有意返回退出码 1。四个已生成案例客户端中位数 12.835172 秒、nearest-rank p95 为 13.355728 秒，均未超 60 秒目标；只有四个观测，不能当成稳定生产分位数。包含首次失败及恢复的模型调用墙钟合计 54.563028 秒。四次成功调用报告 completion 8147、total 19733 tokens；ConnectTimeout 没有 usage，因此不能把其未知用量编成零或据此推算账单。API 提交计数与 provider 事件计数分别保留。

runner 已以 Mock transport 自检 4 次创建/4 次分析/0 次搜索，并验证拒绝外网 origin；仅保存标为 Mock 的 `runner-selftest.json`。度量脚本额外核对缺失审阅、无效单元引用、错分析哈希及失败保留行为。以上自检不计作真实分析成功。所有语义判断均为静态精读；未执行学生网页、CSV 脚本、Pygame 游戏或硬件，也未验证推荐视频。

## v2.5 修复后的同案例回归

集成负责人明确授权在重载的 `8000 / PID 40280`、`project-analysis-v2.5-canonical-tools-debounce` 服务上，对同一组四个输入各提交一次新快照。证据独立保存在 `evidence/phase2-learning-v25/`，没有覆盖 v2.4 首轮失败或迷宫恢复。`input-continuity.json` 验证四个输入与 v2.4 完全相同，且与各自 API 持久化版本一致。`runtime-binding.json` 记录父任务运行 manifest 的路径、哈希与 PID 绑定；模型事件仅从本阶段公开 observer 文件复制。

| 案例 / 阶段 | 新项目 ID / 版本 | 单元数 | 客户端墙钟 | 独立静态复核 |
| --- | --- | --- | --- | --- |
| 番茄钟 / beginner | `ea521eeb-a1a7-4bbc-8845-d3764201b0ae` / v1 | 8 | 15.365290 秒 | 通过；建议合并小型格式化/键盘验证单元，并在实现中明确暂停保存剩余量、继续时重建截止时间 |
| 骑行 CSV / advanced | `424bd3d9-7626-4498-bc90-703aab564b01` / v1 | 8 | 12.416862 秒 | **未通过**：严格正值验收与零时长边界冲突 |
| 按钮反应游戏 / beginner | `dbbc7902-f26a-4a94-9e64-390d42f9fe45` / v1 | 6 | 16.307379 秒 | 通过；真实稳定时间窗后检测按下沿，旧去抖矛盾已消失 |
| 固定迷宫 / intermediate | `ec77f474-496a-4eb1-b5cc-ed0db4276ac3` / v1 | 7 | 13.303683 秒 | 通过；ready/playing/won 保留事件与绘制，胜利后仍可 R/Esc/QUIT |

四次均有单独的 HTTP 200 / `finish_reason=stop` 完整分析事件，没有本分支人工追加或重试。实际事件共 4 个，报告 completion 9234 / total 21456 tokens，模型调用墙钟合计 55.297151 秒。客户端中位数 14.3344865 秒、四例 nearest-rank p95 为 16.307379 秒，未超目标；这些小样本不是生产延迟分布估计。本分支发起的搜课次数仍为零。

工具字段现在均为简短检索目标：番茄钟为 `HTML`、六个 `JavaScript`、`CSS`；骑行为七个 `pandas`、`Matplotlib`；硬件六个 `Arduino`；迷宫七个 `pygame`。`input-continuity.json` 保留完整有序值。相关性与粒度按实际子任务人工判断，而非只因这些词命中就通过；29 个单元均有具体任务与练习，较小单元可合并的备注保留在审阅中。

Arduino 的去抖修复由实际文本支持：技术计划先取得固定时间窗后的稳定状态，再在松开→按下时产生事件并要求松开后才允许下一轮；k3 规定 20–30ms 稳定窗，列出稳定去抖、边沿+锁存与计数验证。按钮明确 INPUT_PULLUP、按下 LOW；等待用 millis 无符号差值与持续采样而非 delay；WAIT 判断抢按，LIGHT 记录亮灯时刻后计反应时长。该结论为静态通过，不能称为硬件执行成功。审阅保留一条低优先级措辞备注：k5 的“再按回到空闲”应在实际固件中确认不会多要求一次开始按键。

## v2.5 新发现的有效行边界矛盾

骑行需求仅将“结束早于开始”判为无效，未将相等时刻判为无效。新计划及 k4 仍使用 `end_time < start_time` 排除；公式 `(end_time-start_time).dt.total_seconds()/60` 对相同起止时间自然得到 0。但 f3 验收写“有效行含 duration_min 列且数值为正值”，k5 练习又写“CSV 含正数时长列”。因此一条起止时间均为 `2026-01-01 09:00:00` 的合成行，会同时满足既定有效规则、得到正确的 0 分钟，却无法通过生成的严格正值验收。应保留非负边界，或由学生明确修改无效规则，不能静默收紧为 `<=`。

该中优先级问题已报告集成负责人，本分支不改生产提示词或 guard、不擅自增加模型调用。`evidence/phase2-learning-v25/manual-review.json` 及修复前快照完整保留逐单元理由、24 项需求映射和具体反例；目前 23/24 项可确认，技术项使整体语义为 false。对应 `metrics.json` 有意退出 1；`manual-review-before-duration-fix.json`、`metrics-before-duration-fix.json` 固定了此阶段失败，不会由后续回归改写。

```powershell
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/phase2_acceptance_metrics.py --directory evidence/phase2-learning-v25
```

四例均为真实模型分析而非 Mock；审阅与度量脚本为零网络。视频候选质量和外部链接仍由集成负责人统一检索、独立审核，本记录不作视频覆盖或播放声明。

## v2.6 验收 runner 准备记录（当时尚未调用服务）

`scripts/phase2_acceptance_v26.py` 已准备，默认仅生成 `evidence/phase2-learning-v26/plan.json`，零网络。它从 v2.5 保存的四个项目读取原始输入与 ID，不创建重复项目；查询实际当前版本后以 `expected_version` 提交新版本，不会覆盖既有版本。新计划锁定相同 24 项独立需求，复制的是需求标准而非 v2.5 的通过/失败或旧单元映射，并固定相等起止时间为 0 分钟、缺失/负时差、倒计时恰为 0、低有效按钮、8×8 负索引/越界等检查点。

运行前必须获集成负责人明确通知 v2.6 已重载冻结。runner 校验实际 manifest 中 `backend/app/analysis_review.py`、`project_analysis.py`、`config.py`、`llm.py` 的 SHA 与本地文件一致，并检查 loopback 端口、根目录与可选确认 PID；能力字段必须为 `project_analysis.prompt_version=project-analysis-v2.6-bounded-semantic-review`、`semantic_review_enabled=true`、`max_model_calls=4`，且 `review_max_output_tokens` 在 1–1500 内。旧 v2.5 manifest 或未启用复核的运行态不能通过 preflight。尚未提交时会先检查全部四个现有项目，输入变化或已有分析进行中则不花费任何模型调用。

每个 POST 前先写带项目/预期新版本的 checkpoint。响应丢失后只读取该预期版本及当前状态，不盲重发；`run.json` 已存在时拒绝再次 `--live`，仅可 `--observe-only` 观察。各例最多一次分析 API 提交，程序内部上限按根实现为 2 次生成 + 2 次独立复核、总 120 秒。observer 同时复制 `project_analysis` 与 `project_analysis_review` 事件，分别计数生成、复核与用量，复核输出还核对实际较低 operator 上限；语义最终结论仍等待独立人工复核。

默认离线计划已生成；Mock 自检验证 0 次项目创建、4 次分析、0 次搜索/确认、POST 前 checkpoint、响应丢失后只读恢复而不重复提交，以及生成/复核事件分别捕获和较低 1200-token 操作配置。自检仅存 `runner-selftest.json`，临时模拟项目输出已清理，不当成真实 v2.6 结果。

待根确认实际 manifest/observer 路径后，运行命令为：

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2'
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/phase2_acceptance_v26.py --live --base-url http://127.0.0.1:8000 --expected-prompt project-analysis-v2.6-bounded-semantic-review --runtime-manifest evidence/phase2/runtime-manifest.json --model-events evidence/phase2/runtime/model-events.jsonl
```

可加 `--runtime-pid` 绑定根确认的新 PID；上面的路径必须指向新生成的 v2.6 manifest，不能沿用旧文件。将 `--live` 换成 `--observe-only` 时没有 POST。旧 `phase2_acceptance.py`、v2.5 输出、需求输入与 `phase2_acceptance_metrics.py` 均保持兼容；v2.6 结果字段继续支持旧度量脚本的 `--directory evidence/phase2-learning-v26`，并由新 runner 的 summary 额外区分生成/复核调用。上述为执行前的零网络准备记录，后续真实结果如下。

## v2.6 真实四例：两例通过、两例拒绝

根明确授权后，runner 核对 `evidence/phase2/runtime-v26-manifest.json`、实际 PID 21076、全部 manifest 中的 backend 文件哈希及新复核模块；能力开关为启用、max4、review1500。四个既有项目输入均与原始案例完全一致，未创建新项目，各仅提交一次分析 API，生成新 v2。结果为：

| 案例 | v2 状态 | 客户端墙钟 | 可人工审查的新分析 |
| --- | --- | --- | --- |
| 番茄钟 | `analysis_failed` / schema | 30.825164 秒 | 无；不假造被拒草稿的具体质量结论 |
| 骑行 CSV | `analyzed` | 32.546064 秒 | 7 单元，6/6 需求静态通过，零时长边界明确修复 |
| Arduino | `analysis_failed` / quality | 30.779665 秒 | 无；不以旧 v2.5 通过替代新输出 |
| 固定迷宫 | `analyzed` | 26.630905 秒 | 6 单元，5/5 需求静态通过，胜利后持续事件与绘制 |

`evidence/phase2-learning-v26/manual-review.json` 明确为 11 项可人工确认、13 项因无 accepted 分析不可审；整体 cohort=false。`metrics.json` 将“不可审”与“已审失败”分开，不把 2/2 已生成输出静态通过冒充 4/4 可用。网页的实际序列为生成→复核→生成；骑行与 Arduino 为生成→生成→复核；迷宫首个生成 HTTP 200 但 JSONDecodeError，有限修正后再生成→复核成功。没有手工重发。

全部 12 个真实模型事件保留，8 次生成、4 次复核，各例 3 次，均在最多 4 次及总预算内；生成 completion 18142、复核 completion 423、total 58575 tokens，usage 全捕获。复核输出分别为 147/10/257/9 tokens，低于 1500。所有终态响应的客户端中位数 30.8024145 秒、p95 32.546064 秒；这只说明响应时间，不消除两例生成失败。源证据和错误没有覆盖。

## v2.6.1 只恢复失败子集

根修复通用 repair 上下文后，明确授权只对网页与 Arduino 再各提交一次。runner 新增 `--case`/`--cases`，计划、上限、return 与 summary 均按 selected_count；本轮只选两个原项目，仍取同一原始输入，当前版本 2→新 3，骑行与迷宫本轮 **0 次分析 API**。Mock 已验证只访问选中项目、POST 前 checkpoint、两个提交上限、13/24 固定需求子集和缺失 usage 保持未知。

真实执行绑定 `evidence/phase2/runtime-v261-manifest.json`、PID 32228、`project-analysis-v2.6.1-review-repair-context`。`evidence/phase2-learning-v261/run.json` 及每例文件保存全部结果；`input-continuity.json` 确认输入未变。

| 恢复案例 | 新版本 | 单元数 | 客户端墙钟 | 独立静态复核 |
| --- | --- | --- | --- | --- |
| 番茄钟 | v3 | 7 | 28.688210 秒 | 7/7；暂停存剩余量、继续重建截止时间、归零切阶段并暂停、专注计数、窄屏与原生键盘均有具体任务和练习 |
| Arduino | v3 | 5 | 19.386940 秒 | 6/6；LOW 有效、间隔稳定采样后再检测下降沿、长按不重发、millis 非阻塞等待/抢按及再开始均明确 |

这两例共 2 次 API、5 次实际模型调用（3 次生成、2 次复核），不是只有最后成功调用：网页有两次生成加一次复核，Arduino 一次生成加一次复核；completion 8047、total 27895 tokens，usage 全捕获。模型时间合计 47.277107 秒，客户端中位数 24.037575 秒。没有额外人工 retry。根的上下文修复由运行 manifest 和测试另证；本记录不凭 tokens 增长推断请求正文。

独立 `manual-review.json` 对 13 项需求逐项映射到真实功能/单元并精读，均静态通过，无新高/中阻断。低优先级备注仍保留：网页“重置计数见假设”引用应补齐；硬件实际固件需验证反应起点取 LED 亮起时刻，四次 5ms 间隔采样只应视作近似稳定窗口，不声称精密 20ms 测量或上板执行成功。

## 最终可供后续检索的明确版本

最终静态验收矩阵由零网络 `scripts/phase2_acceptance_finalize.py` 固定在 `evidence/phase2-learning-final/acceptance.json`。它只允许下表指定来源，核对原始输入、项目身份、分析哈希、完整单元/需求映射与独立审阅，绝不自动退回 v2.5 或拒绝草稿。

| 案例 / 阶段 | 项目 ID | 版本 | 来源提示词 | 单元 / 需求 |
| --- | --- | --- | --- | --- |
| 番茄钟 / beginner | `ea521eeb-a1a7-4bbc-8845-d3764201b0ae` | 3 | v2.6.1 | 7 / 7 |
| 骑行 CSV / advanced | `424bd3d9-7626-4498-bc90-703aab564b01` | 2 | v2.6 | 7 / 6 |
| Arduino / beginner | `dbbc7902-f26a-4a94-9e64-390d42f9fe45` | 3 | v2.6.1 | 5 / 6 |
| 固定迷宫 / intermediate | `ec77f474-496a-4eb1-b5cc-ed0db4276ac3` | 2 | v2.6 | 6 / 5 |

合计 25 个适中粒度单元、24/24 项独立静态需求通过。选定快照的客户端中位数 27.6595575 秒、四例 nearest-rank p95 32.546064 秒；这是混合版本小样本，不是单版本生产 SLA。所有先前失败与恢复仍在各自目录。该矩阵的历史账本覆盖本记录四个阶段的 15 次分析 API 提交、26 个 provider 完成事件，已报告 completion 43993 / total 127659 tokens，另有一次 ConnectTimeout usage 未知；这里只统计列明的学习分析证据，不包含所有搜课/APP 调用，不推算费用。

```powershell
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/phase2_acceptance_v26_metrics.py --directory evidence/phase2-learning-v26
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/phase2_acceptance_v26_metrics.py --directory evidence/phase2-learning-v261
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' scripts/phase2_acceptance_finalize.py
```

第一条保留失败并有意退出 1；后两条退出 0。后续检索分支已收到真实文件与版本，仍需分别审视频相关性、真实链接和页面全流程。本分支没有搜索或部署，没有将静态学习分析验收扩大为所有项目、所有阶段、视频播放或整个 APP 的生产保证。

## 搜课重试：两个版本重绑，原学习内容与审批不变

数据与迷宫原 v2 的首轮真实搜课没有推荐卡片。为在修复后的检索运行态重试，集成负责人实际运行 `scripts/phase2_search_retry_prepare.py`，分别通过一次 `/edit` 创建 v3；没有重新分析、修改学习内容、确认或启动搜课。`evidence/phase2-search-retry-preparation/run.json` 记录 2 次 edit POST、2 个准备完成、0 次分析、0 次确认、0 次搜课、0 次自动重发。它不是新的模型成功案例，不改变此前分析 API 与 provider 用量历史。

| 案例 | 项目 ID | 重绑 | 继承的提示词与审批 |
| --- | --- | --- | --- |
| 骑行 CSV / advanced | `424bd3d9-7626-4498-bc90-703aab564b01` | v2 → v3 | v2.6；7 单元、6 项需求的原独立静态审批 |
| 固定迷宫 / intermediate | `ec77f474-496a-4eb1-b5cc-ed0db4276ac3` | v2 → v3 | v2.6；6 单元、5 项需求的原独立静态审批 |

独立只读核验保存在 `evidence/phase2-search-retry-preparation/independent-export-audit.json`：总体 11 项检查和每例 19 项连续性检查均通过。新旧输入、analysis、prompt、model 标记相同；新版本来源为 `student_edit`、父版本 2、状态 `analyzed`，导出时未确认、未搜课。原审批的判断、单元映射、技术说明和低优先级备注原样保留。`approval.inherited_from` 绑定原 run、原记录、原 manual 文件和单例审批 SHA，并核对 POST payload 为 `expected_version=2` 加原样 analysis。审核没有发出网络或模型请求，也没有重新精读这 11 项需求。

导出的 `source_run.json`、`manual_review.json`、`search_plan.json` 已通过原搜课 runner 的 `make_plan` 和 `check_view` 校验，明确标注仅重绑版本、内容不变、没有新模型分析或独立语义重审。上表最终分析快照中的 v2 仍是实际生成和精读来源；后续搜课可使用原样内容的 v3，不应把分析生成版本与搜课重试版本混为一谈。网页与 Arduino 继续使用原 v3，无须重复 edit。`self-test/` 下的模拟导出不能作为真实搜课输入。

## 学习单元到检索目标的信息损失与有界修复

只读审查确认旧适配器只把明确的技术前缀加单元名称传给 `SearchRequest.knowledge_points`，没有逐单元传递确认的 `concepts`。后续扩展、子技能拆分与覆盖检查使用这段检索文本和共享背景，前端有服务端子技能时优先展示这些标题拆分项。因此，实际学习单元的具体技能可能不在检索或路线覆盖的分母里。这能证明信息流丢失，但不能单凭它认定此前零卡片的全部原因；上游可用性和来源访问限制仍须单独记录。

三个真实已审批例子及原文件 SHA 见 `evidence/phase2-search-retry-preparation/learning-target-contract-review.json`：

| 实际单元 | 原确认的具体技能，不能被业务标题代替 |
| --- | --- |
| pandas 时间列解析与无效行分离 | `pd.to_datetime(errors)`、`isna 与缺失筛选`、`布尔条件 end < start`、`相等时间的边界判断` |
| pygame 真实时间计时与限帧 | `pygame.time.get_ticks 毫秒`、`结束时间减开始时间`、`clock.tick 限帧`、`重置时更新时间基准` |
| Arduino 按钮去抖的稳定时间窗口实现 | `millis()非阻塞定时采样`、`稳定时间窗口去抖`、`下降沿单次触发`、`长按不重复触发` |

集成负责人授权的最小契约已实现：`SearchRequest.learning_targets: dict[str, list[str]]` 默认空字典，key 必须是当前请求中确切的检索名称；每批最多 5 个 key，每单元 1–8 条、每条最多 120 字符、目标字典 JSON 的 UTF-8 总大小不超过 20,000 字节。空白、控制字符、规范化重复和未知 key 被拒绝。适配器从确认快照的 `concepts` 原样复制，不补写 API、背景或学习内容；同一检索名称对应不同概念时拒绝确认，避免静默覆盖。旧手工请求和历史 JSON 缺字段时继续默认空，不伪造目标，无须新增 SQL 列。总大小远低于现有 512,000 字节请求上限。

本分支只修改请求契约、项目适配和确认预检；持久化/缓存、覆盖与缺项补搜由根分支统一集成。非空目标必须参与请求身份，旧空目标的缓存/幂等身份兼容也须保留。增加目标不能增加既定请求预算：目标是待寻找内容依据的要求，初始仍为 unknown；标题、API 名字或传入概念本身不是教学证据。完整单元名称、项目子任务和练习继续保留，不能以部分技能支持代替整单元教学、数字边界行为或项目实践完成。

前端学习路线需按当前确认单元的目标 ID 与原文核对服务端结果。只有标题或 `whole_topic` 的历史结果不能填满新增技能，平台筛选和待核实候选也不能借用其他项的依据。即使概念全部找到正文或目录依据，仍不能推定完整项目练习已完成。另一个后续可改进点是阶段粒度：骑行学生有 Python/统计经验、首次接触 pandas，单一 `advanced` 标签不应推定其熟悉每个库；本次不扩展这一契约。

离线回归命令为 `python -X utf8 -m pytest tests/test_project_learning_targets.py tests/test_project_search_context.py tests/test_projects.py -q`，结果 **80 passed / 0 failed，7.07 秒**，外部请求为 0。新增测试验证历史默认、原文和确认快照、边界/总字节、空/控制/重复/未知 key、同名碰撞与非空目标的哈希差异。此处不把适配测试通过等同于真实检索、页面或生产验收通过。

## 四例检索终态与第五类看板补充

根线程后续实际 r6b 搜课的独立审核位于 `evidence/phase2/search-independent/four-project-terminal-review-summary.json`，逐单元判据和来源审阅说明见 `docs/phase2-search-relevance-rubric.md`。骑行/迷宫搜课快照为 v4，网页/Arduino 为 v3；这些搜课版本不改变各自原分析生成与审批来源。25 个已审批学习单元最终展示 15 条部分匹配卡片，7 单元有部分结果、18 单元无结果、0 单元完整教学支持。四例终态分别耗时约 277、454、409、133 秒，不能据此宣称推荐功能已经生产验收通过。

只读来源核查发现了具体可修问题：Bili 相关视频尾巴误归属、TWT Scoring 目录召回顺序、讲解配套短代码片段过滤、Arduino 工具名与中文紧邻后丢失详情探测 owner，以及 CSS 换行/焦点目录的部分信息未利用。严格数字、API、项目状态等未知项仍保留，未把查询词、模型目标或暂存语义原型当教学证据。新数据库快照只用只读连接与 backup API 取得一致视图，未请求上游或改源库；原 r6b 失败结果不被修复候选覆盖。

原骑行 CSV 报告明确不做看板，因此另补了未见过的中级 Streamlit 自习室看板案例。`evidence/phase2-dashboard-analysis/manual-review.json` 对真实一次分析逐条核对事前六项 rubric 与合成 CSV oracle，静态通过：六单元、保留有效零值、含等号日期范围、空房间选择为空、加权 42.9% 而非逐行平均 45.0%、空指标“—”。`approved-search-plan.json` 可供根线程后续搜课；这不是运行成品或真实视频检索通过。

看板原 harness 统计只覆盖生成任务，原报告保留。完整 observer 另有语义复核，实际共 2 次模型调用、2430 completion tokens、9965 total tokens，两个 call ID 与原始事件子集 SHA 已附在独立 manual review。人工审核没有把模型复核 pass 或关键词命中当质量通过。

## 五类项目的最终静态分析验收汇总

`evidence/phase2/five-project-static-acceptance-summary.json` 已按真实保存的分析 SHA、原输入、固定需求和既有独立人工审核重新核对汇总。前四例为 25 单元、24/24 项静态需求通过，新增 Streamlit 看板为 6 单元、6/6 项通过，合计 **31 学习单元、30/30 项静态需求通过**。表中是各例最终接受的实际生成快照，提示词和版本混合，不能当作五例首轮一次成功率；此前失败、修复和重试记录仍保留。后续仅用于重搜的 edit 版本也不算新的模型分析或独立语义审批。

| 案例及学生阶段 | 接受的分析生成版本 | 提示词 | 单元 | 静态需求 |
| --- | --- | --- | ---: | ---: |
| 番茄钟网页 / beginner | v3 | v2.6.1 | 7 | 7/7 |
| 骑行 CSV 报告 / advanced、首次 pandas | v2 | v2.6 | 7 | 6/6 |
| Arduino 反应游戏 / beginner | v3 | v2.6.1 | 5 | 6/6 |
| Pygame 固定迷宫 / intermediate | v2 | v2.6 | 6 | 5/5 |
| 自习室 Streamlit 看板 / intermediate、首次 Streamlit | v1 | v2.6.1 | 6 | 6/6 |

这里的“通过”仅指先前独立人工审阅确认，学习计划对固定需求有合理任务、技能、先修和练习映射。没有执行学生项目代码、生成的看板成品或硬件，没有据此证明视频教学覆盖或生产就绪。五例最终真实检索还须在新结果保存后另做逐来源、逐目标独立质量审查；原四例 r6b 检索失败结论没有被此静态汇总替换。

为避免把内部修复或语义复核漏出成本分母，新汇总统计上述五个接受分析 API 快照内的所有已观察调用：**8 次生成/修复 + 5 次语义复核 = 13 次模型调用，19,802 completion tokens、67,485 total tokens，未知 usage 为 0**。其中看板为 1 次生成 + 1 次复核，共 2 次、2430 completion、9965 total。此范围不包含更早失败版本、其它回归轮次或视频搜索/重排调用，不代表整个项目历史成本；未估算金额。

看板原 run 的 generation-only 摘要及其 `provider_counts_are_complete` 原值完整保留在历史文件中，不能再据该值声称总共一次调用；新汇总单列完整 observer 修正与两个 call ID。集成负责人已报告修正后的 harness 定向 3 项测试通过；本次只读汇总没有重新运行测试或改写历史账。11 个源 JSON 的 SHA、每例实际模型事件及用量已绑定在新汇总中，写出后再次核对源文件均未变化。本次新增 HTTP 和模型调用均为 0。
