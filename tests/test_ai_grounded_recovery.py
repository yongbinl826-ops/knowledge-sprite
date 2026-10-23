"""Offline recovery contract with real HTTP-provider parsing and page admission.

Only model outputs, provider HTTP replies and fetched HTML are synthetic.
Search accounting, metadata extraction, SQLite, ranking and projection are real.
"""
from copy import deepcopy
from dataclasses import replace
import asyncio
import inspect
import json
import time

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import Query, SearchRequest, now
from backend.app.providers import SerperProvider
from backend.app.service import JobService


POINT = "Pygame 事件循环"
URL = "https://www.bilibili.com/video/BV1xx411c7Df"
DEAD_URL = "https://www.bilibili.com/video/BV1xx411c7Dg"


def visible(group):
    return [*group.get("items", []), *group.get("partial_items", []),
            *group.get("related_recommendations", [])]


class EmptySearch:
    name = "offline-empty-search"

    def __init__(self):
        self.calls = []

    async def search(self, query, language, limit, domains):
        self.calls.append(query)
        return []


class DiscoveryModel:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    async def expand(self, *_):
        return []

    async def suggest_video_discovery(self, points, request, *, excluded_urls=()):
        self.calls.append(list(points))
        return deepcopy(self.plan)

    async def suggest_video_urls(self, *_args, **_kwargs):
        raise AssertionError("Combined discovery must replace, not duplicate, the old model call")


class SourcePages:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def enrich(self, candidate):
        self.calls.append(deepcopy(candidate))
        topic = self.pages.get(candidate["url"])
        if topic is None:
            return {"fetch_status": "not_found", "evidence": []}
        node = {"@context": "https://schema.org", "@type": "VideoObject",
                "name": topic + "公开教学视频", "description": topic + "的定义、创建与实际使用，入门视频教学",
                "thumbnailUrl": "https://images.example.org/course.jpg",
                "contentUrl": "https://media.example.org/lesson.mp4"}
        html = ('<html><head><title>' + node["name"] + '</title><script type="application/ld+json">'
                + json.dumps(node, ensure_ascii=False) + '</script></head><body><h1>'
                + node["name"] + '</h1></body></html>')
        return MetadataExtractor().extract(html, candidate["url"], now())


def organic(topic=POINT, url=URL):
    return {"title": topic + "搜索来源标题", "link": url,
            "snippet": topic + "视频教程，学习定义和使用方法"}


@pytest.fixture
async def recovery_service(tmp_path):
    stores, clients = [], []

    def make(*, plan=None, pages=None, respond=None, **overrides):
        settings = replace(Settings(database_path=str(tmp_path / f"grounded-{len(stores)}.sqlite3"),
            shared_course_library_enabled=False, mooc_gap_search_enabled=False, mooc_refresh_enabled=False,
            public_catalog_fallback=False, official_sitemap_fallback=False, teaching_match_enabled=False,
            search_min_interval_seconds=0, search_max_retries=0, max_search_requests=30,
            max_detail_pages=15, bilibili_public_metadata=True, ai_video_fallback_enabled=True), **overrides)
        model = DiscoveryModel(plan if plan is not None else {
            POINT: {"urls": [], "queries": ["Pygame 事件循环教程", "Pygame 事件循环完整课程"]}})
        fetcher = SourcePages(pages if pages is not None else {URL: POINT})
        captured = []

        async def http_response(request):
            query = json.loads(request.content)["q"]
            captured.append(query)
            response = respond(query, len(captured)) if respond else httpx.Response(200, json={"organic": [organic()]})
            return await response if inspect.isawaitable(response) else response

        client = httpx.AsyncClient(transport=httpx.MockTransport(http_response))
        clients.append(client)
        provider = SerperProvider(replace(settings, serper_api_key="offline-test-key"), client)
        store = Store(settings.database_path)
        stores.append(store)
        service = JobService(settings, store, provider=EmptySearch(), fetcher=fetcher, llm=model)
        service._ai_search_source = lambda *_args, **_kwargs: ("serper", provider, None)
        return service, captured, provider

    yield make
    for client in clients:
        await client.aclose()
    for store in stores:
        store.close()


async def run(service, points=None):
    identifier = service.create(SearchRequest(knowledge_points=points or [POINT], preferred_platforms=["bilibili"]))["job_id"]
    await service.run(identifier)
    return identifier, service.results(identifier)


@pytest.mark.parametrize("urls", [[], [DEAD_URL]])
async def test_live_search_recovers_empty_or_dead_model_url_using_verified_page(recovery_service, urls):
    service, searches, _ = recovery_service(plan={POINT: {"urls": urls, "queries": ["Pygame 事件循环教程"]}})
    identifier, result = await run(service)
    assert len(service.llm.calls) == 1 and searches
    rows = visible(result["groups"][0])
    assert len(rows) == 1
    resource = rows[0]["resource"]
    assert resource["url"] == URL
    assert resource["title"] == POINT + "公开教学视频"
    assert resource["video_evidence_status"] == "page_verified"
    assert not resource.get("playback_verified", False)
    evidence = service.store.evidence(identifier, resource["resource_id"])
    assert any(item["kind"] == "search" and item["source"] == "serper" for item in evidence)
    assert any(item["kind"] == "page" for item in evidence)
    assert service.store.get_job(identifier)["ai_video_fallback"]["remaining_points"] == 0


async def test_valid_direct_video_does_not_consume_grounded_search_requests(recovery_service):
    service, searches, _ = recovery_service(plan={POINT: {"urls": [URL], "queries": ["Pygame 事件循环教程"]}})
    _, result = await run(service)
    assert visible(result["groups"][0])
    assert not searches
    assert len(service.llm.calls) == 1


async def test_repeated_failed_urls_do_not_crowd_fresh_fourth_search_result(recovery_service):
    failed = [f"https://www.bilibili.com/video/BV1xx411c7D{suffix}" for suffix in "ghi"]

    def respond(_query, _count):
        return httpx.Response(200, json={"organic": [*[organic(url=url) for url in failed], organic()]})

    service, searches, _ = recovery_service(plan={POINT: {"urls": failed,
        "queries": ["Pygame 事件循环教程"]}}, respond=respond)
    _, result = await run(service)
    assert len(searches) == 1
    assert [row["url"] for row in service.fetcher.calls] == [*failed, URL]
    assert {row["resource"]["url"] for row in visible(result["groups"][0])} == {URL}


async def test_matching_english_title_after_three_intros_is_inspected_first(recovery_service):
    point = "文件下载"
    intros = [f"https://www.bilibili.com/video/BV1xx411c7D{suffix}" for suffix in "ghi"]

    def respond(_query, _count):
        return httpx.Response(200, json={"organic": [
            *[organic("Streamlit installation tutorial", url) for url in intros],
            organic("Streamlit Download Button tutorial", URL)]})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": []}},
        pages={URL: "Streamlit Download Button tutorial"}, respond=respond, max_detail_pages=1)
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "Streamlit"}))["job_id"]
    await service.run(identifier)
    assert len(searches) == 1
    assert [row["url"] for row in service.fetcher.calls] == [URL]
    rows = visible(service.results(identifier)["groups"][0])
    assert rows and rows[0]["resource"]["video_evidence_status"] == "page_verified", {
        "fetch_calls": service.fetcher.calls, "resources": service.store.resources(identifier),
        "fallback": service.store.get_job(identifier).get("ai_video_fallback")}
    assert rows[0]["reference"]["exact_teaching_verified"] is False


async def test_reordered_search_title_cannot_replace_missing_page_facts(recovery_service):
    point = "文件下载"
    service, _, _ = recovery_service(plan={point: {"urls": [], "queries": []}},
        pages={URL: "Streamlit installation tutorial"},
        respond=lambda *_: httpx.Response(200, json={"organic": [organic("Streamlit Download Button tutorial")]}))
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "Streamlit"}))["job_id"]
    await service.run(identifier)
    assert service.store.get_job(identifier)["ai_video_fallback"]["remaining_points"] == 1
    assert not any("page" in row.get("reference", {}).get("basis", [])
                   for row in visible(service.results(identifier)["groups"][0]))


async def test_model_failure_still_allows_grounded_original_topic_lookup(recovery_service):
    service, searches, _ = recovery_service()

    async def fail_model(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_MODEL_FAILURE")

    service.llm.suggest_video_discovery = fail_model
    identifier, result = await run(service)
    assert len(searches) == 1 and POINT in searches[0]
    assert visible(result["groups"][0])
    assert "PRIVATE_MODEL_FAILURE" not in json.dumps(service.store.get_job(identifier))


async def test_slow_direct_hint_leaves_time_for_grounded_recovery_inside_same_deadline(recovery_service):
    started, stopped = asyncio.Event(), asyncio.Event()
    service, searches, _ = recovery_service(plan={POINT: {"urls": [DEAD_URL],
        "queries": ["Pygame 事件循环教程"]}}, deadline_seconds=2)
    normal_enrich = service.fetcher.enrich

    async def slow_direct(candidate):
        if candidate["url"] == DEAD_URL:
            service.fetcher.calls.append(deepcopy(candidate))
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        return await normal_enrich(candidate)

    service.fetcher.enrich = slow_direct
    identifier, result = await asyncio.wait_for(run(service), timeout=3)
    assert started.is_set() and stopped.is_set()
    assert len(searches) == 1
    assert {row["resource"]["url"] for row in visible(result["groups"][0])} == {URL}
    assert service.store.get_job(identifier)["ai_video_fallback"]["remaining_points"] == 0


async def test_exhausted_search_budget_preserves_direct_page_slot_and_time(recovery_service):
    service, searches, _ = recovery_service(plan={POINT: {"urls": [URL],
        "queries": ["Pygame 事件循环教程"]}}, max_search_requests=1, max_detail_pages=1, deadline_seconds=2)
    normal_enrich = service.fetcher.enrich

    async def slower_valid_page(candidate):
        # Longer than one third of the total deadline: no unusable search
        # allowance may steal this time from the remaining direct page.
        await asyncio.sleep(0.8)
        return await normal_enrich(candidate)

    service.fetcher.enrich = slower_valid_page
    identifier, result = await asyncio.wait_for(run(service), timeout=3)
    job = service.store.get_job(identifier)
    assert job["progress"]["search_requests"] == 1 and len(service.provider.calls) == 1
    assert not searches
    assert [row["url"] for row in service.fetcher.calls] == [URL]
    assert {row["resource"]["url"] for row in visible(result["groups"][0])} == {URL}
    assert job["progress"]["details_attempted"] == 1
    assert not job["ai_video_fallback"].get("direct_fetch_timed_out")


async def test_each_point_gets_first_search_before_second_phrase(recovery_service):
    points = ["Python 列表", "Java 数组", "CSS 选择器", "SQL 多表连接", "HTML 表单"]
    urls = {point: f"https://www.bilibili.com/video/BV1xx411c7D{index}" for index, point in enumerate(points)}
    plan = {point: {"urls": [], "queries": [point + "完整课程", point + "额外视频"]} for point in points}

    def respond(query, _count):
        matches = [organic(point, urls[point]) for point in points if point + "完整课程" in query]
        return httpx.Response(200, json={"organic": matches})

    service, searches, _ = recovery_service(plan=plan, pages={url: point for point, url in urls.items()}, respond=respond)
    identifier, result = await run(service, points)
    assert len(searches) == 10
    assert all(query.endswith(point) for point, query in zip(points, searches[:5]))
    assert all(visible(group) for group in result["groups"])
    assert service.store.get_job(identifier)["progress"]["search_requests"] <= service.settings.max_search_requests


async def test_five_gap_points_keep_grounded_page_slots_when_only_five_details_remain(recovery_service):
    points = ["Python 列表", "Java 数组", "CSS 选择器", "SQL 多表连接", "HTML 表单"]
    urls = {point: f"https://www.bilibili.com/video/BV1xx411c7D{index}" for index, point in enumerate(points)}
    failed = {point: f"https://www.bilibili.com/video/BV1xx411c7E{index}" for index, point in enumerate(points)}
    plan = {point: {"urls": [failed[point]], "queries": [point + "入门视频"]} for point in points}

    def respond(query, _count):
        return httpx.Response(200, json={"organic": [organic(point, urls[point]) for point in points if point in query]})

    service, searches, _ = recovery_service(plan=plan, pages={url: point for point, url in urls.items()},
                                            respond=respond, max_detail_pages=5)
    identifier, result = await run(service, points)
    assert len(searches) == 5
    assert [row["url"] for row in service.fetcher.calls] == list(urls.values())
    assert all(visible(group) for group in result["groups"])
    assert service.store.get_job(identifier)["progress"]["details_attempted"] == 5


async def test_model_query_never_substitutes_for_actual_page_facts(recovery_service):
    invented = "Pygame 事件循环某个未验证课程名字"
    service, searches, _ = recovery_service(plan={POINT: {"urls": [], "queries": [invented]}},
                                            pages={URL: "吉他和弦与指法"})
    identifier, result = await run(service)
    assert searches and searches[0].endswith(POINT) and invented in searches[-1]
    assert not visible(result["groups"][0])
    resource = next(iter(service.store.resources(identifier).values()))
    assert resource["title"] == "吉他和弦与指法公开教学视频"
    assert invented not in resource["title"] and invented not in resource.get("description", "")


async def test_model_failure_and_stalled_chinese_query_still_reach_english_source(recovery_service):
    cancelled = asyncio.Event()
    point = "文本分段"

    async def respond(query, _count):
        if point in query:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        assert "Python text splitting" in query
        return httpx.Response(200, json={"organic": [organic("Python Text Splitting", URL)]})

    service, searches, _ = recovery_service(plan={}, pages={URL: "Python Text Splitting"},
                                           respond=respond, deadline_seconds=3)

    async def unavailable(*_args, **_kwargs):
        raise httpx.ConnectTimeout("offline model connection timeout")

    service.llm.suggest_video_discovery = unavailable
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "Python"}))["job_id"]
    await asyncio.wait_for(service.run(identifier), timeout=4)
    assert cancelled.is_set() and len(searches) == 2
    assert searches[0].endswith("Python 文本分段")
    assert searches[1].endswith("Python text splitting")
    rows = visible(service.results(identifier)["groups"][0])
    assert rows and rows[0]["resource"]["video_evidence_status"] == "page_verified", {
        "fetch_calls": service.fetcher.calls, "resources": service.store.resources(identifier),
        "fallback": service.store.get_job(identifier).get("ai_video_fallback")}
    diagnostic = service.store.get_job(identifier)["ai_video_fallback"]
    assert diagnostic["model_calls"] == 1 and diagnostic["search_query_timeouts"] == 1
    assert diagnostic["remaining_points"] == 0 and diagnostic["error_type"] == "ConnectTimeout"


async def test_slow_sibling_search_cannot_starve_fast_points_source_fetch(recovery_service):
    slow, fast = "事件循环", "文本分段"

    async def respond(query, _count):
        if slow in query or "event loop" in query:
            await asyncio.Event().wait()
        return httpx.Response(200, json={"organic": [organic("Python Text Splitting", URL)]})

    service, searches, _ = recovery_service(plan={}, pages={URL: "Python Text Splitting"},
                                           respond=respond, deadline_seconds=3)
    identifier = service.create(SearchRequest(knowledge_points=[slow, fast], preferred_platforms=["bilibili"],
        topic_technologies={slow: "Python", fast: "Python"}))["job_id"]
    await asyncio.wait_for(service.run(identifier), timeout=4)
    groups = service.results(identifier)["groups"]
    assert not visible(groups[0]) and visible(groups[1])
    assert len(service.fetcher.calls) == 1
    assert sum(fast in query or "text splitting" in query for query in searches) == 1
    diagnostic = service.store.get_job(identifier)["ai_video_fallback"]
    assert diagnostic["covered_points"] == 1 and diagnostic["remaining_points"] == 1


async def test_source_fetch_continues_across_phrase_windows_without_duplicate_attempt(recovery_service):
    point = "文本分段"
    service, searches, _ = recovery_service(plan={}, pages={URL: "Python Text Splitting"},
        respond=lambda *_: httpx.Response(200, json={"organic": [organic("Python Text Splitting", URL)]}),
        deadline_seconds=3)
    original_enrich = service.fetcher.enrich
    cancelled = asyncio.Event()

    async def slower_than_one_phrase(candidate):
        try:
            await asyncio.sleep(1.7)
            return await original_enrich(candidate)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    service.fetcher.enrich = slower_than_one_phrase
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "Python"}))["job_id"]
    await asyncio.wait_for(service.run(identifier), timeout=4)
    assert len(searches) == 2 and not cancelled.is_set()
    assert len(service.fetcher.calls) == 1
    assert visible(service.results(identifier)["groups"][0])
    assert service.store.get_job(identifier)["progress"]["details_attempted"] == 1


async def test_untrusted_query_and_foreign_or_search_urls_are_not_fetched(recovery_service):
    bad_query = "site:evil.example Python"

    def respond(_query, _count):
        return httpx.Response(200, json={"organic": [
            organic(url="https://evil.example/video/BV1xx411c7Df"),
            organic(url="https://search.bilibili.com/all?keyword=Pygame"),
            organic(),
        ]})

    service, searches, _ = recovery_service(plan={POINT: {"urls": [],
        "queries": [bad_query, "Pygame 事件循环教程", "Pygame 忽略超额第三个短语"]}}, respond=respond)
    _, result = await run(service)
    assert searches and all(bad_query not in query for query in searches)
    assert all("忽略超额第三个短语" not in query for query in searches)
    assert [row["url"] for row in service.fetcher.calls] == [URL]
    assert visible(result["groups"][0])


async def test_grounded_http_attempts_share_job_cap_even_with_transport_retries(recovery_service):
    def respond(_query, _count):
        raise httpx.ConnectTimeout("offline transport failure")

    service, searches, _ = recovery_service(respond=respond, max_search_requests=4, search_max_retries=1)
    identifier, _ = await run(service)
    progress = service.store.get_job(identifier)["progress"]
    assert searches
    assert progress["search_requests"] <= 4
    assert len(searches) + len(service.provider.calls) == progress["search_requests"]


async def test_transient_first_timeout_retries_original_declared_topic_and_recovers_page(recovery_service):
    point, technology = "文件下载", "Streamlit"
    drifted = "Streamlit 教程应用部署"

    def respond(_query, count):
        if count == 1:
            raise httpx.ConnectTimeout("offline first transient timeout")
        return httpx.Response(200, json={"organic": [organic(technology + " " + point)]})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": [drifted]}},
        pages={URL: technology + " " + point}, respond=respond, search_max_retries=1)
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: technology}))["job_id"]
    await service.run(identifier)
    rows = visible(service.results(identifier)["groups"][0])
    assert len(searches) == 2 and searches[0] == searches[1]
    assert searches[0].endswith("Streamlit 文件下载")
    assert all(drifted not in query for query in searches)
    assert len(rows) == 1 and rows[0]["resource"]["video_evidence_status"] == "page_verified"
    job = service.store.get_job(identifier)
    assert job["ai_video_fallback"]["search_requests"] == 2
    assert job["progress"]["search_requests"] == len(service.provider.calls) + 2
    assert job["ai_video_fallback"]["remaining_points"] == 0


async def test_retry_cannot_exceed_total_job_search_budget(recovery_service):
    def respond(_query, _count):
        raise httpx.ConnectTimeout("offline transient timeout")

    service, searches, _ = recovery_service(respond=respond, search_max_retries=1, max_search_requests=2)
    identifier, result = await run(service)
    assert len(service.provider.calls) == 1 and len(searches) == 1
    assert service.store.get_job(identifier)["progress"]["search_requests"] == 2
    assert not service.fetcher.calls and not visible(result["groups"][0])


async def test_transient_retries_preserve_first_query_fairness_for_multiple_points(recovery_service):
    points = ["文件下载", "表单输入"]
    urls = {points[0]: URL, points[1]: DEAD_URL}
    seen = set()

    def respond(query, _count):
        if query not in seen:
            seen.add(query)
            raise httpx.ConnectTimeout("offline per-query first transient timeout")
        point = next(point for point in points if point in query)
        return httpx.Response(200, json={"organic": [organic("Streamlit " + point, urls[point])]})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": ["Streamlit 应用部署"]} for point in points},
        pages={url: "Streamlit " + point for point, url in urls.items()}, respond=respond,
        search_max_retries=1, max_search_requests=6)
    identifier = service.create(SearchRequest(knowledge_points=points, preferred_platforms=["bilibili"],
        topic_technologies={point: "Streamlit" for point in points}))["job_id"]
    await service.run(identifier)
    assert len(searches) == 4
    assert all(any(query.endswith("Streamlit " + point) for query in searches[:2]) for point in points)
    assert all("应用部署" not in query for query in searches)
    assert all(visible(group) for group in service.results(identifier)["groups"])
    assert service.store.get_job(identifier)["progress"]["search_requests"] == 6


@pytest.mark.parametrize("status", [400, 429])
async def test_grounded_rejection_stops_source_without_second_phrase(recovery_service, status):
    def respond(_query, _count):
        return httpx.Response(status, headers={"Retry-After": "60"}, json={"error": "offline rejection"})

    service, searches, _ = recovery_service(respond=respond)
    identifier, result = await run(service)
    assert len(searches) == 1
    assert not visible(result["groups"][0])
    assert service.store.get_job(identifier)["status"] in {"partial", "failed"}


async def test_grounded_search_obeys_job_deadline_and_clears_pending_followup(recovery_service):
    stopped = asyncio.Event()

    async def respond(_query, _count):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    service, searches, _ = recovery_service(respond=respond, deadline_seconds=1, parallel_platform_search=True,
                                            open_web_search_enabled=False)
    identifier, result = await asyncio.wait_for(run(service), timeout=2)
    job = service.store.get_job(identifier)
    assert len(searches) == 1 and stopped.is_set()
    assert not visible(result["groups"][0])
    assert not job.get("platform_search", {}).get("followup_pending")
    assert job["status"] in {"partial", "failed"}
    # Re-running a finished timeout must not repeatedly resume a pending lane.
    before = len(searches), len(service.llm.calls)
    await asyncio.wait_for(service.run(identifier), timeout=2)
    assert before == (len(searches), len(service.llm.calls))


async def test_cancel_during_grounded_request_cancels_http_and_never_fetches(recovery_service):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def respond(_query, _count):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    service, searches, _ = recovery_service(respond=respond)
    identifier = service.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["bilibili"]))["job_id"]
    task = asyncio.create_task(service.run(identifier))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert (await service.cancel(identifier))["cancelled"]
        assert stopped.is_set() and len(searches) == 1
        assert not service.fetcher.calls
        assert not visible(service.results(identifier)["groups"][0])
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("stop", ["access_denied", "rate_limited", "engine_pause"])
async def test_original_source_strong_stop_still_blocks_same_configured_provider(recovery_service, stop):
    service, searches, provider = recovery_service()
    service.settings = replace(service.settings, serper_api_key="offline-test-key", ai_video_search_provider="default",
                               searxng_engines=("bing",))
    service._providers["serper"] = provider
    service._provider_errors["serper"] = None
    if stop == "access_denied":
        service.provider.access_denied = True
    elif stop == "rate_limited":
        service.provider.paused_until = time.monotonic() + 60
    else:
        service.provider.engine_pauses = {"bing": time.monotonic() + 60}
        service.provider.engine_timeout_cooldowns = {}
    # Exercise the production selector, not the fixture's injected selector.
    service._ai_search_source = JobService._ai_search_source.__get__(service)
    query = Query(knowledge_point_id="point", query="Pygame 事件循环", domain_filters=["bilibili.com"])
    name, selected, error = service._ai_search_source(query)
    assert name == "searxng" and selected is None and error.code == "source_stopped"
    _, result = await run(service)
    assert not searches and not service.fetcher.calls
    assert not visible(result["groups"][0])


async def test_expired_followup_checks_ownership_before_mutating_and_never_requeues(recovery_service):
    service, searches, _ = recovery_service(parallel_platform_search=True)
    identifier = service.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["bilibili"]),
        consumer_key="project:owner", defer_platform_followups=True)["job_id"]
    job = service.store.get_job(identifier)
    job.update(status="partial", phase="awaiting_followup",
               platform_search_active_seconds=job["budgets"]["deadline_seconds"])
    job["platform_search"].update(initial_done=True, followup_pending=True)
    service._save(job)
    before = deepcopy(service.store.get_job(identifier))
    with pytest.raises(ValueError, match="未持有"):
        service.resume_platform_search(identifier, consumer_key="project:other")
    assert service.store.get_job(identifier) == before
    assert not service.resume_platform_search(identifier, consumer_key="project:owner")
    after = service.store.get_job(identifier)
    assert not after["platform_search"]["followup_pending"]
    assert after["platform_search"]["stopped_reason"] == "job_deadline"
    assert after["phase"] == "done" and after["status"] == "partial"
    assert not searches and service.queue.qsize() == 1  # Original create only, no resumed entry.
