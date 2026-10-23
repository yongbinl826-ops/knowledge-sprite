"""Offline real JobService + MockTransport; no search/account/model requests."""
import asyncio
from contextlib import asynccontextmanager, closing, suppress
from copy import deepcopy
from dataclasses import replace
import json
import time

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Query, SearchRequest
from backend.app.platform_search import platform_budget, search_platform_rounds
from backend.app.providers import SearXNGProvider, TavilyProvider
from backend.app.service import JobService
from test_platform_provider_selection import NoFetch, config


@asynccontextmanager
async def environment(tmp_path, *, mode="timeout", rounds=1, mooc_provider="tavily", enabled=True,
                      key="synthetic-key", keyless=False, searx_handler=None, tavily_status=200):
    calls = []
    settings = config(tmp_path, bilibili_search_rounds=rounds, mooc_search_rounds=1,
                      mooc_search_provider=mooc_provider, global_concurrency=2,
                      max_search_requests=rounds + 1, teaching_match_enabled=True,
                      tavily_api_key=key, tavily_allow_keyless=keyless,
                      llm_provider="none", llm_api_key="")
    # Makes the red test exercise the same old source as well as the candidate.
    object.__setattr__(settings, "searxng_failover_provider", "tavily" if enabled else "")

    async def respond(request):
        assert request.url.host in {"search.test", "api.tavily.com"}
        calls.append(request)
        if request.url.host == "api.tavily.com":
            body = json.loads(request.content)
            assert body["search_depth"] == "basic"
            assert body["include_domains"] in (["bilibili.com"], ["icourse163.org"])
            assert body["include_domains_mode"] == "restrict"
            assert "X-Tavily-Access-Mode" not in request.headers
            return httpx.Response(tavily_status, json={"results": [], "usage": {"credits": 1}})
        if searx_handler:
            return await searx_handler(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic offline timeout", request=request)
        if mode == "unavailable":
            return httpx.Response(500)
        if mode in {"engine", "captcha", "denied", "limited"}:
            reason = {"engine": "timeout", "captcha": "CAPTCHA", "denied": "Access denied",
                      "limited": "Too many requests"}[mode]
            return httpx.Response(200, json={"results": [], "unresponsive_engines": [
                [request.url.params["engines"], reason]]})
        if mode == "403":
            return httpx.Response(403)
        if mode == "429":
            return httpx.Response(429, headers={"retry-after": "300"})
        if mode == "wrong_domain":
            return httpx.Response(200, json={"results": [{"url": "https://example.org/course/1",
                "title": "Unrelated course"}], "unresponsive_engines": []})
        if mode in {"partial", "no_topic"}:
            title = "Python 列表 视频教程" if mode == "partial" else "烹饪教学"
            return httpx.Response(200, json={"results": [{"url": "https://www.bilibili.com/video/BV1234567890/",
                "title": title, "content": title, "template": "videos.html"}],
                "unresponsive_engines": [[request.url.params["engines"], "timeout"]] if mode == "partial" else []})
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})

    with closing(Store(settings.database_path)) as store:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            searx = SearXNGProvider(settings, client)
            tavily = TavilyProvider(settings, client)
            jobs = JobService(settings, store, provider=searx, fetcher=NoFetch(),
                              provider_overrides={"tavily": tavily})
            yield jobs, store, calls, searx, tavily


async def run(jobs, text="Python 列表", platforms=None):
    request = SearchRequest(knowledge_points=[text], preferred_platforms=platforms or ["bilibili", "icourse163"])
    jid = jobs.create(request)["job_id"]
    await jobs.run(jid)
    return jid


def by_platform(store, jid, platform):
    return [row for row in store.attempts(jid) if row["platform"] == platform]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "unavailable", "engine"])
async def test_failure_uses_only_next_existing_slot_with_actual_provider_and_budget(tmp_path, mode):
    async with environment(tmp_path, mode=mode, rounds=2) as (jobs, store, calls, searx, tavily):
        jid = await run(jobs)
        rows = by_platform(store, jid, "bilibili")
        assert [row["provider"] for row in rows] == ["searxng", "tavily"]
        assert [row["status"] for row in rows] == ["failed", "completed"]
        assert rows[1]["configured_provider"] == "searxng"
        assert rows[1]["failover_reason"] in {"search_timeout", "search_unavailable", "upstream_engine_failed"}
        assert rows[1]["query"] == rows[0]["query"]  # Existing failed-first retry slot.
        assert len(calls) == store.get_job(jid)["progress"]["search_requests"] == 3
        assert [row["provider"] for row in by_platform(store, jid, "icourse163")] == ["tavily"]
        assert all(len(row["provider_requests"]) == 1 for row in store.attempts(jid))
        assert all(row["provider_requests"][0]["provider"] == row["provider"] for row in store.attempts(jid))
        assert sum(row.get("api_credits", 0) for attempt in store.attempts(jid)
                   for row in attempt["provider_requests"]) == 2
        assert jobs.llm is None


@pytest.mark.asyncio
async def test_single_round_failure_does_not_add_http_but_explicit_retry_new_job_uses_health(tmp_path):
    async with environment(tmp_path) as (jobs, store, calls, searx, tavily):
        first = await run(jobs)
        assert len(calls) == 2
        assert [row["provider"] for row in by_platform(store, first, "bilibili")] == ["searxng"]
        first_observation = deepcopy(store.attempts(first))
        second = await run(jobs)
        assert len(calls) == 3  # Bili Tavily one; exact MOOC cache zero.
        second_rows = store.attempts(second)
        assert by_platform(store, second, "bilibili")[0]["provider"] == "tavily"
        assert by_platform(store, second, "icourse163")[0]["cache_hit"]
        assert store.get_job(second)["progress"]["search_requests"] == 1
        assert store.attempts(first) == first_observation
        assert all(row["query"] == old["query"] for row, old in zip(second_rows, first_observation))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["empty", "wrong_domain", "partial", "no_topic", "captcha", "denied", "limited", "403", "429"])
async def test_nonfault_and_strong_access_stops_do_not_elect_another_source(tmp_path, mode):
    async with environment(tmp_path, mode=mode, rounds=2) as (jobs, store, calls, searx, tavily):
        jid = await run(jobs)
        assert all(row["provider"] == "searxng" for row in by_platform(store, jid, "bilibili"))
        assert jobs._searxng_failover_health == {}
        assert not store.get_job(jid)["platform_search"].get("source_failovers")
        assert len([call for call in calls if call.url.host == "api.tavily.com"]) == 1  # MOOC only.
        if mode in {"captcha", "denied", "limited", "403", "429"}:
            assert len([call for call in calls if call.url.host == "search.test"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,key,keyless", [(False, "synthetic-key", False), (True, "", False), (True, "", True)])
async def test_explicit_optin_and_existing_api_key_are_both_necessary(tmp_path, enabled, key, keyless):
    async with environment(tmp_path, enabled=enabled, key=key, keyless=keyless, rounds=2,
                           mooc_provider="") as (jobs, store, calls, searx, tavily):
        jid = await run(jobs)
        assert all(row["provider"] == "searxng" for row in store.attempts(jid))
        assert all(call.url.host == "search.test" for call in calls)


@pytest.mark.asyncio
async def test_parallel_platform_does_not_wait_for_or_inherit_other_lane_failure(tmp_path):
    mooc_started = asyncio.Event()

    async def handler(request):
        if request.url.params["engines"] == "video":
            await asyncio.wait_for(mooc_started.wait(), 1)
            raise httpx.ReadTimeout("synthetic", request=request)
        mooc_started.set()
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})

    async with environment(tmp_path, mooc_provider="", rounds=2, searx_handler=handler) as (jobs, store, calls, searx, tavily):
        jid = await run(jobs)
        assert mooc_started.is_set()
        assert by_platform(store, jid, "icourse163")[0]["provider"] == "searxng"
        assert by_platform(store, jid, "bilibili")[1]["provider"] == "tavily"
        assert set(store.get_job(jid)["platform_search"]["source_failovers"]) == {"bilibili"}


@pytest.mark.asyncio
async def test_mooc_failure_can_fail_over_without_switching_healthy_bilibili(tmp_path):
    async def handler(request):
        if request.url.params["engines"] == "web":
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})

    async with environment(tmp_path, mooc_provider="", searx_handler=handler) as (jobs, store, calls, searx, tavily):
        first = await run(jobs)
        second = await run(jobs)
        assert by_platform(store, first, "icourse163")[0]["provider"] == "searxng"
        assert by_platform(store, second, "icourse163")[0]["provider"] == "tavily"
        assert by_platform(store, second, "bilibili")[0]["provider"] == "searxng"
        assert by_platform(store, second, "bilibili")[0]["cache_hit"]


@pytest.mark.asyncio
async def test_source_health_expiry_and_identity_change_do_not_route_from_last_status(tmp_path):
    async with environment(tmp_path) as (jobs, store, calls, searx, tavily):
        await run(jobs)
        for health in jobs._searxng_failover_health.values():
            health["until"] = time.monotonic() - 1
        searx.last_status = "fault"
        jid = await run(jobs)
        assert by_platform(store, jid, "bilibili")[0]["provider"] == "searxng"
        jobs.settings = replace(jobs.settings, searxng_url="http://different.test")
        jid = await run(jobs, "Python 字典")
        assert by_platform(store, jid, "bilibili")[0]["provider"] == "searxng"


@pytest.mark.asyncio
async def test_only_explicit_timeout_cooldown_for_requested_group_can_preselect(tmp_path):
    async with environment(tmp_path, mode="empty", mooc_provider="") as (jobs, store, calls, searx, tavily):
        until = time.monotonic() + 60
        searx.engine_pauses["video"] = until
        searx.engine_timeout_cooldowns["video"] = until
        jid = await run(jobs)
        assert by_platform(store, jid, "bilibili")[0]["provider"] == "tavily"
        assert by_platform(store, jid, "icourse163")[0]["provider"] == "searxng"
        assert searx.engine_pauses["video"] == until


@pytest.mark.asyncio
async def test_tavily_quota_stop_is_not_reset_or_sent_back_to_searx(tmp_path):
    async with environment(tmp_path, rounds=2, mooc_provider="", tavily_status=432) as (jobs, store, calls, searx, tavily):
        first = await run(jobs)
        assert by_platform(store, first, "bilibili")[1]["error_code"] == "quota_exhausted"
        before = len(calls)
        second = await run(jobs, "Python 字典", ["bilibili"])
        assert len(calls) == before
        assert tavily.quota_exhausted
        assert all(row["provider"] == "tavily" and not row["network_attempted"] for row in store.attempts(second))


@pytest.mark.asyncio
async def test_restore_requires_real_stored_attempts_bound_identity_and_original_clock(tmp_path):
    async with environment(tmp_path) as (jobs, store, calls, searx, tavily):
        first = await run(jobs)
        attempts = deepcopy(store.attempts(first))
        jobs._searxng_failover_health.clear()
        before = store.connection.total_changes
        assert jobs.restore_searxng_failover_health(first, source_identity={"provider": "other"}) == 0
        assert jobs.restore_searxng_failover_health(first, source_identity=jobs._search_identity("searxng")) == 1
        remaining = next(iter(jobs._searxng_failover_health.values()))["until"] - time.monotonic()
        assert 295 < remaining <= 300
        assert store.connection.total_changes == before
        assert store.attempts(first) == attempts
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_cancellation_does_not_elect_failover_or_spend_hidden_request(tmp_path):
    started = asyncio.Event()
    never = asyncio.Event()
    async def handler(request):
        started.set()
        await never.wait()

    async with environment(tmp_path, searx_handler=handler) as (jobs, store, calls, searx, tavily):
        jid = jobs.create(SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=["bilibili"]))["job_id"]
        task = asyncio.create_task(jobs.run(jid))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert len(calls) == 1 and calls[0].url.host == "search.test"
        assert jobs._searxng_failover_health == {}
        assert not store.get_job(jid)["platform_search"].get("source_failovers")


@pytest.mark.asyncio
async def test_optin_is_part_of_new_job_identity_and_disabled_active_job_is_not_reused(tmp_path):
    async with environment(tmp_path, enabled=False) as (jobs, store, calls, searx, tavily):
        request = SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=["bilibili"])
        old = jobs.create(request)["job_id"]
        jobs.settings = replace(jobs.settings, searxng_failover_provider="tavily")
        new = jobs.create(request)["job_id"]
        assert old != new
        assert store.get_job(new)["source_failover_policy"]["cooldown_seconds"] == 300
        assert "source_failover_policy" not in store.get_job(old)
        assert not calls


@pytest.mark.asyncio
async def test_existing_retry_cannot_turn_single_platform_slot_into_two_http_calls(tmp_path):
    async with environment(tmp_path, rounds=2) as (jobs, store, calls, searx, tavily):
        # The transport's optional retry is subject to the same slot hook.
        searx.settings = replace(searx.settings, search_max_retries=1)
        jid = await run(jobs)
        assert len(calls) == 3
        assert [row["provider"] for row in by_platform(store, jid, "bilibili")] == ["searxng", "tavily"]
        assert all(len(row["provider_requests"]) == 1 for row in store.attempts(jid))


@pytest.mark.asyncio
async def test_actual_fallback_cache_hit_has_zero_http_and_never_renews_observation(tmp_path):
    async with environment(tmp_path, rounds=2) as (jobs, store, calls, searx, tavily):
        await run(jobs)
        before = [dict(row) for row in store.connection.execute("SELECT * FROM cache ORDER BY key")]
        call_count = len(calls)
        # One existing slot per platform. A two-round plan would legitimately
        # use a new supplementary query after its cached initial success.
        jobs.settings = replace(jobs.settings, bilibili_search_rounds=1)
        jid = await run(jobs)
        assert len(calls) == call_count
        assert all(row["cache_hit"] and not row["provider_requests"] for row in store.attempts(jid))
        assert store.get_job(jid)["progress"]["search_requests"] == 0
        assert [dict(row) for row in store.connection.execute("SELECT * FROM cache ORDER BY key")] == before


@pytest.mark.asyncio
async def test_expired_or_unstarted_attempt_cannot_recreate_health_and_access_pause_overrides(tmp_path):
    async with environment(tmp_path) as (jobs, store, calls, searx, tavily):
        jid = await run(jobs)
        job = store.get_job(jid)
        failed = by_platform(store, jid, "bilibili")[0]
        jobs._searxng_failover_health.clear()
        stale = deepcopy(failed)
        stale["executed_at"] = "2000-01-01T00:00:00+00:00"
        assert jobs._observe_searxng_attempt(job, stale) is False
        unstarted = {**failed, "provider_requests": []}
        assert jobs._observe_searxng_attempt(job, unstarted) is False
        assert jobs._observe_searxng_attempt(job, failed)
        searx.default_group_pause_until = time.monotonic() + 3600
        next_job = await run(jobs)
        assert by_platform(store, next_job, "bilibili")[0]["provider"] == "searxng"


def test_failover_setting_defaults_off_and_environment_is_explicit(monkeypatch):
    assert Settings().searxng_failover_provider == ""
    monkeypatch.setenv("SEARXNG_FAILOVER_PROVIDER", "TAVILY")
    assert Settings.from_env().searxng_failover_provider == "tavily"
    for invalid in ("serper", "auto", True, None, []):
        with pytest.raises(ValueError, match="SEARXNG_FAILOVER_PROVIDER"):
            replace(Settings(), searxng_failover_provider=invalid).validate()


class MemoryOnlyStore:
    """The concurrency fixture needs neither SQLite nor external services."""
    def __init__(self):
        self._cache, self._attempts, self._jobs = {}, [], {}

    def cache_key(self, kind, value):
        import hashlib
        return hashlib.sha256(json.dumps([kind, value], sort_keys=True).encode()).hexdigest()

    def cache_get(self, key):
        return deepcopy(self._cache.get(key))

    def cache_set(self, key, kind, data, ttl):
        self._cache[key] = {"data": deepcopy(data), "cache": {"hit": True, "cached_at": "offline", "stale": False}}

    def save_job(self, job):
        self._jobs[job["job_id"]] = deepcopy(job)

    def add_attempt(self, jid, attempt):
        self._attempts.append(deepcopy(attempt))


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["access_denied", "retry_after"])
@pytest.mark.parametrize("barrier", ["network_slots", "provider_start_lock"])
async def test_original_source_strong_stop_during_wait_blocks_final_fallback_send(stop, barrier):
    calls = []
    settings = replace(Settings(), searxng_url="http://search.test", searxng_engines=("web",),
        searxng_video_engines=("video",), tavily_api_key="synthetic-key", searxng_failover_provider="tavily",
        parallel_platform_search=True, teaching_match_enabled=True, search_max_retries=0,
        open_web_search_enabled=False, shared_course_library_enabled=False, mooc_gap_search_enabled=False, mooc_refresh_enabled=False,
        search_min_interval_seconds=0, bilibili_search_rounds=1, mooc_search_rounds=1,
        max_search_requests=1, max_detail_pages=0, llm_provider="none", llm_api_key="")

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"results": []})

    store = MemoryOnlyStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        searx, tavily = SearXNGProvider(settings, client), TavilyProvider(settings, client)
        jobs = JobService(settings, store, provider=searx, fetcher=NoFetch(), provider_overrides={"tavily": tavily})
        jobs._searxng_failover_health[("bilibili", jobs._searxng_failover_identity())] = {
            "until": time.monotonic() + 200, "reason": "search_timeout"}
        request = SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=["bilibili"])
        point = {"knowledge_point_id": "original-point", "text": "Python 列表"}
        job = {"job_id": "offline-race", "knowledge_points": [point], "request": request.model_dump(),
            "platform_search": platform_budget(settings, 1, ["bilibili"]), "status": "running", "phase": "searching",
            "budgets": {"max_search_requests": 1}, "progress": {"search_requests": 0, "search_successes": 0,
                "search_failures": 0, "queries_completed": 0, "cache_hits": 0, "candidates_discovered": 0,
                "resources_discovered": 0}, "warnings": [], "errors": []}
        slots = asyncio.Semaphore(0 if barrier == "network_slots" else 1)
        state = {"request": request, "points": [point], "resources": {}, "candidates": {},
            "candidate_groups": {point["knowledge_point_id"]: []}, "started": set(), "ready": False,
            "changed": asyncio.Event(), "network_slots": slots}
        if barrier == "provider_start_lock":
            await tavily._request_start_lock.acquire()
        task = asyncio.create_task(search_platform_rounds(jobs, job, state))
        lock = slots if barrier == "network_slots" else tavily._request_start_lock
        for _ in range(100):
            await asyncio.sleep(0)
            if lock._waiters:
                break
        assert lock._waiters, "The test must reach the actual intended send barrier"
        assert job["platform_search"]["source_failovers"]["bilibili"]["to"] == "tavily"
        assert not calls
        if stop == "access_denied":
            searx.access_denied = True
        else:
            searx.paused_until = time.monotonic() + 300
        lock.release()
        await asyncio.wait_for(task, 3)
        assert calls == []
        assert job["progress"]["search_requests"] == 0
        attempt, = store._attempts
        assert attempt["provider"] == "tavily" and attempt["configured_provider"] == "searxng"
        assert attempt["failover_blocked_before_request"] and attempt["failover_stop_source"] == "searxng"
        assert attempt["status"] == "failed" and attempt["error_code"] == "failover_source_stopped"
        assert attempt["provider_requests"] == [] and not attempt["network_attempted"]
        assert not store._cache
        assert jobs._providers["searxng"] is searx and jobs._providers["tavily"] is tavily
        assert searx.access_denied if stop == "access_denied" else searx.paused_until > time.monotonic()
