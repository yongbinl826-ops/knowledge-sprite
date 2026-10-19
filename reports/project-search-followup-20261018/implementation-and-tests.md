# 实施与离线测试记录

本轮只优化查询、证据匹配、详情读取优先级和部分匹配的章节定位。使用现有 FastAPI、SQLite、JobService、真实搜索提供者与抓取器，无新数据库迁移，无配置上限调整，无固定课程注入。

## 改动文件

| 文件 | 本轮改动 |
| --- | --- |
| `backend/app/llm.py` | 关键词扩展首条短语表达核心操作，减少业务叙述和半个复合点；保持原 JSON 结构与任务隔离。 |
| `backend/app/queries.py` | 保留原词首轮，第二轮选一个短且尽量完整的候选；保留技术对象、版本、域名与查询上限。 |
| `backend/app/ranking.py` | 同对象的中文语序、有限核心操作/API证据；原限定项仍 unknown；拒绝旁列、否定、先修、错技术与未知 API 归属。 |
| `backend/app/service.py` | 已有合格候选中，明确可核验的主题证据优先取得详情预算，不改变准入或显示门槛。 |
| `frontend/src/chapterRecommendations.ts` | 部分匹配只推荐实际支持子项所引用且字段已核验的目录记录；保持测验、作业和异语言排除。 |
| `tests/test_followup_queries.py` | 31 项查询专项，含最终扩词长度、无效后缀和 legacy 拼接保护。 |
| `tests/test_followup_detail_admission.py` | 10 项详情排序专项。 |
| `tests/test_project_followup_matching.py` | 105 项匹配专项，包括真实边界反例、仅标签支持和旧 SQL 正例保护。 |
| `frontend/tests/partial-chapter-evidence.test.mjs` | 7 项部分匹配章节专项。 |
| `scripts/probe_project_candidate.py` | 独立有界详情探测，输出实际请求与来源字段，不写入项目搜课数据库。 |
| `scripts/run_query_guard_validation.py` | 对保存请求中的指定知识点进行一次独立正常搜课；新空库、固定预算、不导入课程、不并入主项目。 |
| `README.md` | 链接本轮验收记录，说明部分支持和章节证据边界。 |
| `reports/project-search-followup-20261018/` | 保存基线、诊断、失败及通过日志、独立探测、实网运行、只读审阅和页面证据。 |

仓库原有未提交修改继续保留；这里仅列本轮文件范围。现有参考提交没有回退。没有修改来源访问范围、robots、安全检查、暂停逻辑、凭据或公网部署设置。

## 实际执行

- 改动前完整后端基线：1276 passed、26 subtests passed，70.30 秒。`baseline.xml`。
- 第一轮完整后端：1383 passed、1 failed、26 subtests passed。失败是旧测试禁止扩词提示词出现 `project requirements`，而新提示词的否定句恰含这两个词；仅改为 `never to broaden the requested scope`，任务语义不变，未删除或放宽旧测试。原失败保留在 `first-backend-regression.xml` / `.log`。
- 整项目实网运行前的完整后端：**1386 passed、26 subtests passed**，62.33 秒。`full-before-final-review.xml` / `.log`。保留 1 条原有 Starlette/httpx 弃用警告。此后人工审阅又收紧查询候选选择与仅标签匹配，最终测试另行记录。
- 标签过滤后的完整后端：1414 passed、1 failed、26 subtests passed。旧 SQL 正例已有 MySQL/ROW_NUMBER 的明确同条教学证据，但移除标签后，旧词面分值折扣又推翻了已验证的支持。仅给既有 `sql_row_number_is_window_function` 规则增加同条证据分值保护，未恢复标签或降低通用门槛。保留失败在 `before-sql-guard-fix.xml` / `.log`，新增 7 项边界回归。
- **最终完整后端：1422 passed、26 subtests passed，63.01 秒**，`final-backend.xml` / `.log`；1 条原有弃用警告。全部生产代码已冻结后执行，最后三点真实补测也使用此版本。
- 最终前端逻辑：**41 passed**，`frontend-node.log`。
- 最终前端 Edge Playwright：**41 passed**，28.4 秒，`e2e-results.json` / `.xml` / `e2e.log`。这些是明确使用离线 fixture/Mock 的回归，不冒充真实搜索。
- TypeScript / Vite 生产构建通过，`frontend-build.log`。
- 独立审查复现的旁列 API、错误 receiver、竞争技术和否定共 15 个反例，最终均拒绝支持；相关专项已经纳入完整后端测试。

```powershell
$env:LLM_PROVIDER='none' # 仅此测试子进程；不修改 .env
.venv\Scripts\python.exe -m pytest -q
node --test frontend/tests/*.test.mjs
cd frontend
npm run build
$env:PLAYWRIGHT_CHANNEL='msedge'
npm run test:e2e
```

完整测试包含项目确认、分批、预算、取消、版本、手动搜课与访问策略回归。本轮真实网络验证另见本目录 README；视频播放和整课教学完整性不属于这些离线通过结论。
