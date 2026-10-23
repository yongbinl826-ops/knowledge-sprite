"""One safe, bounded public-page GET; no application database writes."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.fetcher import Fetcher, FetcherConfig, FETCH_DEADLINE_AT
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation

OUT = Path(__file__).resolve().parent
URL = "https://www.bilibili.com/video/BV1nxCXBtEy5/"

async def main():
    settings = Settings.from_env()
    fetcher = Fetcher(FetcherConfig(max_bytes=16_000_000, max_retries=0, max_redirects=0,
        enabled=settings.fetch_enabled, timeout_seconds=settings.fetch_timeout_seconds,
        min_interval_seconds=settings.fetch_min_interval_seconds,
        allowed_restricted_hosts=settings.allowed_restricted_hosts, denied_hosts=settings.denied_fetch_hosts,
        bilibili_public_metadata=settings.bilibili_public_metadata,
        dns_resolver=settings.dns_resolver, phased_timeouts=settings.fetch_phased_timeouts,
        body_idle_timeout_seconds=settings.fetch_body_idle_timeout_seconds,
        body_min_bytes_per_second=settings.fetch_body_min_bytes_per_second,
        body_timeout_cap_seconds=settings.fetch_body_timeout_cap_seconds))
    original_extract = fetcher.extractor.extract
    def capture(html, url, fetched_at):
        if url == URL:
            (OUT / "page.html").write_text(html, encoding="utf-8")
        return original_extract(html, url, fetched_at)
    fetcher.extractor.extract = capture
    deadline = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + 60)
    try:
        resource = await fetcher.enrich({"url": URL, "source": "observed_serper_result"})
    finally:
        FETCH_DEADLINE_AT.reset(deadline)
    resource["resource_id"] = "res_" + hashlib.sha256(URL.encode()).hexdigest()[:24]
    point = {"knowledge_point_id": "K7", "text": "文件下载", "technology": "Streamlit"}
    request = SearchRequest(knowledge_points=["文件下载"], topic_technologies={"文件下载": "Streamlit"}, preferred_platforms=["bilibili"], language="zh")
    own = [item for item in resource.get("evidence", []) if item["kind"] in {"page", "catalog"}]
    chapters = [item for item in resource.get("chapters", []) if re.search(r"下载|download|导出|export", item.get("title", ""), re.I)]
    report = {"url": URL, "isolated_max_bytes": 16_000_000, "production_writes": 0,
        "resource": resource, "download_chapters": chapters,
        "own_related": related_recommendation(point, resource, own, request),
        "request_trace": list(fetcher.request_trace), "playback_verified": False}
    if (OUT / "page.html").exists():
        raw = (OUT / "page.html").read_bytes()
        report.update(saved_bytes=len(raw), saved_sha256=hashlib.sha256(raw).hexdigest())
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("saved_bytes", "download_chapters", "own_related") if key in report}, ensure_ascii=False))
    print(json.dumps({"fetch_status": resource["fetch_status"], "chapters": len(resource["chapters"]), "trace": report["request_trace"]}, ensure_ascii=False))

asyncio.run(main())
