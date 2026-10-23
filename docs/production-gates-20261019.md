# 上线工程门槛审查与本地加固（2026-10-19）

本轮继续审查已交付的两个核心流程，只改上线前必要工程。当前可交付范围是可信单用户、本机、单进程实例；多人共享实例的身份与私有项目隔离尚未实现，不能据此称为公网生产版本。前端源码、已交付界面和视频相关性逻辑没有改动。

## 已发现并修复的具体问题

| 问题与实际观察 | 代码与结果 | 证据 |
| --- | --- | --- |
| 旧版允许第二个 APP 实例打开同一 SQLite；首实例的 running 任务被恢复逻辑改成 interrupted。 | `backend/app/runtime_guard.py` 在数据库打开、建表和恢复之前取得单实例锁；第二实例启动失败，首任务仍 running。正常关闭、启动异常、意外进程退出后可重新取得锁。 | `runtime-owner-before.json`、`runtime-owner-after.json`、`tests/test_runtime_boundaries.py` |
| 旧版重启会自动提交项目的第二个 pending 批次；真实本机 HTTP 复现中新增一次模拟来源请求。 | `ProjectService.start()` 仅恢复记录：项目和未提交批次转 interrupted；不恢复补搜，不新建来源任务。已经原子提交但未关联的批次，只按持久化幂等键、内部 consumer 引用及知识点对应关系重绑原 job。原确认、结果、预算和消耗保留。 | `local-load-independent/baseline-restart-red.json` 与 `report.json` |
| 旧版 20 个实时订阅全部返回 200，没有全局连接上限。 | `MAX_EVENT_STREAMS=16`（严格范围 1–128）；投影前预留名额，超限返回 429 和 Retry-After: 2；断连、取消和异常均释放。组合观察为 16 个 200、4 个 429，随后可重新订阅。 | `security.py`、`config.py`、`tests/test_runtime_boundaries.py`、本地负载报告 |
| 原部署只有 SearXNG，没有 APP 镜像、持久化卷、启动预检和应用健康检查。 | 新增 `Dockerfile`、`compose.app*.yaml`、配置空示例、启动/健康/备份恢复工具及 [操作文档](../deploy/app-operations.md)。Linux host network + 固定 loopback，单 worker、禁代理头、非 root、只读根目录、数据/备份双卷及资源/日志上限。 | `tests/test_app_deployment.py` 49 项离线检查；Compose 5.1.0 实际配置解析通过 |
| 原生启动示例默认信任 Uvicorn 代理头。 | `scripts/start.ps1` 与 README 显式使用 `--no-proxy-headers`，保留单机体验。 | 启动参数及本机恢复后健康/伪造代理头探测 |
| 一部分离线测试依赖历史 reports 路径，独立源码快照缺失这些输入及已安装的浏览器开发依赖。 | 8 个既有匿名公开 HTTP/DOM 样本原字节移到 `tests/fixtures/public_catalog_replays/`，保留原哈希断言；开发依赖复用 package-lock 中已有 Playwright 1.64.0，不下载平台内容。 | `portable-fixtures.json` 与完整回归报告 |

锁文件与数据库放在同一持久化目录，解锁后不删除锁文件，避免 inode 竞争。它只保护遵循本版本启动流程的应用实例，不替代 SQLite 事务，也不能阻止旧版程序或管理员绕过启动流程直接写库。不支持网络文件系统或以别名绕过数据库路径；备份只处理 SQLite，不把锁文件当数据库还原。`.gitignore` 同时排除锁文件和操作者可能建立的容器私有配置。

## 身份与数据边界的真实结论

`/api/capabilities` 明确返回 `authentication:false`。项目列表、按 ID 的项目/任务/证据/结果/SSE 都没有用户主体或 owner 条件。`job_consumers` 是内部任务共享引用，不能当用户授权。本机、Host、Origin、Fetch-Metadata 与伪造代理头的防护有效，但两个获准进入同一实例的合成客户端确实可以交叉读改项目和取消任务。独立 15 项审计通过，证明的是这些边界与共享行为；没有把它包装成“账户隔离通过”。

需要的最小产品决定是：首发采用单用户独立实例，还是多人集中实例且学生项目必须私有。建议当前首发继续独立实例。若要多人私有使用，可由已有可信身份网关按人隔离实例/数据库；若坚持共享同库，则必须选择已有可用身份来源，并对项目、版本、任务、证据、SSE、幂等键、共享缓存与额度做完整的主体归属迁移和授权验证。仅加登录页或信任 `X-User` 头不能补齐这个缺口。本轮未接入身份服务、创建账户或凭据。

## 验证范围与实际观察

冻结组合完整回归为 5411 项测试与 26 个子测试通过，0 失败/错误/跳过，330.65 秒；1 条既有 Starlette/httpx 测试客户端弃用提示。466 个源与测试文件起止哈希一致。源与测试绑定、最终完整回归结果保存在本次证据目录；模拟供应商与真实供应商证据分开。本轮新增真实模型、真实搜索供应商调用均为 0。现有核心功能的历史真实来源验收保留，没有把它升级成此次的新实测。

本机负载脚本 `scripts/validate_local_load.py` 在新建合成 SQLite 上运行真实 loopback HTTP，外部来源和模型使用确定的 MockTransport；非 loopback DNS/连接在建立之前禁止。9 个有限场景、44 项准入检查通过，258 次本机请求含 8 次预期 429、0 次服务 5xx。142 次普通读取 p95 29.138ms，6 次取消 p95 14.546ms，SSE 满载下 12 次健康读取 p95 103.403ms。检查覆盖分析并发 2、检索请求并发 2、分析/项目排队上限、写限流后的取消、任务队列满、来源 503/timeout 后继续服务、重启无新来源工作与预算保留，以及单实例和实时连接边界。阈值在脚本中预先定义。11.7 秒有限观察不代表供应商容量、长期稳定性、多进程扩容能力或生产 SLA。

可重跑的独立本地模拟（输出目录必须不存在）：

```powershell
$env:PYTHON_DOTENV_DISABLED = '1' # 当前测试进程不加载运行配置；正常启动APP另开终端。
.\.venv\Scripts\python.exe -X utf8 -B scripts\validate_local_load.py --help
.\.venv\Scripts\python.exe -X utf8 -B -m pytest tests/test_runtime_boundaries.py tests/test_local_load_harness.py tests/test_access_boundary_audit.py tests/test_app_deployment.py
```

备份测试在合成活跃 WAL 数据库上检查已提交行一致性、未提交行排除、拒绝覆盖既有目标、还原到新文件及仅在副本上演练迁移；未使用或复制实际学生数据库。真实 APP 本地启动继续使用既有配置，工程脚本不读取、哈希、复制或改写实际 `.env` 与实际 SearXNG 配置，也不输出凭据。未修改系统网络/安全设置，未启动 Docker daemon，未提交/推送 Git，未公开部署。

## 仍未取得的生产证据

1. 多人访问模型、已有身份来源和目标宿主环境的选择；目前没有互不信任学生共享实例的隔离。
2. 目标 Linux 的受审镜像 digest、实际镜像构建、host networking、卷/secret UID 权限、资源限制及真实容器停启。默认可变镜像标签只是模板入口；本轮没有 pull/build/up。Windows 原生路径保持可用，Docker Desktop 的 host networking 未验证。
3. 目标环境对实际数据库的恢复演练、真实供应商的预算内集成与较长时间负载观察。当前已有合成演练和历史真实来源证据，不能替代这些最终准入。

在以上决定和目标环境证据完成之前，交付结论保持为“单机版本完成必要加固；公网多人生产未验收”。
