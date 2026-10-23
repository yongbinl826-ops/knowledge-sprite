"""Three real source queries and at most four independent safe video reads.

No production DB access, application state changes, or injected candidate URLs.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.providers import SerperProvider, SearchError, QueryBudgetReached, SearchBudgetReached
from backend.app.fetcher import Fetcher, FetcherConfig, NETWORK_OBSERVER, FETCH_DEADLINE_AT
from backend.app.ai_video_fallback import direct_video_url
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation

OUT = Path(__file__).resolve().parent
QUERIES = ['site:bilibili.com/video/ "streamlit" "上传下载"', 'site:bilibili.com/video/ "streamlit" "下载按钮"', 'site:bilibili.com/video/ "streamlit" "多媒体提供"']


async def main():
    settings = Settings.from_env()
    provider = SerperProvider(settings)
    fetcher = Fetcher(FetcherConfig(enabled=settings.fetch_enabled,
        timeout_seconds=settings.fetch_timeout_seconds, global_concurrency=settings.global_concurrency,
        min_interval_seconds=settings.fetch_min_interval_seconds,
        allowed_restricted_hosts=settings.allowed_restricted_hosts, denied_hosts=settings.denied_fetch_hosts,
        bilibili_public_metadata=settings.bilibili_public_metadata,
        dns_resolver=settings.dns_resolver, phased_timeouts=settings.fetch_phased_timeouts,
        body_idle_timeout_seconds=settings.fetch_body_idle_timeout_seconds,
        body_min_bytes_per_second=settings.fetch_body_min_bytes_per_second,
        body_timeout_cap_seconds=settings.fetch_body_timeout_cap_seconds))
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "production_db_writes": 0,
              "production_config_changes": 0, "injected_urls": False, "mocked": False,
              "logical_query_limit": 3, "physical_search_limit": 6, "detail_candidate_limit": 4,
              "search_requests": 0, "detail_http_requests": 0, "queries": [], "details": []}
    pool = {}
    for index, query in enumerate(QUERIES):
        used = 0
        async def count():
            nonlocal used
            if used >= 2 or report["search_requests"] >= 6:
                raise QueryBudgetReached()
            used += 1
            report["search_requests"] += 1
        with provider.query_scope(count):
            row = {"query": query, "status": "completed", "candidates": []}
            try:
                candidates = await provider.search(query, "zh", 10, ["bilibili.com"])
            except SearchBudgetReached as error:
                candidates = error.partial_candidates
                row.update(status="partial", error_code="query_budget_exhausted")
            except SearchError as error:
                candidates = []
                row.update(status="failed", error_code=error.code)
            row["provider_requests"] = deepcopy(provider.last_requests)
            row["candidates"] = [candidate.model_dump() for candidate in candidates]
            report["queries"].append(row)
            for order, candidate in enumerate(candidates):
                url = direct_video_url(candidate.url, ["bilibili"])
                if url is None or url in pool:
                    continue
                title = candidate.title
                score = int(bool(re.search(r"download_button|文件下载|下载按钮|上传下载", title, re.I))) * 100
                score += int(bool(re.search(r"下载|download|导出|export", title, re.I))) * 20
                score += int(bool(re.search(r"streamlit", title, re.I))) * 5
                score += int(bool(re.search(r"下载|download|导出|export", candidate.snippet, re.I)))
                pool[url] = {"candidate": candidate.model_dump(), "source_query_index": index,
                             "source_order": order, "observed_text_priority": score}
            print(json.dumps({"query": query, "status": row["status"], "candidates": len(candidates),
                              "physical_requests": used, "error_code": row.get("error_code")}, ensure_ascii=False), flush=True)
        (OUT / "searches.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    selected = sorted(pool.values(), key=lambda row: (-row["observed_text_priority"], row["source_query_index"], row["source_order"]))[:4]
    report["selected"] = selected
    async def before_detail():
        if report["detail_http_requests"] >= 20:
            raise TimeoutError("diagnostic_detail_http_budget")
        report["detail_http_requests"] += 1
    observation = NETWORK_OBSERVER.set({"before_target_http": before_detail})
    deadline = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + 120)
    point = {"knowledge_point_id": str(uuid4()), "text": "文件下载", "technology": "Streamlit"}
    request = SearchRequest(knowledge_points=["文件下载"], topic_technologies={"文件下载": "Streamlit"},
                            preferred_platforms=["bilibili"], language="zh")
    try:
        for choice in selected:
            resource = await fetcher.enrich(choice["candidate"])
            resource["resource_id"] = "res_" + hashlib.sha256(resource["canonical_url"].encode()).hexdigest()[:24]
            own_evidence = [row for row in resource["evidence"] if row["kind"] in {"page", "catalog"}]
            related = related_recommendation(point, resource, own_evidence, request)
            relevant_chapters = [row for row in resource.get("chapters", []) if re.search(
                r"下载|download|导出|export", row.get("title", ""), re.I)]
            report["details"].append({"candidate": choice["candidate"], "resource": resource,
                "own_page_related_match": related, "download_chapters": relevant_chapters,
                "playback_verified": False})
            print(json.dumps({"title": resource.get("title"), "url": resource["canonical_url"],
                "fetch_status": resource.get("fetch_status"), "video_evidence_status": resource.get("video_evidence_status"),
                "chapters": len(resource.get("chapters", [])), "download_chapters": relevant_chapters,
                "own_page_related": related is not None}, ensure_ascii=False), flush=True)
            (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        NETWORK_OBSERVER.reset(observation)
        FETCH_DEADLINE_AT.reset(deadline)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["fetch_trace"] = list(fetcher.request_trace)
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())

