# 默认检索链路、证据边界与本地集成验收

最后核验：2026-10-19T18:07:04.050151+00:00。本轮改动已安装到 `D:\项目制知识引导小精灵`，本地预览为 <http://127.0.0.1:8001/>。GitHub 对应仓库 `yongbinl826-ops/knowledge-sprite`，Git HEAD 保持 `ccb306e099452cdeb8827720e5d9a44eff4ef8a4`，未提交、推送或部署到外网。

这是本地可运行、经过真实默认来源联调的交付。本轮没有证明全部项目和学生阶段均已达到生产内容验收：JavaScript 原目标仍缺足够匹配材料；Arduino 的具体框架／算法适配仍未知。软件回归、来源可用、主题证据、学生适配和项目完整覆盖分别报告，不能合并成一个“通过率”。本报告补充先前的 `docs/free-recall-followup-20261019.md`，保留所有原始失败、旧报告和旧交付包。

## 本轮实际检索与学生视角验收

分析输入复用此前真实模型分析，保留原专业知识点名称。本轮模型 HTTP 为 **0**；没有重新声称生成了整份项目分析。初始验收标准在运行前独立冻结于 `evidence/motion-free-recall-20261019/live-three-case-independent/`：有证据才算支持，复合目标逐项核对，未知不能补成完成，课程来源与学习者适配分别判断。

真实来源验收使用隔离的 C 合成数据库，采用原默认提供者路由与生产 Fetcher／调度／持久化／排序／API；为固定预算把 LLM_PROVIDER 设为 none、每 job teaching-match 模型名额设为 0、每选定平台 1 个来源名额、每新 job 2 个详情、搜索重试 0，job／project deadline 为 180／210 秒，关闭 stale／JS render／额外目录 fallback。C 候选备用选项显式开启但没有被选中。没有覆盖新的自动模型分析或教学模型判断，也不是原完整配置下的全项目重跑；D 的真实配置未更改。

| 原目标／项目 | 真实链路与观察 | 实际卡片（主要／部分／待核） | 学习证据与边界 |
| --- | --- | --- | --- |
| `localStorage读写与JSON序列化`／原生 JS 离线单词卡 | SearxNG B站 + Tavily MOOC；最终新任务 17.058 秒，24 候选、2 个自身页面抓取成功 | **0／0／0** | 两页没有同时明确的存储读写与 JSON 序列化依据。零卡不等于源故障；不以 Java／Coze／泛 JSON 介绍代替原生 JS 项目需求。 |
| `按键消抖状态检测`／Arduino 电位器灯 | 为预算明确将实际输入调整为 B站单平台；12.170 秒，12 候选、2 个自身页面 | **2／0／0** | 支持消抖／松手检测主题。CubeMX 来源不能据此声称已适配 Uno；非阻塞、稳定时间窗、millis、边沿实现仍未知。 |
| `pandas分组聚合`／骑行数据看板对照 | 实际输入为 MOOC 单平台；19.970 秒，2 候选、1 个自身课程大纲 | **1／0／0** | NJCIT 课程自己的项目 6／任务 1 明确分组聚合；是课程大纲正例，`video_evidence_status=none`，没有声称验证播放器。 |

可核对的实际入口：

- Arduino：[AV81335462](https://www.bilibili.com/video/av81335462/)；[BV13N411b7Gb](https://www.bilibili.com/video/BV13N411b7Gb/)（自身简介写明 CubeMX）。卡片的主题匹配不等于 Arduino Uno 实现已确认。
- pandas：[Python 数据处理课程](https://www.icourse163.org/course/NJCIT-1469574161)。返回真实课程 URL，自己的大纲支撑匹配；没有编造独立章节链接或时间戳。
- 先前独立来源的 [Vue P24](https://www.bilibili.com/video/BV183411B7nJ/?p=24) 仅支持 JSON 序列化部分；它与本轮新检索是不同观察，不能拿来替换本轮 0 卡或声称原生 JS／Vue 学习适配已证。

此前代表性集合还包括 Python 小游戏、不同熟练度的数据看板和网页／硬件项目；原模型分析与阶段失败保留在原验收资料中。本轮三目标不是上述全部知识点的一次新的完整生产通过。用户只要求跳转平台，未把自动播放验证作为门槛；登录、付费、报名或地区状态未知时保持未知，不将其称为无效链接。章节直链只在真实存在时提供。

## 修改和独立复核

1. 修复中英文连接处可选空格解析。`localStorage读写与JSON序列化` 与含排版空格的写法均能识别原文字面上的“读写”和“JSON序列化”。没有改名称、学生输入、知识粒度合同、证据阈值或 API 证据规则。旧真实 P24 在 compact 名称下恢复为仅序列化部分；本轮新 JS 材料仍为 0。
2. 增加显式可选的通用 SearxNG → Tavily 备用来源。`SEARXNG_FAILOVER_PROVIDER=tavily` 仅使用既有服务端鉴权和原有后续查询名额；默认空值。只有已观察的超时／不可用等失败可触发；真实空结果、验证码、拒绝访问或 Retry-After 强停不能触发。来源健康有效期 300 秒，恢复使用原观察时间，不续命；缓存、trace 按实际来源区分。
3. 独立审查发现发送竞态：选完备用来源后等待并发槽或提供者启动锁，原来源刚进入强停时仍可能外呼。已修为实际 request hook 预约 HTTP 前再次检查；阻止发送时 0 HTTP、0 预算预约，保留原强停原因，不改选其他来源。原 red 保留；最终独立 39 项边界／竞态均通过，其中 8 个已选源后强停场景均没有发送，timeout-only 正例仍能使用原有一个名额。
4. 真实 API 中的 pipeline 字段暴露了右侧误放进度文字的问题。已把检索进度、受限／空态说明和恢复操作移至左侧，右侧仅封面、骨架或图标占位。保留键盘聚焦、屏幕阅读器名称、减少动态效果偏好和现有转场。
5. 新名称解析测试的真实材料已裁成随工程携带的 74,551 字节公共夹具，含原始 receipt 路径／SHA 供核查；运行时只读相对夹具，不依赖本机 C 工作区。已在另一路径复制后通过同样 25 例。

本轮 SearxNG 的四次真实请求均 HTTP 200，**没有在线触发备用来源**。备用实现的验证是离线 MockTransport／状态边界测试，不冒充在线切换成功。原 `.env` 未改，8001 继续沿用既有默认来源和 B站／MOOC 并行策略。usage 辅助 receipt 中 `critic=true` 是遗留 raw flag；实际 professional 路径 `semantic_review_enabled=false`、`review_max_calls=0`，没有 critic 模型调用。

## 测试、浏览器和数据证据

| 检查 | 最终结果 | 证据性质 |
| --- | --- | --- |
| 合并后端全套 | **5,062 通过，0 失败／错误，0 跳过**，231.565 秒 | 离线工程回归；起止源码相同；不是课程推荐成功计数。 |
| 备用来源实现定向／独立复核 | 100 定向；39 独立边界／竞态 | 真正的提供者流程接 MockTransport；0 外部 HTTP、模型、SQLite 或 D 写入。 |
| 专业名解析 | red 9／16 → green 25／25，异地目录 25／25 | 真实裁剪夹具，原 red 与 test-only 可移植修订全部保留。 |
| 最终生产 GET 路由投影 | 3／3，compact JS 分解 applied；数量仍 0／2／1 | 最终代码读取本轮真实 C 合成验收 DB 副本，ASGI GET 不注入响应；源 DB 与 jobs/resources/evidence/matches/search_attempts 等原始表不变，0 新外呼。 |
| 真实 API 浏览器 | 3 案、1440／390 宽度、8 张截图；0 POST／重试、0 console/runtime 错误／横向溢出，右栏无可见文字 | 实际 8003 静态资源和 GET／SSE，无 API 响应注入；封面图片返回 204 测试占位，不代表实际图片或播放验收。 |
| 8001 首页与平板补测 | 6 张新截图；首页 1440／768／390，三案平板 768；无新错误或溢出 | 首页为实际 GET 未注入，不读取／保存学生项目列表内容；三案平板使用同实际服务的产物与最终 GET 原 JSON 精确字节回放，明确为响应注入，0 POST／外部传输。键盘封面聚焦与减少动态偏好通过。 |
| 前端定向与构建 | Node 127／127；20 定向浏览器例；tsc 与构建通过 | 冻结 75 个输入、8 个交付文件；原测试 ARIA 断言修订的 red 也保留。 |
| 8001 本地集成 | 15 个代码／测试／夹具／产物文件；52 个后端文件绑定 | 确认源与实际 HTTP CSS／JS 的哈希，health 与 ready；17 张学生表及行哈希、配置、Git 保护文件、旧静态资源保持；只重启精确核验的空闲 8001，8002 身份不变。 |

全套测试有 1 条现有 Starlette TestClient 对 httpx 的弃用提示；没有失败或运行错误，后续依赖升级时需处理。

最终后端绑定：`15ba1d2c23dd7ae7c4daadc18846f95a8785ab75a855fbaa1fef56a7d5356d4d`。

实际服务的静态产物：

- `/assets/index-C_asloTn.js`：SHA256 `0667e1df5d5e5f643f866617de12796f6927472d36d4b4f16a5413b876e0b6a3`。
- `/assets/index-DMPHqEVe.css`：SHA256 `fbb83b88124530a4953eedfa8d81e783168fffaff21bf66def9366bfac1fb8ec`。

视觉沿用工程已保留的三屏设计素材 `design/imagegen/2026-10-18-three-screens-v2/` 的暖白、石墨黑、电蓝、非对称布局、留白和细分隔线。本轮核对了推荐页设计图与实际桌面／手机图；右栏仅封面遵循用户后续方向。Awwwards、Webby、FWA 是视觉努力目标，未声称获奖。最终截图未发现新增明显高／中优先级界面缺陷；这不覆盖未观察页面、真实图片加载或平台播放。

关键截图（在工作区或增量包内按相同相对路径打开）：

- `evidence/motion-default-chain-20261019/frontend-final/real-controls-r4/readonly-browser_flashcards_intermediate-mobile.png`：真实 JS 零结果与恢复入口。
- `evidence/motion-default-chain-20261019/frontend-final/real-controls-r4/readonly-arduino_pot_button_beginner-desktop.png`：实际两封面布局。
- `evidence/motion-default-chain-20261019/frontend-final/real-controls-r4/readonly-arduino_pot_button_beginner-keyboard.png`：键盘聚焦后的证据说明。
- `evidence/motion-default-chain-20261019/frontend-final/real-controls-r4/readonly-cycling_dashboard_advanced_python-mobile.png`：实际 MOOC 对照结果。
- `evidence/motion-default-chain-20261019/frontend-final/tablet-and-served-r11/actual-homepage-768.png`：实际 8001 平板首页。
- `evidence/motion-default-chain-20261019/frontend-final/tablet-and-served-r11/retained-arduino_pot_button_beginner-768.png`：明确使用保存的最终 GET 响应的平板结果／键盘聚焦。

## 固定预算与失败归因

本轮新增 **6 次来源 HTTP = 4 SearxNG + 2 Tavily**，已耗尽本轮授权名额；两个 Tavily basic 响应各 usage=1，确认按 2 计费单位记录。调用前后 usage 均显示 researcher 67／1000、剩余 933，可能刷新延迟，不能据此声称零消耗。paygo_usage=0、paygo_limit=null；没有启用 paygo、改计费、创建凭据或扩大权限。项目累计日志为 22 次来源 HTTP（Tavily 14、SearxNG 8），确认 basic 用量 12，保留旧 2 次超时计费未知。模型 ledger 仍保留原 11 次尝试，SHA `9b27f30fa614700e38c7e201255705a1fcb80dea33f01150d903b1635416db4b`，本轮新增 0。

native 预算 24／DNS 48。本轮实际发出 7 次 native HTTP（含 robots），native 保守预约数 10，DNS 发出／预约 26。原 summary 字段 `native_HTTP=10` 记的是预约：其中 3 是首个边界失败保守保留值。两个早期尝试共 6 次 native 在连接前被验收守卫挡下，不是平台拒绝，也不是生产 Fetcher 的问题；第二次未增加 native 预约，DNS 均保留计入。没有重置账本或把预约冒充成功抓页。

早期验收还发生过测试项目／job deadline 相等而未发网、以及 root 守卫未正确识别生产 Fetcher 的 numeric-IP URL + 原 Host／SNI。均按精确原因保留原失败，修正测试边界并继续同一 6 次总预算。原 JS UI 仅一次真实重试到 v2，受守卫问题影响；最终 v3 是 root 的实际 edit→confirm→search API，不冒充第二次 UI 重试。旧终态 job、预算、attempt 和缓存 TTL 未清零、改写或复活。最终页面 GET-only，后续最终投影也没有新搜索。

## 运行、回滚和生产前置条件

当前直接打开 <http://127.0.0.1:8001/>。只有在现有进程已停止且端口空闲后，才可在项目目录使用原环境启动：

```powershell
Set-Location -LiteralPath 'D:\项目制知识引导小精灵'
& '.\.venv\Scripts\python.exe' -X utf8 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --workers 1 --no-access-log
```

`/health` 和 `/health/ready` 检查服务与配置；ready 不证明第三方当下可用。构建、输入校验、SSRF／DNS 固定／安全跳转、XSS、安全配置、并发／超时／重试／缓存／每任务和项目预算、队列与滥用控制、日志隐私、SQLite 持久化／迁移和恢复说明继续见 `README.md`、`docs/production-readiness.md`。本轮没有为这些既有检查新增真实外部调用。

本地更新前核对原文件和冻结来源 SHA、Git HEAD、17 表内容、精确进程命令与创建时间，确认 8001 空闲；备份只存命名的 Windows Temp 私有目录，位置由本地 `local-integration/prepared.json` 记录，不打包学生 DB 或私有日志。静态 immutable 资源先安装、index 最后原子切换，旧资源保留。若应用前失败则恢复已改源码；启动后的回滚应先核对当前 after SHA，精确停止本次 8001、恢复对应 before 源码／index，再启动原命令，不能覆盖用户之后的改动或还原旧学生 DB。8002 始终不操作。

剩余生产前置条件和精确边界：

1. 本轮 JS 原目标尚无足够课程内容证据；原 p24 只证明序列化，原生 JS 学生直接学 Vue 的 fit 未证。本轮检索名额已用完，未自行追加请求或模型消费。可交付诚实空态和重试入口，不能声称该学习目标已经完整覆盖。
2. Arduino 泛主题可用，但 CubeMX → Uno、稳定窗口、非阻塞等具体实现未知；按当前请求粒度没有编造支持。Pandas 是课程大纲支持，没有独立片段或播放事实。
3. 本轮只测每选定平台一个来源名额、每新 job 两个详情；没有以全部生产轮次／所有项目知识点重跑。备用来源仅离线触发验证，本轮真实 SearxNG 健康，所以既有 `.env` 保持原样、备用选项默认关闭。
4. 当前是单用户 loopback 架构。公开多用户生产发布仍需另行授权和真实部署环境的身份认证、用户隔离、HTTPS、密钥运维与负载验收；没有外网生产部署或 Git 推送授权，本轮未执行这些操作。

已修复本轮发现的可证软件 P2 并完成独立回归；未知学习适配、覆盖不足和外网部署前置仍如实保留，不以大量离线测试替代生产内容验收。
