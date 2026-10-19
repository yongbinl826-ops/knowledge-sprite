"""Offline regression: a budget stop must not discard completed source responses."""
from dataclasses import replace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Candidate, SearchRequest
from backend.app.providers import QueryBudgetReached, SearchBudgetReached, SearchError, SearXNGProvider
from backend.app.service import BudgetReached, JobService


def options(tmp_path, **overrides):
    return replace(Settings(database_path=str(tmp_path / "budget.sqlite3"), searxng_url="https://search.example",
        searxng_video_engines=("video",), searxng_engines=("web",), searxng_fallback_engines=("backup",),
        search_min_interval_seconds=0, max_search_requests=1, max_detail_pages=0, deadline_seconds=5), **overrides)


def source_body():
    return {"results": [{"title": "意大利面烹饪视频", "url": "https://example.org/food-video",
                         "content": "食品制作课程", "template": "videos.html", "engines": ["video"]}]}


class NoFetch:
    async def enrich(self, candidate):
        raise AssertionError("No detail requests are permitted by these zero-detail offline budgets")


@pytest.mark.asyncio
@pytest.mark.parametrize("budget_error", [BudgetReached, QueryBudgetReached])
async def test_backup_budget_stop_carries_completed_primary_observations(tmp_path, budget_error):
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json=source_body()))) as client:
        provider = SearXNGProvider(options(tmp_path), client)
        count = 0
        async def limit():
            nonlocal count
            if count >= 1:
                raise budget_error()
            count += 1
        provider.request_hook = limit
        with pytest.raises(SearchBudgetReached) as exc:
            await provider.search("Python 列表 视频教程", "zh", 6, [], candidate_check=lambda _: False)
        assert isinstance(exc.value, budget_error)
        assert [item.url for item in exc.value.partial_candidates] == ["https://example.org/food-video"]
        assert len(seen) == count == len(provider.last_requests) == 1
        assert provider.last_requests[0]["candidate_count"] == 1
        assert provider.last_requests[0]["topic_signal_count"] == 0
        # A subsequent empty-budget call cannot inherit the prior candidates.
        with pytest.raises(SearchBudgetReached) as second:
            await provider.search("new topic 视频教程", "zh", 6, [], candidate_check=lambda _: False)
        assert second.value.partial_candidates == [] and len(seen) == 1


@pytest.mark.asyncio
async def test_job_preserves_candidates_without_promoting_irrelevance_or_exceeding_budget(tmp_path):
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json=source_body()))) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=["Python 列表", "SQL 多表连接"], preferred_platforms=[]))["job_id"]
            await jobs.run(job_id)
            job = store.get_job(job_id)
            attempts = store.attempts(job_id)
            resources = store.resources(job_id)
            assert job["status"] == "partial"
            assert job["progress"]["search_requests"] == len(seen) == 1
            assert job["progress"]["search_successes"] == job["progress"]["candidates_discovered"] == 1
            assert job["progress"]["details_attempted"] == 0
            assert len(attempts) == 1 and attempts[0]["status"] == "partial"
            assert attempts[0]["error_code"] == "budget_exhausted" and attempts[0]["candidate_count"] == 1
            assert attempts[0]["network_attempted"] is True
            assert len(attempts[0]["provider_requests"]) == 1 and len(resources) == 1
            resource = next(iter(resources.values()))
            assert resource["fetch_status"] == "not_fetched"
            evidence = store.evidence(job_id, resource["resource_id"])
            assert any(item["kind"] == "search" and item["knowledge_point_id"] == job["knowledge_points"][0]["knowledge_point_id"] for item in evidence)
            assert all(not group["items"] and not group["partial_items"] for group in jobs.results(job_id)["groups"])
            assert store.connection.execute("SELECT COUNT(*) FROM cache WHERE kind='search'").fetchone()[0] == 0
            assert any("预算" in warning for warning in job["warnings"])
        finally:
            store.close()


@pytest.mark.asyncio
async def test_optional_official_budget_stop_preserves_primary_and_stops_later_queries(tmp_path):
    seen = []
    class OfficialBudgetStop:
        name = "official_sitemap"
        def __init__(self):
            self.calls = 0
            self.last_requests, self.last_dns_requests, self.last_discovery = [], [], {}
        async def search(self, *args, **kwargs):
            self.calls += 1
            await self.request_hook()
            raise AssertionError("Official HTTP must not start after the shared request budget is exhausted")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json=source_body()))) as client:
        config = options(tmp_path, searxng_fallback_engines=())
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        official = OfficialBudgetStop()
        jobs.official_fallback = official
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=["Python 列表", "SQL 多表连接"], preferred_platforms=[]))["job_id"]
            await jobs.run(job_id)
            job, attempts = store.get_job(job_id), store.attempts(job_id)
            assert official.calls == 1 and len(seen) == 1
            assert job["status"] == "partial" and job["progress"]["search_requests"] == 1
            assert len(attempts) == 1 and attempts[0]["status"] == "partial" and attempts[0]["candidate_count"] == 1
            assert len(store.resources(job_id)) == 1
            assert attempts[0]["provider_requests"][0]["provider"] == "searxng"
        finally:
            store.close()


@pytest.mark.asyncio
async def test_backup_retry_budget_stop_preserves_primary_and_actual_failure_trace(tmp_path):
    seen = []
    def respond(request):
        seen.append(request.url.params["engines"])
        if seen[-1] == "backup":
            raise httpx.ReadTimeout("offline synthetic timeout", request=request)
        return httpx.Response(200, json=source_body())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path, max_search_requests=4)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=[]))["job_id"]
            await jobs.run(job_id)
            job, attempt = store.get_job(job_id), store.attempts(job_id)[0]
            assert seen == ["video", "backup", "web", "backup"] and job["progress"]["search_requests"] == 4
            assert job["status"] == "partial" and attempt["candidate_count"] == 1
            assert [record["status"] for record in attempt["provider_requests"]] == ["completed", "failed"]
            assert attempt["provider_requests"][1]["error_code"] == "search_timeout"
            assert len(store.resources(job_id)) == 1
        finally:
            store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_budget_preservation_does_not_bypass_access_denial_or_source_pause(tmp_path, status):
    seen = []
    def respond(request):
        seen.append(request.url.params["engines"])
        return httpx.Response(status, headers={"retry-after": "60"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(options(tmp_path), client)
        with pytest.raises(SearchError):
            await provider.search("Python video", "en", 6, [], candidate_check=lambda _: False)
        with pytest.raises(SearchError):
            await provider.search("Python video", "en", 6, [], candidate_check=lambda _: False)
        assert seen == ["video"]


@pytest.mark.asyncio
async def test_budget_stop_before_first_response_never_fabricates_candidate(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("No HTTP budget"))) as client:
        provider = SearXNGProvider(options(tmp_path), client)
        async def exhausted():
            raise BudgetReached()
        provider.request_hook = exhausted
        with pytest.raises(SearchBudgetReached) as exc:
            await provider.search("Python video", "en", 6, [], candidate_check=lambda _: False)
        assert not exc.value.partial_candidates and not provider.last_requests


POINTS = ["Python 列表", "SQL 多表连接", "Java 接口", "CSS 网格布局", "Rust 所有权"]


class HungryOfficial:
    """Offline source requesting optional work until its existing hooks stop it."""
    name = "official_sitemap"

    def __init__(self):
        self.calls = 0
        self.actual_requests = 0
        self.last_requests, self.last_dns_requests, self.last_discovery = [], [], {}

    async def search(self, *args, **kwargs):
        self.calls += 1
        self.last_requests, self.last_dns_requests, self.last_discovery = [], [], {}
        for _ in range(20):
            await self.budget_check_hook()
            await self.request_hook()
            self.actual_requests += 1
            self.last_requests.append({"provider": self.name, "status": "completed", "http_status": 200})
        raise AssertionError("Optional discovery must hit the bounded existing hooks")


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,expected_queries,priority_queries", [(3, 3, 5), (5, 5, 5), (8, 5, 5), (10, 10, 10), (12, 10, 10)])
async def test_priority_rounds_reserve_primary_requests_without_increasing_global_budget(tmp_path, budget, expected_queries, priority_queries):
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json=source_body()))) as client:
        config = options(tmp_path, max_search_requests=budget)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        official = HungryOfficial()
        jobs.official_fallback = official
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=[]))["job_id"]
            await jobs.run(job_id)
            job, attempts = store.get_job(job_id), store.attempts(job_id)
            ids = [point["knowledge_point_id"] for point in job["knowledge_points"]]
            assert job["status"] == "partial"
            assert len(attempts) == expected_queries
            assert [item["knowledge_point_id"] for item in attempts] == (ids * 2)[:expected_queries]
            assert all(item["priority_query_count"] == priority_queries for item in attempts)
            assert job["progress"]["search_requests"] == len(seen) + official.actual_requests == budget
            assert sum(len(item["provider_requests"]) for item in attempts) == budget
            assert all(len(item["provider_requests"]) <= item["priority_request_limit"] for item in attempts)
            assert all(item["candidate_count"] > 0 for item in attempts)
            assert all(item["error_code"] == "query_budget_exhausted" for item in attempts[:-1])
            assert attempts[-1]["error_code"] == "budget_exhausted"
            assert store.connection.execute("SELECT COUNT(*) FROM cache WHERE kind='search'").fetchone()[0] == 0
            # Existing relevance rules still reject all these unrelated fixtures.
            assert all(not group["items"] and not group["partial_items"] for group in jobs.results(job_id)["groups"])
        finally:
            store.close()


@pytest.mark.asyncio
async def test_optional_official_work_cannot_consume_later_points_primary_reservations(tmp_path):
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json=source_body()))) as client:
        config = options(tmp_path, max_search_requests=9, searxng_fallback_engines=())
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        official = HungryOfficial()
        jobs.official_fallback = official
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=[]))["job_id"]
            await jobs.run(job_id)
            job, attempts = store.get_job(job_id), store.attempts(job_id)
            assert len(attempts) == len(seen) == 5 and official.actual_requests == 4
            assert job["progress"]["search_requests"] == 9
            assert len({item["knowledge_point_id"] for item in attempts}) == 5
            assert [item["priority_request_limit"] for item in attempts] == [1, 2, 2, 2, 2]
            assert all(item["candidate_count"] == 1 for item in attempts)
            assert attempts[0]["error_code"] == "query_budget_exhausted"
            assert attempts[-1]["error_code"] == "budget_exhausted"
        finally:
            store.close()


@pytest.mark.asyncio
async def test_empty_primary_slice_continues_without_inventing_candidates(tmp_path):
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, json={"results": []}))) as client:
        config = options(tmp_path, max_search_requests=5)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=[]))["job_id"]
            await jobs.run(job_id)
            job, attempts = store.get_job(job_id), store.attempts(job_id)
            assert len(seen) == len(attempts) == 5
            assert len({item["knowledge_point_id"] for item in attempts}) == 5
            assert all(item["candidate_count"] == 0 for item in attempts)
            assert all(item["error_code"] == "query_budget_exhausted" for item in attempts[:-1])
            assert attempts[-1]["error_code"] == "budget_exhausted"
            assert not store.resources(job_id) and job["status"] == "partial"
        finally:
            store.close()


@pytest.mark.asyncio
async def test_primary_retry_slice_moves_to_next_point_and_keeps_failed_request_trace(tmp_path):
    seen = []
    def fail(request):
        seen.append(request)
        raise httpx.ReadTimeout("offline synthetic timeout", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        config = options(tmp_path, max_search_requests=5)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        try:
            job_id = jobs.create(SearchRequest(knowledge_points=POINTS, preferred_platforms=[]))["job_id"]
            await jobs.run(job_id)
            attempts = store.attempts(job_id)
            assert len(seen) == len(attempts) == 5
            assert len({item["knowledge_point_id"] for item in attempts}) == 5
            assert all(item["provider_requests"][0]["error_code"] == "search_timeout" for item in attempts)
            assert not store.resources(job_id)
        finally:
            store.close()
