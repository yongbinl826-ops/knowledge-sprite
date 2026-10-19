# 项目制知识引导小精灵：2026-10-19 本地候选交付

已完成实现、前后端集成、原工程同步、本地预览、自动回归、真实来源审核与恢复演练。**可交付程度为本地候选；两个核心功能尚未达到生产内容验收。** 自动分析仍有真实质量失败，推荐材料对关键技能的覆盖不足。测试数量、HTTP 200、目录链接和人工修正不能代替生产通过。

## 工程、设计与运行

原工程 `D:\项目制知识引导小精灵`，origin `https://github.com/yongbinl826-ops/knowledge-sprite.git`，HEAD `d4beb5df724d57f7b6e9dde2bb088e7a71f26fc6`。源代码与构建已同步；以SHA基线检查、备份后更新，原未提交内容、`.env`、SearXNG配置、学生数据库及其WAL/SHM、Git HEAD/index均受保护。没有Git推送、外网发布、购买接口、新凭据或扩大权限。

指定设计会话的 [三屏、分镜及提示词](../design/imagegen/2026-10-18-three-screens-v2/) 已实际取得；实现暖白/石墨/钴蓝、非对称两栏、大字号、细线和三步导航。获奖网站是努力目标，没有声称获奖。[最终视觉复核](phase3-visual-review.md)。

预览：[http://127.0.0.1:8000](http://127.0.0.1:8000)，PID **35292**，**2026-10-19 00:32:47 UTC**启动。运行目录是 `C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2`，新库为 `data/preview-phase3.sqlite3`；旧 `data/preview.sqlite3` 保留，D原学生库不用于预览。[运行清单](../evidence/phase3-release/main-runtime/runtime-manifest.json) 绑定44个后端文件和3个构建文件。JS `index-MmM5Tg-A.js`，SHA `ec1f6343bab646034aa4da91b21981d0248b6799f7effa7669ed520bd702d88a`。工作区、stage、D构建相同，[源码与保护核验](../evidence/phase3-release/final-source-verification.json)。临时8010已核验空闲并停止。

服务已运行，不要重复占用端口。重启前核对PID、绝对脚本、创建时间、父进程、监听归属与队列空闲，再停止该实例；随后：

```powershell
Set-Location 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2'
& 'D:\项目制知识引导小精灵\.venv\Scripts\python.exe' -X utf8 `
  scripts/start_local_preview.py --port 8000 `
  --source-env 'D:\项目制知识引导小精灵\.env' `
  --database-name preview-phase3.sqlite3 `
  --application-default-budgets --public-catalog-fallback
```

只在进程内读取已有服务端配置。预览使用30次搜索/40次详情/240秒总时限、单worker、有界公开目录发现，没有改写D原配置预算。[配置、安全、部署和回滚](production-readiness.md)。

## 需求验收矩阵

| 要求 | 实现与证据 | 结论与范围 |
| --- | --- | --- |
| 项目名称+需求生成学习单元 | 可选择/编辑/排序；子任务、目标、必要先修、概念/技能、学后能力与练习保留；每单元生成2–4技能，可编辑至6项；缺背景用可调假设 | 功能完成，自动分析稳定性未通过；不能把人工修正当首次自动成功 |
| 适中粒度及阶段适配 | 初学Web/Arduino、中级pygame、已有Python/统计但新用pandas/Streamlit；按子任务与方法学习，不拆变量，也不只给通用入门 | 独立审阅50单元/122技能/45关键方法组；不是学生实做或硬件实验 |
| 真实视频与推荐原因 | 原平台链接、标题、原因、来源；自身原文/引用/全文哈希/当前技能/原生章节身份联合绑定；标题主题、内容依据、未知分开 | 证据门完成，关键技能推荐效用未通过；登录/付费/地区限制不等于链接失效，未声称自动验证播放 |
| 完整前端 | 输入、加载/取消、可恢复失败、审阅调整、检索、部分/空结果、重试、明确下一步、历史只读 | 104浏览器通过、3个opt-in live跳过；最终真实主服务27张步骤截图 |
| 视觉及可访问性 | 响应式、Enter/Tab、步骤焦点到h1、语义展开/状态提示、减少动效、溢出检测 | Edge1440/768/390通过；本轮配色测量最小5.1599:1；未实测屏幕阅读器、物理真机或Safari/Firefox |
| 安全与运行边界 | 输入/body/Host/Origin、SSRF/URL/XSS、密钥服务端、限流/并发/预算/缓存/故障降级、日志脱敏、健康 | 同一源码两测试目录3687测试及26子测试通过；本机单用户保护，不提供外网认证 |
| 持久化与恢复 | 一致备份、原历史保留、WAL、旧归属迁移、中断恢复、重启幂等 | 14项目/64版本，两独立进程各128历史API读取200，完整性ok、外键错误0、真实外部调用0 |

## 独立质量验收

八例先冻结准则，再审计划、来源与学生适配：[独立矩阵](../evidence/phase3-audit/final-teaching-quality-matrix.r3.md)、[逐技能证据](../evidence/phase3-audit/final-teaching-quality-matrix.r3.json)。允许多门课互补和不同示例迁移，没有要求单视频复刻整个项目。下表是保留的 **r3基线**，不能用后续局部修复重新算为八例通过。

| 项目/背景 | 单元/技能 | r3独立效用 |
| --- | ---: | --- |
| 单车CSV；已有Python/统计，首次pandas | 7/14 | failed |
| pygame迷宫；中级 | 6/18 | partially_useful |
| 番茄钟网页；初学 | 7/16 | partially_useful |
| Arduino反应计时；初学 | 5/15 | failed |
| Streamlit自习室看板；中级 | 6/16 | partially_useful，仅计划有用、材料效用0 |
| 浏览器复习卡；初学 | 7/14 | failed |
| pygame双人乒乓球；中级 | 6/16 | failed |
| Arduino电位器LED；初学 | 6/13 | failed |

合计 **0 accepted_useful、3 partially_useful、5 failed**。最后批准的8份计划3份自动、5份人工修正；首次phase3分析仅2例无人工修正即独立接受，4例需修正、2例没有可用计划。r3显示12张唯一卡，6张语义越界；其余仅有限方法线索，45关键组均未达到完整材料适配。机器计数包含坏声明，不能作为人工覆盖验收。

已修复：泛DOM事件不再推成具体click；数值映射简介不能补出整数截断；LED简介不能补出极性/电阻完整教学；Pong后段 `get_pressed` 不再被观察窗口漏掉；Scoring进入真实判断批；原生分P必须绑定同BV、页号、原目录JSON和自身原文；失败哨兵/旧复核/来源变化不能在GET复活支持。原输入与项目练习保持。[质量说明](phase3-recommendation-quality.md)、[教学合同](phase3-recommendation-contract.md)。

### 修复后四个有限真实回归

| 回归 | 真实结果 | 未证明的部分 |
| --- | --- | --- |
| 新番茄钟，analysis v3.3 | 两生成+两复核均200/JSON，最终quality失败；未保存坏草稿，原输入保留 | 自动分析稳定可用。未留拒绝草稿，无法独立重建每项模型诊断 |
| Arduino v4 | 0主推荐；实际送审的旧LED/映射声明退为未知 | Mixly未实际送审，不能列真实负例通过；关键硬件方法仍缺材料 |
| Web复习卡 v5 | 0主推荐；泛事件不再变成click支持 | DOM完整技能已有材料 |
| Pong v4 | 1条TWT get_pressed自身代码支持；clamp/dt未知 | Scoring已送审但留下失败哨兵，缺逐项响应/应用trace，准确失败阶段未知；不能解释为无来源 |

这一轮15次真实模型调用（9初判+2声明复核+2分析+2分析复核），usage **107906 tokens**，均HTTP200/JSON，**不代表质量通过**。与r3最终29次/185698 tokens及此前累计范围分开记账：[来源与调用账本](../evidence/phase3-audit/r4-final-source-and-call-ledger.md)、[新分析失败复核](../evidence/phase3-audit/r4-analysis-repair-outcome.md)。没有重复运行直到变绿。

随后只改GET目录分配与学生文案，未再调用模型/检索：有界按技能轮转、原生URL去重；当前point合法复核并重绑的同job来源仅可补充目录线索，失败/陈旧/跨源拒绝。Ar真实analogWrite p26恢复，Web泛DOM章节撤除。**最终显示** Ar：0卡/7线索/13未知；Web：0卡/4线索/14未知；Pong：1卡/2线索/1内容技能+15未知。线索始终0覆盖，原项目练习未完成。[主服务三例](../evidence/phase3-release/final-main-get-verification/verification.json)、[八例只读回归](../evidence/phase3-release/final-eight-get-verification/verification.json)。只读重算既有版本不算新的真实搜课或完整生产重验。

最终八例当前读取合计1张主要卡、23条目录线索、1个内容技能/121个未知；其余五例没有用新版再实际搜课。旧结论在新绑定合同下未知，不能倒推平台没有课程。目录课题线索也可能较弱，需继续审查技术和阶段适配，不能把零覆盖标记当作相关性通过。

## 最终验证与截图

原工程两个pyproject测试目录分别执行，241个Python文件起止SHA及工作区/D逐文件相同：`tests` **3568通过**（79.733秒），`backend/tests` **119测试及26子测试通过**（11.467秒），合计 **3687测试及26子测试通过，0失败/错误/跳过**。既有Starlette/httpx弃用提示保留。[主测试](../evidence/phase3-release/d-original-final-regression/backend.xml)、[适配器测试](../evidence/phase3-release/d-original-adapter-regression/backend.xml)。先前阶段与失败证据保留，不相加、不冒充当前验收。

前端 **104通过、3个显式opt-in live跳过、0失败/不稳定；109 Node通过**，TypeScript/Vite构建通过。57源/测试/配置文件+3dist冻结；隔离QA仅Vite缓存目录名称不同，最终构建一致，差异如实列入源码核验。加载/空/错误/取消/恢复/成功/历史、过滤、篡改、原生分P与XSS在离线API夹具中验证。[前端离线证据](../evidence/browser/phase3-topic-pointers/qa-summary.json)。

最终实际Edge：3项目×3步骤×3宽度=27步骤截图，0业务写请求/外呼/控制台或运行错误，input/analysis/version/jobs保持。[浏览器汇总](../evidence/browser/phase3-final-runtime/summary.json)。封面请求在本次测试以本地204限制，未证明封面在线可用；未跳转平台或检验播放。

- [项目输入](../evidence/browser/phase3-final-runtime/pong-v4/desktop-step1.png)
- [知识审阅](../evidence/browser/phase3-final-runtime/pong-v4/desktop-step2.png)
- [推荐路线](../evidence/browser/phase3-final-runtime/pong-v4/desktop-step3.png)
- [真实get_pressed卡](../evidence/browser/phase3-final-runtime/pong-v4/real-get-pressed-card.png)
- [Arduino p26目录线索](../evidence/browser/phase3-final-runtime/arduino-v4/k5-topic-pointers.png)
- [手机审阅](../evidence/browser/phase3-final-runtime/pong-v4/mobile-step2.png)

恢复演练保留了 [初次30秒超时失败](../evidence/recovery-phase3-final/verification.json)。产品源码、API/模型超时及全部恢复断言未改，仅离线128次历史读取的子进程等待改为120秒；实际两进程 **36.424/34.349秒**。在线备份2.485秒、还原3.200秒；78条legacy归属迁移，所有阶段完整性ok、外键错误0，第二次重启幂等。[最终恢复](../evidence/recovery-phase3-final-128-reads/verification.json)、[预算解释](../evidence/recovery-phase3-final-128-reads/harness-budget.json)。这是单机观察，不是并发SLA或供应商证明。

## 仍开放的生产阻碍

1. **分析质量和推荐效用**：新analysis v3.3仍真实失败；首次自动接受率不足，多个关键技能没有已确认材料。拒掉坏声明不能替代好材料。需改善生成/复核一致性、内容召回及跨语方法判断，再用冻结的新项目集独立验收。
2. **部分故障缺少逐对定位**：Scoring有合法来源且送审，却只留响应哈希/失败哨兵，不能猜原响应。后续需有隐私边界的逐对错误诊断；保守必要成分门也可能误拒复合/跨语同义材料，需衡量误拒和效用。
3. **外网部署未授权、未尝试**：仍需目标环境、认证/权限隔离、TLS、供应商配额/条款、持久化磁盘/备份/容量、隐私与保留政策及目标环境回归；没有“部署已成功”或“部署被拒”的结论。

界面未发现未解决的明显高/中优先级缺陷；核心教学质量阻碍仍在，**不能宣布整体验收或生产就绪完成**。源代码、预览、真实失败、独立矩阵、运行绑定、恢复和回滚材料已交付。上一版主交付全文保存在 `evidence/phase3-release/delivery-acceptance-before-phase3.md`。
