# 可选 MIT 脚本：当前 worker 的离线实测与判定规则

日期：2026-10-14。范围：只读生产源码，使用当前生产 worker 和 8 份可审核的合成 HTML 运行系统 Edge。没有 Fetcher、DNS 或真实站点请求；文档字节通过本地 manifest fulfill，其余请求由 CSP 拦截或 route abort。没有源码修改。OS 后台/UDP 全出口隔离依然 unknown。

原始观测：[renderer-csp-route-probe.json](renderer-csp-route-probe.json)。保存了每例完整 fixture HTML、原 CSP、worker 返回的请求/违规记录、Node 与 Edge 主进程清理观察，以及探针前后 worker SHA-256；`source_unchanged=true`。这些是浏览器探针观察，不是新的 pytest/JUnit 通过计数。

## 当前实现的合理判定

只对以下全部成立的请求标记 `optional_integration_blocked, fatal=false`：

1. 入口属于已限定的 MIT OCW 来源。
2. 实际请求 URL 使用 HTTPS，host/path 严格匹配已观察的 Appzi `/w.js` 或 Google Tag Manager `/gtm.js`、`/gtag/js`，不按域名泛化任意路径。
3. route 观察到实际 `method=GET`、`resourceType=script`，且不是后续导航/子 frame。
4. 一律 `route.abort()`；不预取、不 fulfill 可选脚本、不开联网回退。

当前代码先检查非 GET 和导航，再进行可选脚本判断，顺序正确。附加 CSP 仅列精确脚本路径，让对应请求到达 route，以取得完整 URL、method 和资源类型。原站 CSP 仍取交集；被原 CSP 拦截的事件不能误记为已取得 route 事实。

`securitypolicyviolation` 本身不提供可靠 method/resourceType 事实。**不建议从只有 origin 的 blockedURI 反推具体可选脚本。** 即便页面上有一个已知脚本，同 origin 的未知脚本或 fetch 也可能同时触发违规；仅靠 origin、时间接近、sourceFile 或页面声明数量无法证明一一对应。当前“CSP 无法精确关联则 fatal；仅实际 route GET+script 可降级”的方案保留了边界。

## 当前系统 Edge 的实际观察

| 场景 | 观察结果 | 是否致命 |
|---|---|---|
| Appzi `/w.js?token=synthetic`，外部 script | route 获得完整 URL、`GET`、`script`，`optional_integration_blocked`；最终 `rendered` | 否 |
| 同 Appzi URL，fetch GET | `csp_connect-src`，blockedURI 为完整 URL（含 query） | 是 |
| 同 Appzi URL，fetch POST | `csp_connect-src`，blockedURI 为完整 URL；没有 route 的 method 事实 | 是 |
| 同源 `/probe-only`，fetch POST | route `non_get`，`method=POST`、`kind=fetch` | 是 |
| 导航到同 Appzi URL | route `navigation_or_frame`，`method=GET`、`kind=document` | 是 |
| 同源未知 `/unknown-script.js` | route `resource_not_preapproved`，`GET/script` | 是 |
| Appzi 同 host 未知 `/unknown-script.js` | `csp_script-src-elem`，完整未知 URL | 是 |
| Appzi 外部 script，原响应 CSP `script-src 'none'` | `csp_script-src-elem`，完整 Appzi URL；仍 `render_dependency_blocked` | 是 |

本机这批 CSP 事件都保留了完整 URL，**没有实际出现 origin-only 事件**。不能将该有限观察扩大为跨浏览器/版本永远返回完整 URL的保证。当前实现不依赖此保证。

每例只 fulfill 1 个合成主文档；没有第三方资源字节。8 例均观察到所拥有 Node 退出和 Edge 主进程退出；`all_descendant_processes_exited` 仍 unknown。

## 建议固化的测试矩阵

直接将上表形成针对 worker 的参数化回归即可，重点断言 `fatal`、`reason`、实际 method/kind 与 `fulfilled_requests` 仅含主文档。跨源 POST 被 CSP 提前挡下时，只断言 CSP fatal，不伪造 method=POST 的 route 观察；由同源 POST 单独覆盖真正的非 GET route 分支。

另外补两条轻量边界：非 MIT 入口上的相同 Appzi 路径不能降级；模拟只有 origin 的 `csp_script-src-elem` 事件仍 fatal。若有必要再覆盖 GTM 动态插入的实际 GET script；不要通过给泛 origin 放宽 CSP 或让缺失请求联网来制造正例。

截至本次快照，没有发现上述新 route 判定需要必须修复的事实错误。上一份只读报告中的“只改预检跳过不足”问题，当前版本已通过精确 CSP 路径 + 实际 route 分类解决；原站 CSP 仍可使其失败，这是保守边界，并非应该忽略的错误。
