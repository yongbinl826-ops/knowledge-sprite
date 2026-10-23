"""Offline expansion/streaming checks; no live providers or production data."""
import asyncio
from collections import Counter
from contextlib import closing
from dataclasses import replace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, SearchRequest
from backend.app.platform_search import platform_budget, platform_query
from backend.app.providers import SearXNGProvider, TavilyProvider
from backend.app.service import IdempotencyConflict, JobService
from test_mooc_relevance_service import synthetic_outline
from test_parallel_platform_search import NoFetch, options, platform, request, response
from test_platform_provider_selection import config as routed_config, respond as routed_response
from test_projects import analyzed, setup as project_setup, settle


def test_expanded_per_platform_budget_and_limits_are_exact(tmp_path):
    settings = options(tmp_path, max_search_requests=80, bilibili_search_rounds=3, mooc_search_rounds=5)
    plan = platform_budget(settings, 5, ["bilibili", "icourse163", "bilibili"])
    assert plan["policy"] == "platform-rounds-v2"
    assert plan["platform_rounds"] == {"bilibili": 3, "icourse163": 5}
    assert plan["platform_request_limits"] == {"bilibili": 15, "icourse163": 25}
    assert plan["initial_search_requests"] == 10
    assert plan["followup_search_requests"] == 30
    assert plan["max_search_requests"] == 40
    assert platform_budget(settings, 5, ["icourse163"])["max_search_requests"] == 25
    with pytest.raises(ValueError, match="40"):
        platform_budget(replace(settings, max_search_requests=39), 5, ["bilibili", "icourse163"])


def test_expanded_environment_limits_are_not_silently_clipped(monkeypatch):
    for name, value in {"BILIBILI_SEARCH_ROUNDS": "3", "MOOC_SEARCH_ROUNDS": "5",
                        "MAX_SEARCH_REQUESTS": "80", "MAX_DETAIL_PAGES": "60",
                        "SEARCH_RESULTS_PER_QUERY": "12"}.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert (settings.bilibili_search_rounds, settings.mooc_search_rounds) == (3, 5)
    assert (settings.max_search_requests, settings.max_detail_pages, settings.search_results_per_query) == (80, 60, 12)


@pytest.mark.parametrize("field,value", [
    ("bilibili_search_rounds", value) for value in [0, 7, True, "3"]
] + [("mooc_search_rounds", value) for value in [0, 11, True, "3"]])
def test_round_configuration_rejects_invalid_limits(field, value):
    with pytest.raises(ValueError):
        replace(Settings(), **{field: value}).validate()


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("name", ["Python 列表与字典", "pandas 分组聚合", "SQL JOIN and GROUP BY"])
@pytest.mark.parametrize("source", ["bilibili", "icourse163"])
def test_supplementary_queries_are_distinct_and_keep_original_technical_owner(language, name, source):
    point = {"knowledge_point_id": "point", "text": name}
    search = SearchRequest(knowledge_points=[name], preferred_platforms=[source], language=language)
    original_request = search.model_dump(mode="json")
    queries = [platform_query(point, source, search, round_index=index) for index in range(6)]
    assert len(queries) == 6
    assert len({query.query.casefold() for query in queries}) == 6
    assert name in queries[0].query
    expected_domain = "bilibili.com" if source == "bilibili" else "icourse163.org"
    assert all(query.domain_filters == [expected_domain] for query in queries)
    assert search.model_dump(mode="json") == original_request
    assert point == {"knowledge_point_id": "point", "text": name}
    assert all(name.split()[0] in query.query for query in queries)
    assert all(query.knowledge_point_id == "point" for query in queries)
    if name == "Python 列表与字典":
        # Bili's two existing supplementary slots now cover the two literal
        # components independently; a dictionary query must not inherit list.
        first_part, second_part = (1, 2) if source == "bilibili" else (2, 3)
        assert "Python 列表 " in queries[first_part].query
        assert "Python 字典 " in queries[second_part].query
        assert "字典" not in queries[first_part].query
        assert "列表" not in queries[second_part].query


def test_confirmed_targets_diversify_recall_without_donating_operators_or_new_owner():
    text = "pandas 表格数据处理"
    point = {"knowledge_point_id": "point", "text": text}
    search = SearchRequest(knowledge_points=[text], preferred_platforms=["icourse163"],
                          learning_targets={text: ["DataFrame.groupby()", "agg() 聚合"]})
    third = platform_query(point, "icourse163", search, round_index=2).query
    fourth = platform_query(point, "icourse163", search, round_index=3).query
    assert "pandas DataFrame.groupby" in third and "pandas agg 聚合" in fourth
    assert third.startswith("site:icourse163.org/course ")
    assert "(" not in third and ")" not in third


@pytest.mark.asyncio
async def test_expanded_rounds_run_all_queries_with_fair_first_pass_and_larger_result_limit(tmp_path):
    calls = []
    async def respond(req):
        query = req.url.params["q"]
        calls.append(query)
        await asyncio.sleep(.001)
        payload = response(query)
        candidate = payload["results"][0]
        payload["results"] = [{**candidate, "url": candidate["url"].rstrip("/") + str(index)} for index in range(12)]
        return httpx.Response(200, json=payload)
    settings = options(tmp_path, max_search_requests=80, bilibili_search_rounds=3,
                       mooc_search_rounds=5, search_results_per_query=12)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with closing(Store(settings.database_path)) as store:
            jobs = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=NoFetch())
            jid = jobs.create(request(2))["job_id"]
            await jobs.run(jid)
            attempts, job = store.attempts(jid), store.get_job(jid)
            assert len(calls) == job["progress"]["search_requests"] == 16
            # Two topics with the same explicit owner can intentionally use
            # the same broad MOOC course query; their evidence stays separate.
            assert len(set(calls)) == 15
            assert Counter(map(platform, calls)) == {"bilibili": 6, "icourse163": 10}
            assert [row["search_phase"] for row in attempts[:4]] == ["initial"] * 4
            assert Counter(row["search_round"] for row in attempts) == {1: 4, 2: 4, 3: 4, 4: 2, 5: 2}
            assert all(row["candidate_count"] == 12 for row in attempts)
            assert job["progress"]["queries_planned"] == job["progress"]["queries_completed"] == 16
            assert job["platform_search"]["completed_rounds"] == 5
            assert job["platform_search"]["finished"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429, 432])
async def test_more_rounds_do_not_restart_a_stopped_mooc_source_or_consume_bilibili_quota(tmp_path, status):
    calls = []
    def respond(req):
        calls.append(req)
        if req.url.host == "api.tavily.com":
            return httpx.Response(status, headers={"retry-after": "600"})
        return routed_response(req)
    settings = routed_config(tmp_path, bilibili_search_rounds=3, mooc_search_rounds=5,
                             max_search_requests=80, search_results_per_query=12)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with closing(Store(settings.database_path)) as store:
            jobs = JobService(settings, store, provider=SearXNGProvider(settings, client),
                provider_overrides={"tavily": TavilyProvider(settings, client)}, fetcher=NoFetch())
            jid = jobs.create(request(2))["job_id"]
            await jobs.run(jid)
            assert len([row for row in calls if row.url.host == "api.tavily.com"]) == 1
            assert len([row for row in calls if row.url.host == "search.test"]) == 6
            assert store.get_job(jid)["progress"]["platform_search_requests"] == {"bilibili": 6, "icourse163": 1}
            mooc = [row for row in store.attempts(jid) if row["platform"] == "icourse163"]
            assert len(mooc) == 10 and sum(row["network_attempted"] for row in mooc) == 1


@pytest.mark.asyncio
async def test_first_mooc_outline_can_be_displayed_while_other_initial_search_is_pending(tmp_path):
    blocked, release, fetched = asyncio.Event(), asyncio.Event(), asyncio.Event()
    name = "Python 列表与字典"
    url = "https://www.icourse163.org/course/OWN-123"
    class Search:
        async def search(self, query, *args):
            if "SQL" in query:
                blocked.set()
                await release.wait()
                return []
            return [Candidate(id="first", title=name, url=url, snippet=name + " 课程教学", query=query,
                              source="offline", resource_type_hint="course", type_source="search_template")]
    class Fetch:
        async def enrich(self, candidate):
            result = MetadataExtractor().extract(synthetic_outline(), url, "offline-first-result")
            fetched.set()
            return result
    settings = options(tmp_path, max_detail_pages=2, global_concurrency=2,
                       bilibili_search_rounds=3, mooc_search_rounds=5, max_search_requests=80)
    with closing(Store(settings.database_path)) as store:
        jobs = JobService(settings, store, provider=Search(), fetcher=Fetch())
        jid = jobs.create(SearchRequest(knowledge_points=[name, "SQL 多表连接"],
                                       preferred_platforms=["icourse163"]))["job_id"]
        running = asyncio.create_task(jobs.run(jid))
        try:
            await asyncio.wait_for(blocked.wait(), 2)
            await asyncio.wait_for(fetched.wait(), 2)
            for _ in range(50):
                group = jobs.results(jid)["groups"][0]
                if group["discovery_items"]:
                    break
                await asyncio.sleep(.01)
            assert group["discovery_items"][0]["mooc_relevance"]["status"] == "outline_supported"
            assert not running.done()
            assert not store.get_job(jid)["platform_search"].get("initial_done")
            assert store.get_job(jid)["progress"]["queries_completed"] == 1
        finally:
            release.set()
            await asyncio.wait_for(running, 3)


@pytest.mark.asyncio
async def test_old_persisted_two_round_plan_is_not_expanded_by_new_settings(tmp_path):
    settings = options(tmp_path)
    class Search:
        async def search(self, *args):
            return []
    with closing(Store(settings.database_path)) as store:
        jobs = JobService(settings, store, provider=Search(), fetcher=NoFetch())
        jid = jobs.create(request(2))["job_id"]
        job = store.get_job(jid)
        del job["platform_search"]["platform_rounds"]
        jobs._save(job)
        jobs.settings = replace(settings, bilibili_search_rounds=3, mooc_search_rounds=5)
        await jobs.run(jid)
        assert len(store.attempts(jid)) == 8
        assert store.get_job(jid)["platform_search"]["completed_rounds"] == 2


@pytest.mark.asyncio
async def test_project_confirmation_reserves_larger_batches_without_losing_points(tmp_path):
    _, store, jobs, projects = project_setup(tmp_path, parallel_platform_search=True,
        teaching_match_enabled=False, bilibili_search_rounds=3, mooc_search_rounds=5,
        project_max_detail_pages=360, project_max_search_requests=480)
    jobs.settings = projects.settings = replace(projects.settings, max_search_requests=80, max_detail_pages=60)
    try:
        view = await analyzed(projects, 7, preferred_platforms=["bilibili", "icourse163"])
        confirmed = projects.confirm(view["project_id"], 1, [])
        budget = confirmed["version"]["budgets"]
        assert budget["selected_count"] == 7
        assert budget["batch_search_requests"] == [45, 18]
        assert budget["reserved_search_requests"] == 63
        assert budget["reserved_detail_pages"] == 120
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


def test_equal_total_with_different_platform_rounds_cannot_reuse_active_job_or_idempotency_key(tmp_path):
    settings = options(tmp_path, max_search_requests=80, bilibili_search_rounds=3, mooc_search_rounds=5)
    with closing(Store(settings.database_path)) as store:
        jobs = JobService(settings, store, provider=object(), fetcher=NoFetch())
        first = jobs.create(request(2), idempotency_key="expanded-plan")
        assert jobs.create(request(2), idempotency_key="expanded-plan")["job_id"] == first["job_id"]
        assert jobs.create(request(2))["job_id"] == first["job_id"]
        jobs.settings = replace(settings, bilibili_search_rounds=4, mooc_search_rounds=4)
        with pytest.raises(IdempotencyConflict):
            jobs.create(request(2), idempotency_key="expanded-plan")
        second = jobs.create(request(2))
        assert second["job_id"] != first["job_id"]
        assert store.get_job(first["job_id"])["budgets"]["max_search_requests"] == store.get_job(second["job_id"])["budgets"]["max_search_requests"]


def test_old_v1_idempotency_hash_and_missing_rounds_remain_compatible(tmp_path):
    settings = options(tmp_path)
    with closing(Store(settings.database_path)) as store:
        jobs = JobService(settings, store, provider=object(), fetcher=NoFetch())
        first = jobs.create(request(2), idempotency_key="legacy-plan")
        job = store.get_job(first["job_id"])
        del job["platform_search"]["platform_rounds"]
        jobs._save(job)
        expected_hash = store.cache_key("request", {"request": job["request"], "policy": "platform-rounds-v1", "defer_followups": False})
        assert store.idempotent_request("legacy-plan")["request_hash"] == expected_hash
        assert jobs.create(request(2), idempotency_key="legacy-plan")["job_id"] == first["job_id"]
        assert jobs.create(request(2))["job_id"] == first["job_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("new_bilibili,new_mooc,rejected", [(4, 4, True), (2, 4, False)])
async def test_project_respects_confirmed_per_source_allowance_even_when_total_does_not_grow(tmp_path, new_bilibili, new_mooc, rejected):
    _, store, jobs, projects = project_setup(tmp_path, parallel_platform_search=True,
        teaching_match_enabled=False, bilibili_search_rounds=3, mooc_search_rounds=5)
    jobs.settings = projects.settings = replace(projects.settings, max_search_requests=80)
    jobs.start()
    try:
        view = await analyzed(projects, 2, preferred_platforms=["bilibili", "icourse163"])
        pid = view["project_id"]
        projects.confirm(pid, 1, [])
        projects.search(pid, 1)
        jobs.settings = projects.settings = replace(projects.settings,
            bilibili_search_rounds=new_bilibili, mooc_search_rounds=new_mooc)
        await settle(projects)
        batch = projects.results(pid, 1)["version"]["batches"][0]
        if rejected:
            assert batch["status"] == "budget_exceeded"
            assert batch["error"]["code"] == "runtime_limits_changed"
            assert not batch.get("job_id") and store.job_counts() == {}
        else:
            assert batch["job_id"]
            assert store.get_job(batch["job_id"])["budgets"]["max_search_requests"] == 14
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()
