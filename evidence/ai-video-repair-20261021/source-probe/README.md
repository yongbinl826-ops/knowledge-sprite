# Live source diagnosis, 2026-10-21

This directory contains bounded real discovery and page checks. No production database, provider routing, proxy or security settings were changed, and no candidate URL was injected into production code or search results.

## Findings

- Current `.env` routing: Bilibili uses `searxng`; MOOC uses `tavily`; both Tavily and Serper are configured; the SearXNG failover provider is unset. Bilibili public metadata fetching is enabled.
- Nine real search HTTP requests were made: five Serper and four Tavily. Retries were disabled only inside these diagnostic scripts to enforce the request cap. Standard ten-result queries were used. No access restriction or rate-limit response was observed.
- Serper found ten results each for `Python 列表 教程` and `pandas groupby 分组聚合`, under Bilibili video scope.
- The overconstrained `pygame Rect colliderect 碰撞检测` phrase returned zero Serper results and mostly unrelated Tavily results. The simpler `pygame 碰撞检测` phrase returned ten results from each provider. The narrower `pygame colliderect` phrase returned zero Serper results. Result counts alone do not establish relevance.
- Seven real candidate pages were fetched through the existing configured safe fetcher. All seven yielded `fetched` and `page_verified` metadata. Playback was not attempted, so `playback_verified` remains false.

## Grounded sample set

| Requested point | Real discovered video | Strict topic support | Related reference |
|---|---|---|---|
| Python 列表 | https://www.bilibili.com/video/BV1EXjAzaEAH/ | supported | yes |
| pandas 分组聚合 | https://www.bilibili.com/video/BV1388y6xEHt/ | supported | yes |
| pygame 矩形碰撞检测 | https://www.bilibili.com/video/BV1UoyKBCECZ/ | not established for rectangle-specific teaching | yes |

The current product's `related-reference-v1` policy accepts the Pygame collision tutorial as a relevant reference; the strict ranker does not claim the page proves rectangle-specific teaching. This distinction is preserved in `ranking-report.json`. These direct diagnostics are not end-to-end acceptance of the repaired service.

## Root cause and viable repair

The prior model-only fallback emitted stale/unconfirmed direct URLs and had no grounded retrieval alternative. Existing configured search services can obtain fresh real links. A bounded fallback can ask AI for plain search hints, search those hints with the configured independent provider, fetch the returned pages, and retain the existing page/type/relevance gates. Query expansion should avoid combining every implementation keyword into one phrase. A provider response or an AI suggestion is not page or playback verification.

## Evidence

- `search-report.json`: first six source requests and their actual candidates.
- `pygame-search-report.json`: three additionally authorized query simplifications.
- `details-report.json`, `pygame-details-report.json`, `pandas-details-report.json`: actual page evidence and safe-fetch traces.
- `ranking-report.json`: unchanged production strict ranker and related-reference projection applied offline to the fetched evidence.
- Python scripts reproduce the bounded diagnostic sequence; re-running them makes new real requests.
