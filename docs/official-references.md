# 官方接口与依赖依据

核对日期：2026-10-13。实现调用 HTTP API，未引入未经核实的搜索 SDK 或平台私有 API。

| 资料 | 核对与实现用途 |
| --- | --- |
| [SearXNG Search API](https://docs.searxng.org/dev/search_api.html) | `/search`、`q`、`language`、`format=json`；定向查询使用 `site:`。 |
| [实际镜像对应的 SearXNG webadapter 源码](https://github.com/searxng/searxng/blob/ad46ebd7d87666edb5f116c5b274b47f689ac6cd/searx/webadapter.py) | `parse_generic` 验证 engines 参数按实例引擎名选择来源；API 文档未逐项列出此参数，因此同时核对固定版本源码与真实响应。 |
| [SearXNG engine settings](https://docs.searxng.org/admin/settings/settings_engines.html) | 引擎名称、分类、disabled 与 timeout 的定义；不启用未知凭据或规避访问拒绝的配置。 |
| [SearXNG search settings](https://docs.searxng.org/admin/settings/settings_search.html) | 显式启用 `search.formats: [html, json]`；不使用陌生公共实例。 |
| [SearXNG container installation](https://docs.searxng.org/admin/installation-docker.html) | 官方 GHCR 镜像、设置目录、缓存目录与本机端口映射。镜像固定 digest。 |
| [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search) | `POST https://api.tavily.com/search`、Bearer 认证、query/max_results/include_domains；关闭答案与原始正文。 |
| [HTTPX transports](https://www.python-httpx.org/advanced/transports/) / [httpcore SNI](https://www.encode.io/httpcore/extensions/#sni_hostname) | 静态 HTTP、测试替身、钉住已核验 IP 的 TCP 连接与原域名 TLS 验证。 |
| [Cloudflare DoH JSON](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/) | 可选固定可信解析出口，A/AAAA全部验证；默认仍为系统解析。 |
| [FastAPI server workers](https://fastapi.tiangolo.com/deployment/server-workers/) | 第一版固定单 worker；任务、缓存和证据在 SQLite。 |
| [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) | `uv.lock`、`uv sync --frozen`；完整依赖解析与安装。 |
| [Crawl4AI](https://docs.crawl4ai.com/) | 已核对。浏览器子请求出口隔离尚未实现，因此未安装、未启用、未宣称支持动态采集。 |
| [coursecreator](https://github.com/mkarjun/coursecreator) | 仅参考主题到学习资源的流程；没有复制预置视频、登录、游戏化、考试或付费功能。 |

具体软件版本见 `pyproject.toml`、`uv.lock`、`frontend/package-lock.json` 和 `reports/dependency-inventory.json`。文档存在不等于服务已经联网验收；验收边界见实现报告。

- [YouTube Terms: Permissions and Restrictions (3)](https://www.youtube.com/static?template=terms)：2026-10-13 核对，直接自动访问要求符合列明例外或书面许可；本应用不符合公开搜索引擎身份例外，停止直接抓取与 YouTube 直搜引擎。
- [SearXNG use_default_settings engines remove/keep_only](https://docs.searxng.org/admin/settings/settings.html#use-default-settings)：用于移除未经许可的直接平台引擎；最终本机实例仅保留明确选用的两类独立搜索引擎。

- [OpenLearn FAQ](https://www.open.edu/openlearn/about-openlearn/frequently-asked-questions-on-openlearn) 与 [Open University 网站使用条件](https://about.open.ac.uk/strategy-and-policies/policies-and-statements/conditions-use-open-university-websites)：核对公开学习内容与第三方材料边界；许可说明不能覆盖实际 HTTP 拒绝。本次 robots 403 已保留并停采，未据此宣称目录或课程页面可取。
- 动态渲染的新增成果仅为 [可审核 fixture 离线桥](../experiments/controlled-renderer/README.md)。复用现有 Playwright/Edge，未安装 Crawl4AI，未接入真实站脚本；普通路由拦截和 offline 不等于操作系统级网络隔离。
