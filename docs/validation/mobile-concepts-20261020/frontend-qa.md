# 手机前端 r2 交付与验证

候选位于 `tmp/mobile-frontend-candidate-20261020/frontend`，冻结清单为本目录 `freeze-r2.json`，SHA256 `54a60cfada1f05167a211a8e74f6942ee9b440eb01c741ed2a658f799e3984df`。不可变 r1 快照和所有首轮失败继续保留。清单包含 93 个源码/测试/公开配置输入、相对最初公开基线的 19 项生产文件和 10 项测试/夹具差异，以及逐项 r1→r2 before/after SHA。未修改 package、lock、Android 工程或旧网页 dist。

## 已实现

- 显示名统一为“项目制学习引导小精灵”，存储键/appId 不变。知识点保留专业名称和勾选，移除排序控件、顺序提示及按勾选先后改变优先级的行为。已有服务端顺序仅用于稳定展示。
- `VITE_DEVICE_MODE=true` 使用设备自己的项目、版本、选择、草稿、学习进度和历史；默认网页仍走原控制器。个人项目不读取服务器 `/api/projects` 列表。共享课程库只读，公开元数据不带个人标记，也不宣称完整匹配当前知识点。
- 输入/选择/已学会/编辑/本机确认可离线保存。已知离线或配置不可用时，明确显示“仅本机确认，未开始课程检索”；同份确认幂等，不伪造排队/完成，不恢复联网后自动 POST。历史结果保留，在线显式查找才产生新临时任务。
- Android 使用本地 `DurableDeviceStore` get/set，必须收到 `committed===true` 才视为写入完成。双槽影子写、完整 SHA、提交指针和串行事务保留旧记录；写入失败/4MiB 限额不默默退回内存。Web QA 才使用 localStorage；iOS 未支持时拒绝写入，不声明耐久性。
- 每次新任务使用新 UUID 和随机 32 字节能力令牌；先可靠保存不可变 ticket，再 POST。网络不确定只读原任务，不自动重发；初次 POST 未完成时轮询暂停。429 按 Retry-After 回退，过期/重启 404 保留本机内容并要求明确重试。令牌仅在 Authorization，不放 URL/EventSource；完成结果可靠保存后清除令牌。
- 显示安全的 `检索语境：…` 辅助元数据；确认/search 只显式提交当前可见且选中的 `reviewed_topic_technologies`，名称不被修改、隐藏 plan/concepts 不参与推断。空集合传 `{}`。与独立后端 safe-value 夹具一致，包含 micro:bit、.NET 8、C++、Vue.js 3、Web Audio API。
- 提供本机单项目删除并明确不可恢复；活动任务未处理时阻止删除。外链经现有 safe URL 校验，由原生 Browser 插件交给系统浏览器。保留右栏纯封面、原动效、键盘焦点和减少动态效果。

## 验证范围与结果

| 验证 | 结果 | 证据 |
|---|---|---|
| 所有现有与新增 Node 用例 | 159/159，0 skip/fail | `node-r2-final.txt` |
| TypeScript | 通过 | 执行 `node node_modules/typescript/bin/tsc -b`，exit 0 |
| 设备构建 | 通过；只写 dist-mobile | `build-r2-offline-final.txt` |
| 设备实际 Edge 控件流程 | 4/4 | `browser-r2-offline-final.json` |
| 旧网页关键回归 | 9/9 | `legacy-r2-offline-final.json` |
| 1440/768/390 截图 | 已实际打开，未见新增明显 P1/P2 | `browser-r2-offline-final-artifacts/` |

设备 4 用例分别覆盖：两个隔离存储 context 的项目不可互见/共享课程相同；冷启动离线草稿、选择、学习进度、历史和本机确认；2300ms 首次 POST 延迟期间无抢先 GET；完整 search 投影保留 local ID、纯封面和显式技术 map；存储满时旧数据字节不变且不发送新任务；明确删除；不确定提交跨 reload 不重发；429≥2s 后 GET 404 恢复；direct_search 的明确取消和新能力重试。请求附件脱敏，不记录真实凭据。

旧网页 9 用例覆盖 `cover-only.spec.ts`、`simple-review.spec.ts`、`project-lifecycle.spec.ts`。`project.spec.ts` 和 `motion-flow.spec.ts` 仅维护新增显式 map 的精确 payload 断言，本轮未重跑其完整文件；不把 9 个 focused 用例描述成全部旧浏览器套件。

浏览器使用真实已安装 Edge，响应由 Playwright 本机合成 API 提供。`device-api-fixture.json` 是独立后端真实 ASGI + 合成 providers 生成的 API 形状，使用夹具不等同本前端已经与运行的后端联调。全部外部请求阻断，图片为 204 占位；真实模型、来源搜索、D 写入均为 0。Browser plugin 不在当前技能中，使用仓库既有 Playwright；未下载依赖或浏览器。

首轮 Illegal invocation、旧按钮 selector、以及业务异常被错误包装成存储错误的报告保留，修正后重新执行最终报告；未删测试掩盖失败。

## 关键截图

- 手机离线审阅：`browser-r2-offline-final-artifacts/mobile-device-two-isolated-cedb2-first-POST-has-no-early-GET-chromium/mobile-offline-review.png`
- 平板纯封面结果：`browser-r2-offline-final-artifacts/mobile-device-search-proje-de26f-w-POST-deletion-is-explicit-chromium/tablet-results-cover-only.png`
- 桌面共享课程库：`browser-r2-offline-final-artifacts/mobile-device-two-isolated-cedb2-first-POST-has-no-early-GET-chromium/desktop-shared-courses.png`

另有手机共享库、任务过期恢复截图。占位封面是测试环境有意阻断图片，不作为真实封面加载通过证据。

## 构建与集成边界

QA 构建通过 `build-qa.mjs` 使用 `envDir:false`，设备模式 true、HTTPS 占位基址 `https://device-api.example.invalid`、debug loopback false。输出：

- `dist-mobile/assets/index-Cp5SYJ1U.js` SHA256 `ebcecb1a20eef94e7c3966b29f9524ad14d942066eea572c5053dc093e17f0fe`
- `dist-mobile/assets/index-B1lqFFZf.css` SHA256 `9b8b44b20522e96445ef8f8018680000fc2c2a0104e0faf2882aa30259c065de`

此基址不会用于交付运行。Root 合并原生脚本/依赖和前端后，需为实际 HTTPS 或显式 debug loopback 重建并同步原生资产。`DEV=false` 加显式 `VITE_MOBILE_DEBUG_LOOPBACK=true` 的 production-debug 路径已有 Node 回归；release 仍默认拒绝 HTTP。

私有 QA Vite 保留供后续 root 核验：5195/PID30956 为设备，5196/PID66192 为旧网页；均 `envDir:false`，API proxy 指向 `127.0.0.1:1`，测试中全部 API 拦截。未停止或接触 8001/8002。

剩余门槛：Root 的运行 ASGI 联调、实际配置构建/Capacitor sync，以及 Android SDK 编译、真实设备 crash-kill/耐久写入/系统返回与 Browser 插件验证。未声称 APK 已运行，未声称 iOS 已实现。真实安装卸载/清除数据会丢失本机记录，界面已提示；无登录、云同步或导入导出 UI。
