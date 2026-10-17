# 第三方依赖与许可证

核对日期：2026-10-13。版本以实际安装结果和锁文件为准；本表许可证来自包元信息，完整传递依赖清单见 `reports/dependency-inventory.json`。这是软件来源记录，不替代发布时对许可证原文的核对。

| 组件 | 锁定版本 | 包声明许可证 | 用途 |
| --- | --- | --- | --- |
| Python | 3.13 系列，本机 uv 3.13.5 | PSF | 服务端运行时 |
| FastAPI | 0.143.0 | MIT | HTTP API |
| Uvicorn | 0.54.0 | BSD-3-Clause | 单 worker 服务 |
| Pydantic | 2.14.1 | MIT | 输入/结构化输出验证 |
| HTTPX / httpcore | 0.28.1 / 1.0.9 | BSD-3-Clause | HTTP 与 TLS SNI |
| Beautiful Soup | 4.15.0 | MIT | 静态 HTML 元信息 |
| python-dotenv | 1.2.4 | BSD-3-Clause | 服务端本地配置 |
| SQLite | Python 标准库提供 | Public Domain（SQLite 核心） | 任务、关系和证据持久化 |
| React / React DOM | 19.3.0 | MIT | 中文界面 |
| Vite | 8.3.4 | MIT | 前端构建 |
| TypeScript | 7.0.2 | Apache-2.0 | 前端类型检查 |
| Playwright | 1.64.0 | Apache-2.0 | 隔离浏览器流程测试；可选生产离线 DOM 补全 |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | MIT / Apache-2.0 | 后端测试 |
| SearXNG | 2026.10.11-ad46ebd7d | AGPL-3.0-or-later | 独立自托管搜索服务 |

SearXNG 官方镜像为 `ghcr.io/searxng/searxng@sha256:ddd642cae6eac75412938fd846ddbf440a2df029cfeae8a562b8b205f4e35e25`，本项目未修改其源码；[上游源码与许可证](https://github.com/searxng/searxng/blob/master/LICENSE)。SearXNG 与应用是独立进程，通过 HTTP 通信。部署、修改或分发 SearXNG 时应保留其许可证与相应源码义务。

`uv.lock` 锁定跨平台 Python 依赖和下载哈希；`requirements.lock.txt` 是不含测试依赖的带哈希导出。`frontend/package-lock.json` 锁定 npm 传递依赖及 integrity。Chromium 测试二进制由对应 Playwright 版本下载，不装入正式应用。

Tavily 与可选模型是外部服务，不作为离线开源库打包。本次未配置它们的账号/密钥，也没有购买额度。可选 Cloudflare DoH 会向 Cloudflare 发送待解析的课程域名，默认 `DNS_RESOLVER=system`；其固定端点依据[官方 JSON DNS 文档](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/)。

未引入 Crawl4AI、Nemo2011/bilibili-api 或平台私有接口。未复制 coursecreator 代码。Image Gen 概念图只作为设计与验收参考，页面文字和控件由 React 实现，不把概念图当作运行界面。

课程/视频的标题、摘要、页面元信息和链接仍归对应来源；这里只保存发现证据，不下载或转存视频，不重新授权内容。应用源码的最终分发许可证由项目所有者决定，本次未替其指定。
