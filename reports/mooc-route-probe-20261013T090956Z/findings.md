# MOOC / 学堂查询路由诊断

2026-10-13。主应用在诊断阶段保持冻结；8 次本机 SearXNG 对照请求及已发出的 2 次 Bing HTML 对照请求均保存，未请求已被验证码/拒绝的引擎，未新增服务或凭据。后续只做离线分析与 mock 测试。

## 观察

| 主题 | 限定站点 | Bing 原始/域内 | DuckDuckGo videos 原始/域内 |
| --- | --- | --- | --- |
| Python 列表与字典 课程 | icourse163.org | 10 / 0 | 60 / 60 |
| Python 列表与字典 课程 | xuetangx.com | 10 / 0 | 0 / 0 |
| linear algebra eigenvalues course | icourse163.org | 10 / 0 | 2 / 2 |
| linear algebra eigenvalues course | xuetangx.com | 10 / 0 | 0 / 0 |

全部 8 次 SearXNG 响应为 HTTP 200，`unresponsive_engines=[]`。Bing 的 40 条原始结果全部为目标域之外的 URL；同主题只替换 site 条件，结果仍相同。Python 查询前列是 python.org 等普通网页，英文 linear algebra 查询前列反而是 Visual Studio Code 网页。过滤结果为零符合域名约束，没有把这些外域结果伪装成 MOOC/学堂课程。

固定镜像的官方 `bing.py` 将完整 query 交给 `urlencode` 写入 `q`，没有移除 site 语法；响应解析也包含 Bing `ck/a` 跳转链接解码。直接调用同一官方 URL 构造函数的两次 HTML 对照中，生成 URL 的解码 q、响应的搜索框与标题都保留完整 site 条件，但结果依然为外域。这支持“当前 Bing 上游返回不遵守/未有效满足限定查询”，不能进一步确认其服务端原因。不是已证实的查询编码或应用域名过滤故障。直接对照使用容器内 urllib，和 SearXNG 生产网络传输实现不相同，该差异保留在报告中。

官方 Bing 文档说明 `site:` 用于限定网站，冒号后不加空格，同时说明功能可能受地区影响：[Advanced search keywords](https://support.microsoft.com/en-us/bing/advanced-search-keywords)。这里没有根据这一说明推断具体故障原因。

DDG videos 的 MOOC 结果均是真实索引返回的课程入口；搜索视频模板仅为搜索级视频证据，不能当作课程页面核验。学堂本次没有命中，不能声称修复后已支持其真实检索结果。未在应用中硬编码这些课程 URL。

## 获授权的最小修复

`generate_queries` 原本就给所有平台限定查询附加 `视频教程` 或 `video tutorial`。旧 provider 仅因存在 `domain_filters` 强制排除了视频路由，使这些查询改走当前异常的 Bing。现移除这一排斥条件：只由查询的视频意图与服务端 `searxng_video_engines` 配置决定视频路由，仍把完整 site 查询送到上游，并在返回后执行同样的域名过滤。没有按平台或知识点写例外。

新增每次真实 provider request 的 `filter_counts`、`candidate_trace`、`candidate_trace_omitted`，追踪最多 20 条、每个 URL 最多 500 字符；仅反映通过本地 URL 安全规范化的公开 HTTP(S)地址，去掉 query/fragment，不反映凭据或内网 URL。保留原候选 URL 的 SHA-256 便于核对；过滤摘要覆盖所有原始条目，包括结果限额之外的条目。已有持久化及缓存历史记录自动保留这些字段。超过 4096 字符的候选 URL 明确丢弃，不再截断成另一 URL。

provider 缓存身份从 3 升至 4，旧记录保留；页面 extractor 缓存版本仍为此前的 4。本次修复未改变限流、权限拒绝、引擎暂停或回退规则。

`uv run --frozen pytest tests/test_core.py tests/test_provider_routing.py -q`：78 passed。包括中文/英文生成站点查询的视频路由、回退请求预算、访问拒绝硬停止、过滤追踪边界/脱敏、缓存历史保留。未执行修改后的真实网络验收，留给统一验收。

## 文件与诊断过程限制

- `report.json` 与 `response-01.json` … `response-08.json`：每次请求原始 JSON、完整查询、HTTP 状态、结果 URL/标题/引擎及过滤原因。
- `official-image-bing.py`、`official-image-duckduckgo_extra.py`：固定官方镜像中的源码副本，哈希和镜像 digest 在 report.json。
- `bing-direct-report.json`、`bing-direct-1.html`、`bing-direct-2.html`：两次 HTML 对照。该报告第一次离线 HTML 解析没有显式指定 UTF-8，导致中文字段显示乱码；原始已按 UTF-8 保存 HTML 完整，`bing-direct-utf8-observations.json` 从原始保存 HTML 离线正确解码，不重新发出请求。
- `bing-direct-launch-error.txt`：早先容器诊断脚本因不存在 httpx 而在发请求前失败；改用标准库 urllib 后产生上面的两次网络请求。随后 Windows 控制台 GBK 打印失败发生在报告已保存之后，未因此重试网络。

最小建议：使用修复后的通用视频意图路由做统一真实验收；学堂若仍为零就保留真实“未找到”与平台未验证边界。当前证据不支持新增第三方引擎、削弱域名过滤或预置课程答案。
