"""Legacy-query observations may be reused exactly, never renewed or broadened."""
from contextlib import asynccontextmanager, closing
from copy import deepcopy
import json
import time

import httpx
import pytest

from backend.app.db import Store
from backend.app.models import Candidate, SearchRequest
from backend.app.platform_search import platform_query
from backend.app.providers import SearXNGProvider, SerperProvider, TavilyProvider
from backend.app.service import JobService
from test_platform_provider_selection import NoFetch, config


POINT = "pandas 数据分组与聚合"
V1 = "course-discovery-phrases-v1"


@asynccontextmanager
async def environment(tmp_path, *, provider="tavily", rounds=1, both=False):
    calls = []

    def transport(request):
        calls.append(request)
        if request.url.host == "api.tavily.com":
            return httpx.Response(200, json={"results": []})
        if request.url.host == "google.serper.dev":
            return httpx.Response(200, json={"organic": []})
        assert request.url.host == "search.test", "Only synthetic HTTP is permitted"
        return httpx.Response(200, json={"results": [], "unresponsive_engines": []})

    settings = config(tmp_path, mooc_search_provider=provider, serper_api_key="synthetic-key",
                      mooc_search_rounds=rounds, bilibili_search_rounds=1)
    request = SearchRequest(knowledge_points=[POINT], preferred_platforms=(
        ["bilibili", "icourse163"] if both else ["icourse163"]))
    with closing(Store(settings.database_path)) as store:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            jobs = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=NoFetch(),
                              provider_overrides={"tavily": TavilyProvider(settings, client),
                                                  "serper": SerperProvider(settings, client)})
            jid = jobs.create(request)["job_id"]
            yield jobs, store, request, jid, calls


def scope(jobs, store, request, jid, *, index=0, platform="icourse163", provider=None):
    job = store.get_job(jid)
    point = job["knowledge_points"][0]
    query = platform_query(point, platform, request, round_index=index)
    return {"policy": job["platform_search"]["policy"],
            **jobs._search_identity(provider or jobs.settings.search_provider_for(platform)),
            "original_point": point["text"], "query": query.query, "domains": query.domain_filters,
            "language": request.language, "limit": jobs.settings.search_results_per_query}


def seed(store, fields, *, title="Pandas 数据分组与聚合课程", ttl=3600):
    key = store.cache_key("search", fields)
    candidate = Candidate(id="cached-course", title=title,
                          url="https://www.icourse163.org/course/OWN-123", snippet=POINT + " 教学内容",
                          source=fields["provider"], query=fields["query"], resource_type_hint="course")
    store.cache_set(key, "search", {"candidates": [candidate.model_dump()], "upstream_warnings": []}, ttl)
    return key


def saved(store, key):
    row = store.connection.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["tavily", "serper"])
async def test_same_v1_query_reuses_original_observation_without_network_or_timestamp_renewal(tmp_path, provider):
    async with environment(tmp_path, provider=provider) as (jobs, store, request, jid, calls):
        current = scope(jobs, store, request, jid)
        assert current["mooc_query_policy"] == "course-discovery-phrases-v2"
        key = seed(store, {**current, "mooc_query_policy": V1})
        before = saved(store, key)
        original_point = deepcopy(store.get_job(jid)["knowledge_points"][0])
        await jobs.run(jid)
        assert not calls
        attempt, = store.attempts(jid)
        assert attempt["cache_hit"] and not attempt["network_attempted"]
        assert attempt["query"] == current["query"] and attempt["provider"] == provider
        assert attempt["provider_requests"] == [] and attempt["candidate_count"] == 1
        assert saved(store, key) == before
        assert saved(store, store.cache_key("search", current)) is None
        assert store.get_job(jid)["knowledge_points"][0] == original_point
        assert store.get_job(jid)["progress"]["search_requests"] == 0
        resource, = store.resources(jid).values()
        evidence = store.evidence(jid, resource["resource_id"])
        search = [row for row in evidence if row["kind"] == "search"]
        assert len(search) == 1
        assert search[0]["query"] == current["query"]
        assert search[0]["knowledge_point_id"] == original_point["knowledge_point_id"]
        assert not any(item["resource"]["platform"] == "icourse163"
                       for group in jobs.results(jid)["groups"] for item in group["discovery_items"])


@pytest.mark.asyncio
async def test_current_policy_cache_takes_precedence_over_legacy_without_rewriting_either(tmp_path):
    async with environment(tmp_path) as (jobs, store, request, jid, calls):
        fields = scope(jobs, store, request, jid)
        current = seed(store, fields, title="Pandas 数据分组与聚合 当前观察")
        legacy = seed(store, {**fields, "mooc_query_policy": V1}, title="Pandas 数据分组与聚合 早期观察")
        before = [saved(store, key) for key in (current, legacy)]
        await jobs.run(jid)
        assert not calls
        assert [saved(store, key) for key in (current, legacy)] == before
        assert [row["title"] for row in store.resources(jid).values()] == ["Pandas 数据分组与聚合 当前观察"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"original_point": "pandas 数据分组"}, {"query": "site:icourse163.org/course pandas 聚合 课程"},
    {"domains": ["example.org"]}, {"language": "en"}, {"limit": 99},
    {"provider": "serper"}, {"provider_version": -1}, {"policy": "old-platform-plan"},
])
async def test_legacy_cache_cannot_cross_original_scope_provider_or_observation_contract(tmp_path, change):
    async with environment(tmp_path) as (jobs, store, request, jid, calls):
        fields = scope(jobs, store, request, jid)
        key = seed(store, {**fields, "mooc_query_policy": V1, **change})
        before = saved(store, key)
        await jobs.run(jid)
        assert len(calls) == 1 and calls[0].url.host == "api.tavily.com"
        attempt, = store.attempts(jid)
        assert attempt["network_attempted"] and not attempt["cache_hit"]
        assert attempt["candidate_count"] == 0
        assert saved(store, key) == before


@pytest.mark.asyncio
async def test_expired_legacy_observation_is_not_renewed_or_reused(tmp_path):
    async with environment(tmp_path) as (jobs, store, request, jid, calls):
        key = seed(store, {**scope(jobs, store, request, jid), "mooc_query_policy": V1}, ttl=-1)
        before = saved(store, key)
        await jobs.run(jid)
        assert len(calls) == 1 and not store.attempts(jid)[0]["cache_hit"]
        assert saved(store, key) == before


@pytest.mark.asyncio
async def test_first_five_exact_queries_reuse_v1_but_changed_sixth_phrase_query_runs_once(tmp_path):
    async with environment(tmp_path, rounds=6) as (jobs, store, request, jid, calls):
        legacy_keys = []
        for index in range(6):
            fields = scope(jobs, store, request, jid, index=index)
            if index == 5:
                fields["query"] = "site:icourse163.org/course pandas 数据分组与聚合 课程 大纲"
            legacy_keys.append(seed(store, {**fields, "mooc_query_policy": V1}))
        before = [saved(store, key) for key in legacy_keys]
        await jobs.run(jid)
        attempts = store.attempts(jid)
        assert len(attempts) == 6 and [row["cache_hit"] for row in attempts] == [True] * 5 + [False]
        assert len(calls) == 1
        assert json.loads(calls[0].content)["query"] == 'site:icourse163.org/course pandas "数据分组" "聚合"'
        assert [saved(store, key) for key in legacy_keys] == before
        assert all(saved(store, store.cache_key("search", scope(jobs, store, request, jid, index=index))) is None
                   for index in range(5))
        assert store.get_job(jid)["progress"]["search_requests"] == 1


@pytest.mark.asyncio
async def test_mooc_legacy_compatibility_does_not_change_bilibili_query_or_cache_identity(tmp_path):
    async with environment(tmp_path, both=True) as (jobs, store, request, jid, calls):
        seed(store, {**scope(jobs, store, request, jid), "mooc_query_policy": V1})
        bili = scope(jobs, store, request, jid, platform="bilibili")
        assert "mooc_query_policy" not in bili
        bad_key = seed(store, {**bili, "mooc_query_policy": V1})
        before = saved(store, bad_key)
        await jobs.run(jid)
        assert len(calls) == 1 and calls[0].url.host == "search.test"
        assert calls[0].url.params["q"] == "site:bilibili.com/video pandas 数据分组与聚合 视频教程"
        attempt, = [row for row in store.attempts(jid) if row["provider"] == "searxng"]
        assert attempt["network_attempted"] and not attempt["cache_hit"]
        assert saved(store, bad_key) == before


@pytest.mark.asyncio
async def test_due_refresh_bypasses_both_current_and_legacy_cache_and_preserves_the_legacy_clock(tmp_path):
    from test_mooc_refresh import CoursePages, SearchHTTP, request, run, service, settings

    configured, transport, pages = settings(tmp_path), SearchHTTP(), CoursePages()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with closing(Store(configured.database_path)) as store:
            jobs = service(configured, store, client, pages)
            await run(jobs)
            old = time.time() - 86401
            store.connection.execute("UPDATE mooc_refresh_state SET last_success=?,last_attempt=?", (old, old))
            store.connection.commit()
            transport.calls.clear()
            req = request()
            jid = jobs.create(req)["job_id"]
            fields = scope(jobs, store, req, jid, index=2)
            current = seed(store, fields)
            legacy = seed(store, {**fields, "mooc_query_policy": V1})
            before = saved(store, legacy)
            await jobs.run(jid)
            live = [row for row in store.attempts(jid) if row["network_attempted"]]
            assert len(live) == len(transport.mooc_calls) == 1
            assert live[0]["refresh_probe"] and not live[0]["cache_hit"]
            assert live[0]["query"] == fields["query"]
            assert saved(store, legacy) == before
            assert saved(store, current)["data"] != before["data"]
            assert store.connection.execute("SELECT last_success FROM mooc_refresh_state").fetchone()[0] > old
