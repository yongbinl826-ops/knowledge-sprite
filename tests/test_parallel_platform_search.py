"""Offline HTTP/barrier tests. No live engines, models or production SQLite."""
import asyncio
from collections import Counter
from dataclasses import replace
from hashlib import sha256

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.main import create_app
from backend.app.providers import SearXNGProvider
from backend.app.service import AdmissionRejected, JobService
from test_projects import analyzed, setup as project_setup, settle


class NoFetch:
    async def enrich(self, candidate):
        raise AssertionError("These tests must never fetch real pages")


def options(tmp_path, **extra):
    return replace(Settings(database_path=str(tmp_path / "parallel.sqlite3"),
        searxng_url="http://search.example", searxng_engines=("web",),
        searxng_video_engines=("video",), searxng_fallback_engines=("web", "video"),
        parallel_platform_search=True, teaching_match_enabled=False, open_web_search_enabled=False,
        # Original restricted-lane controls opt out explicitly; new defaults
        # are exercised by test_requirements_discovery and mobile ASGI tests.
        shared_course_library_enabled=False, mooc_gap_search_enabled=False, mooc_refresh_enabled=False,
        max_search_requests=30, max_detail_pages=0, search_min_interval_seconds=0,
        search_max_retries=1, deadline_seconds=10), **extra)


def request(count=5):
    return SearchRequest(knowledge_points=[f"Python 明确知识点 {i}" for i in range(count)],
                         preferred_platforms=["bilibili", "icourse163"])


def platform(query):
    return "bilibili" if "bilibili.com" in query else "icourse163"


def response(query):
    key = sha256(query.encode()).hexdigest()[:10]
    url = f"https://www.bilibili.com/video/BV{key}/" if platform(query) == "bilibili" else f"https://www.icourse163.org/course/QA-{key}"
    return {"results": [{"url": url, "title": "Python 知识点课程 " + query,
        "content": query, "template": "videos.html" if platform(query) == "bilibili" else "default.html"}],
        "unresponsive_engines": []}


@pytest.mark.asyncio
async def test_both_platforms_overlap_and_all_initial_queries_finish_before_optional_requests(tmp_path):
    calls, active, peak = [], 0, 0
    async def respond(req):
        nonlocal active, peak
        query = req.url.params["q"]
        calls.append((query, req.url.params["engines"]))
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.002)
        active -= 1
        return httpx.Response(200, json=response(query))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        jid = jobs.create(request())["job_id"]
        await jobs.run(jid)
        job = store.get_job(jid)
        attempts = store.attempts(jid)
        assert peak >= 2
        assert job["budgets"]["max_search_requests"] == 20
        assert job["progress"]["search_requests"] == len(calls) == 20
        assert job["progress"]["platform_search_requests"] == {"bilibili": 10, "icourse163": 10}
        assert [row["search_phase"] for row in attempts] == ["initial"] * 10 + ["followup"] * 10
        assert Counter((row["knowledge_point_id"], row["platform"]) for row in attempts[:10]) == Counter(
            (point["knowledge_point_id"], p) for point in job["knowledge_points"] for p in request().preferred_platforms)
        assert sum(len(row["provider_requests"]) for row in attempts) == 20
        for row in attempts:
            assert len(row["provider_requests"]) == 1
            trace = row["provider_requests"][0]
            assert all(platform(entry["url"]) == row["platform"] for entry in trace.get("candidate_trace", []))
        assert all(engine == ("video" if platform(q) == "bilibili" else "web") for q, engine in calls)
        assert job["platform_search"]["finished"] is True
        groups = jobs.results(jid)["groups"]
        assert {row["resource"]["platform"] for group in groups for row in group["discovery_items"]} == {"bilibili"}
        retained = store.resources(jid)
        assert {resource["platform"] for resource in retained.values()} == {"bilibili", "icourse163"}
        assert job["progress"]["details_attempted"] == 0
        for group in groups:
            # Both discovery lanes persist their observations. A search-only
            # MOOC has no own outline and therefore cannot be recommended.
            diagnostic = group["mooc_relevance"]
            assert diagnostic["candidate_count"] > 0 and diagnostic["recommended_count"] == 0
            for candidate in diagnostic["candidates"]:
                assert retained[candidate["resource_id"]]["platform"] == "icourse163"
                assert candidate["assessment"]["display_eligible"] is False
                assert any(row["kind"] == "search" and row.get("knowledge_point_id") == group["knowledge_point_id"]
                           for row in store.evidence(jid, candidate["resource_id"]))
        store.close()


@pytest.mark.asyncio
async def test_timeout_retry_is_deferred_until_every_point_has_both_platform_initial_attempts(tmp_path):
    calls = []
    async def respond(req):
        query = req.url.params["q"]
        calls.append(query)
        if platform(query) == "bilibili" and len([q for q in calls if q == query]) == 1:
            raise httpx.ReadTimeout("isolated timeout")
        return httpx.Response(200, json=response(query))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        jid = jobs.create(request(2))["job_id"]
        await jobs.run(jid)
        attempts = store.attempts(jid)
        assert len(calls) == 8
        assert len(set(calls[:4])) == 4
        assert [row["search_phase"] for row in attempts[:4]] == ["initial"] * 4
        failures = [row for row in attempts[:4] if row["platform"] == "bilibili"]
        assert len(failures) == 2 and all(row["status"] == "failed" for row in failures)
        for row in failures:
            retried = next(a for a in attempts[4:] if a["platform"] == row["platform"] and a["knowledge_point_id"] == row["knowledge_point_id"])
            assert retried["query"] == row["query"] and retried["status"] == "completed"
        store.close()


@pytest.mark.asyncio
async def test_mooc_failure_keeps_every_bilibili_result_and_does_not_steal_its_quota(tmp_path):
    calls = []
    async def respond(req):
        query = req.url.params["q"]
        calls.append(query)
        if platform(query) == "icourse163":
            return httpx.Response(502)
        return httpx.Response(200, json=response(query))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        jid = jobs.create(request(3))["job_id"]
        await jobs.run(jid)
        assert Counter(map(platform, calls)) == {"bilibili": 6, "icourse163": 6}
        job = store.get_job(jid)
        assert job["progress"]["search_requests"] == 12
        assert job["progress"]["search_failures"] == 6
        assert all(group["discovery_items"] for group in jobs.results(jid)["groups"])
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_shared_access_denial_stops_all_lanes_instead_of_bypassing_through_other_platform(tmp_path, status):
    calls = []
    async def respond(req):
        calls.append(req)
        return httpx.Response(status, headers={"retry-after": "60"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        provider = SearXNGProvider(config, client)
        jobs = JobService(config, store, provider=provider, fetcher=NoFetch())
        jid = jobs.create(request(3))["job_id"]
        await jobs.run(jid)
        assert provider.access_denied if status == 403 else provider.paused_until > 0
        assert len(calls) <= 2
        assert store.get_job(jid)["progress"]["search_requests"] == len(calls)
        assert all(row["error_code"] == ("access_denied" if status == 403 else "rate_limited") for row in store.attempts(jid))
        store.close()


@pytest.mark.asyncio
async def test_cancellation_joins_all_platform_tasks_and_keeps_isolated_request_records(tmp_path):
    entered = asyncio.Event()
    active = 0
    async def respond(req):
        nonlocal active
        active += 1
        if active == 2:
            entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        jobs.start()
        try:
            jid = jobs.create(request(2))["job_id"]
            await asyncio.wait_for(entered.wait(), 2)
            cancelled = await jobs.cancel(jid)
            assert cancelled["status"] == "cancelled"
            assert active == 0
            attempts = store.attempts(jid)
            assert len(attempts) == 2
            assert all(row["status"] == "cancelled" and len(row["provider_requests"]) == 1 for row in attempts)
            assert store.get_job(jid)["progress"]["search_requests"] == 2
            assert not jobs.provider.last_requests
        finally:
            await jobs.stop()
            store.close()


@pytest.mark.asyncio
async def test_engine_pause_observed_during_shared_start_wait_prevents_queued_request(tmp_path):
    calls = []
    async def respond(req):
        calls.append(req)
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [["shared", "CAPTCHA"]]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path, searxng_engines=("shared",), searxng_video_engines=("shared",),
                         searxng_fallback_engines=(), search_min_interval_seconds=.01)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        jid = jobs.create(request(2))["job_id"]
        await jobs.run(jid)
        assert len(calls) == 1
        assert store.get_job(jid)["progress"]["search_requests"] == 1
        store.close()


@pytest.mark.asyncio
async def test_suspended_project_job_resumes_without_repeating_initial_search_or_rewriting_evidence(tmp_path):
    calls = []
    async def respond(req):
        calls.append(req.url.params["q"])
        return httpx.Response(200, json=response(calls[-1]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        jobs.start()
        try:
            jid = jobs.create(request(2), consumer_key="project:isolated", defer_platform_followups=True)["job_id"]
            await asyncio.wait_for(jobs.queue.join(), 2)
            first = store.get_job(jid)
            assert first["phase"] == "awaiting_followup" and len(calls) == 4
            evidence = store.connection.execute("SELECT id,data FROM evidence WHERE job_id=? ORDER BY id", (jid,)).fetchall()
            with pytest.raises(ValueError):
                jobs.resume_platform_search(jid, consumer_key="project:someone-else")
            assert jobs.resume_platform_search(jid, consumer_key="project:isolated")
            assert not jobs.resume_platform_search(jid, consumer_key="project:isolated")
            await asyncio.wait_for(jobs.queue.join(), 2)
            assert len(calls) == 8
            assert store.get_job(jid)["platform_search"]["finished"]
            for row in evidence:
                assert store.connection.execute("SELECT data FROM evidence WHERE id=?", (row["id"],)).fetchone()[0] == row["data"]
        finally:
            await jobs.stop()
            store.close()


@pytest.mark.asyncio
async def test_warm_cache_covers_each_platform_without_any_new_http_requests(tmp_path):
    calls = []
    async def respond(req):
        calls.append(req.url.params["q"])
        return httpx.Response(200, json=response(calls[-1]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        first = jobs.create(request(1))["job_id"]
        await jobs.run(first)
        count = len(calls)
        second = jobs.create(request(1))["job_id"]
        await jobs.run(second)
        assert first != second and len(calls) == count
        job = store.get_job(second)
        assert job["progress"]["cache_hits"] == 4
        assert job["progress"]["search_requests"] == 0
        assert job["progress"]["initial_platform_pairs_completed"] == 2
        store.close()


def test_dynamic_budget_scales_with_point_and_platform_counts_and_rejects_an_insufficient_cap(tmp_path):
    config = options(tmp_path)
    store = Store(config.database_path)
    jobs = JobService(config, store, provider=object(), fetcher=NoFetch())
    for count in (1, 2, 5):
        job = store.get_job(jobs.create(request(count))["job_id"])
        assert job["budgets"]["max_search_requests"] == count * 4
    limited = JobService(replace(config, max_search_requests=12), Store(":memory:"), provider=object(), fetcher=NoFetch())
    with pytest.raises(AdmissionRejected) as exc:
        limited.create(request(5))
    assert exc.value.code == "search_budget_insufficient"
    assert limited.queue.qsize() == 0
    store.close()


@pytest.mark.asyncio
async def test_project_barrier_covers_all_seven_selected_points_across_both_batches_before_followups(tmp_path):
    _, store, jobs, projects = project_setup(tmp_path, parallel_platform_search=True, teaching_match_enabled=False)
    jobs.start()
    try:
        view = await analyzed(projects, 7, preferred_platforms=["bilibili", "icourse163"])
        pid = view["project_id"]
        confirmed = projects.confirm(pid, 1, [])
        budget = confirmed["version"]["budgets"]
        assert budget["reserved_search_requests"] == 35
        assert budget["batch_search_requests"] == [25, 10]
        projects.search(pid, 1)
        await settle(projects)
        result = projects.results(pid, 1)
        batches = result["version"]["batches"]
        assert len(batches) == 2 and sum(store.job_counts().values()) == 2
        attempts = [row for batch in batches for row in store.attempts(batch["job_id"])]
        chronological = sorted(attempts, key=lambda row: row["executed_at"])
        assert [row["search_phase"] for row in chronological] == ["initial"] * 21 + ["followup"] * 14
        assert result["version"]["budgets"]["actual_search_requests"] == 35
        for batch in batches:
            job = store.get_job(batch["job_id"])
            assert job["platform_search"]["finished"]
            assert job["progress"]["queries_completed"] == job["progress"]["queries_planned"]
            assert job["platform_search_active_seconds"] <= job["budgets"]["deadline_seconds"]
        assert len(result["points"]) == 7
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_http_api_accepts_dynamic_budget_and_retains_both_platforms_with_mooc_outline_gate(tmp_path):
    calls = []
    async def respond(req):
        calls.append(req.url.params["q"])
        return httpx.Response(200, json=response(calls[-1]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as provider_client:
        config = options(tmp_path)
        app = create_app(config, provider=SearXNGProvider(config, provider_client), fetcher=NoFetch())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as api:
                accepted = await api.post("/api/search-jobs", json=request(3).model_dump())
                assert accepted.status_code == 202
                jid = accepted.json()["job_id"]
                await asyncio.wait_for(app.state.service.queue.join(), 3)
                job = (await api.get(f"/api/search-jobs/{jid}")).json()
                assert job["budgets"]["max_search_requests"] == 12
                assert job["progress"]["platform_search_requests"] == {"bilibili": 6, "icourse163": 6}
                before = len(calls)
                result = (await api.get(f"/api/search-jobs/{jid}/results")).json()
                assert len(calls) == before
                assert result["discovery_only"]
                assert all({row["resource"]["platform"] for row in group["discovery_items"]} == {"bilibili"} for group in result["groups"])
                retained = app.state.store.resources(jid)
                assert {resource["platform"] for resource in retained.values()} == {"bilibili", "icourse163"}
                assert job["progress"]["details_attempted"] == 0
                for group in result["groups"]:
                    diagnostic = group["mooc_relevance"]
                    assert diagnostic["candidate_count"] > 0 and diagnostic["recommended_count"] == 0
                    assert all(retained[row["resource_id"]]["platform"] == "icourse163"
                               and row["assessment"]["display_eligible"] is False for row in diagnostic["candidates"])


@pytest.mark.asyncio
async def test_http_api_rejects_insufficient_budget_without_submitting_a_partial_plan(tmp_path):
    config = options(tmp_path, max_search_requests=12)
    app = create_app(config, provider=object(), fetcher=NoFetch())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as api:
            result = await api.post("/api/search-jobs", json=request(5).model_dump())
            assert result.status_code == 422
            assert result.json()["code"] == "search_budget_insufficient"
            assert app.state.store.job_counts() == {}


@pytest.mark.asyncio
async def test_cancel_during_followups_never_resumes_a_cancelled_job(tmp_path):
    calls = []
    waiting = asyncio.Event()
    async def respond(req):
        calls.append(req.url.params["q"])
        if len(calls) > 2:
            waiting.set()
            await asyncio.Event().wait()
        return httpx.Response(200, json=response(calls[-1]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config = options(tmp_path)
        store = Store(config.database_path)
        jobs = JobService(config, store, provider=SearXNGProvider(config, client), fetcher=NoFetch())
        jobs.start()
        try:
            jid = jobs.create(request(1))["job_id"]
            await asyncio.wait_for(waiting.wait(), 2)
            await jobs.cancel(jid)
            job = store.get_job(jid)
            assert job["status"] == "cancelled" and job["phase"] == "done"
            assert not jobs.resume_platform_search(jid, consumer_key="manual")
        finally:
            await jobs.stop()
            store.close()


@pytest.mark.asyncio
async def test_missing_later_batch_initial_pass_prevents_earlier_batch_followups(tmp_path):
    _, store, jobs, projects = project_setup(tmp_path, parallel_platform_search=True, teaching_match_enabled=False)
    blocked = asyncio.Event()
    class Search:
        async def search(self, query, *args, **kwargs):
            if "步骤 5" in query:
                blocked.set()
                await asyncio.Event().wait()
            return []
    jobs.provider = Search()
    jobs.start()
    try:
        view = await analyzed(projects, 7, preferred_platforms=["bilibili", "icourse163"])
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        await asyncio.wait_for(blocked.wait(), 3)
        current = projects.results(pid, 1)
        second_job = current["version"]["batches"][1]["job_id"]
        await jobs.cancel(second_job)
        await settle(projects)
        result = projects.results(pid, 1)
        first_job = result["version"]["batches"][0]["job_id"]
        assert all(row["search_phase"] == "initial" for row in store.attempts(first_job))
        assert store.get_job(first_job)["progress"]["search_requests"] == 15
        assert any("首轮未完成" in warning for warning in result["version"]["warnings"])
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()
