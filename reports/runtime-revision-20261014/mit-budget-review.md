# MIT 有界正文预算与完整发现链：只读审查

2026-10-14。只读生产实现、旧 JSON 与脚本；本报告不修改生产代码，不发外网请求，不重用旧 XML 为候选或缓存。root 为本轮唯一生产实现写者。所有预算值在本文件中均为实施建议，尚非新实网结果。

## 证据与诊断边界

- 最早完整 root XML：363036 B，正文阶段 5.165452 s，平均约 68.63 KiB/s；来源是 `completion-20261013/mit-discovery-probe.json`。
- 最近分阶段失败：已收到 HTTP 200，259803 B / 固定 10 s 正文预算，按预算区间约 25.37 KiB/s；`body_total` 触发，`body_idle=5s` 未触发。来源为 `completion-20261013/mit-transport-revision-live.json`。
- 最近失败只证明该次传输未在 10 s 读完；不证明 10 s 期间匀速、不证明新响应总长仍为 363036 B。该响应 Content-Length 未进入遥测，不能用旧长度补填。
- 更早 `official-repair-live.json` 的失败阶段仍 unknown，不能回填为 body_total。

现代码在 `fetcher.py` headers 后使用 `min(bodycap, max_bytes / Rmin)`，未以本次 Content-Length 选择所需字节规模；上轮新 scope 强制 bodycap=10。外围 `_request` 总期限为首响应 timeout + bodycap，即 20 s；调整正文计算时必须同时明确外围总上限，不能只改内层 timer。

## 建议：一次确定的绝对期限

保留身份、DNS/IP/SNI、robots、字节、访问停止、零重试和整体任务期限。不同阶段定义如下，所有绝对时间使用同一个 monotonic/event-loop 时钟：

1. `Djob` 是任务启动时确定的绝对结束时间。DNS、同主机等待、网络槽等待和 CPU 处理均消耗它，不在进入某个阶段时重新开始。
2. 每次 HTTP 开始时记录 `t0`，固定首响应上限 `H`、正文硬上限 `Bhard`，设 `Drequest=min(Djob,t0+H+Bhard)`。headers 阶段结束期限为 `min(Drequest,t0+H)`。
3. 收到 headers 后，合法非负整数 Content-Length 不超过本次响应字节 cap `C` 时，使用 `S=Content-Length`；无长度时 `S=C`。超大长度立即停止读取；异常长度按 HTTP framing 错误拒绝，或显式记录 unknown 并使用 C，不能给出额外授权或猜长度。
4. 从 headers 到正文结束，选择 `Tsize=I+S/Rmin`，其中 `I` 为一次固定空闲余量，`Rmin` 为明确配置的最低可接受平均吞吐政策。`Dbody=min(Drequest,Djob,theaders+Bhard,theaders+Tsize)`。此 deadline 设置一次，各 chunk 不重置或延长。
5. 每次等下一 chunk 的空闲期限为 `min(I,Dbody-now)`；外围等待仍不能超过 `Drequest-now`。剩余时间非正时在计数/解析/发起 HTTP 前停止。外部取消原样传播，partial body 不进入提取器和成功缓存。

固定 idle 余量的作用是避免 64 B robots 等小响应出现 `64/Rmin` 只有数毫秒的不合理正文期限；它只加一次，不按 chunk 追加。请求最多等 `H+Bhard`，全任务仍最多到 Djob。若剩余任务不足，不为追求目录而扩展总体 deadline。

一个可审议配置是 H=10 s、I=5 s、Rmin=16 KiB/s、Bhard=30 s，HTTP 总最多 40 s。这是允许较慢传输的有界政策，低于最近实测平均 25.37 KiB/s；不能称为测得的真实最低速度或保证成功。以旧 363036 B 仅做算例，正文预算为 27.158 s；未知长度且 C=500000 B 时最多 30 s。新请求必须使用自身 headers，禁止直接把旧 363036 B 写进预算。root 若采用不同政策，应在新 scope 固定后再执行。

预算实现宜使用独立 job deadline ContextVar，避免放在会被 `OfficialSitemapProvider.search` 替换的 NETWORK_OBSERVER 字典中。当前 service 已有 asyncio.timeout 总体取消保护，但 transport 无法读出剩余 job 时间；建议显式传递并 finally 复原，子任务自动继承，不能跨任务串值。渲染自身更短 deadline 可取最小值，但不替换任务 deadline。

遥测建议新增：本次 Content-Length 的合法/unknown 状态及有限数值、selected_size、byte_cap、rate/idle/phase cap、各阶段绝对期限或剩余预算、触发 budget 的具体原因。延续已有阶段/partial bytes/hash，不保存请求凭据或原始 headers。必须区分 body_idle、body_total、request_total、job_deadline、用户取消。

## 索引到页面/目录的请求与缓存

新鲜 SQLite、同源无重定向、没有其他失败时，预期最少链为：

| 请求 | 准入来源 | 预算归属 |
| --- | --- | --- |
| robots | 官方固定 origin 的 robots | 1 target、最多 2 DoH；官方 search HTTP |
| root XML | 本次 robots 实际声明 | 1 target、最多 2 DoH；官方 search HTTP |
| 一个 child XML | 完整原知识点/版本词面匹配的实际 index loc | 1 target、最多 2 DoH；官方 search HTTP |
| course/resource page | child 内实际 loc，不剥 sitemap 路径拼造 | 1 target、最多 2 DoH；1 detail 资源单位 |
| catalog page（若实际存在） | 课程页实际同课程 video_galleries 链接 | 1 target、最多 2 DoH；1 catalog/detail 单位 |

因此同源正常路径为 5 target / 最多 10 DoH；6/12 的整体预算可容纳 1 次额外跳转，但不能保证所有重定向模式都完成。若课程实际没有目录导航，必须保留 course 已核验、目录 unknown，不更换 child 来追求成功。默认一个子图、一个候选；课程与目录类型证据各自独立，播放仍未验证。

`search_requests` 只覆盖官方发现期前三项；`details_attempted`/`catalog_pages_attempted` 是资源单位，不能当作后两项实际 HTTP 的全部计数。robots、重定向、失败请求均可能增量，故整条链的 6 target/12 DoH 硬限制仍需在共享 transport/resolver wrapper 逐实际调用执行，而非只配置 max_search_requests 和 max_detail_pages。每个预算耗尽检查应先于下一次 DNS/HTTP，计数在真实发出前预留。

已确认缓存边界：

- root/child 只有完整 fetch 并通过 parse_sitemap 后才 `_put`；partial root 不入官方 source cache。上轮 partial hash 不是可读索引。
- robots 声明、root、child 按来源 URL/解析版本/TTL/DNS/允许与停采策略区分，source TTL 默认 21600 s。只读命中不修改原 observed_at；缓存不等于本次 HTTP。
- 官方模式/回退关闭外层 query cache，避免基于临近过期 index 产生更长寿的结果缓存；真实页面缓存另有证据隔离与不完整目录策略。
- Fetcher robots 规则有自身 3600 s TTL；需要真实网络读取页面/索引时仍经 Fetcher 规则检查。一次验证应使用独立 fresh SQLite/Fetcher，防旧 index 或 page cache 掩盖传输结果；不是清空正式库。
- `_stopped_code` 仍在 Provider 实例内保持失败暂停；本轮未建议在同一次验证中恢复或重试。使用新的受控验证实例属于新授权实验，不是自动重试。访问拒绝/Retry-After 停止规则不变。
- 独立构造 `OfficialSitemapProvider(settings)` 时默认创建 Fetcher 的分支尚未复制 phased 新字段；JobService 注入 shared Fetcher 和现验证 runner 显式注入 Fetcher 的主链不受影响。若 root 修改构造路径，应补兼容测试，防配置为 phased 实际却未启用。

## 建议离线测试

1. 有 Content-Length 的固定期限来自自身长度；改变 cap 不改变合法已知长度的预算，长度缺失才按 cap。0/负/布尔/无限/逗号冲突/超长 header 不放宽时间或字节授权。
2. headers 消耗 9 s、正文 20 s 可在 request hard cap 和 job剩余充足时结束；bodycap 增加而外围仍旧 20 s 的错误必须被回归抓到。
3. 小 robots 在一次 idle 余量内完成；慢 trickle 到固定 body deadline 即结束，频繁 chunk 不能延期。
4. job 仅剩 3 s 时，DNS/header/body 总和不能再借出 H+Bhard；NETWORK_OBSERVER 被 provider替换也不丢绝对 deadline；取消最终关闭流并保留 partial，后续 job deadline 不污染。
5. 五目标内存链 robots→root→child→course→目录，global=1，不猜课程 URL，真实 loc 和逐章 ID/hash/provenance 验证；第六请求到限后，下一次 DNS/HTTP 都不再发。
6. root partial 失败缓存为空；root完整成功第二次同 source 命中且保留原时间；TTL 到期后一次重新获取，不能用旧 XML 报告作为生产来源。实际 page 覆盖不足则仍不推荐。

本报告没有执行这些新增测试或新的实网批次。原失败记录、预算和 hash 保持原样。
