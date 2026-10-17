# 受控离线渲染桥实验（生产远程渲染关闭）

本目录是独立实验，未接入 `backend/app`，没有修改依赖锁文件。它只执行这里可以逐行审核的 `fixtures/course.html` 和 `course.js`。不得把真实站点 HTML/JavaScript 换入后称为同等安全，不能用于重试 OpenLearn 403、受限 B站、MOOC 或学堂页面。

## 当前可验证链路

1. `preflight.py` 复用现有 `Fetcher.fetch()`，但注入**只读内存 HTTP 响应表与固定 DNS fixture**。同一套 URL、公网 IP、站点策略、robots 和重定向校验仍执行；没有真实 DNS、DoH 或 HTTP，也没有 fallback。正例为 robots 加两个逻辑资源，共 3 次内存请求。
2. 预审包通过 stdin 单行 JSON 发给 `renderer.mjs`。Node 只接受 `audited_fixture_only` 模式与固定 scenario，逐字节比较包内容和本地可信 fixture、校验 SHA-256、固定 URL/MIME、资源数与字节预算。不是可执行任意脚本的接口。
3. 使用当前仓库已安装的 Playwright **1.64.0** 和系统 **Edge**，建立临时匿名 context，不读取登录状态、storage state 或 cookies。无需安装、下载浏览器。
4. 在创建 page 前安装 context route、WebSocket route 和初始化防护。页面离线；HTTP 仅可 `fulfill` 预审字节或 `abort`。没有 `route.fetch`、`route.continue`、真实 HTTP 客户端或缺资源在线回退。
5. 非 GET、未预审 URL、额外文档导航、frame、媒体请求、popup、worker、WebSocket、下载均拒绝。另设 CSP（禁 frame/worker/media/object/form 等）、`serviceWorkers: block`、`acceptDownloads: false`；JS 构造器防护只作为额外层。
6. stdout 返回有限结果：渲染后的 HTML、实际 fulfill 列表、失败原因、所拥有 Edge 主进程退出观察和隔离边界。stdin 后续 `{"cancel":true}` 可取消当前任务；finally 关闭 context、browser、BrowserServer。

## 运行

在仓库根目录 PowerShell：

```powershell
.venv\Scripts\python.exe experiments/controlled-renderer/preflight.py |
  node experiments/controlled-renderer/renderer.mjs

.venv\Scripts\python.exe -m pytest experiments/controlled-renderer/test_renderer.py -q
```

测试只使用本地 fixture。正例生成一个合成 Course 和两条目录，然后交给现有静态提取器验证；视频证据仍为 none。这不是新增真实课程、真实目录或播放验收。

## 预算和清理口径

- 最多 8 个预审逻辑资源、总计 100,000 字节；同一渲染中 fulfill 请求数与累计字节再次受限。robots 的内存预审请求另外计数。
- 单个输出 HTML 上限 100,000 字节，输入 JSON 总计上限 300,000 字节。
- 浏览器启动上限 10 秒；页面开始前安装渲染 deadline，默认 5 秒、允许 50–10,000 ms。
- 超时 fixture 设置的 **200 ms 是页面渲染阶段 deadline**，不含 Edge 启动、连接、context 配置和清理，不是整个任务总耗时。取消用例仅验证收到 `ready` 后立即发 cancel，不证明启动中、复杂脚本执行中或任意时刻取消的全部情形。
- Python 测试驱动有独立 20 秒通信 deadline（取消测试等待 ready 最多另 15 秒）。必要时只终止自己创建的 Node 子进程树，不关闭用户已有 Edge。此兜底路径是测试驱动措施，不是独立 Node 桥对任意系统故障的完整恢复保证。
- 正常收到桥结果的测试检查 Node 退出和所记录 Edge **主进程**不再存活。驱动通信/解析失败时，报告独立记录原异常、所处阶段、拥有的进程 PID、强制清理与清理异常；没有桥结果时 `result=null`，不能推定 Edge 已退出。即使主进程退出已观察，也不将此夸大为操作系统全部后代进程/网络通道的安全证明。

## 隔离边界：unknown 必须保留

本实验读取了已安装版本的 `frontend/node_modules/playwright-core/types/types.d.ts` 中 route、Service Worker、offline、routeWebSocket、BrowserServer 相关 API 文档。官方接口参考：[route](https://playwright.dev/docs/api/class-browsercontext#browser-context-route)、[offline](https://playwright.dev/docs/api/class-browsercontext#browser-context-set-offline)、[WebSocket route](https://playwright.dev/docs/api/class-browsercontext#browser-context-route-web-socket)。

离线状态、HTTP route、CSP 和 JS 防护**不能证明整个浏览器进程的网络出口隔离**，尤其不能据此证明 WebRTC/UDP、浏览器后台组件、扩展或本地环境的所有通道均被操作系统阻断。`process_network_egress` 与 `webrtc_udp_egress` 固定报告 `unknown`。没有修改 OS 防火墙，也没有抓包或进程级外联证明。Playwright BrowserServer 与驱动间使用本机控制 WebSocket，这是控制通道，不是站点访问。

因此生产远程渲染保持关闭：`mode=remote` 或任意非 fixture 模式在浏览器启动前拒绝。任意真实站脚本、远端动态依赖、真实受限页的渲染和播放都**未验证**。

## 保留的验证记录

`reports/completion-20261013/controlled-renderer-offline.json` 以 runs 追加保留每轮尝试，不覆盖早期失败。首轮 14 通过、1 失败来自 guard 的失败状态名不一致（已实际阻断，返回 Worker，而测试期待 forbidden_operation）；修正后原 15 项通过，新增未换行大输入保护后的完整一轮为 **16 passed in 59.62s**。未把 fixture 结果纳入真实站通过率。

后续只读审查发现驱动在通信/解析异常时会在记录前抛出，已将桥调用记录移入 `finally`；清理失败单列，不掩盖原异常。新增两种**无浏览器、无网络的 Python 子进程替身**：超时强制清理、异常 JSON 正常退出。连同五项已有启动前拒绝/预算用例，针对性验证为 **7 passed, 11 deselected in 2.05s**。历史 runs 保留；后续报告允许 `result=null`，需同时读取 `harness_error_type`、`phase`、`forced_cleanup` 和 `cleanup_error_type`。

证据收束后完整重跑：**18 passed in 60.10s**。独立 JUnit 为 `reports/completion-20261013/controlled-renderer-final.xml`；摘要为 `controlled-renderer-summary.json`（同目录），测试计数从 JUnit 读取，不从 attempts 数量推断。正例摘要记录真实渲染 DOM 经静态提取器得到的合成 Course 名称、两条目录字段与逐章证据绑定断言结果。18 项通过包含预期失败/拒绝的测试，并不意味着 18 次成功渲染。
