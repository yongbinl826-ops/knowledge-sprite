# 前端设计与验证依据

设计参考：`concept.png`，使用内置 Image Gen 生成，生成后已经 view_image 检查。用途仅为界面设计，不参与任何课程数据或搜索结果。

## 实现系统

- 1536 × 1024 桌面参考；左侧学习需求表单、右侧结果与证据区。800 px 以下为单列，表单在前。
- 背景 `#f5f9f7`、白色面板、标题 `#113c3b`、正文 `#183c3b`、次要文字 `#64758a`、主色 `#167d68`、边框 `#d9e3e8`；警示为浅琥珀色。
- 字体 Microsoft YaHei / PingFang SC / 系统无衬线；主标题 34 px、分区标题 24 px、正文 14–18 px、辅助信息 11–13 px。
- 面板圆角 10 px，输入框 8 px；细线书本和搜索图标，均为代码原生 SVG。
- 品牌、主标题、说明、输入框、平台选择、开始查找、能力状态、空状态均来自概念和用户明确需求。
- 结果与运行状态为用户指定的必要扩展：来源/缓存/元信息/未知条件/失败状态采用同一色彩、文字和间距系统。没有课程缩略图或占位课程。
- 唯一主按钮“开始查找”。所有外部文本由 React 转义，不插入采集到的 HTML。资源外链仅允许 HTTP(S)，以 `noopener noreferrer` 打开原站。

## 概念提示词

Use case: ui-mockup. Chinese practical learning search tool named 项目制知识引导小精灵. Full 1536 × 1024 desktop surface. Calm mint background, white panels, forest green headings, teal accent. Header brand and 课程与视频发现. Heading 从知识点，找到学习入口. Left form: multiple knowledge points, student level, language, optional technical version and project background, preferred B站/中国大学 MOOC/学堂在线, 开始查找. Right 学习资源 section: unconfigured SearXNG/Tavily notice and honest empty state 从一个知识点开始. Footer: true source links, unknown information explicitly marked, return to original platform. No fake resources, metrics, percentages, charts, accounts, dashboards, video players, or invented product claims. Code-native text and controls, thin borders, restrained radii, legible Chinese.

## 浏览器路径和测试隔离

本会话未列出 Browser 插件及对应 browser skill，Playwright 用于可重复的自动化流程测试。根代理使用内置浏览器进行实际后端状态验收。

`frontend/tests/search.spec.ts` 的拦截响应仅存在于测试目录，生产入口没有导入测试数据。`desktop-fixture-results.png` 的结果全部是测试响应，不是联网验收证据。正常页面和构建均以 live 后端为唯一资源来源。

测试命令：`npm run build`、`npx playwright install chromium --only-shell`、`npm run test:e2e`。

依赖版本按 npm 官方 registry 实际解析并锁定；已核对 [Vite 官方安装要求](https://vite.dev/guide/) 与 [React 版本文档](https://react.dev/versions)。使用 Node.js 24.14.0。
