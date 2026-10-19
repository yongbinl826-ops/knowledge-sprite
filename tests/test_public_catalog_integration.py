"""Offline integration: public discovery is a bounded probe, never video proof."""
import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Candidate, SearchRequest
from backend.app.providers import SearXNGProvider, SearchError
from backend.app.service import JobService


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_denied", [False, True])
async def test_public_catalog_uses_a_fair_slice_and_never_promotes_index_titles(tmp_path, catalog_denied):
    primary_queries, fetched = [], []
    def respond(request):
        primary_queries.append(request.url.params["q"])
        return httpx.Response(200, json={"results": []})

    class Catalog:
        name = "public_catalog"
        calls = 0
        request_hook = dns_request_hook = budget_check_hook = None
        last_requests, last_dns_requests, last_warnings, last_discovery = [], [], [], {}
        async def search(self, query, *args, **kwargs):
            self.calls += 1
            await self.request_hook()
            self.last_requests = [{"provider": self.name, "url": "https://www.freecodecamp.org/news/tag/matplotlib/",
                                   "status": "completed", "http_status": 403 if catalog_denied else 200}]
            if catalog_denied:
                raise SearchError("access_denied", "公开目录拒绝访问，未转用其他目录路径")
            return [Candidate(id=f"catalog-{i}", title="Matplotlib 误差棒绘制与对数坐标设置 视频完整课程",
                url=f"https://www.freecodecamp.org/news/observed-article-{i}/", source=self.name, query=query,
                discovery_evidence={"kind": "public_catalog_link", "source_url": self.last_requests[0]["url"],
                    "confidence": "low", "independent_detail_required": True}) for i in range(3)]

    class TextArticles:
        async def enrich(self, candidate):
            fetched.append(candidate["url"])
            return {"fetch_status": "fetched", "metadata_evidence_level": "page", "resource_type": "unknown",
                    "video_evidence_status": "none", "evidence": []}

    settings = Settings(database_path=str(tmp_path / "catalog.sqlite3"), searxng_url="https://search.example",
        searxng_video_engines=("primary",), max_search_requests=6, max_detail_pages=8,
        search_min_interval_seconds=0, public_catalog_fallback=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=TextArticles())
        catalog = service.public_catalog = Catalog()
        try:
            job_id = service.create(SearchRequest(knowledge_points=["Matplotlib 误差棒绘制与对数坐标设置"]))["job_id"]
            await service.run(job_id)
            attempts = store.attempts(job_id)
            assert [a["provider"] for a in attempts[:3]] == ["searxng", "searxng", "public_catalog"]
            assert catalog.calls == 1
            assert len(primary_queries) > 2  # A different public source's refusal cannot revoke allowed primary search.
            assert len(fetched) == (0 if catalog_denied else 2)
            result = service.results(job_id)["groups"][0]
            assert not result["items"] and not result["partial_items"] and not result["review_items"]
            assert store.get_job(job_id)["progress"]["search_requests"] == len(primary_queries) + 1 <= 6
            if not catalog_denied:
                assert len(store.resources(job_id)) == 3
                assert all(e["source"] == "public_catalog" for r in store.resources(job_id).values()
                    for e in store.evidence(job_id, r["resource_id"]))
        finally:
            store.close()


def test_public_catalog_probe_does_not_accept_foreign_hosts_or_other_point_evidence():
    point = {"knowledge_point_id": "p"}
    evidence = [{"kind": "search", "source": "public_catalog", "knowledge_point_id": "p"}]
    resource = {"canonical_url": "https://www.freecodecamp.org/news/actual-observed-article/"}
    assert JobService._public_catalog_probe(point, resource, evidence, {})
    assert not JobService._public_catalog_probe(point, {"canonical_url": "https://attacker.example/article/"}, evidence, {})
    assert not JobService._public_catalog_probe(point, resource, [dict(evidence[0], knowledge_point_id="other")], {})
    assert not JobService._public_catalog_probe(point, resource, evidence, {"public_probes_started": {"p": {"one", "two"}}})
