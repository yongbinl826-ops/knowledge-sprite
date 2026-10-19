# Phase 3 隔离前端验收

此目录记录隔离 stage 的实现与验证，当前不表示已集成到主工程或真实模型/检索已经通过。主工程与 r9c 预览保持原状态。

## 展示合同

- “先学这些技能”只接收确认单元明确列出的 `learning_skills`，不从项目参数、验收条件或标题临时造目标。精确的 `skill_n`、原文、当前可见资源、匹配记录和汇总必须一致。
- “本课标题明确”是独立的入门线索级别。正文、目录或严格绑定同课笔记才标“内容有依据”。标题不升级为正文，检索摘要不升级为本课标题。
- 支持记录必须引用同一资源的唯一 Evidence，完整 Evidence.text 的 UTF-8 SHA-256、逐字引文、来源 URL 和字段 provenance 同时一致。FCC/TWT 继续使用原有严格视频与正文绑定；损坏摘要、跨页、重复 ID、待核实和隐藏平台不算支持。
- “带回项目练习”原样保留任务、具体参数与检查条件，静态提示“待自己实践”。不会因为找到课程而标成已学会，也不会因为项目练习未完成而称课程无价值。
- 历史版本无技能字段时保留缺省，不造技能；原项目要求明细折叠，实际 API 操作核心可作为本课标题线索单独展示。需要学生明确编辑才能新增技能。

## 验证边界

所有本目录浏览器用例使用本地隔离 mock API，Vite 5177 的代理目标是不可用回环端口 1，不会转发到主 8000。真实服务 smoke 保持 opt-in 并单列跳过。已有实际 HTML/API 派生 fixture 仅验证离线 source binding，既不是本轮新的 HTTP 成功，也不是播放/教学质量验收。

新用例覆盖两轴、标题与正文等级、平台筛选、损坏 SHA/错技能、历史 API 核心、编辑限制/保存、空结果、1440/768/390、键盘展开与来源链接、减少动态和可见文字对比度。旧安全/证据回归保留在 `project-coverage.spec.ts`，主动展开折叠的旧明细后继续验证原严格计数与损坏反例；旧 next-step 改为保留参数教学与项目实践边界。

截图已实际打开检查：`two-axes-{desktop,tablet,mobile}.png`、`source-title-expanded.png`、`historical-api-core-clue.png`、`editable-learning-skills.png`、`empty-materials-practice-retained.png`。

## 发现与修复记录

1. 初版内容下一步使用“右侧要求”，在窄屏上下堆叠后不准确。改为“按项目要求试做”，已随 focused 浏览器回归。
2. 完整兼容审阅发现历史缺省 `learning_skills` 被补成空数组，导致未修改直接确认误建版本。新增独立失败复现，保留 `legacy-default-before-fix.*` 与 trace。首轮完整回归有 49 通过、5 失败、41 未执行、3 真实 opt-in 跳过；5 个失败均涉及额外字段/版本。现已保留未编辑历史字段的缺省值，新增“直接确认仍为 v1、0 edit”回归与原技术字段、历史版本、三宽三步流程回归均已通过；首轮结果不算完整验收。

## 交付与待办

最终完整回归：96 个 mock 浏览器用例通过，3 个真实服务 opt-in 用例单列跳过；75 个 Node 用例通过；隔离 `tsc -b && vite build` 通过。最终没有未执行的 mock 用例、失败或 flaky。三宽无横溢，可见文字实测对比度不低于 4.5；键盘、减少动态与历史兼容通过。保留全部首轮失败记录。

最终 source/dist SHA、55 个受测 source/test/fixture/dist 文件清单、测试结果与主 49 文件保护核对以 `production-freeze.json`、`tested-manifest.json`、`qa-summary.json` 为准。最终 JS `index-bJsKPpvc.js` SHA-256 `1703e4dab5369ae47c3a720154c665490071542163b6c77c49070bb79c81cd5a`。Hidden Vite 的精确 PID/命令见 `vite-5177-process.json`。真实审阅/失败页和 r2 两例进度/终态已完成只读三宽复验，详见下文；实际教学内容覆盖仍未通过。

独立目录的测试命令：

```powershell
Set-Location -LiteralPath 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\tmp\phase3-work\frontend'
node --experimental-strip-types --test tests/*.test.mjs
npm run build
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_EXTERNAL_SERVER='1'
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:5177'
$env:QA_SOURCE_ROOT='C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2'
$env:QA_LIVE_SMOKE='0'
$env:QA_EVIDENCE_ROOT='tests/evidence/phase3/full-regression-final'
$env:PLAYWRIGHT_JSON_OUTPUT='tests/evidence/phase3/e2e-all-final-results.json'
$env:PLAYWRIGHT_OUTPUT_DIR='tests/evidence/phase3/e2e-all-final-artifacts'
npm run test:e2e -- --workers=1
```

浏览器插件当前不可用，本轮使用仓库已安装的 Playwright 与本机 Edge；没有新下载浏览器或依赖。`node_modules` 是 root 建立的现有依赖 junction，Vite cache 写入本 stage 的 `.vite-stage`。

## 候选 8010 真实只读检查

root 明确授权后，对 stage PID 26564、manifest SHA `25f7efaccb94a15a51c376265217450efd9f7881338608d96641de70d34c3558` 进行 GET-only 浏览器检查，实际 served bundle 与上述最终 SHA 一致。证据在 `real-runtime-8010-review/`，与 mock 报告分开。

- `e7da3936-e5ad-4211-84e7-3be271fc7613` v1：真实审阅页 7 单元，均有 2–4 条技能；三宽入口和展开字段截图、键盘 Enter/Tab、字段原文和概念保留检查通过。
- `3c339e7c-7f22-4aa5-aebc-3ac2f412d65c` v1：实际有界模型生成 `invalid_json` 失败后，三宽失败页保留原始项目名/需求，恢复按钮可用；没有点击重试。
- 0 非 GET、0 外站、0 浏览器 console/runtime 错误，初末 analysis/version/batches/confirmation 不变。没有直接访问数据库；不声称其他并发任务没有提交。
- 已实际打开桌面/平板审阅、手机技能字段、手机失败截图，未见新增明显 UI P1/P2。独立审阅发现 k6 无效 id 的恢复策略表述矛盾，已明确 `contentQualityAccepted=false`，不把界面渲染通过当作分析内容通过。

此 r1 节仅记录当时审阅/失败页，不代表后续 r2。两轮均没有由本浏览器代理发起确认、检索、模型或播放操作。

## r2 8010 实际进度与课程终态

最终报告：`real-runtime-r2/final-summary.json`。运行 PID **32436**；manifest SHA `3ff902df5c35411f9229b6d97e5633cd348cee4f7a81100408112e20708ae252`；served bundle 仍为上述 `bJsKPpvc` SHA。两个终态初末 API、原分析/版本/批次/job 绑定完整保存。

| 实际项目 | 版本 | 单元 | 声明且 DOM 逐项核对的技能 | 当前课程 | 内容级技能 | 仅本课标题线索 | 未确认技能 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 离线复习卡网页 | v3 | 7 | 14 | 1 | 0 | 1 | 13 |
| Arduino 电位器调节 LED 亮度 | v2 | 6 | 13 | 0 | 0 | 0 | 13 |

Arduino k1 为 **3** 条技能、k2–k6 各 2 条，API 与 DOM 一致；之前一条进度消息误写成 12，已核对更正，没有漏渲染技能。真实 Web running 仅保留初始 GET，浏览器加载态采用 Arduino 的 running 三宽截图，未把终态截图称作加载态。

- 桌面 1440、平板 768、手机 390：进度与终态无横溢，减少动态下动画/过渡停用；实际 Web 学习路线文字最低实测对比度约 **5.16:1**。
- Web k3 自身标题线索明确，未升级为正文；disabled 等技能仍未知，原参数/边界和项目试做保持“待自己实践”。键盘 Enter 可展开来源，Tab 可到安全外链，未打开平台。
- Arduino 终态 6 个空单元无等待动画或“等待材料”误导，全部学习目标保留，提示调整/重新检索；平台搜索链接明确“非已推荐视频”。键盘可切本地主题、展开旧明细。
- 实际预算、详情未核验、类型不明等警告保留并展开截图。0 非 GET、0 外部平台/封面网络请求、0 浏览器运行/console 错误。外部封面由浏览器拦截本地返回 204，截图中的封面 fallback 不用于判断实际 CDN 是否可用。
- 已打开桌/平/手机单元和卡片、Arduino 三技能空态、实际查找说明与 running 截图，未发现本轮新增明显 UI P1/P2。55 个 stage 受测文件、49 个主工程受保护文件均 0 SHA 漂移；未改前端 source/tests/dist。

这两例没有产生内容级支持。内容/目录/同课笔记正例只在隔离回归与保留来源夹具中通过，不能冒充此轮真实生产覆盖。因此 **推荐的教学覆盖尚未达到生产验收**；UI 正确表达不足不等于补齐课程。

追加实际游戏长文本抽查：`ec77f474-496a-4eb1-b5cc-ed0db4276ac3` Maze v7，`real-runtime-r2/maze-v7-length/report.json`。仅做 390px 窄屏单次检查，不重复整套尺寸回归；6 单元共 18 条技能逐条与 DOM 一致，最长单元（k2）的名称、技能、项目参数/练习均无内部或页面横溢；键盘可切主题、展开旧明细并 Tab 到平台搜索入口。初末 version/analysis/jobs 原样，0 非 GET/外呼/console/runtime。已实际打开 `mobile-longest-unit.png`，未见新明显问题。

后续仅等待 root 提供最终 8000 PID/manifest 后做部署绑定与关键流程简单复核；不会访问仍在运行的旧 8000 或主动创建业务任务。
