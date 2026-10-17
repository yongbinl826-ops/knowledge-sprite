# 官方项目与规则参考

核对日期：2026-10-14。用于实现选择与边界核对，没有安装下列新依赖，也没有复制其项目代码。Star 为当日 GitHub API 读数，不能代表质量或本项目验证。

| 项目 | 当日参考 | 本轮采用与不采用的原因 |
| --- | --- | --- |
| [SearXNG](https://github.com/searxng/searxng) | 约 38.4k stars，AGPL-3.0 | 沿用已安装的实例，显式指定已有引擎组。官方 [Search API](https://docs.searxng.org/dev/search_api.html) 说明查询由引擎解释，不能把 site 查询或 HTTP 200 当作相关结果保证。本轮加内容失败判断和独立备用组。 |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | 4,163 stars，MIT | [评分接口](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html)可做文本相似度，但相似字符串不能纠正 managers / context managers 的概念差异，故未引入。 |
| [RQ](https://github.com/rq/rq) | 10,693 stars，[BSD-2-Clause](https://github.com/rq/rq/blob/master/LICENSE) | 参考[任务生命周期与 worker](https://python-rq.org/docs/workers/)及[失败处理](https://python-rq.org/docs/exceptions/)。当前不引入 Redis/Valkey，Windows worker 的限制也不能跳过实际验证。 |
| [Dramatiq](https://github.com/Bogdanp/dramatiq) | 5,329 stars，[LGPL-3.0](https://github.com/Bogdanp/dramatiq/blob/master/COPYING.LESSER) | 参考[故障与重试分类](https://dramatiq.io/guide.html)。默认重试策略不适合本项目固定外部请求预算，未直接采用。 |
| [Celery](https://github.com/celery/celery) | 28,973 stars，[BSD-3-Clause](https://github.com/celery/celery/blob/main/LICENSE) | 官方[介绍](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)不支持 Windows；当前本机单 worker 没有引入它的必要。 |

为修复真实证据中的误删，仅采用两项有官方语义依据的有限术语等价，不设 URL 白名单：

- SQL 上下文中的 `ROW_NUMBER` / `row number` 属于窗口函数，保留函数应用相关链接；不据此断言覆盖所有窗口函数。[Microsoft Learn](https://learn.microsoft.com/en-us/sql/t-sql/functions/row-number-transact-sql?view=sql-server-ver17)
- 同一证据明确出现 CSS Grid、explicit，并给出 `grid-template-columns` 或 `grid-template-rows`，可支持显式轨道主题；只有泛 Grid 或尺寸调整标题仍不足。[W3C CSS Grid 规范](https://www.w3.org/TR/css-grid-1/#explicit-grids)

对应规则记录在 match.topic_match_rules。其余英文复合知识点仍采用保守的完整词面判断；任意术语翻译与语义泛化没有获得验证。
