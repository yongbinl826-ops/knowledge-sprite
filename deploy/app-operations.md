# 单机应用部署模板

本模板面向 **Linux 本机、一个操作者、一个应用进程、本地磁盘 SQLite**。没有加入账户、外网入口、多人隔离或 TLS 身份方案；不能由这些模板或离线测试推导公网多人可用。Windows 保留项目原有 `scripts/start.ps1`。Docker Desktop 只有在操作者已经启用并验证 host networking 时才能考虑本模板；普通桥接部署不适用，不能为连接方便关闭 `LOCAL_ONLY`。

## 已核实的代码边界

- 旧 `compose.yaml` 只有 SearXNG 服务，没有应用镜像、应用数据卷、应用资源上限或应用健康检查。
- `backend/app/security.py:RequestSecurityMiddleware` 在 `LOCAL_ONLY=true` 时校验实际客户端必须为 loopback。桥接容器即使只向宿主 `127.0.0.1` 发布端口，应用仍可能看到桥接地址并拒绝。这里用 Linux `network_mode: host`，应用固定监听 `127.0.0.1:8000`，保留原校验；未使用代理头伪装本机地址。
- `backend/app/main.py:create_app` 在 lifespan 打开 Store、启动单队列 worker，并从 `frontend/dist` 同源提供页面。Store/ProjectStore 在启动时执行兼容建表和恢复；多 worker/多副本不在支持范围。主工程本轮新增的数据库生命周期锁必须与数据库一起保存在同一个持久化卷，运行和崩溃恢复时均不得手动删除锁文件；不能通过提高 Uvicorn worker 数或另开副本扩容。这里只备份 SQLite 文件，不把锁文件当作数据库进行备份或还原。
- `/health` 检查 SQLite 和 worker；`/health/ready` 另含检索/模型配置与最近观察。后者不调用上游，也不证明账号余额、真实课程召回或播放。本镜像 Docker healthcheck 使用 `/health`，避免未配置模型时无限重启；上线验收必须单独检查 ready 和两项核心功能。
- `pyproject.toml` 要求 Python 3.13；`requirements.lock.txt` 包含固定版本和包哈希。前端有 `package-lock.json`，Node 24 满足该项目声明的版本范围。

这些文件是可检查的候选模板。本轮没有 pull/build/up、改 Docker daemon、修改系统网络、读取实际 `.env`/SearXNG 私有配置或部署到外网。基础镜像标签仍需在目标环境拉取并固定为审核过的 digest；镜像构建、Linux 权限、目标机器重启恢复和真实供应商功能尚须实测。

## 构建与配置

1. 将应用源码和本模板作为同一受控版本，先执行工程的后端、前端测试。保留前一版源码/锁文件/前端产物/镜像标签和数据库备份。不要把任务 evidence 或学生数据作为构建上下文。
2. 在目标 Linux 主机核对 Python/Node 基础镜像与架构，设定经审核的 `NODE_IMAGE`、`PYTHON_IMAGE` digest，再构建：

   ```sh
   docker build --build-arg NODE_IMAGE='node@sha256:REVIEWED_DIGEST' \
     --build-arg PYTHON_IMAGE='python@sha256:REVIEWED_DIGEST' \
     -t knowledge-sprite-app:RELEASE .
   ```

   占位符不是实际 digest，不应直接执行。默认可变标签仅为开发构建入口，不是已验证的供应链锁定。Python 安装使用包哈希校验，`npm ci` 使用原锁文件；任何安装失败应停止，不能临时去掉锁或换未知镜像源。前端在 builder 构建，运行镜像没有 Node/浏览器。JS 渲染功能由模板明确关闭；需要它时应单独审核镜像和浏览器隔离，不能只改 flag。
3. 非秘密参数使用 `deploy/app.env.example` 的副本（例如主机外部的 `/srv/sprite/config/app.env`）。这是新示例，不复制实际项目 `.env`。按已有授权选择来源/模型及费用上限；默认模型不配置、来源不替你创建账号或选择备用源。`TEACHING_MATCH_ENABLED=true` 与并行来源保留。示例每批 30 搜索、40 详情、并发 2、0 搜索重试，未扩大原全局边界。真实限流/验证码仍由应用停止，不因重建容器绕过。
4. 三类现有 API Key 使用 **独立文件**，格式见 `deploy/app-api-keys.env.example`，放在仓库之外。目标 Linux 主机必须让容器 UID/GID 10001 可以只读访问挂载文件，同时禁止其他用户读取；例如由管理员设为 `root:10001`、模式 `0640`。若操作者本身就是 UID 10001，也可用其自有 `0600` 文件。普通 Compose 的文件型 secret 是 bind mount，不能假定 YAML 中的 uid/mode 会替你改好宿主文件权限；错误权限会安全地启动失败。上述权限操作必须由目标机器操作者审阅，本轮未执行。不在命令行、构建参数、前端变量、Git 或日志中填写 Key。该文件由 Compose secret 挂载，entrypoint 只接受三个 Key 名称、禁插值并限制大小；容器启动后只在进程内设置环境。容器管理员仍可读取进程内存/环境，这不替代主机访问控制。

   ```sh
   export APP_IMAGE=knowledge-sprite-app:RELEASE
   export APP_CONFIG_FILE=/srv/sprite/config/app.env
   export APP_API_KEYS_FILE=/srv/sprite/config/app-api-keys.env
   docker compose --env-file deploy/app.env.example -f compose.app.yaml config --quiet
   docker compose --env-file deploy/app.env.example -f compose.app.yaml up -d --no-build app
   ```

   上述命令是供操作者审阅的运行方式，本轮未执行。`--env-file` 显式使用公开示例，避免 Compose 自动读取工作目录的 `.env`；实际秘密文件不会成为镜像层或 Compose 环境插值参数。不要把完整 `docker compose config` 输出贴到共享日志，特别是自行改用环境变量传 Key 时。

5. 已有、经授权的本机 SearXNG 可用其原公开端口。仅在原搜索配置已由操作者独立准备好时，用已有 `compose.yaml` 和额外 overlay：

   ```sh
   docker compose --env-file deploy/app.env.example -f compose.yaml -f compose.app.yaml \
     -f compose.app.searxng.yaml up -d --no-build app
   ```

   这不会生成/改写搜索 secret；既有设置的审核和配置要求保持。`service_started` 不保证上游引擎健康。若端口已被原实例占用，停止并核对归属，不能杀掉未知实例或启动第二套冒用旧数据。搜索独立失败不等于应用基础设施失败。

## 运行和隐私

访问 `http://127.0.0.1:8000`。应用固定单 worker、禁代理头、禁访问日志；非 root UID/GID 10001，根文件系统只读，仅数据/备份卷和 64MiB 临时目录可写，drop 全部 capability，禁止提权。Compose 设 1 CPU、1GiB 内存、128 PID、30MiB 日志轮转和 SIGTERM 45 秒窗口；示例限制同时打开的 SSE 连接为 `MAX_EVENT_STREAMS=16`，超限由主工程返回 429/Retry-After 并在关闭时释放。它们是初始单机上限，未经过负载 SLA 验证；OOM/磁盘满必须按任务状态和日志处理，不能靠盲目提高并发增加费用。

本轮主工程的启动恢复应把遗留运行任务标记为 interrupted 并停止挂起项目，不自动续发付费/搜索调用；用户通过原有重试流程明确发起。部署模板不提交任何分析或搜索请求。该行为必须在最终集成源上回归，不由 healthcheck 200 推断；目标 Linux 中断/重启尚未实测。

`app-data` 保存 SQLite 与 WAL，`app-backups` 单独保存备份；named volume 首次从镜像继承 UID 10001 的目录权限。若使用既有或 bind volume，应先由目标主机管理员核对文件属主和本地磁盘，不在本模板里 root 自动 chown 用户数据。SQLite 不放 NFS/跨机共享文件系统。不要执行 `docker compose down -v`。

健康检查可以在容器内运行：

```sh
docker compose --env-file deploy/app.env.example -f compose.app.yaml exec -T app python /app/deploy/app-healthcheck.py
docker compose --env-file deploy/app.env.example -f compose.app.yaml exec -T app python /app/deploy/app-healthcheck.py --ready
```

探针仅访问固定 loopback、禁代理和重定向、限制响应大小；只输出状态，不输出响应或配置。默认无模型的 `--ready` 返回非零是诚实的未配置。观察 `docker compose logs --tail 100 app`，只保留脱敏路由/状态/异常类型；不要加 `--access-log` 或供应商 debug body。应用 SQLite 保存学生输入、历史与证据，备份同样敏感；保留期限/离线加密/磁盘余量/备份访问权由实际操作者制定，本模板不自动删除历史。

## 备份、迁移演练与回滚

先停止接受新任务，等待任务终态，记录版本、镜像、非秘密配置和备份文件名。运行中的一致快照用 SQLite backup API；不要直接复制活动 SQLite/WAL，不用 `immutable=1` 忽略 WAL。备份源以 `mode=ro` 打开，目标必须是新文件，完整性与外键校验失败会停止。单次 backup 有 30 秒期限，失败新文件会清理，不覆盖旧备份。

```sh
docker compose --env-file deploy/app.env.example -f compose.app.yaml exec -T app \
  python /app/deploy/app-backup.py backup --snapshot before-RELEASE.sqlite3
docker compose --env-file deploy/app.env.example -f compose.app.yaml exec -T app \
  python /app/deploy/app-backup.py migrate-copy --snapshot rehearsal-RELEASE.sqlite3
```

`migrate-copy` 仅在新备份副本上打开 Store/ProjectStore，演练建表/兼容迁移和完整性；不启动队列、不中断源任务、不调用供应商。它不证明旧应用可读取新 schema，也不替代包含旧项目和中断任务的完整恢复脚本、目标运行环境验证及核心真实流程验收。默认脚本只输出新文件名、SHA、表数和状态，不输出学生行。

回滚时只停止本应用，保留搜索服务和故障库：

```sh
docker compose --env-file deploy/app.env.example -f compose.app.yaml stop app
docker compose --env-file deploy/app.env.example -f compose.app.yaml run --rm --no-deps --entrypoint python app \
  /app/deploy/app-backup.py restore --snapshot before-RELEASE.sqlite3 --database rollback-RELEASE.sqlite3
export APP_DATABASE_PATH=/var/lib/knowledge-sprite/rollback-RELEASE.sqlite3
export APP_IMAGE=knowledge-sprite-app:PREVIOUS_RELEASE
docker compose --env-file deploy/app.env.example -f compose.app.yaml up -d --no-build app
```

恢复到不同的新文件名，原故障 DB/WAL 和备份均保留；已有目标文件会被拒绝。只在同一时刻运行一个版本，禁止双写。使用发布前备份会失去备份后新增数据，应先让操作者明确损失范围。对上一版镜像执行 `/health`、`--ready`、旧项目/历史读取，再按已有授权验证关键流程。不要在回滚时重新生成学生分析或无授权新增付费调用。

## 本轮验证的边界

便携测试覆盖模板约束、loopback/来源/路径预检、固定单 worker 命令、secret 格式和脱敏、健康探针的大小/重定向边界、活动 WAL 的一致备份、未提交行排除、拒绝覆盖、恢复到新文件及仅副本迁移。Compose 可做本地语法展开；不连接 Docker daemon。不把这些离线证据称为已成功构建/运行容器、已验证上游或公网生产就绪。目标镜像构建及 digest、Linux 权限/host networking、单实例锁、真正停止/重启、当前库恢复和用户核心质量验收仍是发布前条件。
