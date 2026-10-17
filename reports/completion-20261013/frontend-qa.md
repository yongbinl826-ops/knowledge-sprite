# 前端验收与冻结记录 · 2026-10-13

结果：最终 Edge E2E **28/28 通过**，0 跳过、0 重试后通过；生产构建通过。前端源码与 dist 已冻结。本报告仅证明隔离 API fixture 下的前端行为，真实后端与外网固定批次由总验收另行记录。

## 环境与隔离

- Windows；Node 24.14.0 / npm 11.9.0；Edge 155.0.4283.45；项目现有 Playwright 1.64.0，`PLAYWRIGHT_CHANNEL=msedge`。Playwright 项目名称仍为 `chromium`，实际启动 Edge。
- 页面 `http://127.0.0.1:5173/`，标题“项目制知识引导小精灵 · 课程与视频发现”。桌面 1536×1024，手机 390×844。
- 此会话未提供技能指定 Browser 插件，使用现有 Playwright 完成测试；无需安装浏览器。后续若要使用该插件工作流，可选择安装 Browser 插件。
- 每项测试默认阻止未匹配的 API 与外部 HTTP 请求，再由各项 fixture 精确覆盖；静态前端文件可访问本地 Vite。最终 28 份浏览器诊断记录显示未匹配请求 **0**、未捕获运行时异常 **0**。没有调用真实搜索、外部课程页面或正式数据库。

## 本轮完成

| 流程 | 实现与证据边界 |
| --- | --- |
| 任务取消 | 使用后端 cancel API；防止重复点击；返回确认前不冒称取消成功；cancelled 为终态并停止轮询、保留结果。失败保持“未确认”，自然完成竞争保留原终态。 |
| 重复创建与刷新恢复 | 每次逻辑提交生成 Idempotency-Key；超时/网络失败重试沿用原 body/key。未确认的 body/key 存于当前标签页 sessionStorage；刷新后展示原需求，用户点“继续上次未确认提交”可恢复已经结束的原任务；有效 job ID 才清除。不同需求/清除后新提交使用新 key。清除入口不取消任务。 |
| 请求生命周期 | 15 秒超时；AbortController 中止旧轮询、卸载请求与失败 Promise.all 的兄弟请求；generation 防止迟到响应覆盖新任务。React StrictMode 双 effect 情况已覆盖。 |
| 课程与讲次身份 | 展示同来源课程、开课版本与讲次是否已识别；校验来源证据 ID/URL。缺失或冲突证据保持未知；仅返回资源统计，明确不是跨网站独立课程总数。 |
| 普通 Course 与视频 | 普通 Course 必须有可靠 JSON-LD Course 或 MIT 课程主页类型证据；通用 CSS 目录不能单独证明课程。普通课程不等同视频，播放保持未核验。 |
| 平台与目录边界 | 分别显示搜索发现、自动采集政策/待核对许可、浏览器访问未逐页实测、目录无证据、播放未验。任务 completed 不代表每个平台有结果或全部细节完成。原目录逐章来源/时间证据校验保留。 |

## 验证记录

最终完整运行：`frontend-e2e-frozen.json`，28 项通过；逐测试 console/runtime/network 记录另存 `frontend-diagnostics-frozen.json`。6 条 console 错误均来自测试主动注入的 HTTP 503 / ERR_CONNECTION_RESET，没有未捕获 React/页面异常。表单、分组筛选、安全外链、章节注入与时间证据、未知字段、取消竞争、超时幂等、刷新恢复均已实际操作；检查了正确页面标题、主体内容和无 Vite overlay。

构建：`frontend-build-recovery.log`，`tsc -b && vite build` 成功；产物 `index-Qo-4g853.js` 与 `index-3FonNVyt.css`。构建后只改过测试截图方式，没有再改生产源码。`frontend-freeze-manifest.json` 记录所有前端源码、最终测试文件、dist 的逐文件 SHA-256。

复现命令（在 frontend 目录运行；改报告名可保留本次证据）：

```powershell
$env:PLAYWRIGHT_CHANNEL = 'msedge'
$env:PLAYWRIGHT_JSON_OUTPUT_NAME = '../reports/completion-20261013/frontend-e2e-new-run.json'
npm run test:e2e -- --reporter=list,json --output=../reports/completion-20261013/frontend-e2e-new-run
npm run build
```

保留的早期结果：默认 Chromium 因缺少 `chromium_headless_shell-1248` 未启动；没有下载浏览器。首次 Edge 23/25，2 项失败是 fixture 假设仅一次 effect，与 React StrictMode 不符；修正为覆盖全部旧请求和兄弟 AbortSignal 后 25/25。普通 Course 场景后 26/26；刷新恢复后 28/28。所有旧 JSON、失败 trace 和截图目录仍保留。

## 截图与人工检查

已查看桌面恢复入口、取消保留结果、平台边界与手机课程身份。手机无横向溢出；通过滚动确认最后一张卡片实际可见，再回到第一张卡片保存真实手机视口。早期整页手机截图的离屏 `content-visibility` 占位不能作为已阅读卡片的证据，因此最终采用视口截图。

| 画面 | 文件 |
| --- | --- |
| 刷新后原需求与继续按钮 | [桌面恢复入口](verified-submission-recovery-desktop.png) |
| 同来源身份与 unknown、来源入口 | [手机实际视口](verified-identity-evidence-mobile.png) |
| 取消终态与保留资源 | [取消后的结果](verified-cancelled-preserved-results.png) |
| 完成边界与平台能力详情 | [平台能力](verified-platform-policy-boundaries.png) |

限制：fixture 截图内容不是实际课程发现；本次前端测试不证明外部平台可采集、浏览器可访问、课程身份跨站一致或视频可播放。当前标签页关闭/存储被浏览器禁用后，不保证未确认提交的刷新恢复；浏览器拒绝存储时页面明确提示限制。真实 API 与生产 build 的最终浏览器验证应结合总验收报告阅读。
