"""Offline end-to-end tests for untrusted AI links and actual page admission.

The provider, model and HTTP boundary are synthetic. Metadata extraction,
SQLite persistence, resource ranking and result/SSE projections are real.
"""
from copy import deepcopy
from dataclasses import replace
import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, SearchRequest, now
from backend.app.providers import SearchError
from backend.app.result_stream import job_snapshot, result_events
from backend.app.service import JobService


POINT = "Python 列表"
URL = "https://www.bilibili.com/video/BV1xx411c7Df"


def video_html(topic):
    node = {"@context": "https://schema.org", "@type": "VideoObject",
            "name": topic + "入门视频教程", "description": topic + "的定义、创建与使用，入门视频教学",
            "thumbnailUrl": "https://images.example.org/course.jpg",
            "contentUrl": "https://media.example.org/lesson.mp4"}
    return ('<html><head><title>' + node["name"] + '</title><script type="application/ld+json">'
            + json.dumps(node, ensure_ascii=False) + '</script></head><body><h1>'
            + node["name"] + '</h1></body></html>')


class OfflineSearch:
    name = "offline-ai-fallback-test"

    def __init__(self, candidates=()):
        self.candidates = list(candidates)
        self.calls = []

    async def search(self, query, language, limit, domains):
        self.calls.append(query)
        return [row.model_copy(update={"query": query}) for row in self.candidates]


class OfflineModel:
    def __init__(self, suggestions=None, error=None):
        self.suggestions = suggestions if suggestions is not None else {POINT: [URL]}
        self.error = error
        self.calls = []

    async def expand(self, *_):
        return []

    async def rerank(self, *_):
        raise AssertionError("Teaching reranking is disabled for these isolated tests")

    async def suggest_video_urls(self, points, request, *, excluded_urls=()):
        self.calls.append({"points": list(points), "request": request, "excluded_urls": list(excluded_urls)})
        if self.error:
            raise self.error
        return deepcopy(self.suggestions)


class OfflinePages:
    def __init__(self, pages=None, failure=None):
        self.pages = pages if pages is not None else {URL: POINT}
        self.failure = failure
        self.calls = []

    async def enrich(self, candidate):
        self.calls.append(deepcopy(candidate))
        if self.failure == "exception":
            raise RuntimeError("PRIVATE_FETCH_ERROR")
        if self.failure:
            return {"fetch_status": self.failure, "evidence": []}
        return MetadataExtractor().extract(video_html(self.pages[candidate["url"]]), candidate["url"], now())


@pytest.fixture
def make_service(tmp_path):
    stores = []

    def make(*, model=None, fetcher=None, provider=None, **overrides):
        settings = replace(Settings(database_path=str(tmp_path / f"ai-video-{len(stores)}.sqlite3"),
            shared_course_library_enabled=False, mooc_gap_search_enabled=False, mooc_refresh_enabled=False,
            public_catalog_fallback=False, official_sitemap_fallback=False, teaching_match_enabled=False,
            search_min_interval_seconds=0, max_search_requests=30, max_detail_pages=15,
            bilibili_public_metadata=True, ai_video_fallback_enabled=True), **overrides)
        store = Store(settings.database_path)
        stores.append(store)
        return JobService(settings, store, provider=provider or OfflineSearch(),
                          fetcher=fetcher or OfflinePages(), llm=model or OfflineModel())

    yield make
    for store in stores:
        store.close()


async def run(service, points=None):
    identifier = service.create(SearchRequest(knowledge_points=points or [POINT], preferred_platforms=["bilibili"]))["job_id"]
    await service.run(identifier)
    return identifier, service.results(identifier)


def visible(group):
    return [*group.get("items", []), *group.get("partial_items", []),
            *group.get("related_recommendations", [])]


@pytest.mark.asyncio
async def test_empty_search_fetches_ai_url_and_publishes_only_actual_page_facts(make_service):
    service = make_service()
    identifier, result = await run(service)
    assert service.llm.calls[0]["points"] == [POINT]
    assert len(service.llm.calls) == len(service.fetcher.calls) == 1
    submitted = service.fetcher.calls[0]
    assert submitted["url"] == URL
    assert not submitted["title"] and not submitted["snippet"]
    assert submitted["resource_type_hint"] == "unknown"
    rows = visible(result["groups"][0])
    assert len(rows) == 1
    resource = rows[0]["resource"]
    assert resource["url"] == URL and resource["title"] == POINT + "入门视频教程"
    assert resource["video_evidence_status"] == "page_verified"
    assert resource["thumbnail_url"] == "https://images.example.org/course.jpg"
    assert resource.get("playback_verified", False) is False
    assert service.store.resources(identifier)[resource["resource_id"]]["playback_verified"] is False
    evidence = service.store.evidence(identifier, resource["resource_id"])
    assert any(row["kind"] == "ai_suggestion" for row in evidence)
    assert not any(row["kind"] == "search" for row in evidence)
    title_id = service.store.resources(identifier)[resource["resource_id"]]["field_provenance"]["title"]["evidence_id"]
    assert next(row for row in evidence if row["evidence_id"] == title_id)["kind"] == "page"
    assert service.store.get_job(identifier)["progress"]["details_attempted"] == 1


@pytest.mark.asyncio
async def test_already_visible_point_never_asks_model_for_more_links(make_service):
    source = Candidate(id="found", title=POINT + "视频教程", url=URL, source="offline", query="",
                       resource_type_hint="video", type_source="search_template")
    service = make_service(provider=OfflineSearch([source]))
    _, result = await run(service)
    assert visible(result["groups"][0])
    assert service.llm.calls == []


@pytest.mark.asyncio
async def test_batch_contains_only_uncovered_points(make_service):
    source = Candidate(id="found", title=POINT + "视频教程", url=URL, source="offline", query="",
                       resource_type_hint="video", type_source="search_template")
    other, other_url = "SQL 多表连接", "https://www.bilibili.com/video/BV1xx411c7Dg"
    service = make_service(provider=OfflineSearch([source]), model=OfflineModel({other: [other_url]}),
                           fetcher=OfflinePages({URL: POINT, other_url: other}))
    _, result = await run(service, [POINT, other])
    assert service.llm.calls[0]["points"] == [other]
    assert URL in service.llm.calls[0]["excluded_urls"]
    assert all(visible(group) for group in result["groups"])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_url", [
    "javascript:alert(1)", "http://127.0.0.1/video", "https://user:pass@www.bilibili.com/video/BV1xx411c7Df",
    "https://search.bilibili.com/all?keyword=Python", "https://www.bilibili.com/", "https://youtu.be/abcdefg",
])
async def test_invalid_or_non_detail_suggestions_are_never_fetched_or_displayed(make_service, bad_url):
    service = make_service(model=OfflineModel({POINT: [bad_url]}))
    identifier, result = await run(service)
    assert len(service.llm.calls) == 1 and not service.fetcher.calls
    assert not visible(result["groups"][0])
    assert not service.store.resources(identifier)


@pytest.mark.asyncio
async def test_unrelated_fetched_video_is_not_promoted_by_requested_topic(make_service):
    service = make_service(fetcher=OfflinePages({URL: "吉他和弦与指法"}))
    identifier, result = await run(service)
    assert len(service.fetcher.calls) == 1
    assert not visible(result["groups"][0])
    assert not result["groups"][0].get("discovery_items")
    resource = next(iter(service.store.resources(identifier).values()))
    assert resource["title"] == "吉他和弦与指法入门视频教程"
    assert resource["video_evidence_status"] == "page_verified"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["not_found", "access_denied", "site_policy_blocked", "exception"])
async def test_unconfirmed_or_failed_fetch_cannot_become_an_ai_recommendation(make_service, failure):
    service = make_service(fetcher=OfflinePages(failure=failure))
    identifier, result = await run(service)
    assert len(service.fetcher.calls) == 1
    assert not visible(result["groups"][0])
    assert not result["groups"][0].get("discovery_items")
    assert "PRIVATE_FETCH_ERROR" not in json.dumps(service.store.get_job(identifier))


@pytest.mark.asyncio
async def test_each_missing_point_gets_a_detail_slot_before_extra_urls(make_service):
    points = [POINT, "Java 数组", "CSS 选择器", "SQL 多表连接", "HTML 表单"]
    suggestions = {point: [f"https://www.bilibili.com/video/BV1xx411c{index}{suffix}f"
                          for suffix in range(3)] for index, point in enumerate(points)}
    pages = {url: point for point, urls in suggestions.items() for url in urls}
    service = make_service(model=OfflineModel(suggestions), fetcher=OfflinePages(pages), max_detail_pages=5)
    identifier, result = await run(service, points)
    assert len(service.llm.calls) == 1 and service.llm.calls[0]["points"] == points
    assert [row["url"] for row in service.fetcher.calls] == [suggestions[point][0] for point in points]
    assert service.store.get_job(identifier)["progress"]["details_attempted"] == 5
    assert all(visible(group) for group in result["groups"])


@pytest.mark.asyncio
async def test_model_cannot_expand_three_url_limit_or_add_an_unrequested_point(make_service):
    urls = [f"https://www.bilibili.com/video/BV1xx411c7D{suffix}" for suffix in "fghij"]
    suggestions = {POINT: urls, "unrequested topic": ["https://www.bilibili.com/video/BV1xx411c7Dk"]}
    service = make_service(model=OfflineModel(suggestions),
                           fetcher=OfflinePages({url: "吉他和弦与指法" for url in urls}))
    identifier, result = await run(service)
    assert [row["url"] for row in service.fetcher.calls] == urls[:3]
    assert len(service.store.resources(identifier)) == 3
    assert not visible(result["groups"][0])


@pytest.mark.asyncio
async def test_shared_ai_url_fetches_once_and_can_support_both_requested_points(make_service):
    other = "Python 字典"
    service = make_service(model=OfflineModel({POINT: [URL], other: [URL]}),
                           fetcher=OfflinePages({URL: "Python 列表与字典"}))
    identifier, result = await run(service, [POINT, other])
    assert len(service.fetcher.calls) == 1
    assert len(service.store.resources(identifier)) == 1
    assert all(visible(group) for group in result["groups"])


@pytest.mark.asyncio
async def test_ordinary_detail_work_leaves_room_for_ai_within_original_cap(make_service):
    source_urls = ["https://www.bilibili.com/video/BV1xx411c7Dg", "https://www.bilibili.com/video/BV1xx411c7Dh"]
    candidates = [Candidate(id=str(index), title=POINT + "视频教程", url=url, source="offline", query="",
                            resource_type_hint="video", type_source="search_template")
                  for index, url in enumerate(source_urls)]
    pages = {url: "吉他和弦与指法" for url in source_urls}
    pages[URL] = POINT
    service = make_service(provider=OfflineSearch(candidates), fetcher=OfflinePages(pages), max_detail_pages=3)
    identifier, result = await run(service)
    assert len(service.llm.calls) == 1
    assert len(service.fetcher.calls) == 3
    assert [row["url"] for row in service.fetcher.calls][-1] == URL
    assert service.store.get_job(identifier)["progress"]["details_attempted"] == 3
    assert {row["resource"]["url"] for row in visible(result["groups"][0])} == {URL}


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_slow_source_cannot_consume_time_reserved_for_ai_fallback(make_service, parallel):
    stopped = asyncio.Event()

    class SlowSearch(OfflineSearch):
        async def search(self, query, language, limit, domains):
            self.calls.append(query)
            if parallel and len(self.calls) == 1:
                return []  # The next platform round must not remain pending after timing out.
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    service = make_service(provider=SlowSearch(), deadline_seconds=1,
                           parallel_platform_search=parallel, open_web_search_enabled=False)
    identifier, result = await asyncio.wait_for(run(service), timeout=2)
    assert stopped.is_set()
    assert len(service.llm.calls) == len(service.fetcher.calls) == 1
    assert visible(result["groups"][0])
    assert service.store.get_job(identifier)["status"] == "partial"
    if parallel:
        plan = service.store.get_job(identifier)["platform_search"]
        assert plan["initial_done"] and not plan["followup_pending"]
        assert plan["stopped_reason"] == "source_deadline"


@pytest.mark.asyncio
async def test_timeout_after_one_ai_match_preserves_partial_status_when_all_searches_failed(make_service):
    other, other_url = "SQL 多表连接", "https://www.bilibili.com/video/BV1xx411c7Dg"
    stopped = asyncio.Event()

    class BrokenSearch(OfflineSearch):
        async def search(self, query, language, limit, domains):
            self.calls.append(query)
            raise SearchError("search_timeout", "Offline provider failure")

    class SlowSecondPage(OfflinePages):
        async def enrich(self, candidate):
            if candidate["url"] == other_url:
                self.calls.append(deepcopy(candidate))
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            return await super().enrich(candidate)

    service = make_service(provider=BrokenSearch(), fetcher=SlowSecondPage(), deadline_seconds=1,
                           model=OfflineModel({POINT: [URL], other: [other_url]}))
    identifier, result = await asyncio.wait_for(run(service, [POINT, other]), timeout=2)
    job = service.store.get_job(identifier)
    assert stopped.is_set() and job["progress"]["search_successes"] == 0
    assert job["status"] == "partial" and result["status"] == "partial"
    assert job["ai_video_fallback"]["covered_points"] == 1
    assert visible(result["groups"][0]) and not visible(result["groups"][1])


@pytest.mark.asyncio
async def test_model_fallback_remains_inside_original_job_deadline(make_service):
    stopped = asyncio.Event()

    class SlowModel(OfflineModel):
        async def suggest_video_urls(self, points, request, *, excluded_urls=()):
            self.calls.append(list(points))
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    service = make_service(model=SlowModel(), deadline_seconds=1)
    identifier, result = await asyncio.wait_for(run(service), timeout=2)
    assert len(service.llm.calls) == 1 and stopped.is_set()
    assert not service.fetcher.calls and not visible(result["groups"][0])
    assert service.store.get_job(identifier)["status"] in {"partial", "failed"}


@pytest.mark.parametrize("kind,points,expected_extra_calls", [("direct_search", 2, 1), ("search", 12, 3)])
def test_mobile_reserves_one_extra_model_call_per_batch_without_raising_fetch_caps(kind, points, expected_extra_calls):
    from backend.app.mobile_tasks import MobileTaskPayload, MobileTasks
    from backend.app.project_service import ProjectService

    enabled = Settings(ai_video_fallback_enabled=True, fetch_enabled=True)
    disabled = replace(enabled, ai_video_fallback_enabled=False)
    selected = [{"id": f"p{index}"} for index in range(points)]
    if kind == "direct_search":
        payload = MobileTaskPayload.model_validate({"kind": kind, "request": {
            "knowledge_points": [f"Python topic {index}" for index in range(points)],
            "preferred_platforms": ["bilibili"]}})
    else:
        payload = SimpleNamespace(kind=kind, input=SimpleNamespace(preferred_platforms=["bilibili"]))

    def costs(settings):
        projects = ProjectService.__new__(ProjectService)
        projects.settings = settings
        return MobileTasks._costs(SimpleNamespace(settings=settings, projects=projects), payload, selected)

    before, after = costs(disabled), costs(enabled)
    assert after["model_calls"] == before["model_calls"] + expected_extra_calls
    assert after["detail_pages"] == before["detail_pages"]
    assert after["detail_http"] == before["detail_http"]
    assert after["search_requests"] == before["search_requests"]


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"max_detail_pages": 0}, {"ai_video_fallback_enabled": False}, {"fetch_enabled": False}])
async def test_no_model_or_fetch_calls_when_supplement_cannot_run(make_service, overrides):
    service = make_service(**overrides)
    _, result = await run(service)
    assert not service.llm.calls and not service.fetcher.calls
    assert not visible(result["groups"][0])


@pytest.mark.asyncio
async def test_model_failure_is_contained_and_does_not_leak_provider_text(make_service):
    service = make_service(model=OfflineModel(error=RuntimeError("PRIVATE_MODEL_ERROR")))
    identifier, result = await run(service)
    assert len(service.llm.calls) == 1 and not service.fetcher.calls
    assert not visible(result["groups"][0])
    assert service.store.get_job(identifier)["status"] in {"completed", "partial"}
    assert "PRIVATE_MODEL_ERROR" not in json.dumps(result)
    assert "PRIVATE_MODEL_ERROR" not in json.dumps(service.store.get_job(identifier))


@pytest.mark.asyncio
async def test_cancel_during_model_call_stops_before_any_fetch(make_service):
    started = asyncio.Event()

    class WaitingModel(OfflineModel):
        async def suggest_video_urls(self, points, request, *, excluded_urls=()):
            started.set()
            await asyncio.Event().wait()

    service = make_service(model=WaitingModel())
    identifier = service.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["bilibili"]))["job_id"]
    task = asyncio.create_task(service.run(identifier))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        outcome = await service.cancel(identifier)
        assert outcome["cancelled"]
        assert not service.fetcher.calls
        assert not visible(service.results(identifier)["groups"][0])
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_results_and_reconnected_sse_are_read_only(make_service):
    class Connected:
        async def is_disconnected(self):
            return False

    service = make_service()
    identifier, _ = await run(service)
    before = list(service.store.connection.iterdump())
    calls_before = len(service.llm.calls), len(service.provider.calls), len(service.fetcher.calls)
    for _ in range(3):
        snapshot = job_snapshot(service, service.store, identifier)
        messages = [message async for message in result_events(Connected(),
            lambda: job_snapshot(service, service.store, identifier),
            lambda: service.store.connection.total_changes, snapshot)]
        assert len(messages) == 2 and "event: complete" in messages[-1]
        assert visible(snapshot["groups"][0])
    assert calls_before == (len(service.llm.calls), len(service.provider.calls), len(service.fetcher.calls))
    assert list(service.store.connection.iterdump()) == before
