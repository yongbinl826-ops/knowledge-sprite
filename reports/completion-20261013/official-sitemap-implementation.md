# MIT 官方发现：实现、边界与修复验证入口

日期：2026-10-13。生产源码、验证 runner 与 scope 已冻结；本报告编写时尚未执行新的真实修复验证。旧 held-out 失败与原始报告保留，以下离线结果不是联网覆盖率或播放验收。

## 配置与发现链

默认仍为 `SEARCH_PROVIDER=searxng`。`SEARCH_PROVIDER=official_sitemap` 明确选择仅 MIT OCW 的来源；`OFFICIAL_SITEMAP_FALLBACK=false` 默认关闭，启用后仅在主来源正常空结果且查询域范围包含 MIT 时尝试。主来源的拒绝访问、限流或配置失败不会触发官方回退。

`OFFICIAL_SITEMAP_CACHE_TTL_SECONDS=21600`（0–86400）；`OFFICIAL_SITEMAP_CHILDREN_PER_QUERY=1`（1–2）。没有新生产依赖。生产不读取 reports 中保存的探针 XML。

来源链是实际 robots 声明 → 同源根 sitemap → 完整原知识点/版本词面匹配的课程子 sitemap → 子 sitemap 的真实 `<loc>`。XML 只接受 UTF-8 和规定命名空间，拒绝 DTD/实体、非同源 URL 和过量响应；不通过删除 `/sitemap.xml` 拼造课程页。没有匹配即返回 0，不能把细知识点扩大成宽泛课程。

候选保留独立 `discovery_evidence`：实际 loc、来源 URL/hash/UTC、根索引身份、缓存命中与低置信 URL 路径标题。路径词只用于有限召回，不是页面教学覆盖。最终纯官方候选必须有真实 page/catalog 原知识点与版本覆盖，并有独立课程或视频类型依据。混入普通搜索证据时，官方路径标题/摘要仍不参与规则或 LLM 相关性；实际普通搜索证据可按原规则使用。可靠 Course 页面可以是无视频证据的课程，不能称为已播放或含视频已核验。

## 预算、隔离与缓存

官方索引复用现有安全 Fetcher、公网 DNS 校验、IP 钉住、TLS 主机身份、robots/站点规则、重定向检查及共享网络槽。官方发现重试为 0，target HTTP 包括 robots、根图、子图、重定向，计入任务 `search_requests`。它的实际 DoH A/AAAA HTTP 单列 `progress.discovery_dns_requests` 和 attempt 的 `provider_dns_requests`，不按“每次解析必为两次”推算。详情 HTTP 与全部 DoH 的总上限由下述验证 wrapper 另外约束，不能把官方搜索计数误读为整个任务全部网络量。

Fetcher 的可选 `NETWORK_OBSERVER` 是按任务安装、finally 复原的替换式 ContextVar；默认无观察器时保持原行为。它不是可嵌套的总预算器。真实验证的 target transport / DNS resolver 独立 wrapper 在每次实际调用处计数，DNS wrapper 在 Provider 安装观察器后再组合当前计数钩子，覆盖索引、详情、目录、robots 和重定向。

官方 source 缓存按固定来源身份、策略、TTL、DNS、停采/允许域及解析版本隔离，不使用过期索引。启用官方模式或回退时，外层查询结果缓存关闭，避免从接近过期的索引产生一个新的长寿查询缓存；robots 声明、根图和子图使用自身 TTL。正常 SearXNG 模式缓存逻辑保持不变。

官方 source 的失败只暂停该来源。可选回退发生 SearchError 时保留真实失败请求，warning 含 `code=official_source_failed`、`source=official_sitemap` 与 `error_code`，MIT `last_status=fault`；主来源保持自身状态，后续主查询继续。主来源自己的拒绝仍按原规则停止，取消与任务预算异常不会被回退 catch 吞掉。该次 attempt 的 completed 指主来源正常空结果，不把其内部 MIT 403 请求改成 200 或成功。

## 离线验证与冻结

- 官方来源集成、独立边界和 runner 合计 61 passed，见 `official-sitemap-source-isolation.xml`；包含 MIT 403 / 配置错误后下一知识点主来源成功，以及主来源拒绝的停止反例。
- 独立 XML/URL/细词/版本/真实 loc 边界 43 passed，见 `official-sitemap-boundaries-final.xml`。
- runner 独立预算与停止测试 7 passed，见 `official-repair-runner-final.xml`；包括 robots、重定向、目录、第一次 DoH 失败实际计数、同源限制以及 401/403/429/带 Retry-After 的 503 全局停止。
- 根任务在最后源码冻结后完整后端回归 **372 passed + 26 subtests**，见 `backend-all-final-after-fallback.xml`。先前 362 项通过报告和早期失败报告均保留，不覆写失败历史。

## 唯一真实修复验证

scope 为 [official-repair-scope.json](official-repair-scope.json)，runner 为 [verify_official_discovery.py](../../scripts/verify_official_discovery.py)。在项目根目录手动运行一次：

```powershell
.\.venv\Scripts\python.exe scripts/verify_official_discovery.py
```

固定输入 `probability / geology / microeconomics`，是开发后选定的修复验证，不是独立 held-out。不启用模型、不从旧报告注入候选。走真实 JobService → 官方 Provider → Fetcher → 页面解析 → results。

硬上限为 12 次目标 HTTP、24 次实际 DoH HTTP、36 次合计；并发 1、重试 0、任务期限 180 秒；目标响应最多 2,000,000 字节，DoH 最多 65,536 字节。逐次解析和目标请求前核验 MIT 同源；访问限制、网络/大小/DNS 失败或预算到达后停止后续请求，保留触发响应、空结果和 partial，不替换主题、不重跑。

新鲜隔离数据库为 `reports/completion-20261013/official-repair.sqlite3`，结果为 `official-repair-live.json`。已有任一 DB/结果文件即拒绝重跑。报告保存每次实际请求 UTC、HTTP/错误、截断、来源 hash、真实响应文件、完整任务/证据、独立页面/目录审核、源码前后 hash 和旧 held-out hash。源码 hash 递归包含 source_adapters。不要把 runner 退出成功当作课程或目录验收通过。

验证完成后可由根任务使用该隔离 DB 在本机 8001 展示已保存任务；8000 与正式 DB 不变。查看结果接口不需要重新提交检索。本报告不预告本次网络结果；实际状态以唯一生成的 live JSON 为准。
