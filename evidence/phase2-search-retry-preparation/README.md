# 搜课重试版本准备

当前仅完成离线计划和 MockTransport 自测，真实 API、模型、搜课和平台请求均为 0。须等待根任务确认重载的运行态并授权后，才运行 `--live`。

脚本：`scripts/phase2_search_retry_prepare.py`。

源审批：`evidence/phase2-learning-v26/run.json` 和 `manual-review.json` 中已独立静态精读通过的两个案例：

| 案例 | 项目 | 原版本 → 目标版本 |
| --- | --- | --- |
| bicycle_csv_advanced | 424bd3d9-7626-4498-bc90-703aab564b01 | 2 → 3 |
| pygame_maze_intermediate | ec77f474-496a-4eb1-b5cc-ed0db4276ac3 | 2 → 3 |

`plan.json` 固定了源文件、每例输入、分析和人工审批的 SHA。执行时先 GET 全部项目，要求仍为审批对应的当前版本、终态 `partial`，且输入/分析/提示词完全相同。然后各最多一次 `POST /api/projects/{id}/edit`，请求仅含 `expected_version` 与原样 `analysis`，不调用分析、确认、搜课或外部平台接口。

每次 POST 前持久化 `run.json` checkpoint。失去响应只 GET，要求新版本恰为原版本 + 1、`origin=student_edit`、`parent_version` 等于原版本、状态 `analyzed`、未确认/未搜课，输入/分析/提示词相同。未观测到成功或绑定不一致时保留未决状态，不自动重发。已有 `run.json` 只能使用 `--observe-only`。

成功后生成 `source_run.json`、`manual_review.json` 和兼容原搜课 runner 的 `search_plan.json`。继承审批保留原要求、单元判断和低优先级备注，通过 `approval.inherited_from` 记录源文件、记录与审批 SHA；仅重绑版本，没有新模型分析或新的人工精读，不代表视频或生产验收通过。

命令（替换为根任务确认的重载运行态，不猜 PID）：

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2'
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' -X utf8 scripts/phase2_search_retry_prepare.py --live --base-url http://127.0.0.1:8000 --runtime-manifest <确认的manifest路径> --runtime-pid <确认的PID> --runtime-prompt <确认的capabilities提示词版本>
```

恢复观察使用完全相同参数，将 `--live` 改为 `--observe-only`。它不会补交未提交的其他案例。

`self-test.json` 和 `self-test/` 是零网络 MockTransport 测试证据；子目录中的项目视图、新版本与审批导出均为模拟，**不可用于真实搜课或真实验收**。6 项测试涵盖成功原样编辑、已持久化但失响应的只读恢复、未持久化失响应不重发、整组内容变化时零 POST、错误来源/父版本拒绝，以及禁止分析/搜课/确认/创建接口。成功与失响应场景另校验 POST 前 checkpoint、原审批继承、`make_plan` 兼容和重复执行只读。
