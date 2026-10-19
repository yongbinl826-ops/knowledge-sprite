"""The existing 12-search profile must be able to reach the public fallback."""
import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.providers import SearXNGProvider
from backend.app.service import JobService


@pytest.mark.asyncio
async def test_public_directory_round_is_reserved_without_raising_twelve_request_budget(tmp_path):
    primary = []
    def respond(request):
        primary.append(request.url.params["q"])
        return httpx.Response(200, json={"results": []})
    class CachedCatalog:
        name = "public_catalog"
        request_hook = dns_request_hook = budget_check_hook = None
        last_requests, last_dns_requests, last_warnings, last_discovery = [], [], [], {}
        calls = 0
        async def search(self, *args, **kwargs):
            self.calls += 1
            self.last_requests = []
            if self.calls == 1:
                for number in range(3):
                    await self.request_hook()
                    self.last_requests.append({"provider": self.name, "status": "completed", "http_status": 200})
            # Later units reuse the same directory snapshot without new HTTP.
            return []
    class NoDetail:
        async def enrich(self, _):
            pytest.fail("No candidates were discovered")
    settings = Settings(database_path=str(tmp_path / "twelve.sqlite3"), searxng_url="https://search.example",
        searxng_video_engines=("primary",), searxng_fallback_engines=("backup",),
        max_search_requests=12, max_detail_pages=12, public_catalog_fallback=True, search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        try:
            service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=NoDetail())
            source = service.public_catalog = CachedCatalog()
            names = [f"pandas 具体项目子任务{index}" for index in range(5)]
            job_id = service.create(SearchRequest(knowledge_points=names))["job_id"]
            await service.run(job_id)
            attempts = store.attempts(job_id)
            assert len({a["knowledge_point_id"] for a in attempts[:5]}) == 5
            assert attempts[5]["provider"] == "public_catalog"
            assert source.calls == 5
            assert store.get_job(job_id)["progress"]["search_requests"] == len(primary) + 3 <= 12
        finally:
            store.close()
