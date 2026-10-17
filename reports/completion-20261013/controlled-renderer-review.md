# 受控渲染实验只读审查 · 2026-10-13

结论：当前固定 fixture 实验的默认拒绝边界与 README 主要声明一致；未发现可由请求包把任意真实站脚本交给浏览器执行的入口。**不能据此开放生产远程渲染。** 有一处失败记录口径缺口，已通知 root 与实现代理。

范围：只读 `experiments/controlled-renderer/{renderer.mjs,preflight.py,test_renderer.py,README.md,fixtures/*}` 和既有 `controlled-renderer-offline.json`。未运行浏览器、外部请求、测试、真实搜索或正式数据库操作；没有修改实验或前端代码。下列“观察”均来自保存的旧记录，不是本次复跑。

## 发现

**P2 · 异常清理路径未保存尝试记录。** `test_renderer.py:70-83` 在等待 ready / communicate 异常时执行拥有的 Node 进程树清理，随后直接 `raise`，跳过 `ATTEMPTS.append`；输出 JSON 解析等异常也发生在 append 之前。因此此 JSON 不会记录该路径的 `forced_cleanup: true`，而 README:45 的“保留每轮尝试”覆盖面更宽。建议在不掩盖原异常的前提下记录 exception、PID、清理动作与退出观察，或明确账本仅包含成功收取的结果；驱动兜底路径不能称已验证。这个问题不否定既有正常 cancel/timeout 的清理证据，也不构成 remote 渲染入口。

## 已核对的拒绝与执行边界

| 项目 | 代码与保存证据 | 结论 |
| --- | --- | --- |
| 生产远程模式 | `renderer.mjs:40-41` 仅接受 `audited_fixture_only`；`run()` 第一步 validate（67），之后才 launchServer（74）。既有 remote 尝试返回 `remote_rendering_disabled` 且无 browser_pid；生产 backend/frontend 未搜索到此桥接入口。 | 默认关闭，先拒绝后启动。 |
| 额外脚本与字节 | 仅允许两个 fixture 文件名、固定 URL/MIME、限定 scenario；包中字节须与本地可信文件逐字节相同，并核验 SHA-256。fixture HTML 只加载固定 course.js；JSON-LD 为合成非执行数据。 | 在“本地 fixture 文件本身可信且已审核”的前提下，包不能替换任意脚本。允许修改本地可信文件的操作者处于此边界之外。 |
| 页面请求 | context 在建 page 前安装 HTTP/WebSocket route、offline 与 init script。HTTP 只 fulfill 内存字节或 abort；源码没有 route.fetch / route.continue，也无缺资源在线回退。 | 页面 HTTP 仅限预审字节。不能推导整个进程零外联。 |
| 预审 | `preflight.py` 注入固定 DNS 与内存 HTTP 表，缺项抛错；复用 Fetcher 的策略、robots、URL/重定向检查。 | 这里的 actual_network_requests=0 仅描述内存预审，不是浏览器进程的网络测量。 |
| 禁止操作 | 非 GET/未预审 URL/额外导航、frame/媒体、popup/worker、WebSocket 等由 route、CSP、事件及额外 JS 防护限制；页面预算、输入/输出字节有上限。 | fixture 中覆盖的操作被拒绝。未把 JS 构造器拦截称作不可绕过的浏览器沙箱。 |

## 清理证据与 unknown

现有 JSON 有 3 轮 run，分别保存 13、13、14 个桥接尝试；其中最后一轮包含正常 course、5 种拒绝、取消、渲染超时、5 种启动前拒绝与未换行大输入拒绝。两个纯预审测试没有桥接尝试条目，所以 attempt 数不是 pytest 总数。README 记录最终 16 passed；本次只读审查没有重新验证该 pytest 汇总。

最后一轮取消记录的 Edge 主进程 PID 为 38116，超时记录为 62860；二者均保存 `node_exit_code=0`、`forced_cleanup=false`、`context_closed=true`、`browser_exit_observed=true`。测试代码另用 alive(PID) 断言该**主进程**已退出。这支持已记录场景中所拥有 Node 和 Edge 主进程退出，不证明所有后代、全部系统故障或任意脚本情况下都能回收。finally 的 close 操作没有各自独立 watchdog；README 已将测试驱动 20 秒通信 deadline 与独立 Node 桥的一般故障保证区分开。

README 与每个浏览器结果明确保留 `process_network_egress=unknown`、`webrtc_udp_egress=unknown`。没有 OS 防火墙策略、抓包或进程级外联证据；启动参数、offline、CSP、HTTP route 与禁用构造器不能替代这些证明。本机 BrowserServer 控制 WebSocket 已与站点访问区分。

本实验不得作为 MOOC 许可待核对或学堂/B站/YouTube 等限制的回退。不得把合成 Course/两条目录计入真实页面、课程、视频目录或播放成功率。当前 README 已作上述限制说明，审查无需扩大功能或启动任何真实站渲染。
