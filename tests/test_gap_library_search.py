"""Bounded gap-fill scheduling. All providers and outlines are local fixtures."""
import asyncio
from collections import Counter
from contextlib import closing
from dataclasses import replace

import httpx
import pytest

from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, SearchRequest, now
from backend.app.providers import SearchError, SearXNGProvider, TavilyProvider
from backend.app.result_stream import job_snapshot
from backend.app.service import IdempotencyConflict, JobService
from test_mooc_relevance_service import synthetic_outline
from test_parallel_platform_search import NoFetch, options, platform
from test_platform_provider_selection import config as routed_config, respond as routed_response


POINT = "Python 列表与字典"
URL = "https://www.icourse163.org/course/OWN-123"


def settings(tmp_path, **extra):
    extra.setdefault("mooc_refresh_enabled", False)  # Gap-only controls; refresh has its own suite.
    return options(tmp_path, bilibili_search_rounds=3, mooc_search_rounds=5,
        max_search_requests=80, mooc_gap_search_enabled=True,
        mooc_target_courses_per_point=1, **extra)


class Search:
    def __init__(self):
        self.calls = []

    async def search(self, query, *args):
        self.calls.append(query)
        mooc = platform(query) == "icourse163"
        return [Candidate(id="mooc" if mooc else "bili", title=POINT,
            url=URL if mooc else "https://www.bilibili.com/video/BV1VZ4y1G7YB/",
            snippet=POINT + " 课程教学", query=query, source="offline",
            resource_type_hint="course" if mooc else "video", type_source="search_template")]


class Outline:
    def __init__(self, chapters=("列表", "字典")):
        self.chapters = chapters
        self.calls = []
        self.started = asyncio.Event()
        self.release = None

    async def enrich(self, candidate):
        self.calls.append(candidate["url"])
        if "icourse163" not in candidate["url"]:
            return {"fetch_status": "not_found"}
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        await asyncio.sleep(.02)
        return MetadataExtractor().extract(synthetic_outline(chapters=self.chapters),
                                          candidate["url"], now())


@pytest.mark.asyncio
async def test_covered_point_skips_all_mooc_searches_and_keeps_every_bilibili_round(tmp_path, monkeypatch):
    config = settings(tmp_path)
    search = Search()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=NoFetch())
        # The library service owns matching/provenance. Here its coverage hook
        # explicitly supplies a full first point and an empty second point.
        monkeypatch.setattr(jobs, "_mooc_coverage_count", lambda job, point, state:
                            int(point["text"] == POINT))
        jid = jobs.create(SearchRequest(knowledge_points=[POINT, "Python 文件读取"],
                                       preferred_platforms=["bilibili", "icourse163"]))["job_id"]
        await jobs.run(jid)
        job = store.get_job(jid)
        assert Counter(map(platform, search.calls)) == {"bilibili": 6, "icourse163": 5}
        progress = job["progress"]
        assert progress["queries_planned"] == progress["queries_completed"] == 16
        assert progress["search_requests"] == 11
        assert progress["queries_skipped"] == progress["gap_queries_skipped"] == 5
        skipped = [row for row in store.attempts(jid) if row["status"] == "skipped"]
        assert len(skipped) == 5
        assert all(row["platform"] == "icourse163" and not row["network_attempted"]
                   and not row["provider_requests"] and not row["cache_hit"] for row in skipped)
        full, empty = [job["gap_search"]["points"][point["knowledge_point_id"]]
                       for point in job["knowledge_points"]]
        assert full["stopped_reason"] == "coverage_target_met" and full["remaining"] == 0
        assert empty["remaining"] == 1 and empty["stopped_reason"] == "max_rounds_reached"


@pytest.mark.asyncio
async def test_first_outline_finishes_before_supplementary_mooc_credit_is_spent(tmp_path):
    config = settings(tmp_path, max_detail_pages=4)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        jid = jobs.create(SearchRequest(knowledge_points=[POINT],
                                       preferred_platforms=["bilibili", "icourse163"]))["job_id"]
        await jobs.run(jid)
        assert Counter(map(platform, search.calls)) == {"bilibili": 3, "icourse163": 1}
        job = store.get_job(jid)
        assert job["progress"]["queries_completed"] == 8
        assert job["progress"]["gap_queries_skipped"] == 4
        group = jobs.results(jid)["groups"][0]
        assert group["mooc_relevance"]["recommended_count"] == 1
        assert sum("icourse163" in url for url in outline.calls) == 1
        attempts = store.attempts(jid)
        assert all(row["search_phase"] == "initial" for row in attempts[:2])


@pytest.mark.asyncio
async def test_partial_outline_never_satisfies_the_gap_target(tmp_path):
    config = settings(tmp_path, max_detail_pages=4)
    search, outline = Search(), Outline(chapters=("列表",))
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        jid = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(jid)
        job = store.get_job(jid)
        assert len(search.calls) == 5 and job["progress"]["gap_queries_skipped"] == 0
        assert jobs.results(jid)["groups"][0]["mooc_relevance"]["recommended_count"] == 0
        point = job["knowledge_points"][0]
        assert job["gap_search"]["points"][point["knowledge_point_id"]]["remaining"] == 1


@pytest.mark.asyncio
async def test_no_detail_budget_does_not_deadlock_supplementary_search(tmp_path):
    config = settings(tmp_path)
    search = Search()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=NoFetch())
        jid = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await asyncio.wait_for(jobs.run(jid), 1)
        assert len(search.calls) == 5
        assert store.get_job(jid)["progress"]["gap_queries_skipped"] == 0


@pytest.mark.asyncio
async def test_gap_wait_is_cancelled_without_issuing_a_second_mooc_search(tmp_path):
    config = settings(tmp_path, max_detail_pages=4)
    search, outline = Search(), Outline()
    outline.release = asyncio.Event()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        jobs.start()
        try:
            jid = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
            await asyncio.wait_for(outline.started.wait(), 1)
            await asyncio.sleep(.03)
            assert len(search.calls) == 1
            cancelled = await asyncio.wait_for(jobs.cancel(jid), 1)
            assert cancelled["status"] == "cancelled" and len(search.calls) == 1
        finally:
            await jobs.stop()


@pytest.mark.asyncio
async def test_deferred_project_followups_reuse_first_pass_outline_without_repeating_search(tmp_path):
    config = settings(tmp_path, max_detail_pages=4)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        jobs.start()
        try:
            jid = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]),
                consumer_key="project:gap-fixture", defer_platform_followups=True)["job_id"]
            await asyncio.wait_for(jobs.queue.join(), 2)
            assert store.get_job(jid)["phase"] == "awaiting_followup" and len(search.calls) == 1
            assert jobs.resume_platform_search(jid, consumer_key="project:gap-fixture")
            await asyncio.wait_for(jobs.queue.join(), 2)
            job = store.get_job(jid)
            assert job["platform_search"]["finished"]
            assert len(search.calls) == len(outline.calls) == 1
            assert job["progress"]["gap_queries_skipped"] == 4
        finally:
            await jobs.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429, 432])
async def test_gap_search_keeps_source_stop_and_independent_bilibili_lane(tmp_path, status):
    calls = []
    def respond(req):
        calls.append(req)
        if req.url.host == "api.tavily.com":
            return httpx.Response(status, headers={"retry-after": "600"})
        return routed_response(req)
    config = routed_config(tmp_path, bilibili_search_rounds=3, mooc_search_rounds=5,
        max_search_requests=80, mooc_gap_search_enabled=True, mooc_target_courses_per_point=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with closing(Store(config.database_path)) as store:
            jobs = JobService(config, store, provider=SearXNGProvider(config, client),
                provider_overrides={"tavily": TavilyProvider(config, client)}, fetcher=NoFetch())
            jid = jobs.create(SearchRequest(knowledge_points=[POINT],
                                           preferred_platforms=["bilibili", "icourse163"]))["job_id"]
            await jobs.run(jid)
            assert len([row for row in calls if row.url.host == "api.tavily.com"]) == 1
            assert len([row for row in calls if row.url.host == "search.test"]) == 3
            job = store.get_job(jid)
            assert job["progress"]["gap_queries_skipped"] == 0
            assert job["progress"]["platform_search_requests"] == {"bilibili": 3, "icourse163": 1}
            gap = job["gap_search"]["points"][job["knowledge_points"][0]["knowledge_point_id"]]
            assert gap["stopped_reason"] == {403: "access_denied", 429: "rate_limited", 432: "quota_exhausted"}[status]


@pytest.mark.asyncio
async def test_real_shared_library_reuses_one_course_for_two_current_points_without_search(tmp_path):
    config = settings(tmp_path, max_detail_pages=4, shared_course_library_enabled=True)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        first = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(first)
        assert store.get_job(first)["progress"]["library_courses_saved"] == 1
        calls = list(search.calls)
        second = jobs.create(SearchRequest(knowledge_points=[POINT, "Python 列表"],
                                           preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(second)
        job = store.get_job(second)
        assert job["status"] == "completed" and not job["errors"]
        assert job["progress"]["library_hit_pairs"] == 2
        assert job["progress"]["library_courses_reused"] == 1
        assert job["progress"]["search_requests"] == job["progress"]["details_attempted"] == 0
        assert job["progress"]["gap_queries_skipped"] == 10
        assert search.calls == calls and len(outline.calls) == 1
        groups = jobs.results(second)["groups"]
        assert len(groups) == 2 and all(group["mooc_relevance"]["recommended_count"] == 1 for group in groups)
        snapshot = job_snapshot(jobs, store, second)
        assert snapshot["pipeline"]["displayed"] == 1
        assert snapshot["pipeline"]["stage"] == "complete" and snapshot["pipeline"]["terminal"]
        assert snapshot["pipeline"]["search_requests"] == 0
        for group in groups:
            receipt = group["discovery_items"][0]["discovery_evidence"][0]
            assert receipt["kind"] == "course_library"
            assert receipt["knowledge_point_id"] == group["knowledge_point_id"]


@pytest.mark.asyncio
async def test_library_result_remains_visible_when_bilibili_source_fails(tmp_path):
    config = settings(tmp_path, max_detail_pages=4, shared_course_library_enabled=True)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        first = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(first)
        class FailingBilibili:
            async def search(self, query, *args):
                assert platform(query) == "bilibili"
                raise SearchError("search_unavailable", "offline fixture failure")
        jobs.provider = FailingBilibili()
        jobs._providers[config.search_provider] = jobs.provider
        second = jobs.create(SearchRequest(knowledge_points=[POINT],
                                           preferred_platforms=["bilibili", "icourse163"]))["job_id"]
        await jobs.run(second)
        job = store.get_job(second)
        assert job["status"] == "partial"
        assert job["progress"]["search_failures"] == 3
        assert job["progress"]["gap_queries_skipped"] == 5
        assert job["progress"]["library_courses_reused"] == 1
        assert jobs.results(second)["groups"][0]["mooc_relevance"]["recommended_count"] == 1


@pytest.mark.asyncio
async def test_gap_filling_can_rediscover_a_library_course_without_losing_it_or_double_counting(tmp_path):
    config = settings(tmp_path, max_detail_pages=4, shared_course_library_enabled=True)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        first = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(first)
        jobs.settings = replace(config, mooc_target_courses_per_point=2)
        second = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(second)
        job = store.get_job(second)
        assert job["status"] == "completed" and not job["errors"]
        assert job["progress"]["queries_completed"] == 5
        assert job["progress"]["library_courses_reused"] == 1
        point = job["knowledge_points"][0]
        assert job["gap_search"]["points"][point["knowledge_point_id"]]["accepted_count"] == 1
        assert jobs.results(second)["groups"][0]["mooc_relevance"]["recommended_count"] == 1


@pytest.mark.asyncio
async def test_unrelated_point_search_thumbnail_cannot_invalidate_existing_library_receipt(tmp_path):
    config = settings(tmp_path, max_detail_pages=4, shared_course_library_enabled=True)
    search, outline = Search(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        first = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(first)
        class ThumbnailSearch(Search):
            async def search(self, query, *args):
                rows = await super().search(query, *args)
                return [row.model_copy(update={"thumbnail_url": "https://example.com/course.jpg",
                                               "thumbnail_source": "search_result"}) for row in rows]
        changed = ThumbnailSearch()
        jobs.provider = changed
        jobs._providers[config.search_provider] = changed
        second = jobs.create(SearchRequest(knowledge_points=[POINT, "SQL 多表连接"],
                                           preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(second)
        job = store.get_job(second)
        assert job["status"] == "completed" and not job["errors"]
        assert all("SQL" in query for query in changed.calls)
        assert job["progress"]["gap_queries_skipped"] == 5
        assert jobs.results(second)["groups"][0]["mooc_relevance"]["recommended_count"] == 1


@pytest.mark.asyncio
async def test_root_and_www_urls_do_not_count_as_two_independent_courses(tmp_path):
    config = replace(settings(tmp_path, max_detail_pages=4), mooc_target_courses_per_point=2)
    class AliasSearch(Search):
        async def search(self, query, *args):
            row = (await super().search(query, *args))[0]
            return [row, row.model_copy(update={"url": URL.replace("www.", "")})]
    search, outline = AliasSearch(), Outline()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=outline)
        jid = jobs.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"]))["job_id"]
        await jobs.run(jid)
        job = store.get_job(jid)
        point = job["knowledge_points"][0]
        assert job["gap_search"]["points"][point["knowledge_point_id"]]["accepted_count"] == 1
        assert len(search.calls) == 5 and job["progress"]["gap_queries_skipped"] == 0
        assert jobs.results(jid)["groups"][0]["mooc_relevance"]["recommended_count"] == 1


@pytest.mark.asyncio
async def test_disabled_gap_policy_never_calls_coverage_or_wait_hooks(tmp_path, monkeypatch):
    config = options(tmp_path, bilibili_search_rounds=3, mooc_search_rounds=5, max_search_requests=80)
    assert config.mooc_gap_search_enabled is False
    search = Search()
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=search, fetcher=NoFetch())
        def unexpected(*args):
            raise AssertionError("disabled gap policy must not call its hooks")
        monkeypatch.setattr(jobs, "_mooc_coverage_count", unexpected)
        monkeypatch.setattr(jobs, "_wait_mooc_checks", unexpected)
        jid = jobs.create(SearchRequest(knowledge_points=[POINT],
                                       preferred_platforms=["bilibili", "icourse163"]))["job_id"]
        await jobs.run(jid)
        job = store.get_job(jid)
        assert Counter(map(platform, search.calls)) == {"bilibili": 3, "icourse163": 5}
        assert job["progress"]["queries_completed"] == 8
        assert not job.get("gap_search") and not job["progress"].get("gap_queries_skipped")


@pytest.mark.asyncio
async def test_fetch_disabled_does_not_wait_for_a_probe_that_cannot_run():
    from test_mooc_relevance_service import setup, discover
    jobs, job, state, _ = setup(detail_budget=4)
    try:
        jobs.settings = replace(jobs.settings, fetch_enabled=False, mooc_gap_search_enabled=True)
        discover(jobs, job, state, URL)
        await asyncio.wait_for(jobs._wait_mooc_checks(job, state["points"][0], state), .2)
    finally:
        jobs.store.close()


@pytest.mark.parametrize("initial,changed", [
    ({}, {"mooc_gap_search_enabled": True}),
    ({}, {"shared_course_library_enabled": True}),
    ({"mooc_gap_search_enabled": True}, {"mooc_target_courses_per_point": 2}),
    ({"shared_course_library_enabled": True}, {"mooc_target_courses_per_point": 2}),
    ({"mooc_gap_search_enabled": True}, {"mooc_gap_search_enabled": False}),
])
def test_changed_discovery_policy_cannot_reuse_active_job_or_old_idempotency_key(tmp_path, initial, changed):
    config = options(tmp_path, mooc_target_courses_per_point=1, **initial)
    request = SearchRequest(knowledge_points=[POINT], preferred_platforms=["icourse163"])
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=object(), fetcher=NoFetch())
        first = jobs.create(request, idempotency_key="gap-policy")
        assert jobs.create(request, idempotency_key="gap-policy")["job_id"] == first["job_id"]
        assert jobs.create(request)["job_id"] == first["job_id"]
        jobs.settings = replace(config, **changed)
        with pytest.raises(IdempotencyConflict):
            jobs.create(request, idempotency_key="gap-policy")
        second = jobs.create(request)
        assert second["job_id"] != first["job_id"]
        assert store.get_job(second["job_id"]).get("discovery_policy") != store.get_job(first["job_id"]).get("discovery_policy")


def test_mooc_policy_changes_do_not_change_a_bilibili_only_job_identity(tmp_path):
    config = options(tmp_path)
    request = SearchRequest(knowledge_points=[POINT], preferred_platforms=["bilibili"])
    with closing(Store(config.database_path)) as store:
        jobs = JobService(config, store, provider=object(), fetcher=NoFetch())
        first = jobs.create(request, idempotency_key="bilibili-only-policy")
        jobs.settings = replace(config, mooc_gap_search_enabled=True, shared_course_library_enabled=True,
                                mooc_target_courses_per_point=5)
        assert jobs.create(request, idempotency_key="bilibili-only-policy")["job_id"] == first["job_id"]
        assert jobs.create(request)["job_id"] == first["job_id"]
