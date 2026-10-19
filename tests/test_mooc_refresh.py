"""Offline refresh contract: real provider/extractor paths, synthetic HTTP only.

The clock replaces only mooc_refresh.time; it cannot age course evidence,
expire unrelated caches, or change asyncio scheduling.
"""
import asyncio
from contextlib import closing
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from backend.app import mooc_refresh as refresh_module
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import SearchRequest, now
from backend.app.mooc_refresh import MoocRefresh
from backend.app.platform_search import platform_query
from backend.app.providers import SearXNGProvider, TavilyProvider
from backend.app.result_stream import job_snapshot, result_events
from backend.app.service import JobService
from test_gap_library_search import POINT, URL
from test_mooc_relevance_service import synthetic_outline
from test_platform_provider_selection import config as routed_config
from test_result_stream import Connection


NEW_URL = "https://www.icourse163.org/course/OWN-789"
SUCCESS = {"status": "completed", "network_attempted": True,
           "cache_hit": False, "upstream_warnings": []}


@pytest.fixture
def clock(monkeypatch):
    value = [time.time()]
    monkeypatch.setattr(refresh_module, "time", SimpleNamespace(time=lambda: value[0]))
    return value


def settings(tmp_path, **changes):
    return routed_config(tmp_path, **{
        "bilibili_search_rounds": 3, "mooc_search_rounds": 5,
        "max_search_requests": 80, "max_detail_pages": 8,
        "shared_course_library_enabled": True, "mooc_gap_search_enabled": True,
        "mooc_target_courses_per_point": 1, "mooc_refresh_enabled": True,
        "mooc_refresh_interval_seconds": 86400, **changes,
    })


def request(*, both=False):
    return SearchRequest(knowledge_points=[POINT],
                         preferred_platforms=["bilibili", "icourse163"] if both else ["icourse163"])


class SearchHTTP:
    def __init__(self):
        self.calls = []
        self.course_url = URL
        self.status = 200

    def __call__(self, req):
        self.calls.append(req)
        if req.url.host == "api.tavily.com":
            body = json.loads(req.content)
            assert body["include_domains"] == ["icourse163.org"]
            assert body["search_depth"] == "basic"
            if self.status != 200:
                return httpx.Response(self.status, headers={"retry-after": "600"})
            return httpx.Response(200, json={"results": [{
                "title": POINT + " 课程", "url": self.course_url,
                "content": POINT + " 课程教学",}]})
        assert req.url.host == "search.test", "No unmocked HTTP destination is permitted"
        assert "bilibili.com" in req.url.params["q"]
        return httpx.Response(200, json={"results": [{
            "title": POINT + " 视频教程",
            "url": "https://www.bilibili.com/video/BV1VZ4y1G7YB/",
            "content": POINT + " 视频教程", "template": "videos.html",
        }], "unresponsive_engines": []})

    @property
    def mooc_calls(self):
        return [row for row in self.calls if row.url.host == "api.tavily.com"]

    @property
    def bilibili_calls(self):
        return [row for row in self.calls if row.url.host == "search.test"]


class CoursePages:
    def __init__(self):
        self.calls = []
        self.new_chapters = ("列表", "字典")
        self.block_new = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def enrich(self, candidate):
        url = candidate["url"]
        self.calls.append(url)
        if "icourse163.org" not in url:
            return {"fetch_status": "not_found"}
        is_new = url == NEW_URL
        if is_new and self.block_new:
            self.started.set()
            await self.release.wait()
        await asyncio.sleep(.005)
        return MetadataExtractor().extract(synthetic_outline(
            course_id="789" if is_new else "123",
            chapters=self.new_chapters if is_new else ("列表", "字典")), url, now())


def service(config, store, client, pages):
    return JobService(config, store, provider=SearXNGProvider(config, client), fetcher=pages,
                      provider_overrides={"tavily": TavilyProvider(config, client)})


async def run(jobs, req=None):
    jid = jobs.create(req or request())["job_id"]
    await jobs.run(jid)
    return jid


def refresh_rows(store):
    return [dict(row) for row in store.connection.execute("SELECT * FROM mooc_refresh_state")]


def mooc_attempts(store, jid):
    return [row for row in store.attempts(jid) if row["platform"] == "icourse163"]


def recommended(jobs, jid):
    return jobs.results(jid)["groups"][0]["mooc_relevance"]["recommended_count"]


def test_first_claim_lease_boundary_and_successful_refresh_cadence(tmp_path, clock):
    with closing(Store(str(tmp_path / "unit.sqlite3"))) as store:
        refresh = MoocRefresh(store)
        first = refresh.claim("opaque-key")
        assert first == {"query_index": 1, "sequence": 0}
        assert refresh.claim("opaque-key") is None
        clock[0] += 299
        assert refresh.claim("opaque-key") is None
        clock[0] += 1
        assert refresh.claim("opaque-key") == first
        assert refresh.observed("opaque-key", SUCCESS)
        assert refresh.claim("opaque-key") is None
        clock[0] += 86399
        assert refresh.claim("opaque-key") is None
        clock[0] += 1
        assert refresh.claim("opaque-key") == {"query_index": 2, "sequence": 1}


@pytest.mark.parametrize("change", [
    {"status": "failed", "error_code": "rate_limited"},
    {"status": "failed", "error_code": "search_unavailable"},
    {"status": "partial"}, {"status": "cancelled"},
    {"network_attempted": False}, {"cache_hit": True},
    {"upstream_warnings": [{"code": "upstream_engine_failed"}]},
])
def test_cache_failure_and_partial_observations_do_not_renew_success(tmp_path, clock, change):
    with closing(Store(str(tmp_path / "unit.sqlite3"))) as store:
        refresh = MoocRefresh(store)
        assert refresh.observed("opaque", SUCCESS)
        previous = refresh_rows(store)[0]
        clock[0] += 86400
        refresh.claim("opaque")
        assert not refresh.observed("opaque", {**SUCCESS, **change})
        current = refresh_rows(store)[0]
        assert current["last_success"] == previous["last_success"]
        assert current["sequence"] == previous["sequence"]
        assert current["last_attempt"] == clock[0]
        assert refresh.claim("opaque") is None


def test_success_rotates_bounded_query_indices_and_failure_does_not_advance(tmp_path, clock):
    with closing(Store(str(tmp_path / "unit.sqlite3"))) as store:
        refresh = MoocRefresh(store)
        indices = []
        for _ in range(7):
            claim = refresh.claim("opaque")
            indices.append(claim["query_index"])
            assert refresh.observed("opaque", SUCCESS)
            clock[0] += 86400
        assert indices == [1, 2, 3, 4, 5, 1, 2]
        failed_claim = refresh.claim("opaque")
        assert not refresh.observed("opaque", {**SUCCESS, "status": "failed"})
        clock[0] += 300
        assert refresh.claim("opaque") == failed_claim


def test_refresh_state_is_persistent_and_contains_only_opaque_topic_identity(tmp_path, clock):
    path = str(tmp_path / "persistent.sqlite3")
    point = {"text": "Python 私有内部处理123", "learning_targets": ["secret-z", "secret-a"]}
    req = SearchRequest(knowledge_points=[point["text"]], project_context="private-project-917")
    key = MoocRefresh.topic_key(point, req, "private-profile")
    with closing(Store(path)) as store:
        refresh = MoocRefresh(store)
        refresh.claim(key)
        refresh.observed(key, SUCCESS)
    clock[0] += 3600
    with closing(Store(path)) as store:
        restarted = MoocRefresh(store)
        assert restarted.claim(key) is None
        rows = refresh_rows(store)
        assert rows[0]["topic_key"] == key and len(key) == 64
        assert set(rows[0]) == {"topic_key", "last_success", "last_attempt", "sequence"}
        persisted = json.dumps(rows, ensure_ascii=False)
        for secret in (point["text"], "secret-z", "secret-a", "private-project-917", "private-profile"):
            assert secret not in persisted
        clock[0] += 86400
        assert restarted.claim(key) == {"query_index": 2, "sequence": 1}


def test_topic_identity_normalizes_text_targets_and_separates_matching_profiles():
    point = {"text": "Python   列表与字典", "learning_targets": ["字典", "列表"]}
    req = request()
    key = MoocRefresh.topic_key(point, req, "profile-a")
    assert key == MoocRefresh.topic_key(
        {"text": " python 列表与字典 ", "learning_targets": ["列表", "字典"]},
        req.model_copy(update={"project_context": "Another private project"}), "profile-a")
    assert key != MoocRefresh.topic_key(point, req, "profile-b")
    assert key != MoocRefresh.topic_key(point, req.model_copy(update={"language": "en"}), "profile-a")
    assert key != MoocRefresh.topic_key(point, req.model_copy(update={"technical_version": "3.14"}), "profile-a")
    assert key != MoocRefresh.topic_key({**point, "learning_targets": ["列表"]}, req, "profile-a")


@pytest.mark.asyncio
async def test_warm_jobs_and_restart_within_24_hours_issue_zero_mooc_http(tmp_path, clock):
    config, transport, pages = settings(tmp_path), SearchHTTP(), CoursePages()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with closing(Store(config.database_path)) as store:
            jobs = service(config, store, client, pages)
            cold = await run(jobs)
            assert recommended(jobs, cold) == 1 and len(transport.mooc_calls) == 1
            first = refresh_rows(store)[0]
            clock[0] += 3600
            transport.calls.clear()
            warm = await run(jobs, request(both=True))
            assert not transport.mooc_calls and len(transport.bilibili_calls) == 3
            assert recommended(jobs, warm) == 1
            assert store.get_job(warm)["progress"]["gap_queries_skipped"] == 5
            assert all(row["status"] == "skipped" for row in mooc_attempts(store, warm))
            assert refresh_rows(store)[0] == first
        with closing(Store(config.database_path)) as store:
            restarted = service(config, store, client, pages)
            transport.calls.clear()
            warm = await run(restarted)
            assert not transport.calls and recommended(restarted, warm) == 1
            assert len(pages.calls) == 2  # One MOOC page and the independent Bilibili candidate.
            assert refresh_rows(store)[0] == first


@pytest.mark.asyncio
async def test_due_satisfied_point_runs_one_initial_refresh_bypassing_cached_query(tmp_path, clock):
    config, transport, pages = settings(tmp_path), SearchHTTP(), CoursePages()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with closing(Store(config.database_path)) as store:
            jobs = service(config, store, client, pages)
            await run(jobs)
            previous = refresh_rows(store)[0]
            clock[0] += 86401
            transport.calls.clear()
            req = request(both=True)
            jid = jobs.create(req)["job_id"]
            job = store.get_job(jid)
            point = job["knowledge_points"][0]
            query = platform_query(point, "icourse163", req, round_index=2)
            key = store.cache_key("search", {"policy": job["platform_search"]["policy"],
                **jobs._search_identity("tavily"), "original_point": point["text"],
                "query": query.query, "domains": query.domain_filters,
                "language": req.language, "limit": config.search_results_per_query})
            store.cache_set(key, "search", {"candidates": [], "upstream_warnings": []}, 999999)
            assert store.cache_get(key)["cache"]["hit"]
            await jobs.run(jid)
            attempts = mooc_attempts(store, jid)
            live = [row for row in attempts if row["network_attempted"]]
            assert len(transport.mooc_calls) == len(live) == 1
            assert len(transport.bilibili_calls) == 3
            assert live[0]["refresh_probe"] and live[0]["search_phase"] == "initial"
            assert not live[0]["cache_hit"] and live[0]["query"] == query.query
            assert sum(row["status"] == "skipped" for row in attempts) == 4
            progress = store.get_job(jid)["progress"]
            assert progress["mooc_refresh_probes"] == 1
            assert progress["platform_search_requests"] == {"bilibili": 3, "icourse163": 1}
            assert recommended(jobs, jid) == 1
            current = refresh_rows(store)[0]
            assert current["last_success"] == clock[0]
            assert current["sequence"] == previous["sequence"] + 1


@pytest.mark.asyncio
async def test_normal_gap_query_cache_hit_never_pretends_a_new_discovery_succeeded(tmp_path, clock):
    config = settings(tmp_path, shared_course_library_enabled=False)
    transport, pages = SearchHTTP(), CoursePages()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with closing(Store(config.database_path)) as store:
            jobs = service(config, store, client, pages)
            await run(jobs)
            previous = refresh_rows(store)[0]
            clock[0] += 86401
            transport.calls.clear()
            cached = await run(jobs)
            attempts = mooc_attempts(store, cached)
            assert attempts[0]["cache_hit"] and not attempts[0]["network_attempted"]
            assert not transport.calls and recommended(jobs, cached) == 1
            assert refresh_rows(store)[0] == previous


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_failed_refresh_does_not_mark_fresh_retry_covered_slots_or_storm_next_job(tmp_path, clock, status):
    config, transport, pages = settings(tmp_path), SearchHTTP(), CoursePages()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with closing(Store(config.database_path)) as store:
            jobs = service(config, store, client, pages)
            await run(jobs)
            previous = refresh_rows(store)[0]
            clock[0] += 86401
            transport.status = status
            transport.calls.clear()
            failed = await run(jobs, request(both=True))
            attempts = mooc_attempts(store, failed)
            assert len(transport.mooc_calls) == 1 and len(transport.bilibili_calls) == 3
            assert attempts[0]["status"] == "failed" and attempts[0]["refresh_probe"]
            assert all(row["status"] == "skipped" for row in attempts[1:])
            assert recommended(jobs, failed) == 1
            failed_state = refresh_rows(store)[0]
            assert failed_state["last_success"] == previous["last_success"]
            assert failed_state["sequence"] == previous["sequence"]
            assert failed_state["last_attempt"] == clock[0]

            # A fresh provider has no process-local pause state. The persisted
            # lease alone must suppress the next covered job's request.
            restarted = service(config, store, client, pages)
            transport.status = 200
            transport.calls.clear()
            clock[0] += 299
            warm = await run(restarted)
            assert not transport.calls and recommended(restarted, warm) == 1
            assert all(row["status"] == "skipped" for row in mooc_attempts(store, warm))
            assert not store.get_job(warm)["progress"].get("mooc_refresh_probes")
            assert refresh_rows(store)[0] == failed_state
            clock[0] += 1
            recovered = await run(restarted)
            assert len(transport.mooc_calls) == 1 and recommended(restarted, recovered) == 1
            assert refresh_rows(store)[0]["last_success"] == clock[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("chapters,expected", [(("列表", "字典"), 2), (("列表",), 1)])
async def test_refresh_sse_appends_new_course_only_after_complete_outline(tmp_path, clock, chapters, expected):
    config, transport, pages = settings(tmp_path), SearchHTTP(), CoursePages()
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with closing(Store(config.database_path)) as store:
            jobs = service(config, store, client, pages)
            await run(jobs)
            clock[0] += 86401
            transport.course_url = NEW_URL
            transport.calls.clear()
            pages.new_chapters = chapters
            pages.block_new = True
            jid = jobs.create(request())["job_id"]
            task = asyncio.create_task(jobs.run(jid))
            stream = None
            try:
                await asyncio.wait_for(pages.started.wait(), 2)
                snapshot = lambda: job_snapshot(jobs, store, jid)
                initial = snapshot()
                assert initial["pipeline"]["displayed"] == 1
                assert not initial["pipeline"]["terminal"]
                stream = result_events(Connection(), snapshot, lambda: store.connection.total_changes,
                    initial, initial_revision=store.connection.total_changes, interval=.001)
                frames = [await anext(stream)]
                assert '"displayed":1' in frames[0] and "event: snapshot" in frames[0]
                pages.release.set()
                async def consume():
                    async for frame in stream:
                        frames.append(frame)
                await asyncio.wait_for(asyncio.gather(task, consume()), 2)
                values = [json.loads(frame.split("\ndata: ", 1)[1]) for frame in frames
                          if "event: snapshot" in frame]
                assert values[-1]["pipeline"]["terminal"]
                assert values[-1]["pipeline"]["displayed"] == expected
                assert all(value["pipeline"]["displayed"] in {1, expected} for value in values)
                assert frames[-1].startswith("event: complete") or "\nevent: complete" in frames[-1]
                assert len(transport.mooc_calls) == 1 and recommended(jobs, jid) == expected
                group = jobs.results(jid)["groups"][0]
                visible = {row["resource"]["canonical_url"] for row in group["discovery_items"]}
                assert (NEW_URL in visible) is (expected == 2)
                if expected == 1:
                    assert group["mooc_relevance"]["status_counts"]["outline_partial"] == 1
            finally:
                pages.release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if stream is not None:
                    await stream.aclose()
