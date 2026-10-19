"""Bounded MOOC partial-primary reuse, using mock HTTP and an isolated DB."""
import httpx
import pytest

from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.providers import SearXNGProvider
from backend.app.service import JobService
from test_parallel_platform_search import NoFetch, options


@pytest.mark.asyncio
async def test_completed_broad_course_observation_reuses_cache_with_partial_diagnostics_and_original_age(tmp_path):
    calls = []

    def reply(request):
        calls.append(request.url.params["q"])
        return httpx.Response(200, json={"results": [{
            "url": "https://www.icourse163.org/course/OWN-123", "title": "Python程序设计",
            "content": "程序设计入门课程",}], "unresponsive_engines": []})

    config = options(tmp_path, mooc_refresh_enabled=True, mooc_gap_search_enabled=True)
    store = Store(config.database_path)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
            request = SearchRequest(knowledge_points=["Python socket 超时设置"], preferred_platforms=["icourse163"])
            first = jobs.create(request)["job_id"]
            await jobs.run(first)
            cold = store.attempts(first)
            assert len(calls) == 2
            assert all(row["status"] == "partial" and row["error_code"] == "query_budget_exhausted" for row in cold)
            assert all(row["upstream_warnings"][0]["code"] == "no_topic_signal" for row in cold)
            cache_before = [tuple(row) for row in store.connection.execute("SELECT * FROM cache ORDER BY key")]
            original_times = {row["observed_at"] for resource in store.resources(first).values()
                for row in store.evidence(first, resource["resource_id"]) if row["kind"] == "search"}
            second = jobs.create(request)["job_id"]
            await jobs.run(second)
            warm = store.attempts(second)
            assert second != first and len(calls) == 2
            assert all(row["cache_hit"] and not row["network_attempted"] for row in warm)
            assert all(row["status"] == "partial" and row["error_code"] == "query_budget_exhausted" for row in warm)
            assert all(not row["upstream_warnings"] and row["cache_origin_warnings"][0]["code"] == "no_topic_signal" for row in warm)
            assert store.get_job(second)["progress"]["search_requests"] == 0
            assert jobs.results(second)["groups"][0]["mooc_relevance"]["recommended_count"] == 0
            assert [tuple(row) for row in store.connection.execute("SELECT * FROM cache ORDER BY key")] == cache_before
            assert {row["observed_at"] for resource in store.resources(second).values()
                for row in store.evidence(second, resource["resource_id"]) if row["kind"] == "search"} == original_times
            assert not list(store.connection.execute("SELECT * FROM mooc_refresh_state"))
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["engine_fault", "timeout", "rate_limited", "access_denied"])
async def test_faulted_primary_is_never_saved_as_reusable_partial_observation(tmp_path, failure):
    def reply(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if failure in {"rate_limited", "access_denied"}:
            return httpx.Response(429 if failure == "rate_limited" else 403, headers={"retry-after": "300"})
        return httpx.Response(200, json={"results": [{
            "url": "https://www.icourse163.org/course/OWN-123", "title": "烹饪课程",
            "content": "Explicit irrelevant synthetic course",}],
            "unresponsive_engines": [["web", "timeout"]]})

    config = options(tmp_path)
    store = Store(config.database_path)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
            jid = jobs.create(SearchRequest(knowledge_points=["Python socket 超时设置"],
                preferred_platforms=["icourse163"]))["job_id"]
            await jobs.run(jid)
            assert not list(store.connection.execute("SELECT key FROM cache WHERE kind='search'"))
            assert jobs.results(jid)["groups"][0]["mooc_relevance"]["recommended_count"] == 0
    finally:
        store.close()
