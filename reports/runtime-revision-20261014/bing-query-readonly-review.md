# Bing 查询质量：本机只读诊断

日期：2026-10-14。范围：只读既有 JSON、运行容器的公开源代码，并离线执行纯查询解析/URL 构造函数。没有发起搜索或其他 HTTP，没有读取运行配置、环境变量、凭据、Cookie 或容器日志，没有修改应用/容器配置。

## 结论

**未发现本地查询截词或 URL 编码缺陷。** 两次既有实验共 6 个真实 `/search` URL 均完整传入查询；保存的 SearXNG JSON 也回显完整查询。直接取当前容器 `RawTextQuery`、Bing `request()` 和 curl_cffi `requote_uri()` 的函数定义做离线重建，6/6 的最终 `q` 解码后与完整查询一致，仅多余空格被标准化。

这不证明 Bing 真实收到了完全相同的出站请求，也不证明它遵守了全部词面和 `site:`。历史实验未捕获 SearXNG → Bing 的请求 URL、重定向链或 Bing 原始 HTML；运行时插件、响应缓存/路由、搜索查询重写或降级行为仍未定位。不能把当前现象归因为“编码 bug”、某种代理行为或 Bing 的确定机制。

## 已有真实记录

| 报告 | 3 次查询的变化 | HTTP/原始结果 | 结果表现 |
| --- | --- | --- | --- |
| `dynamic-live.json` | `Artificial Intelligence for Beginners` + video tutorial / course lesson / `(site:microsoft.github.io)` | 全部 200，各 10 条；无 unresponsive_engines | 3 次 URL 列表完全一致，主要是 Artificial 字典、电影和视频页面 |
| `dynamic-course-id-live.json` | `AI-For-Beginners` + 同样查询模板和 site 限定 | 全部 200，各 10 条；无 unresponsive_engines | 3 次 URL 列表完全一致，主要是 OpenAI、Gemini、IBM、ChatGPT 等 AI 入口 |

两次 site 查询都 10/10 域不匹配，应用因此返回 0 个该域候选。原始结果实际不包含 `microsoft.github.io`，不是应用域过滤误删了符合该域的条目。各响应文件 SHA-256 与原报告记录全部相符。精确 URL、完整查询、响应哈希验证和离线重建输出见 `bing-query-readonly-review.json`。

## 本机代码证据

镜像为 `ghcr.io/searxng/searxng@sha256:ddd642cae6eac75412938fd846ddbf440a2df029cfeae8a562b8b205f4e35e25`；容器 `knowledge-sprite-searxng-1`。公共源文件的原字节快照与 SHA-256 已保存，以下行号对应 `bing-readonly-sources/` 中的快照。

- 应用 `backend/app/providers.py:268–272` 把完整 `query` 放入 `params['q']`，通过参数编码发送；前面的 bang 清理不改变这 6 条输入。
- `webadapter.py:251–254` 用 `RawTextQuery(form['q'])`，取 `getQuery()`。`query.py:287–306` 按空白拆分，仅 `!`、`!!`、`:` 开头的语言指令及 `<` 等已知指令可能被单独解析；这些输入没有这种指令。`(site:...)` 和普通 `site:...` 都保留；`query.py:323–324` 用空格连接所有用户查询部分。
- `search.py:105` 把完整 `self.search_query.query` 交给引擎。`online.py:232` 调用 `engine.request(query, params)`，`:211` 把整个 `params['url']` 交网络层。
- `bing.py:79–90` 构造 `{'q': query, 'adlt': ...}` 后直接 `urlencode(query_params)`。区域仅增加 `setlang/cc`，不拆查询。它不是官方 Bing API，而是 HTML 搜索引擎实现。
- `network.py:283` 直接调用 `client.request(method, url, ...)`；`client.py:23` 的 `AsyncClient` 没有覆盖请求 URL 构造。
- 安装的 curl_cffi 为 0.16.3；`curl_utils.py:687–696` 处理可选参数后 `requote_uri(url)`，最后 `CurlOpt.URL = url.encode()`。离线测试覆盖当前编码路径，`+`、连字符、括号和 `%3A` 均保留正确查询含义。

重建时 locale/safesearch 使用显式测试值 `en-us/off`，并非从运行配置读取。它们不影响 `q`。没有导入或初始化 SearXNG 应用，也没有调用网络模块。测试仅运行白名单 AST 定义。

复现（项目根目录）：`.\.venv\Scripts\python.exe reports/runtime-revision-20261014/reproduce_bing_query_offline.py`。结果为 `checks=6, all_checks_passed=true, within_group_result_urls_identical=true, requests_sent=0`。

## 仍未知与最小后续建议

现有材料只能确认“应用完整发送、SearXNG 完整回显、已审公开构造路径没有截词、上游返回结果没有满足完整意图”。SearXNG HTTP 200 表示其接口成功响应，不能当成搜索语义质量通过。

不建议凭这些记录修改 URL 编码或放松相关性/域过滤，也不建议重新搜索来替换失败。若之后单独授权新的受控诊断，最少需要同时记录单次引擎准备发送的脱敏 URL、最终响应 URL/状态/重定向次数、原始 Bing HTML 的哈希及公开标题/查询提示，以定位发生在哪一层；不记录认证头、Cookie 或凭据。当前轮次没有执行该网络诊断。
