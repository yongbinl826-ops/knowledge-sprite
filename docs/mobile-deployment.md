# 手机模式运行、备份与回滚

## 配置边界

手机原生工程及本机数据见 [mobile-native.md](mobile-native.md)，接口和隐私边界见 [mobile-architecture.md](mobile-architecture.md)。原默认 `APP_MODE=legacy` 不变。手机后端必须显式 `APP_MODE=mobile`；这个模式不打开旧 `DATABASE_PATH`，旧项目/检索接口返回 404，没有把匿名手机流量接进旧的单用户项目库。

非秘密示例为 [deploy/mobile.env.example](../deploy/mobile.env.example)。不要将实际 `.env`、API 密钥、学生库、签名材料打进 APK、容器镜像或交付压缩包。服务端凭据由已有部署者单独配置，本次没有创建或扩大权限。

保持 `TEACHING_MATCH_ENABLED=true`、`PARALLEL_PLATFORM_SEARCH=true`。手机模式拒绝关闭这两个开关，不能用跳过教学匹配伪装成功。启动、健康检查、读取任务/课程不会主动调用模型。未配置模型/搜索时，课程库浏览仍可使用已有公共条目，分析/检索需向学生明确返回配置或来源不可用状态。

## 本地启动

在 Python 虚拟环境安装 `requirements.lock.txt` 后，从项目根目录运行：

```powershell
$env:APP_MODE = 'mobile'
$env:PYTHON_DOTENV_DISABLED = '1'
$env:MOBILE_PUBLIC_DATABASE_PATH = 'data/mobile-public.sqlite3'
$env:TEACHING_MATCH_ENABLED = 'true'
$env:PARALLEL_PLATFORM_SEARCH = 'true'
$env:LOCAL_ONLY = 'true'
$env:LLM_PROVIDER = 'none'
$env:SEARCH_PROVIDER = 'searxng'
$env:SEARXNG_URL = ''
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8017 --no-proxy-headers
```

此示例关闭 dotenv 自动加载且没有上游配置，仅用于本地结构和错误恢复检查，不代表真实分析能力已验收。若当前 shell 已有供应商环境变量，应在专用干净进程中启动；不要借示例意外沿用真实凭据触发费用。浏览器预览需要与其 URL 精确匹配的 `CORS_ORIGINS`，APP 原生来源使用 `MOBILE_ORIGINS`。

`/health` 用于内存任务工作器和公共库状态，`/health/live` 用于进程存活，`/health/ready` 仅说明配置及最近观察，不是实时上游探测。启动后应实读返回值，不把 HTTP 200 等同于视频可播放或教学适配。

## 公开运行前仍需的事项

1. 部署者提供 HTTPS API 地址，APP release 构建以 `VITE_API_BASE_URL` 固定该地址。前端内置本机资源，不能用 `server.url` 远程网页替代。
2. 确定反向代理、证书、精确 `ALLOWED_HOSTS` 和来源。直接服务保持 loopback；不要为绕过访问检查盲目设 `LOCAL_ONLY=false`、通配域名或信任任意转发头。
3. 本版本限流和运行中任务属于单进程；使用一个 worker。若可信代理转发全部请求，本地 peer 限额会保守地成为所有客户端共享限额。部署方需在可信入口完成真实来源的公平限流；本版本不把客户端自行提供的 `X-Forwarded-For` 当身份。
4. 按实际供应商预算调整全站每日预留上限。预留是防滥用的最坏情况额度，不是账单；失败/取消不返还，UTC 日期切换恢复每日额度。上游密钥配额/金额上限由供应商控制台作为额外边界。
5. 在已获授权的真实接口上验证项目分析及 B 站/MOOC 检索，明确登录/付费/地区限制，不以 mock 数据替代。当前阶段没有新增付费模型请求。
6. 原生构建、真实手机或模拟器安装启动、系统返回键/安全区域/外部浏览器跳转、平台签名及商店隐私材料分别验收。没有 SDK/JDK 或签名时应停在对应前置条件。

本次不修改系统网络/安全设置、不部署外网服务、不购买 API、不创建签名凭据、不推送 Git。

`MOBILE_DAILY_DETAIL_HTTP` 的计数口径为详情目标页面和 robots 的原生 HTTP：每详情槽保守预留 `4 页面重定向跳 × (1 页面 + 4 robots 跳) × 2 尝试 = 40`。目录补页也占详情槽；手机模式关闭 JS 渲染。默认系统 DNS 没有 DoH HTTP；若部署者另启用 DoH，每原生请求还可能有 A/AAAA 各一次、至多两次 DoH HTTP，因此总体网络请求上界可按此部分的三倍评估。这个字段不应被描述为包含 DNS、搜索供应商和模型在内的所有请求或真实费用。模型按最多两次分析、非技能检索每点两次、含技能检索额外判定/复核额度保守预约；混合技能与空平台列表也纳入上界。

## 数据和回滚

旧数据文件不迁移、不覆盖。手机模式的公共 SQLite 是新增独立文件，仅公共课程白名单字段和 UTC 聚合预算。临时个人处理数据只在 RAM，服务端重启会结束任务；手机保留原有本机数据并提示由用户明确重试，不能自动重新消费模型额度。

公共库离线备份应使用 SQLite backup API 形成一致副本，校验 `PRAGMA integrity_check`；恢复时先停单实例，再恢复经过校验的公共库副本。不要直接复制正在写入的 WAL 数据库单文件。公共库可从经过验证的课程事实重新积累；预算备份回滚可能降低当天已预留计数，恢复时应维持当天额度的保守上限，不能靠回滚重置额度。

专用脚本只接受带 `.mobile-public` 标记、正确应用 ID 和 v1 白名单表/字段的公共库；未知旧库会在打开 SQL 之前拒绝，目标必须为新文件：

```powershell
python scripts/backup_mobile_public.py --source data/mobile-public.sqlite3 --destination backups/mobile-public-20261020.sqlite3
```

目标父目录由操作者预先建立，数据库与同名 `.mobile-public` 标记一起保留。脚本不覆盖已有备份，失败产物不标记为可恢复库。本次备份测试均使用临时合成数据，没有打开实际学生库。

代码回滚使用本次按文件清单保存的原件，并先停止对应实例；该工具只回滚代码和公开资产，不回滚数据库。手机模式的个人处理状态在 RAM，停止后失效，新公共库仍保留。手机记录不删除，也不改写原有学生历史。

本次专业概念检索会给新的 legacy 检索任务保存 `topic_technologies`。旧 r16 的严格请求读取器不能读取该新增非空字段。因此，一旦旧 Web 模式已经写入新格式任务，不能直接将旧 r16 代码覆盖在该库上运行，也不能删除技术语境或改写历史来伪装兼容。应使用保留新字段读取兼容性的修复版本前进恢复，或先验证兼容读取器；文件恢复成功不等于数据库降级通过。本次没有打开真实学生库进行降级试验。设备存储迁移同样必须保持向前兼容或有可恢复副本，不提供用户数据导出/导入入口。
