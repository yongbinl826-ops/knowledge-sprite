"""Bounded, owned cover retries without foreground work or real requests."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import time

import httpx
import pytest

from backend.app import fast_video_search as fast
from backend.app import helpful_video_chapters as module
from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher, catalog_identity
from test_background_covers import IMAGE, POINTS, native_metadata, state_with_cards
from test_fast_video_search import settings


RESOURCE = {"resource_id": "one", "url": "https://www.bilibili.com/video/BV1VZ4y1G7YB", "title": "Python"}


@pytest.fixture(autouse=True)
def offline_and_short_backoff(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Cover retry tests cannot perform real network/model/search operations")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(fast, "complete_json", forbidden)
    monkeypatch.setattr(fast, "build_provider", forbidden)
    assert module.COVER_TRANSIENT_RETRY_BACKOFF_SECONDS == 1.0
    monkeypatch.setattr(module, "COVER_TRANSIENT_RETRY_BACKOFF_SECONDS", .02)


@asynccontextmanager
async def managed(fetch, **kwargs):
    options = dict(cover_only=True, background_mode=True, deadline=time.monotonic() + 2,
                   max_resources=12, max_http_requests=24, max_semantic_batches=0)
    options.update(kwargs)
    enricher = HelpfulVideoChapterEnricher(settings(), POINTS, fetch_catalog=fetch, **options)
    try:
        yield enricher
    finally:
        await enricher.close()


async def drain(enricher):
    enricher.finish_admission()
    await asyncio.wait_for(enricher.run_background_match(collect_seconds=0), 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout_exception", "dns_error", "network_error"])
async def test_cover_retry_success_keeps_failure_evidence_and_frozen_recommendation(failure):
    state = state_with_cards(1)
    before = deepcopy(state)
    calls, instances = [], []
    async def fetch(resource):
        calls.append(resource["url"])
        if len(calls) == 1:
            if failure == "timeout_exception":
                raise asyncio.TimeoutError()
            return {"url": resource["url"], "fetch_status": failure}
        return native_metadata(resource)
    def factory(*args, **kwargs):
        instance = HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)
        instances.append(instance)
        return instance
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None,
                                           chapter_enricher_factory=factory)
    assert len(calls) == 2 and calls[0] == calls[1]
    detail = result["diagnostics"]["covers"]
    assert detail["network_scheduled_resources"] == 1 and detail["fetch_attempts"] == 2
    assert detail["cover_retry_attempts"] == detail["cover_retry_succeeded"] == 1
    assert detail["cover_retry_exhausted"] == detail["page_failures_unresolved"] == 0
    attempts = detail["resources"][0]["attempts"]
    assert len(attempts) == 2 and not attempts[0]["retry"] and attempts[1]["retry"]
    assert attempts[0]["status"] == ("timeout" if failure == "timeout_exception" else failure)
    assert attempts[1]["status"] == "cover_received"
    if failure == "timeout_exception":
        assert detail["timeouts"] == 1
    assert result["catalog_enrichment"]["status"] == "completed"
    assert result["recommendations"]["loop"][0]["resource"]["thumbnail_url"] == IMAGE
    assert result["recommendations"]["loop"][0]["matched_chapters"] == before["recommendations"]["loop"][0]["matched_chapters"]
    assert result["progress"] == before["progress"]
    for field in ("status", "started_at", "finished_at", "elapsed_seconds"):
        assert result[field] == before[field]
    assert all(task.done() for instance in instances for task in instance._tasks)


@pytest.mark.asyncio
async def test_two_failures_stop_at_one_retry_and_report_current_failure():
    calls = []
    async def fetch(resource):
        calls.append(resource["url"])
        return {"url": resource["url"], "fetch_status": "network_error"}
    async with managed(fetch) as enricher:
        enricher.enqueue(RESOURCE, ["loop"])
        await drain(enricher)
        assert len(calls) == 2
        assert enricher.diagnostics["cover_retry_exhausted"] == 1
        assert enricher.diagnostics["page_failures_unresolved"] == 1
        assert fast._catalog_incomplete(enricher.diagnostics)
        assert not enricher.enqueue_cover(RESOURCE, ["loop"])
        assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["fetched", "policy_unreviewed", "access_denied", "rate_limited", "not_found", "unsafe_url", "paid"])
async def test_empty_or_restricted_pages_are_never_automatically_retried(status):
    calls = []
    async def fetch(resource):
        calls.append(resource["url"])
        return {"url": resource["url"], "fetch_status": "fetched" if status == "paid" else status,
                "requires_payment": status == "paid"}
    async with managed(fetch) as enricher:
        enricher.enqueue(RESOURCE, ["loop"])
        await drain(enricher)
        assert len(calls) == 1
        assert enricher.diagnostics["cover_retry_scheduled"] == 0


@pytest.mark.asyncio
async def test_completed_foreground_failure_needs_explicit_background_cover_admission():
    calls, covers, chapters = [], [], []
    async def fetch(resource):
        calls.append(resource["url"])
        return ({"url": resource["url"], "fetch_status": "network_error"}
                if len(calls) == 1 else native_metadata(resource))
    async with managed(fetch, cover_only=False, background_mode=False,
                       publish=lambda *args: chapters.append(args), on_cover=lambda *args: covers.append(args)) as enricher:
        enricher.enqueue(RESOURCE, ["loop"])
        await asyncio.gather(*enricher._tasks)
        assert len(calls) == 1 and not enricher.enqueue_cover(RESOURCE, ["loop"])
        enricher.expand_background(max_resources=12, max_http_requests=24, max_semantic_batches=0,
                                  deadline=time.monotonic() + 2)
        assert enricher.enqueue_cover(RESOURCE, ["loop"])
        assert enricher.enqueue_cover({**RESOURCE, "resource_id": "alias"}, ["loop"])
        await drain(enricher)
        assert len(calls) == 2 and covers and not chapters
        assert enricher.diagnostics["network_scheduled_resources"] == 1
        assert enricher.diagnostics["cover_retry_attempts"] == 1


@pytest.mark.asyncio
async def test_pending_foreground_page_can_gain_background_cover_retry_without_rematching_chapters():
    entered, release = asyncio.Event(), asyncio.Event()
    calls, chapters, covers = [], [], []
    async def fetch(resource):
        calls.append(resource["url"])
        if len(calls) == 1:
            entered.set()
            await release.wait()
            raise asyncio.TimeoutError()
        return native_metadata(resource)
    async with managed(fetch, cover_only=False, background_mode=False,
                       publish=lambda *args: chapters.append(args), on_cover=lambda *args: covers.append(args)) as enricher:
        enricher.enqueue(RESOURCE, ["loop"])
        await entered.wait()
        enricher.expand_background(max_resources=12, max_http_requests=24, max_semantic_batches=0,
                                  deadline=time.monotonic() + 2)
        assert enricher.enqueue_cover(RESOURCE, ["loop"])
        release.set()
        await drain(enricher)
        assert len(calls) == 2 and covers and not chapters
        assert enricher.diagnostics["semantic_calls"] == 0


@pytest.mark.asyncio
async def test_coverless_catalog_cache_refresh_can_retry_without_changing_saved_chapters():
    calls, chapters, covers = [], [], []
    async def fetch(resource):
        calls.append(resource["url"])
        return ({"url": resource["url"], "fetch_status": "dns_error"}
                if len(calls) == 1 else native_metadata(resource))
    async with managed(fetch, cover_only=False, background_mode=False,
                       load_cached_catalog=lambda resource: native_metadata(resource, with_image=False),
                       publish=lambda *args: chapters.append(args), on_cover=lambda *args: covers.append(args)) as enricher:
        enricher.enqueue(RESOURCE, ["loop"])
        await asyncio.gather(*enricher._tasks)
        before = deepcopy(chapters)
        assert before and not calls
        enricher.expand_background(max_resources=12, max_http_requests=24, max_semantic_batches=0,
                                  deadline=time.monotonic() + 2)
        assert enricher.enqueue_cover(RESOURCE, ["loop"])
        await drain(enricher)
        assert len(calls) == 2 and covers
        assert chapters == before
        assert enricher.diagnostics["cover_refreshes"] == enricher.diagnostics["cover_retry_attempts"] == 1


@pytest.mark.asyncio
async def test_backoff_releases_both_host_lock_and_global_slot():
    calls = []
    other = {**RESOURCE, "resource_id": "two", "url": "https://www.bilibili.com/video/av50123"}
    async def fetch(resource):
        calls.append(resource["resource_id"])
        if calls == ["one"]:
            return {"url": resource["url"], "fetch_status": "network_error"}
        return native_metadata(resource)
    async with managed(fetch, concurrency=1) as enricher:
        enricher.enqueue(RESOURCE, ["loop"])
        enricher.enqueue(other, ["loop"])
        await drain(enricher)
        assert calls == ["one", "two", "one"]
        assert enricher.diagnostics["network_scheduled_resources"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["budget", "deadline", "budget_during_backoff"])
async def test_retry_never_overruns_http_or_owner_deadline(stop):
    calls = []
    holder = {}
    async def fetch(resource):
        calls.append(resource["resource_id"])
        enricher = holder["enricher"]
        assert enricher.diagnostics["http_requests"] < enricher.max_http_requests
        enricher.diagnostics["http_requests"] += 1
        enricher._records[catalog_identity(resource["url"])]["diagnostic"]["http_requests"] += 1
        return ({"url": resource["url"], "fetch_status": "network_error"}
                if resource["resource_id"] == "one" else native_metadata(resource))
    options = ({"max_http_requests": 1} if stop == "budget" else
               {"deadline": time.monotonic() + .01} if stop == "deadline" else {"max_http_requests": 2})
    async with managed(fetch, **options) as enricher:
        holder["enricher"] = enricher
        enricher.enqueue(RESOURCE, ["loop"])
        if stop == "budget_during_backoff":
            enricher.enqueue({**RESOURCE, "resource_id": "two", "url": "https://www.bilibili.com/video/av50124"}, ["loop"])
        await drain(enricher)
        assert calls.count("one") == 1
        assert enricher.diagnostics["http_requests"] <= enricher.max_http_requests
        assert enricher.diagnostics["cover_retry_attempts"] == 0
        assert enricher.diagnostics["cover_retry_skipped_deadline" if stop == "deadline" else "cover_retry_skipped_budget"] == 1
        assert fast._catalog_incomplete(enricher.diagnostics)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["backoff", "second_request"])
async def test_cancellation_owns_backoff_and_second_request_without_late_publication(phase):
    calls, covers = [], []
    second = asyncio.Event()
    async def fetch(resource):
        calls.append(resource["url"])
        if len(calls) == 1:
            return {"url": resource["url"], "fetch_status": "network_error"}
        second.set()
        await asyncio.Event().wait()
    async with managed(fetch, on_cover=lambda *args: covers.append(args)) as enricher:
        enricher.enqueue(RESOURCE, ["loop"])
        enricher.finish_admission()
        owner = asyncio.create_task(enricher.run_background_match(collect_seconds=0))
        if phase == "backoff":
            while not enricher.diagnostics["cover_retry_scheduled"]:
                await asyncio.sleep(0)
            assert not next(iter(enricher._records.values()))["done"]
        else:
            await second.wait()
        await enricher.close()
        await asyncio.wait_for(owner, .5)
        assert len(calls) == (1 if phase == "backoff" else 2)
        assert not covers and all(task.done() for task in enricher._tasks)
        assert enricher.diagnostics["cancelled"] == 1
