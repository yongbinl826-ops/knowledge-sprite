"""Requirements correction: actual queue/provider hooks, all upstreams mocked."""
import asyncio
from collections import Counter
from dataclasses import replace
from contextlib import closing

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.platform_search import platform_budget
from backend.app.providers import SearXNGProvider
from backend.app.service import AdmissionRejected, JobService


def options(**changes):
    return replace(Settings(database_path=":memory:", searxng_url="https://search.example",
        searxng_engines=("web",), searxng_video_engines=("video",), searxng_fallback_engines=(),
        parallel_platform_search=True, teaching_match_enabled=True, max_detail_pages=0,
        search_min_interval_seconds=0, search_max_retries=1, global_concurrency=3, deadline_seconds=10), **changes)


def request(n=2):
    return SearchRequest(knowledge_points=[f"Python 列表 {i}" for i in range(n)],
                         preferred_platforms=["bilibili", "icourse163"])


def lane(query):
    return "bilibili" if "site:bilibili.com" in query else "icourse163" if "site:icourse163.org" in query else "open_web"


@pytest.mark.asyncio
async def test_default_normal_job_has_unrestricted_lane_and_complete_fair_initial_barrier():
    calls, active, peak = [], 0, 0
    async def respond(req):
        nonlocal active, peak
        query = req.url.params["q"]
        calls.append((query, req.url.params.get("engines")))
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.002)
        active -= 1
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    config = options()
    assert config.open_web_search_enabled and config.teaching_match_enabled
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with closing(Store(":memory:")) as store:
            jobs = JobService(config, store, provider=SearXNGProvider(config, client))
            jid = jobs.create(request())["job_id"]
            await jobs.run(jid)
            job, attempts = store.get_job(jid), store.attempts(jid)
            assert peak == 3
            assert job["budgets"]["max_search_requests"] == len(calls) == 10
            assert Counter(row["platform"] for row in attempts) == {"open_web": 2, "bilibili": 4, "icourse163": 4}
            assert all(row["search_phase"] == "initial" for row in attempts[:6])
            assert all(row["search_phase"] == "followup" for row in attempts[6:])
            assert Counter((row["knowledge_point_id"], row["platform"]) for row in attempts[:6]) == Counter(
                (point["knowledge_point_id"], platform) for point in job["knowledge_points"] for platform in ("bilibili", "icourse163", "open_web"))
            assert all(row["domain_filters"] == [] and "site:" not in row["query"] for row in attempts if row["platform"] == "open_web")
            assert all(engine == "web" for query, engine in calls if lane(query) == "open_web")
            assert all(len(row["provider_requests"]) == 1 for row in attempts)
            assert jobs.course_library is not None and jobs.mooc_refresh is not None


def test_default_five_points_fit_budget_and_insufficient_plan_is_recoverably_rejected():
    assert platform_budget(options(), 5, ["bilibili", "icourse163"])["initial_search_requests"] == 15
    assert platform_budget(options(), 5, ["bilibili", "icourse163"])["max_search_requests"] == 25
    with closing(Store(":memory:")) as store:
        jobs = JobService(options(max_search_requests=14), store)
        with pytest.raises(AdmissionRejected) as caught:
            jobs.create(request(5))
        assert caught.value.code == "search_budget_insufficient" and caught.value.status == 422
        assert store.job_counts() == {}


@pytest.mark.parametrize("cap", [20, 21, 24, 26, 29, 30, 35])
def test_all_default_platforms_keep_initial_pass_and_clip_only_fair_optional_slots(cap):
    plan = platform_budget(options(max_search_requests=cap), 5, ["bilibili", "icourse163", "xuetangx"])
    assert plan["initial_search_requests"] == 20
    assert plan["requested_search_requests"] == 35
    assert plan["reserved_search_requests"] == plan["max_search_requests"] == min(cap, 35)
    assert sum(plan["platform_request_limits"].values()) == min(cap, 35)
    assert plan["budget_limited"] == (cap < 35)
    for platform in ("bilibili", "icourse163", "xuetangx"):
        indexes = plan["followup_point_indexes"].get("1", {}).get(platform, [])
        counts = [indexes.count(index) for index in range(5)]
        assert max(counts)-min(counts) <= 1
        assert len(indexes) == len(set(indexes))


@pytest.mark.asyncio
async def test_one_lane_failure_cannot_remove_other_lanes_or_first_passes():
    calls = []
    async def respond(req):
        query = req.url.params["q"]
        calls.append(query)
        return httpx.Response(502 if lane(query) == "icourse163" else 200,
                              json={"results": [], "unresponsive_engines": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with closing(Store(":memory:")) as store:
            config = options()
            jobs = JobService(config, store, provider=SearXNGProvider(config, client))
            jid = jobs.create(request())["job_id"]
            await jobs.run(jid)
            assert Counter(map(lane, calls)) == {"open_web": 2, "bilibili": 4, "icourse163": 4}
            job = store.get_job(jid)
            assert job["progress"]["search_requests"] == 10
            assert job["progress"]["search_failures"] == 4
            assert len(store.attempts(jid)) == 10


@pytest.mark.asyncio
async def test_clipped_plan_executes_all_initial_pairs_and_only_reserved_fair_followups():
    calls = []
    async def respond(req):
        calls.append(req.url.params["q"])
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    config = options(max_search_requests=26, mooc_gap_search_enabled=False)
    req = request(5).model_copy(update={"preferred_platforms": ["bilibili", "icourse163", "xuetangx"]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with closing(Store(":memory:")) as store:
            jobs = JobService(config, store, provider=SearXNGProvider(config, client))
            jid = jobs.create(req)["job_id"]
            await jobs.run(jid)
            job, attempts = store.get_job(jid), store.attempts(jid)
            assert len(calls) == job["progress"]["search_requests"] == 26
            assert job["status"] == "partial" and job["platform_search"]["budget_limited"]
            assert job["budgets"]["requested_search_requests"] == 35
            assert job["budgets"]["reserved_search_requests"] == 26
            assert len(attempts) == job["progress"]["queries_planned"] == 26
            assert all(row["search_phase"] == "initial" for row in attempts[:20])
            assert len({(row["knowledge_point_id"], row["platform"]) for row in attempts[:20]}) == 20
            for platform in ("bilibili", "icourse163", "xuetangx"):
                counts = Counter(row["knowledge_point_id"] for row in attempts[20:] if row["platform"] == platform)
                per_point = [counts[p["knowledge_point_id"]] for p in job["knowledge_points"]]
                assert max(per_point) - min(per_point) <= 1


@pytest.mark.asyncio
async def test_exact_prior_lane_cache_is_read_without_renewal_or_extra_source_request():
    calls = []
    async def respond(req):
        calls.append(req.url.params["q"])
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    config = options(open_web_search_enabled=False, bilibili_search_rounds=1, mooc_search_rounds=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with closing(Store(":memory:")) as store:
            jobs = JobService(config, store, provider=SearXNGProvider(config, client))
            first = jobs.create(request(1))["job_id"]
            await jobs.run(first)
            before = [tuple(row) for row in store.connection.execute("SELECT key,created,expires,data FROM cache WHERE kind='search'")]
            jobs.settings = replace(config, open_web_search_enabled=True)
            second = jobs.create(request(1))["job_id"]
            await jobs.run(second)
            assert len(calls) == 3 and lane(calls[-1]) == "open_web"
            assert store.get_job(second)["progress"]["search_requests"] == 1
            assert store.get_job(second)["progress"]["cache_hits"] == 2
            after = {row[0]: tuple(row) for row in store.connection.execute("SELECT key,created,expires,data FROM cache WHERE kind='search'")}
            assert all(after[row[0]] == row for row in before)


@pytest.mark.asyncio
async def test_default_new_plan_can_defer_and_resume_without_repeating_initial_web_lane():
    calls = []
    async def respond(req):
        calls.append(req.url.params["q"])
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with closing(Store(":memory:")) as store:
            config = options()
            jobs = JobService(config, store, provider=SearXNGProvider(config, client))
            jid = jobs.create(request(), consumer_key="owner", defer_platform_followups=True)["job_id"]
            await jobs.run(jid)
            assert len(calls) == 6 and store.get_job(jid)["phase"] == "awaiting_followup"
            assert jobs.resume_platform_search(jid, consumer_key="owner")
            await jobs.run(jid)
            assert len(calls) == 10 and Counter(map(lane, calls))["open_web"] == 2


@pytest.mark.asyncio
async def test_original_persisted_plan_does_not_gain_web_requests_after_configuration_changes():
    calls = []
    async def respond(req):
        calls.append(req.url.params["q"])
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})
    config = options(open_web_search_enabled=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with closing(Store(":memory:")) as store:
            jobs = JobService(config, store, provider=SearXNGProvider(config, client))
            jid = jobs.create(request(1))["job_id"]
            jobs.settings = replace(config, open_web_search_enabled=True)
            await jobs.run(jid)
            assert len(calls) == 4 and all(lane(query) != "open_web" for query in calls)
            assert store.get_job(jid)["platform_search"]["policy"] == "platform-rounds-v1"
