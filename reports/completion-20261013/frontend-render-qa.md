# 受控 JS 补全前端同步

2026-10-13。本次仅同步已有 UI，没有修改后端、正式数据库或环境开关。

- 课程证据识别新增后端已有的 `html.microsoft_ai.curriculum_table`，仍要求来源、页面 URL 与 evidence id 对应。
- 来源展开中显示渲染状态、静态/DOM 提取目录项数与 DOM SHA-256。`rendered` 明确显示为“离线执行完成（不代表字段有增益）”；新增字段必须对应同 render id、DOM hash 和 acquisition 的页面/目录字段证据。缺失字段、非法 hash、未完成状态保持未知，观看仍未实测。
- 能力详情区分“在线浏览器采集回退”和“受控 JS 补全”，显示开关、页面/资产允许名单及单次补全限制。配置状态不称为动态采集成功。

## 验证

遵循 frontend-testing-debugging 与 react-best-practices。当前会话没有 Browser 插件 skill，使用仓库既有 Playwright + 系统 Edge；未安装浏览器或依赖。流程为隔离 API fixture → 查看资源 → 展开证据 → 核对动态/静态差异及失败 → 展开能力 → 切换已配置/关闭状态。

`npm run build` 成功，产物 `index-DnN_Zrpq.js` 为 263.84 kB（gzip 83.52 kB），CSS 沿用 `index-3FonNVyt.css`。

相关 Edge E2E **5 passed in 8.7s**：移动端、平台政策边界、普通课程/父课程证据、新动态诊断、新渲染配置。每例 runtime、console、意外网络记录均为空；所有 API 与外部请求均由 fixture 默认拒绝层隔离，没有真实搜索或浏览器外联。页面非空，交互与状态切换通过；桌面 1536×1024 和移动 390×844 截图已查看，移动无横向溢出。

证据文件：

- `frontend-render-e2e.json`：5 项结果与逐例 browser-diagnostics。
- `frontend-render-artifacts/`：新增诊断、配置与已有政策/移动视图截图。
- `frontend-render-freeze-manifest.json`：本次 frontend/src 和 dist 的 SHA-256。

这些测试只证明 UI 按给定证据展示；不证明真实来源新增目录、JS 必要性或可播放性。旧报告未覆盖，本次没有重跑全套 E2E。
