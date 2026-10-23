# 跨项目视频推荐：最终覆盖与缺口（2026-10-21）

**结论：本轮未通过“每个知识点都能自动补齐可用视频”的验收。** 两组当前页面分别显示 6/11、2/9 个知识点的相关链接，共 8/20；这是界面链接覆盖，不是全部外链当前可打开或播放的证明。

按已确认的有限收尾范围，固定教学大纲 v23 和新画板项目 v5，每组只做一轮最终桌面与 390px 页面复核。没有增加模型、付费搜索、采集、项目版本或播放检查；没有手工注入链接。真实采集与模型运行记录沿用这两组已有的当轮结果。

| 项目 | 当前版本 | 显示相关链接的点 | 卡片数 | 最终界面 |
|---|---:|---:|---:|---|
| 教学大纲生成助手 | 23 | **6/11** | 11 | 桌面/390px 通过；覆盖未通过 |
| 原生 JavaScript 浏览器画板（跨项目真实验收） | 5 | **2/9** | 6 | 桌面/390px 通过；覆盖未通过 |

两组的补链、候选地址、查询语句及后台诊断均未出现在前端；页面仍可显示简短的“搜索参考/课程参考”来源标记。控制台错误、页面异常、写请求、媒体请求和横向溢出均为零。标题与封面跳转地址一致，分集地址保留来源绑定。

17 张卡片中，3 张有当前保存的自身页面/目录证据，其余 14 张依赖真实搜索来源。没有把 `link_eligible=true`、HTTP 200 或构建通过解释为播放认证。当前外站是否需要登录/付费、链接是否此刻可打开，未确认项均为 **unknown**；null 不代表免费。两条 MOOC 入口属于同一门课程。

## 全部 20 个知识点

下表只统计最终真实 UI 已显示的卡片。额外已有来源及历史链接单列，不加进自动覆盖率。

### 教学大纲生成助手 · v23

项目 ID：`fdfd2ce1-c5c7-4119-81ca-924d6c377c93`；最终检查：`2026-10-21T13:19:33.002Z`。

| 点 | 知识点 | 当前链接 | 来源及缺口原因 |
|---|---|---|---|
| k1 | 教材目录文本解析与层级树构建 | **无当前卡片** | 已有慕课层级树相关目录，但当前自动投影没有生成该点可展示链接。 |
| k2 | 声明式数据模型与字段约束校验 | [【吴恩达】Pydantic规范LLM完整工作流（API对接 Tool Calling完整实操）——Pydantic for LLM Workflows](https://www.bilibili.com/video/BV1ypLX6wE5o/)（真实搜索参考） | 真实搜索来源支持 Pydantic 工作流；尚未取得该视频自身完整页面。 |
| k3 | 跨字段业务规则校验 | **无当前卡片** | 中文恢复查询完成后为零；英文查询已发送后取消，不能解释为外部没有视频。 |
| k4 | 参数化提示词模板 | [【全748集】目前B站最全最细的AI Agent零基础全套教程，2026最新版，全程干货无废话！七天就能从小白到大神！少走99%的弯路！学完即就业，带你玩转AI_哔哩哔哩_bilibili](https://www.bilibili.com/video/BV18Zu76fEoH)（真实搜索参考） | 真实搜索摘要支持提示词模板，当前仅能提供父课程参考，未确认具体分集。 |
| k5 | OpenAI 兼容对话补全接口调用 | [第13讲：调用OpenAI Chat Completions API——手写第一次真实请求](https://www.bilibili.com/video/BV14TYd6QEe6/)（真实搜索参考）<br>[OpenAI API Python教程：实现Chat Completion对话补全](https://www.bilibili.com/video/BV1M9ah6JEwZ/)（真实搜索参考） | 真实搜索标题直接涉及 Chat Completions API；当前两条均为搜索参考。 |
| k6 | 非确定性输出重试策略 | **无当前卡片** | 本版本未取得被接受的重试机制来源；历史章节不计入当前自动覆盖。 |
| k7 | 模板引擎文档渲染 | [超简单!Python动态渲染HTML数据](https://www.bilibili.com/video/BV18W421w75G/)（真实搜索参考）<br>[Python全栈（老男孩4期）Django框架入门到应用](https://www.bilibili.com/video/BV1mW411G7g6)（真实搜索参考）<br>[jinja2 模板引擎页面动态渲染代码实战](https://www.bilibili.com/video/BV1nposYWEtR/)（真实搜索参考）<br>[第132集Jinja2模板引擎!动态网页渲染](https://www.bilibili.com/video/BV1y8xozJEAF/)（真实搜索参考）<br>[3.1-JInja2模板引擎概述](https://www.bilibili.com/video/BV1a8pwe6Eck/)（真实搜索参考） | 真实搜索来源支持 Jinja2 渲染/模板；相关参考不等于完整文档渲染教学。 |
| k8 | Word 文档程序化生成 | **无当前卡片** | 本版本未取得被接受的 python-docx 视频；历史 v22 有真实链接，单列补充。 |
| k9 | 集合差集比对 | [一题理解Python的集合差集运算规则](https://www.bilibili.com/video/BV1Cw4m1e7Nu/)（真实搜索参考） | 真实搜索标题直接涉及 Python 集合差集。 |
| k10 | 会话状态管理 | [Streamlit 程序执行流程-组件状态与通信-session states的使用以及组件函数回调-3-python数据产品开发](https://www.bilibili.com/video/BV1hs4y137K7/)（真实搜索参考） | 真实搜索标题直接涉及 Streamlit session states 与组件回调。 |
| k11 | 表单输入校验与提交控制 | **无当前卡片** | 当前候选未提供足够的 Streamlit 表单校验与提交控制依据；泛框架内容没有算作覆盖。 |

### 原生 JavaScript 浏览器画板（跨项目真实验收） · v5

项目 ID：`4ace8b3d-8110-4650-9899-e17205711b9c`；最终检查：`2026-10-21T13:20:05.910Z`。

| 点 | 知识点 | 当前链接 | 来源及缺口原因 |
|---|---|---|---|
| k1 | HTML Canvas 元素与 2D 绘图上下文 | [HTML5 Canvas详细知识点](https://www.bilibili.com/video/BV1BfpieUE3K/)（真实搜索参考） | 新增显示的是本版本已有真实搜索来源；当前未获取该候选详情页。 |
| k2 | CSS 响应式布局与视口适配 | [千锋教育web前端html+css+js视频教程200集（完整版）](https://www.bilibili.com/video/BV1R4411J7tQ/?p=207)（自身页面/目录）<br>[无废话！12分钟搞懂CSS Grid 网格布局一行代码实现响应式布局！](https://www.bilibili.com/video/BV1yXqaBoEv1/?p=1)（自身页面/目录）<br>[pink老师html、css进阶导读](https://www.bilibili.com/video/BV1yY411R7bb/?p=132)（自身页面/目录）<br>[Web前端设计_洛阳科技职业学院_中国大学MOOC(慕课)](https://www.icourse163.org/course/LYKJXY-1207005804)（真实搜索参考）<br>[Web前端设计_洛阳科技职业学院_中国大学MOOC(慕课)](https://www.icourse163.org/learn/LYKJXY-1207005804?tid=1463411449)（真实搜索参考） | 三条 B 站链接绑定自身响应式目录；另两条为同一 MOOC 课程不同入口的搜索参考，不是两门独立课程。 |
| k3 | Canvas 逻辑尺寸、设备像素比与坐标换算 | **无当前卡片** | 已有 Canvas translate/rotate/scale 目录，仅作额外相关参考；尚未进入当前自动投影，也未证明 DPR/client 坐标换算完整覆盖。 |
| k4 | Pointer 事件统一鼠标与触摸输入 | **无当前卡片** | 没有已确认的 JavaScript Pointer 来源；Unity/硬件结果被排除。恢复查询排队取消、未发出 HTTP。 |
| k5 | Canvas 路径描边与线条样式 | **无当前卡片** | 确认存在新增误拒：父资源无尾斜杠，真实目录父地址带尾斜杠，同一 BV 的合法 p=7 被 link_eligible 标成 false。来源与相关性仍保留，但当前 UI 隐藏；尚未修复。 |
| k6 | HTML 表单控件值读取与事件绑定 | **无当前卡片** | 混合 HTML/JS/Vue/React 课程和 jQuery val/html/text 不能确认原生 HTML 控件值读取与事件绑定；两个语义候选为 unknown。 |
| k7 | 操作历史栈与撤销/重做游标 | **无当前卡片** | JavaScript 语言发展历史不是操作历史栈/undo-redo；英文恢复查询排队取消、未发出 HTTP。 |
| k8 | Canvas 全量重绘策略 | **无当前卡片** | 当前自身目录未确认清除/更新/全量重绘机制；英文恢复查询排队取消、未发出 HTTP。 |
| k9 | Canvas.toBlob 图像导出与浏览器下载 | **无当前卡片** | 下载器、缓存导出及 ComfyUI 结果不是 JavaScript Canvas.toBlob；两条恢复查询均未发出 HTTP。 |

## 已有补充来源：不计入当前自动覆盖

这些地址来自已保存的真实目录或历史结果，未写回生产数据库，本轮也未重新打开外站。

| 项目/点 | 额外链接 | 依据与边界 |
|---|---|---|
| 教学大纲生成助手 / k8 | [python-docx：标题、段落、列表、表格](https://www.bilibili.com/video/BV1eh41167AL/) | 历史 v22 自身来源；未出现在当前 v23 自动显示中 |
| 原生 JavaScript 浏览器画板 / k1 | [9-3：扩展 Canvas 的 context](https://www.bilibili.com/video/BV1T5411e7N7/?p=39) | 当前 v5 自身目录；相关上下文参考，不证明完整入门覆盖 |
| 原生 JavaScript 浏览器画板 / k3 | [4-3：应用 translate、rotate 和 scale](https://www.bilibili.com/video/BV1T5411e7N7/?p=13) | 当前 v5 自身目录；相关坐标/缩放参考，DPR 与 client 换算 unknown |
| 原生 JavaScript 浏览器画板 / k5 | [3-1：线条的帽子：lineCap](https://www.bilibili.com/video/BV1T5411e7N7/?p=7) | 当前 v5 自身目录及旧 UI；最终 UI 因尾斜杠误拒而未显示 |

## 已合并的修复与未解决问题

- 页面缓存归属：新获取页面使用自身缓存状态，避免继承搜索缓存字段。B 站同视频的已知追踪参数身份可兼容，仍拒绝其他视频、错误分集和未知身份参数。
- 相关链接资格：后台从真实来源生成 `link_eligible`，前端检查来源绑定后显示相关视频/课程；保留付费、登录、报名状态。已知失败、错误技术或媒体故障仍排除。主推荐与相关参考分别处理。
- 任务尚在排队/运行时，未抓取的搜索候选不再提前关闭缺口；已抓取自身页面的主题与技术证据可否决误导性搜索摘要。没有增加调用额度。
- **仍有新增缺陷：画板 k5 尾斜杠误拒。** `related_recommendations.py` 新资格检查调用 `_own_catalog_target` 时，父资源 `/video/BV1T5411e7N7` 和真实目录父地址 `/video/BV1T5411e7N7/` 被表示差异挡住，合法 `?p=7` 得到 false。离线检查确认身份、引用新鲜度、媒体状态、语义及技术均通过；仅在内存中换成已观察的带斜杠根地址即变 true。本轮没有继续修改或重跑最终界面，所以仍按 2/9 交付。
- **恢复窗口与队列仍是缺口原因。** 画板后四点 9 条逻辑恢复请求中只有 5 次真实 HTTP：2 次成功、3 次发送后取消；另 4 次排队取消。已使用 38/64 搜索、15/60 详情额度，未用尽计数额度，剩余时间与共享队列限制了后面的点。没有实施额外调度优化。取消/未发送不能写成外部零结果。
- 模型不是可靠链接数据库：画板后四点的真实发现调用完成，但 4 个 URL 数组均为空；另一次语义判断的 5 对均为 unknown。没有伪造直链，也未把模型空数组概括成“所有视频都不可用”。

## 验证与服务状态

- 最终后端回归：**2,015/2,015** 通过，失败/错误/跳过均为 0；65 个后端源码文件与该次回归时哈希一致。初次合并曾出现 44 个失败，已保留原始失败日志；修复了未抓取候选提前关闭缺口等问题，再完成上述回归。回归没有覆盖上述最终发现的尾斜杠误拒，不能用全绿掩盖它。
- 前端：**102/102** 单测通过，TypeScript 与 Vite 构建通过。实际 8001 提供的 JS/CSS 字节哈希与构建一致。
- 桌面与手机窄屏共 40 次知识点选择检查，覆盖与 UI 完整性分别记录。桌面截图有两张远程封面尚未加载；手机检查时已有图片均加载，另各项目两张使用占位图。不声明全部封面在所有截图中加载成功。
- 8001、8017 均 ready，队列/活动任务/待分析/待搜索为 0。恢复前服务已不在运行，退出原因 unknown；本次没有停止任何业务服务。两库备份保留，所有表行数、任务与搜索记录哈希、项目版本历史哈希均与恢复前一致，SQLite 完整性正常，`.env` 未变。
- 恢复启动器有一个本地辅助 Python 等待未返回，疑似 Windows 继承输出管道，原因未证实；已核验它与业务服务控制台隔离，普通 Ctrl+C 未使其退出，没有强制终止。8001/8017 的独立健康验证正常，辅助进程不运行采集任务。该异常保留在恢复记录中。
- 本轮测试为 Web 桌面与 390px 布局，不是新 APK 验收；未发布、推送或打包。

## 证据文件

- [逐点机器可读结果](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/final-link-closeout.json)
- [教学大纲最终真实 UI](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/guide-final-ui/browser-live-report.json)
- [画板最终真实 UI](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/canvas-final-ui/browser-live-report.json)
- [后端最终回归](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/backend-regression-final.json)
- [前端单测](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/frontend-tests.log)
- [服务恢复记录](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/service-restore.json)
- [数据/源码/运行资源最终核对](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/integrity-final.json)
- [画板已有来源审核 K1–K5](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/source-review-v5-part-a.md)
- [画板已有来源审核 K6–K9](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/source-review-v5-part-b.md)

最终截图：

![教学大纲桌面示例](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/guide-final-ui/desktop-point-5.png)

![画板下载知识点缺口（390px）](C:/Users/xiaoer/.codex/visualizations/2026/10/20/01a15bae-1f7a-7032-b594-30e75dfef8ff/cross-project-20261021/final-closeout/canvas-final-ui/mobile-point-9.png)
