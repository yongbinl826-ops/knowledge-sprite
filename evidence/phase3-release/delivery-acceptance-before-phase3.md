# 项目制知识引导小精灵：最终本地交付验收

已完成本地端到端实现、联调、安全与稳定性改进、五类真实项目验收、独立复核和原工程集成。**当前交付是经过验证的本地候选版；推荐内容覆盖未达到生产验收。** 31个学习单元均未完整覆盖，不能用测试数或视频数量代替内容质量。

## 工程、设计与运行

原工程为`D:\项目制知识引导小精灵`，远程`https://github.com/yongbinl826-ops/knowledge-sprite.git`，原HEAD`d4beb5df724d57f7b6e9dde2bb088e7a71f26fc6`。用户未提交修改保留。工作区为`C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2`。指定设计会话的三张原图、分镜与提示词已取得：`design/imagegen/2026-10-18-three-screens-v2/`；暖白、石墨、钴蓝、非对称排版、细边框、阶段导航构成统一系统。获奖站点只是品质参照。

预览：[http://127.0.0.1:8000](http://127.0.0.1:8000)。最终r9c进程PID34988，启动于2026-10-18 21:31:40 UTC，启动清单`evidence/phase2/runtime-r9c-manifest.json`。使用工作区合成验收库`data/preview.sqlite3`。没有Git推送、外网部署、购买接口、新凭据或权限扩张；原`.env`、SearXNG配置、学生库及Git HEAD/index受SHA保护。

核对并停止空闲旧预览后可以复现；不要直接重复启动占用端口：

```powershell
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' `
  'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\scripts\start_local_preview.py' `
  --source-env 'D:\项目制知识引导小精灵\.env' `
  --application-default-budgets --public-catalog-fallback
```

仅此进程覆盖搜索/详情预算30/40、启用有界公开目录；实际并发1、截止240秒。原12/12及关闭公开目录的配置未改写。普通`scripts/start.ps1`按原`.env`运行。停服核对PID、命令、创建时间、父进程及空闲状态；不向共享控制台发送中断。构建、配置、健康检查、备份及回滚见[运行边界](production-readiness.md)。

## 需求验收矩阵

| 要求 | 实现及证据 | 结论与范围 |
| --- | --- | --- |
| 项目名称＋需求分析 | 单元含项目子任务、目标、先修、概念、能力和练习；可选、可编辑和排序；背景缺失给可调整假设 | 五类已接受版本共31单元、30/30独立静态需求检查通过；不是首次生成成功率，不是学生代码或硬件执行验证。[学习验收](phase2-learning.md) |
| 学生阶段及具体任务 | 初学Web/Arduino、已有pygame基础、会Python/统计但首次pandas、Streamlit看板分别审查 | 避免通用Python基础替代项目技能；保留数值/状态/先修。看板加权指标有9行独立oracle |
| 原目标进入推荐 | `learning_targets`原文绑定、持久化、检索、缓存和恢复 | 原限定不被基础API替换；补充API核心不进入原完成数。[推荐合同](phase2-recommendation-contract.md) |
| 真实视频、来源与理由 | 安全URL、来源、标题、推荐原因；普通partial与review分开；时刻/章节仅用观察事实 | 最终28张partial均有页面视频身份，另2张review不计覆盖；身份不等于完整教学或播放验证。**内容门槛未通过** |
| 完整前端 | 输入、生成/取消、可恢复错误、审阅、先修确认、检索/取消、推荐、空态、重试新版本、历史只读 | 88浏览器用例、58 Node及TypeScript/Vite构建通过；3个明确opt-in live用例未混入离线通过数 |
| 视觉与可访问性 | 1440/768/390宽、键盘/焦点/语义标签、减少动态效果、对比度 | 实际Edge截图三宽无溢出；16点对比度最小5.33283:1；未做物理读屏器、Safari/Firefox实测。[前端验收](frontend-qa-phase2.md) |
| 安全与成本 | body/Host/Origin/输入校验、SSRF/URL/XSS、密钥只在服务端、超时/重试/队列/并发/限流/缓存、来源冷却、日志脱敏 | 本机单用户单worker；不当作多用户认证。锁定依赖当次公告查询无匹配 |
| 持久化及恢复 | SQLite backup/WAL、旧schema迁移、两独立进程重启、幂等恢复及历史读取 | 10项目37版本，两轮各74次历史读取200；完整性ok、外键错误0、真实外部调用0。[恢复演练](../evidence/recovery-phase2-r9-final/verification.json) |

## 真实检索与最终读取

最近一次真实检索是r8，每例一次确认/搜索、0新分析、0自动重试；原终态在`evidence/phase2-search-r8-*`，汇总`evidence/phase2/search-r8-terminal-summary.json`。r9/r9c只重读同一已完成job/batch、同一审核计划；不是新检索、没有新增模型调用、未验证平台播放。r9c读取前后同一只读SQLite连接`data_version`不变。

| 案例版本 | 单元 | r8真实终态秒 | r9c partial / review卡 | API有限线索some / none | UI正文目录some / none |
| --- | ---: | ---: | ---: | ---: | ---: |
| 骑行CSV分析v6 | 7 | 107.296 | 14 / 1 | 5 / 2 | 4 / 3 |
| pygame迷宫v6 | 6 | 106.401 | 2 / 0 | 2 / 4 | 2 / 4 |
| 番茄钟网页v5 | 7 | 126.118 | 5 / 1 | 3 / 4 | 3 / 4 |
| Arduino反应计时v5 | 5 | 85.482 | 3 / 0 | 1 / 4 | 1 / 4 |
| Streamlit自习室看板v2 | 6 | 112.624 | 4 / 0 | 2 / 4 | 2 / 4 |
| 总计 | 31 | — | 28 / 2 | 13 / 18 | 12 / 19 |

**两种some都仅表示部分子项，完整单元始终0。** 15单元有partial卡；有的只讲API使用核心，不能增加原目标完成数。CSV写出单元只有标题级有限线索，API可作partial，UI按正文/目录门槛保持0/9；原`index=False`、计数链、文件名和目录要求未知。不能把API13称为13个有正文支持的单元，见`evidence/phase2/data-csv-source-layer-review.json`。最终原始结果、SHA及每个未知项见`evidence/phase2-read-r9c/summary.json`、各例`project-results.json`、`evidence/phase2/final-content-gaps.json`。

登录、付费、地区和抓取限制如实保留，不误称失效链接；不编造章节、时刻或参数。独立修复包括具体API/focus-visible查询与详情优先、TWT有界系列发现和本课DOM/笔记/视频绑定、排除Streamlit单元中的Excel、作者音频/未来完整版提示、无本课视频身份网页降review。局部API原拼写使用核心不证明别名/参数；全源“不教学/仅演示”不能被补充路径恢复。r9c撤除仅以“显示文字”支持精确`pygame.font`的B站卡，保留同课明确`SysFont→render→blit`的TWT材料；`clock.tick`仍只支持限帧，不支持`get_ticks`或经过时间。

旧r6/r7/r8失败、首轮r9合成夹具合同失败、r9c开发定向失败完整保留，不改写成通过或相加；原真实来源不为测试改写。所选学习计划成本13次生成/修复/复核、67,485 total tokens；r8搜课关键词另31次、21,281 total tokens，usage均已知。最终只读阶段0新调用；这些是限定范围，非全部历史总成本。

## 最终冻结验证及截图

r9c工作区与D原工程**各3024 passed＋26 subtests passed，0失败/错误/跳过**，耗时73.75/72.94秒；144个Python文件两目录及测试前后逐文件SHA相同，树SHA`da47762bb51042092297d4a5b685b765f720a41c15bcf9b73046e32d225d18de`。仅1条既有Starlette/httpx弃用提醒。证据`evidence/phase2/final-r9c-dual-regression.json`、`backend-final-r9c.xml`、`d-original-r9c.xml`。离线回归不证明推荐教学完整。

前端49文件冻结，JS`index-BQdT_Xnf.js` SHA`74e6eaeedcc3a2f3348defaab80d15eb26415b8fc44237eb89368ae66d311c96`，CSS`index-Dp7JZzcL.css`。88/58及构建在`evidence/browser/phase2/api-core-copy/`；实际五例三步/三宽、历史scope和8单元特写在`runtime-r9/`，r9c定点重验在`runtime-r9c/`。旧r9b Maze截图保留作历史，不混称最终卡数。加载/错误/恢复等来自明确标注的离线网络夹具，真实终态单独记录。

- [项目输入](../evidence/browser/phase2/runtime-r9/terminal/bicycle_csv_advanced/desktop-project-input.png)
- [知识审阅（平板）](../evidence/browser/phase2/runtime-r9/terminal/study_room_streamlit_intermediate/tablet-knowledge-review.png)
- [真实推荐（桌面）](../evidence/browser/phase2/runtime-r9/terminal/bicycle_csv_advanced/desktop-actual-course.png)
- [局部材料与原目标未知（手机）](../evidence/browser/phase2/runtime-r9/semantic-boundaries/bicycle_csv_advanced/k3-mobile-learning-boundary.png)
- [最终精确字体支持与项目缺项（桌面）](../evidence/browser/phase2/runtime-r9c/semantic-boundaries/pygame_maze_intermediate/k4-desktop-learning-boundary.png)
- [最终字体课程卡（手机）](../evidence/browser/phase2/runtime-r9c/semantic-boundaries/pygame_maze_intermediate/k4-mobile-actual-material.png)
- [历史技术归属提示（手机）](../evidence/browser/phase2/runtime-r9/terminal/dashboard_history_v1/mobile-historical-scope.png)

最终`/health/live`、`/health`、`/health/ready`均200，队列/待分析/待检索0；ready只看配置和最近观察，不是实时上游探针。五例冷读最大2.538秒；九次顺序暖读均200、最大0.114075秒，见`evidence/phase2/performance-final-r9c-data-maze.json`，不是负载SLA。独立差异闭环见[最终独立复核](../evidence/phase2/final-r9c-independent-closure.json)；整合负责人亦实际打开最终桌面/手机字体图及平板审阅图，记录于`evidence/phase2/root-final-visual-review.json`。

源码同步按原始及本任务最新SHA核对、冲突即停、备份、原子替换，不复制凭据或原库。最终dist/保护检查见`evidence/source-integration-verification.json`，交付文件密钥匹配检查见`evidence/delivery-secret-audit.json`。最终双回归原HEAD/index、配置和数据未变。

## 剩余生产条件

**内容质量门槛失败，不是缺密钥而未测：真实模型、检索和来源取证已经运行。** UI口径19/31原路线没有正文/目录支持，12/31也仅部分、0完整。时间数据清洗、pygame网格/状态/胜负、Web计时/状态/交互、Arduino去抖/非阻塞计时、Streamlit筛选/加权汇总仍缺足够本课证据；已有API片段不能补齐项目要求。按父会话最终限制停止新增检索和业务模型调用，保留精确缺口供后续定向补充及真实复验，不能包装成全功能可生产。

公开生产还需明确授权及目标环境的认证/权限隔离、TLS与代理路径、配额/费用、持久化磁盘和备份保留/隐私政策、依赖安装及目标浏览器回归。本次未获外网部署授权、未尝试部署；不是部署被拒或结果未知。当前可交付范围是本地应用、源码、预览、截图及可追溯验收材料。旧主验收全文保留在`evidence/phase2/delivery-acceptance-before-final-r9c.md`。
