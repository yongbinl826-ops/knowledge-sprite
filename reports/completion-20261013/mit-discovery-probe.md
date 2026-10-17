# MIT 官方发现路线：一次有界真实探针

日期：2026-10-13。生产源码、配置、数据库和已有 held-out 记录均未修改。此次不是重跑先前失败案例。

## 结论

MIT 官方公开 sitemap 索引可读取，适合作为后续独立发现路线的研究入口；**尚未证明可以按任意知识点动态返回相关课程，未实现或接入生产 Provider**。

`https://ocw.mit.edu/search/` 的静态 HTML 没有课程链接、搜索表单或明确的搜索 API 声明，只有供 JavaScript 使用的搜索挂载节点。robots 实际声明的 sitemap 是索引，里面的 2,588 条 URL 是子 sitemap 地址，不能直接当成 2,588 门已获取课程，更不能当成当前知识点的推荐结果。

## 预注册范围与实际执行

执行前已保存 `mit-discovery-probe-scope.json`，脚本为 `scripts/probe_mit_discovery.py`。起点固定为官方 `/search/`；沿途仅执行现有 Fetcher 的 robots、安全 DNS、TLS 主机验证、钉住公网 IP、状态限制与重定向规则。没有 browser/JS、媒体、搜索引擎、凭据或数据库请求。

主任务明确的预算：最多 4 次目标 HTTP（含 robots/HTML/XML/重定向）、DoH 最多 12 次，总计最多 16 次；并发 1、重试 0、期限 75 秒。目标最多 2,000,000 bytes，robots 最多 256,000 bytes，sitemap 最多 500,000 bytes，DoH 每响应最多 65,536 bytes。

实际用时 **21.707 秒**：目标 **3 次**、DoH **6 次**、合计 **9 次 HTTP**，全部返回 200；没有重定向、重试、截断或失败替换。未为了用满额度追加请求。所有任务依次等待前一个请求完成。每次目标请求均执行现有 A/AAAA 公网地址校验，解析 HTTP 单列，未将其隐藏在目标计数之外。

| 顺序 | 目标 URL | HTTP | 返回字节 | 来源 SHA-256 |
|---|---|---|---|---|
| 3 | `https://ocw.mit.edu/robots.txt` | 200 | 64 | `bc14953e303dd365bbcf48ed7a552baeb0bf6d03f3c426db7310e649d137a9f6` |
| 6 | `https://ocw.mit.edu/search/` | 200 | 9,835 | `7264e09eb1ab42e76a9d86e242692ecf4774cc68384b6c26c0f5444a65dd4f8b` |
| 9 | `https://ocw.mit.edu/sitemap.xml` | 200 | 363,036 | `a031e44f51efaf0a5fcda850d350de34b864d572c14705ebf047893f7325cd07` |

每个目标请求之前顺序执行两次固定 Cloudflare DoH HTTP，六次均为 200，每响应 253–386 bytes。完整请求 URL、UTC 开始/响应/读取时间、状态、错误字段、字节数、截断标记和响应哈希保存在 `mit-discovery-probe.json`。三份目标原文分别保存在 `mit-discovery-source-3.txt`、`mit-discovery-source-6.html`、`mit-discovery-source-9.xml`。报告还记录脚本、scope、Fetcher 和 URL 安全模块哈希。

## 观察及适用边界

1. robots 明确包含 `Allow: /` 与 `Sitemap: https://ocw.mit.edu/sitemap.xml`。它证明本次路径规则允许读取，不独立代表所有内容使用许可。
2. 搜索 HTML 中没有 `form`，没有可见课程首页链接；存在 `#search-page` 和 JavaScript 资源引用。仅有一份站点介绍型 JSON-LD，未声明可直接调用的查询接口。没有获取脚本资源或猜测 API。
3. sitemap 根类型为 `sitemapindex`，共 2,588 个不同 `<loc>`：2,587 个位于课程路径下的子 sitemap，加 1 个全站 sitemap。它们尚不是课程页面内容或教学主题证据。本轮按预注册规则不递归跟随。
4. 新探针词 `eigenvectors` 只用于预设可能的表单查询和后续离线索引文字比对。由于无公开表单，**未向网站提交该查询**。保存的子 sitemap URL 中没有字面命中此词；这不能说明 MIT 没有相关课程，课程主题或章节可能根本不在 URL slug 中。

## 最小可行后续方向（未执行）

若未来另行授权，可研究把 robots 实际声明的 sitemap 索引作为可更新、带源哈希的发现材料，并严格限制每次只读取从索引真实观察到的相关子 sitemap。只有从子 sitemap 的真实 `<loc>` 获取课程/讲次 URL 后，才能生成相应候选；不能简单去掉 `/sitemap.xml` 猜造首页，再声称是已观察的课程链接。

这条路线仍需解决英文课程 slug 对任意中文/英文细知识点的召回不足，以及索引缓存、单次详情预算、类型和相关性证据。当前证据不足以承诺它优于既有搜索链路。也不应为了评估而批量克隆 2,587 个子索引。若研究网站前端声明的公开查询能力，需新范围允许读取实际引用的脚本并先核查合法入口，不能本轮直接追加请求。

因此当前交付为真实探针和可审计原文；生产 Provider 保持冻结，不新增种子课程，不替换原 held-out 失败结果。
