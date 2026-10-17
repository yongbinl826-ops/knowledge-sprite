# 单次 Bing 传输取证方案（只读设计，尚未执行）

2026-10-14。本轮仅阅读当前容器公开源代码与既有 `bing-query-readonly-review.*`；没有导入 SearXNG 应用、发起 HTTP、读取实例配置/环境变量/Cookie/凭据或修改生产文件。本文件是后续需独立授权的方案，不是实测结果。

## 可行性与最小入口

可以在现有容器中启动一个独立 Python 进程，复用安装版本的 **Bing 模块 → OnlineProcessor → searx.network → 原 AsyncClient/curl_cffi**。只在该进程内包装记录函数，进程退出即消失；无需重启、修改或注入正在服务的 worker。

固定唯一查询为此前已执行的：`(site:microsoft.github.io) Artificial Intelligence for Beginners course lesson`。不得换词、追加无站点查询、翻页或替换失败。

建议入口顺序如下（接口经本机源码只读确认，未运行）：

1. 用容器虚拟环境绝对解释器 `/usr/local/searxng/.venv/bin/python` 启动独立进程。清空继承环境，仅提供所需公开路径/语言参数；设置 `SEARXNG_DISABLE_ETC_SETTINGS=1`，不提供 `SEARXNG_SETTINGS_PATH`。此已存在的内部测试开关使 `settings_loader.py:93–116,194–204` 不读取 `/etc/searxng`，避免默认 `import searx` 自动读取实例凭据。它只改变此次进程的环境。
2. 在导入 SearXNG 前装入默认关闭的网络调用门禁。使用库自带公开默认配置，随后仅在内存中设置所需已知非敏感实验值：Bing 单引擎、TLS 验证开、无代理/认证、单请求、无重试、无重定向、明确总超时。若要求与运行实例的 locale/HTTP 版本等完全一致，需由主代理提供已经审计的白名单值；不能为此打印完整 settings/env。不得增加 stealth、指纹切换或代理。
3. `searx.engines.load_engines([{'name':'bing','engine':'bing','shortcut':'bi', ...公开值...}])`。它从安装包 `engine_traits.json` 读 traits；**不调用 `fetch_traits()`**。当前 `bing.py` 没有 `init()` 或 `setup()`。
4. `searx.network.initialize(settings_engines=[...], settings_outgoing=...明确公开值...)`，随后 `OnlineProcessor(searx.engines.engines['bing'])`。不导入 `searx.webapp`，不执行 `searx.search.initialize()` 的全引擎初始化，也不初始化 plugins/Valkey/网页端。
5. 用真实 `SearchQuery` 构造固定 query、`EngineRef('bing','general')`、lang=`en`、page=1、已记录的 safesearch；`processor.get_params(search_query,'general')`；`processor.init_network_in_thread(start_time=default_timer(), timeout_limit=...)`。
6. 打开一次调用许可，再调用原 `processor._search_basic(query, params)`。它依次调用原 `engine.request()`、`_send_http_request()` 和 `engine.response()`；包装只观察和施加预算，不改查询文本或解析规则。`finally` 关闭客户端、恢复内存包装、输出结果并结束进程。

必须把这标为“同安装版本的独立受控传输复现”，不是当前服务 worker 的逐字运行状态复刻。它不含 Flask/pre_search 插件和实例缓存/会话状态，不能倒推两次历史请求的原始出站行为。

## 记录点与严格一次边界

| 位置（容器公开源文件） | 接口与用途 |
| --- | --- |
| `/usr/local/searxng/searx/search/processors/online.py:232` | 原 `engine.request(query,params)` 返回后记录最终准备的 `params['url']` 与解码 `q` |
| 同文件 `:167–211` | `_send_http_request` 将 URL 原样交 `searx.network.get`；默认 `allow_redirects=False,max_redirects=0` 位于 `:112–124` |
| `/usr/local/searxng/searx/network/network.py:271–307` | 原 `Network.call_client/request` 仍执行；不以另一个 HTTP 库取代 |
| `/usr/local/searxng/searx/network/client.py:23` | 在该独立进程内给 `AsyncClient.request` 加包装，保存原方法并委托；在 `Network.patch_response` 转换错误前保存状态/正文哈希 |
| `/usr/local/searxng/.venv/lib/python3.14/site-packages/curl_cffi/requests/utils.py:687–696` | 库完成 URL 参数与 quoting，送入 `CurlOpt.URL`；可用内存记录 `Curl.setopt` 的 **仅 URL 选项**，捕获实际交给 libcurl 的 URL，不记录其他选项 |
| `/usr/local/searxng/.venv/lib/python3.14/site-packages/curl_cffi/requests/session.py:363–390,422` | `response.history`、每项 URL/status、`response.url/status_code/redirect_count`；不序列化 response/headers/cookies |

客户端门禁须在委托原方法**之前**验证 `method=GET`、HTTPS、目标 `www.bing.com`、初始 path=`/search`、`q` 等于固定查询、已打开许可且真实调用计数为 0，然后扣除唯一额度。任何第二次调用均本地拒绝。

仅设 `retries=0` 不足：`network.py:289–296` 对首次 `CurlConnectionError` 会关闭客户端并 `continue`，不扣重试次数。实际调用门禁要覆盖这一分支，并在首次失败后永久关闭此次许可。不要把它记录为已经实际发出的第二次 HTTP。

默认 Bing 路径不跟随重定向；应忠实保留该设置。遇 3xx 记录响应 URL/status 和经过安全处理的 Location 后结束，`redirect_count=0` 是有效证据，不能为了补“每跳”而额外跟随。当前 `response.history` 只含重定向元信息，**不含中间响应正文**；不能据此声称拥有每跳 raw hash。如果以后另行授权跟随，必须另立重定向预算，并在逐跳发送前校验目标；不属于此次一请求设计。

## 字节、时间与输出

建议该唯一目标 HTTP 上限 2 MiB，明确总时限（例如 20 秒）和整个子进程硬截止（例如 30 秒），具体数值由正式 scope 固定。用原 curl_cffi `content_callback`（`utils.py:1014–1015`）逐块更新 SHA-256/有界 buffer，超过上限立即中断；成功后把完整 buffer 回填 `response.content`，供原 Bing 解析器使用。发生超限/超时只保留 `complete=false`、实际字节数、partial hash 和错误类别，禁止把部分正文当完整 HTML 解析结果。

`raw_body_sha256` 应准确称为“HTTP 客户端解压后的原始 HTML 字节哈希，解析前”，不是压缩线上字节的哈希。回调模式没有默认 `response.content` buffer，必须补回，不能忽略此差异。

输出仅含：固定输入、准备 URL、实际 libcurl URL、UTC 开始/结束、目标调用数、最终 URL、HTTP status、redirect_count/history 的安全 URL/status、正文完整性/字节数/哈希、有限公开标题/查询框值/结果 URL、解析异常类别。初始查询 URL 可以完整保存；遇重定向 URL 中未知参数时保留安全参数、原 URL hash 和遮盖说明，不打印令牌、用户信息或 Cookie。禁止完整 header/debug/exception repr dump。

若 `searx.network.request()` 的 `future.result(timeout)` 到期，该实现不会显式 `future.cancel()`（`network/__init__.py:94–107`）。不能只返回父层错误后留后台连接；应在独立进程内为实际 client 委托设硬超时、`finally` 关闭网络客户端，父进程到硬截止终止此次子进程。结果需区分“客户端超时并已关闭”与“父进程硬终止”。

## 初始化额外网络风险

- `import searx` 会自动 `init_settings()` 读取用户设置：用上述禁用 `/etc` 的隔离启动避免，不是只把输出藏起来。
- `import searx.webapp` 末尾直接 `init()`（`:1371–1430`），会初始化 DB/cache、favicons、Valkey、plugins 和全体 engines；**禁止走此入口**。
- `EngineProcessor.initialize()`（`abstract.py:139–168`）可能启动任意引擎的 `init()` 线程；不初始化全引擎。当前 Bing 没有此函数，直接构造 processor 即可。
- `EngineTraits.fetch_traits()` 会调用引擎上游；Bing 的实现明确请求 `/account/general`；**禁止调用**。`load_engine()` 的 `EngineTraitsMap.from_data()` 是本地 traits 读取。
- `check_network_configuration()` 只在 Tor network 上调用 get_client；`get_client()` 在 using_tor_proxy 时会请求 `https://check.torproject.org/api/ip`（`network.py:180–190`）。明确 using_tor_proxy=false/proxies=None，且不调用此检查。
- `network.client` 导入时启动一个事件循环线程；这本身不发 HTTP，客户端连接是随后按需建立。仍应让所有可发送入口在准备期保持关闭，意外调用即失败。
- 当前安装 client 公开默认使用 curl_cffi 的 `chrome` impersonation 选项；这是既有代码事实，不能静默新增/更换指纹以求通过。正式方案应明确是否原样保留已批准的现有传输参数；如果禁用它，须把传输差异列为实验限制，不能声称完全复刻。

## 建议离线门禁测试（未执行）

准备阶段客户端调用被阻止；原 engine 生成完整 site query；第 2 次实际 client 调用被阻止（覆盖隐含 ConnectionError 重试）；3xx 不跟随；200 的完整 HTML 经原 response() 解析且 hash 一致；超过字节上限只留 partial；401/403/429 后无新增请求；总超时最终关闭子进程；输出不含 headers/Cookie/认证。

本轮没有创建或执行联网 runner。后续执行前应把该方案缩成固定 scope，再由主代理统一授权唯一网络窗口。
