# 开源解析/采集工具研究与最小比较方案

研究时间：2026-10-13 10:49–10:56 UTC（北京时间 18:49–18:56）。本轮只读取官方 GitHub、PyPI、npm、官方文档和已发布 wheel 中的源码；没有安装生产依赖、修改应用、请求新的课程页面或启用浏览器。wheel 仅在内存解包选定源码用于审计，SHA-256 与 PyPI 公布值一致。

**选择 Scrapling 0.4.15 的 `Selector` 作为离线比较候选，暂不引入其网络采集器或 Crawlee 调度框架。尚未执行对照实验，字段提升、性能提升与本机运行兼容性均为 unknown。**

## 当前维护、版本与兼容性

星数来自 2026-10-13 10:49 UTC 的官方 GitHub API 快照，随时间变化，仅作为维护背景，不作为正确性或合规性指标。三个仓库均未归档、未禁用。

| 项目 | 当前稳定版本 / 发布时间 | 许可证 | 星数 / 最近推送 | Python 3.13 判断 |
| --- | --- | --- | --- | --- |
| [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling) | [0.4.15](https://github.com/D4Vinci/Scrapling/releases/tag/v0.4.15)，2026-08-23 | BSD-3-Clause | 87,175；2026-10-12 22:39 UTC | [PyPI](https://pypi.org/project/scrapling/0.4.15/) 要求 >=3.10，显式列出 3.13；包本身是 py3-none-any wheel。lxml/orjson 等原生依赖仍需隔离安装核验，本轮未运行。 |
| [apify/crawlee-python](https://github.com/apify/crawlee-python) | [1.10.4](https://github.com/apify/crawlee-python/releases/tag/v1.10.4)，2026-10-06 | Apache-2.0 | 9,586；2026-10-13 09:01 UTC | [PyPI](https://pypi.org/project/crawlee/1.10.4/) 要求 >=3.10，显式列出 3.13；声明兼容，未在本机安装/运行。 |
| [apify/crawlee](https://github.com/apify/crawlee) | [3.18.2](https://github.com/apify/crawlee/releases/tag/v3.18.2)，2026-09-29 | Apache-2.0 | 26,133；2026-10-13 08:48 UTC | 这是 JavaScript/TypeScript 项目，不是上述 Python 包；npm 当前声明 Node >=16，Python 3.13 不适用。引入会增加独立 JS 运行时/进程边界。 |

发布元数据、星数和推送时间分别保存在 `official-metadata-summary.json`、`*-repo.json`、`*-release.json`；源码清单及哈希在 `source-snapshot-manifest.json`。许可证取自仓库元数据及发布 wheel 自带 LICENSE，不把许可证当成目标网站采集许可。

## 解析与安全传输是两个独立判断

Scrapling 官方文档支持直接把 HTML 字符串/字节传给 `Selector`，提供 CSS/XPath 与属性读取；它不需要为了查询 DOM 重新请求 URL。[Selector 文档](https://scrapling.readthedocs.io/en/latest/parsing/main_classes.html)、[查询文档](https://scrapling.readthedocs.io/en/latest/parsing/selection.html)

固定发布版源码确认：`scrapling.__init__` 延迟导入，`Selector` 是 lxml HTML 包装；基础安装依赖与 `fetchers` 额外依赖分开。因此可只比较解析能力。`adaptive=False` 保持关闭，不使用历史 DOM 的相似重定位推测课程字段；显式 `huge_tree=False` 保留解析器的大树保护，沿用现有输入字节上限。传入 `url` 仅作为来源与相对链接解析上下文，实验不调用链接跟随。默认源码没有显式传 `no_network`；不能仅据此宣称全部外部引用路径已经验证，实验必须检查零网络访问。

Scrapling 的 HTTP fetcher 源码使用 curl_cffi，固定版默认 `impersonate='chrome'`，重定向默认 `safe`。这些功能不用于本任务。`safe` 重定向声明不等同于现有“每个 DNS 结果审核、连接钉住公网 IP、原始 TLS SNI、每跳 robots、全局/每 host 并发与统一预算”的完整链路。没有发现可以直接接入当前 HTTPX 安全 transport 并保证所有路径执行它的已验证方案，所以不直接联网替换。即使能关闭某个 impersonation 参数，也不解决整条传输链的等价验证问题。[发布版源码](https://github.com/D4Vinci/Scrapling/blob/v0.4.15/scrapling/engines/static.py)

Crawlee Python 官方提供可插拔 `HttpClient`，自定义客户端需处理 `crawl`、`send_request`、`stream` 及资源清理；从架构上可以将这些入口统一委托给现有安全传输，但需要实现与测试。[官方指南](https://crawlee.dev/python/docs/guides/http-clients)、[接口](https://crawlee.dev/python/api/class/HttpClient)

固定 1.10.4 wheel 的 `crawlee/http_clients/_httpx.py` 明确说明，`HttpxHttpClient` 的 `mounts` 和 `transport` 参数会被忽略；传入现有 DNS-pinned transport 不会自动生效。该版本使用 **httpx2**，不是本项目现有 httpx。`BasicCrawler` 默认 `respect_robots_txt_file=False`、`retry_on_blocked=True`，默认客户端为 Impit；这些默认值不能直接用于本任务。必须显式关闭绕过/指纹/代理行为，验证所有导航、robots、sitemap、重定向与辅助请求路径，才可考虑替换。[固定发布版源码](https://github.com/apify/crawlee-python/blob/v1.10.4/src/crawlee/http_clients/_httpx.py)

另有官方已披露的 sitemap SSRF 历史问题：受影响到 1.6.3，1.7.0 起修复。本次候选 1.10.4 高于修复版本；这不证明其默认设置满足本项目全部 DNS/robots 安全边界。[官方安全公告](https://github.com/apify/crawlee-python/security/advisories/GHSA-3r75-xc34-5f44)

结论是保留现有 Fetcher 负责已许可 HTTP 请求；解析器只消费它已经获得的内容。JS Crawlee 和 Python Crawlee 都有用途，但本项目已有有界队列、证据持久化、并发与恢复机制，当前没有证据证明替换整套框架比单独改进字段适配更小、更可靠。curl_cffi 已作为 Scrapling 可选传输依赖审查，不单独引入；本轮不需要扩大到 Crawl4AI 或新增浏览器依赖。

## 可实施的最小离线比较

1. 冻结四份既有、经允许 HTTP 链路获得的 HTML：MIT 课程主页、真实视频目录、视频页，以及 Archive 内嵌 playlist 页面。对应路径、字节数、SHA-256、原采集报告写在 `tool-research.json`。只读这些文件，不跟随页面链接，不新抓取平台。真实课程发现仍以原搜索证据为准，测试文件不能注入在线候选。
2. 在独立临时环境以 Python 3.13 安装固定 `scrapling==0.4.15` 的基础包，不用 `[fetchers]` / `[all]`，不改项目 `.venv`、pyproject 或锁文件；记录完整解析依赖及哈希。本步尚未执行。
3. A 组为现有 `MetadataExtractor` / BeautifulSoup(`html.parser`)；B 组用 `Selector(content=html, url=source_url, adaptive=False, huge_tree=False)`。给两组**相同字节、相同字段规则、相同 JSON-LD 和章节语义校验**。先用等价 CSS/XPath 做严格对照，再单独标记新增适配规则的收益，不能把“新增规则”冒充“更换解析器”的收益。
4. 比较标题、简介、作者、语言、日期、时长、资源类型、独立视频证据、章节标题/顺序/数量、来源 URL 与时间字段。每项差异必须指出原 HTML 位置/属性和证据；没有的数据保持 null。普通 Course/大纲不得升格为视频；Archive 媒体文件名不得臆造为章节页面 URL；已有页面证据不能代表可播放性。
5. 另建明确标记的合成负例：畸形 HTML、普通大纲、错误页/登录页、空目录、外部引用/脚本/图片标签。实验进程禁止网络，记录任何尝试；不得调用 Fetcher、浏览器或动态执行。它们用于边界测试，不替代真实 HTML 的效果评估。
6. 首要指标是有证据字段增量、错误字段与回归、章节及证据引用一致性；耗时只作为次要描述指标。若相同规则下没有实际收益，保留 BeautifulSoup。通过兼容性或速度测试不能升级为网站权限、搜索覆盖或在线生产验收。

验收前仍为 unknown：隔离环境依赖能否完整安装、零网络/外部引用测试是否通过、真实字段是否增加、解析时延及维护成本。研究阶段未执行这些实验，也没有更改生产行为。


## 后续授权实测（不覆盖上述初始研究快照）

2026-10-13T10:57:42.887036+00:00 至 2026-10-13T10:57:43.777973+00:00，已在独立 Python 3.13.5 环境完成四 HTML、每组 7 次的纯 Selector 实验。所有输出一致、新增非空字段 0；本轮决定保留 BeautifulSoup 并改进模块化语义适配，生产锁不变。上述研究时点的“尚未运行”保留为历史事实，当前已测范围、时延与未测边界见 [实测报告](selector-experiment.md)、[完整结果](selector-comparison.json)、[采用决定](selector-decision.json)。
