"""Offline fixtures: an empty coverage assessment must not prevent metadata discovery."""
import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.service import JobService
from backend.app.providers import SearXNGProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("page_teaches_skills", [True, False])
@pytest.mark.parametrize("preferred_platforms", [["bilibili"], []])
async def test_zero_coverage_gets_bounded_real_query_catalog_probes(tmp_path, page_teaches_skills, preferred_platforms):
    queries, fetched = [], []
    topic = "Matplotlib 误差棒绘制与对数坐标设置"

    def respond(request):
        queries.append(request.url.params["q"])
        # The initial whole-unit query finds no usable source. The narrower
        # second query finds actual video-shaped candidates with broad titles.
        rows = [] if len(queries) == 1 else [
            {"title": "Matplotlib 完整视频课程", "url": f"https://www.bilibili.com/video/BV1cd411c7D{suffix}", "template": "videos.html"}
            for suffix in "fgh"]
        return httpx.Response(200, json={"results": rows})

    class PageFacts:
        async def enrich(self, candidate):
            fetched.append(candidate["url"])
            title = ("Matplotlib 误差棒绘制公开课" if len(fetched) == 1 else "Matplotlib 对数坐标设置公开课") if page_teaches_skills else "Matplotlib 完整视频课程"
            eid = "page-title-" + str(len(fetched))
            return {"title": title, "fetch_status": "fetched", "metadata_evidence_level": "page",
                "field_provenance": {"title": {"source": "html.title", "evidence_id": eid, "url": candidate["url"]}},
                "evidence": [{"id": eid, "evidence_id": eid, "kind": "page", "field": "title", "source": "html.title",
                              "url": candidate["url"], "text": title}]}

    settings = Settings(database_path=str(tmp_path / "zero-coverage.sqlite3"), searxng_url="https://search.example",
        searxng_video_engines=("primary",), max_search_requests=2, max_detail_pages=8,
        search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        jobs = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=PageFacts())
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=[topic], preferred_platforms=preferred_platforms))["job_id"]
            await jobs.run(job_id)
            assert len(queries) == 2
            assert topic in queries[0]
            assert "Matplotlib 误差棒绘制" in queries[1] and "对数" not in queries[1]
            assert len(fetched) == 2  # The third broad source does not escape the probe cap.
            group = jobs.results(job_id)["groups"][0]
            assert not group["items"]
            if page_teaches_skills:
                assert len(group["partial_items"]) == 2
                assert group["collection_coverage"]["status"] == "all_subtopics_supported"
                assert not group["collection_coverage"]["single_resource_full_coverage"]
            else:
                assert not group["partial_items"] and not group["review_items"]
            assert store.get_job(job_id)["progress"]["search_requests"] <= 2
        finally:
            store.close()


def test_catalog_probe_can_use_an_earlier_executed_gap_without_borrowing_other_point():
    from tests.test_video_readiness import record
    point = {"knowledge_point_id": "p", "text": "pandas 分组聚合与图表绘制"}
    resource, evidence = record("pandas 完整视频课程")
    evidence[0]["query"] = "first-gap"
    state = {"gap_queries": {"p": "second-gap"}, "gap_query_history": {"p": {"first-gap", "second-gap"}}}
    assert JobService._gap_catalog_probe(point, resource, evidence, state)
    assert not JobService._gap_catalog_probe(point, resource, [dict(evidence[0], knowledge_point_id="other")], state)
    assert not JobService._gap_catalog_probe(point, resource, [dict(evidence[0], query="unexecuted-query")], state)
