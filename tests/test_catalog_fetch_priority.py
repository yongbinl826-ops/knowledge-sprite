"""Offline course queue scheduling with controlled arrivals and completion."""
import asyncio

import pytest

from backend.app.config import Settings
from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher


POINTS = [{"id": "p", "name": "事件处理"}]


def resource(number, **extra):
    return {"resource_id": str(number), "url": f"https://www.bilibili.com/video/av{1000 + number}",
            "title": "公开课程", **extra}


def metadata(course):
    url = course["url"]
    return {"url": url, "fetch_status": "fetched", "fetched_at": "2026-10-28T01:00:00+00:00",
            "thumbnail_url": "https://i0.hdslb.com/bfs/archive/observed.jpg",
            "field_provenance": {"thumbnail_url": {"source": "meta.og:image", "url": url,
                "fetched_at": "2026-10-28T01:00:00+00:00", "evidence_id": "native-page-image"}},
            "chapters": [{"title": "事件处理", "source_url": url, "page_number": 1,
                "source": "html.bilibili.__INITIAL_STATE__.videoData.pages", "evidence_id": "chapter-1"}]}


async def finish(enricher):
    enricher.finish_admission()
    await asyncio.wait_for(enricher.run_background_match(collect_seconds=0), 1)


@pytest.mark.asyncio
async def test_same_host_two_reads_and_other_host_use_global_capacity():
    started, release, filled = [], asyncio.Event(), asyncio.Event()

    async def fetch(course):
        started.append(course["resource_id"])
        if len(started) == 3:
            filled.set()
        await release.wait()
        return metadata(course)

    enricher = HelpfulVideoChapterEnricher(Settings(), POINTS, fetch_catalog=fetch)
    try:
        for number in range(3):
            assert enricher.enqueue(resource(number), ["p"])
        assert enricher.enqueue(resource(3, url="https://www.icourse163.org/course/TEST-1234567"), ["p"])
        await asyncio.wait_for(filled.wait(), .5)
        assert started == ["0", "1", "3"]
        assert enricher._active_fetches == 3
        assert enricher._active_hosts["www.bilibili.com"] == 2
        release.set()
        await finish(enricher)
        assert sorted(started) == ["0", "1", "2", "3"]
        assert enricher._active_fetches == 0 and not enricher._fetch_waiters
    finally:
        await enricher.close()


@pytest.mark.asyncio
async def test_cover_request_promotes_existing_waiter_without_duplicate_or_lost_catalog():
    started, first_started, release = [], asyncio.Event(), asyncio.Event()
    chapters, covers = [], []

    async def fetch(course):
        started.append(course["resource_id"])
        if course["resource_id"] == "0":
            first_started.set()
            await release.wait()
        return metadata(course)

    enricher = HelpfulVideoChapterEnricher(Settings(), POINTS, fetch_catalog=fetch,
        concurrency=1, background_mode=True, publish=lambda *args: chapters.append(args),
        on_cover=lambda *args: covers.append(args))
    try:
        enricher.enqueue(resource(0), ["p"])
        await asyncio.wait_for(first_started.wait(), .5)
        enricher.enqueue(resource(1), ["p"])
        enricher.enqueue(resource(2), ["p"])
        await asyncio.sleep(0)
        assert len(enricher._fetch_waiters) == 2
        assert enricher.enqueue_cover(resource(2), ["p"])
        release.set()
        await finish(enricher)
        assert started == ["0", "2", "1"]
        assert {row[0] for row in chapters} == {"0", "1", "2"}
        assert {row[0] for row in covers} == {"0", "1", "2"}
        assert enricher.diagnostics["network_scheduled_resources"] == 3
        assert enricher.diagnostics["fetch_attempts"] == 3
    finally:
        await enricher.close()


@pytest.mark.asyncio
async def test_new_missing_cover_overtakes_queued_courses_with_known_images():
    started, first_started, release = [], asyncio.Event(), asyncio.Event()

    async def fetch(course):
        started.append(course["resource_id"])
        if course["resource_id"] == "0":
            first_started.set()
            await release.wait()
        return metadata(course)

    enricher = HelpfulVideoChapterEnricher(Settings(), POINTS, fetch_catalog=fetch,
        concurrency=1, background_mode=True)
    try:
        enricher.enqueue(resource(0), ["p"])
        await asyncio.wait_for(first_started.wait(), .5)
        for number in (1, 2):
            enricher.enqueue(resource(number, thumbnail_url="https://i0.hdslb.com/known.jpg"), ["p"])
        await asyncio.sleep(0)
        enricher.enqueue_cover(resource(3), ["p"])
        release.set()
        await finish(enricher)
        assert started == ["0", "3", "1", "2"]
        assert enricher.diagnostics["fetch_attempts"] == 4
    finally:
        await enricher.close()


@pytest.mark.asyncio
async def test_promoted_early_cover_reuses_queue_entry_and_still_gets_chapters():
    started, first_started, release = [], asyncio.Event(), asyncio.Event()
    chapters = []

    async def fetch(course):
        started.append(course["resource_id"])
        if course["resource_id"] == "0":
            first_started.set()
            await release.wait()
        return metadata(course)

    enricher = HelpfulVideoChapterEnricher(Settings(), POINTS, fetch_catalog=fetch,
        concurrency=1, publish=lambda *args: chapters.append(args))
    try:
        enricher.enqueue(resource(0), ["p"])
        await asyncio.wait_for(first_started.wait(), .5)
        enricher.enqueue(resource(1), ["p"])
        assert enricher.enqueue_early_cover(resource(2), ["p"])
        await asyncio.sleep(0)
        assert enricher.enqueue(resource(2), ["p"])
        release.set()
        await finish(enricher)
        assert started == ["0", "2", "1"]
        assert {row[0] for row in chapters} == {"0", "1", "2"}
        assert enricher.diagnostics["fetch_attempts"] == 3
    finally:
        await enricher.close()


@pytest.mark.asyncio
async def test_shared_queue_wakes_all_waiters_across_hosts_and_priority_changes():
    started = []

    async def fetch(course):
        started.append(course["resource_id"])
        # Interleave admission, release, and wakeups instead of completing all
        # fake reads synchronously in their task's first turn.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return metadata(course)

    enricher = HelpfulVideoChapterEnricher(Settings(), POINTS, fetch_catalog=fetch,
        max_resources=40, background_mode=True)
    try:
        courses = [resource(number, url=f"https://{'www.' if number % 2 else ''}bilibili.com/video/av{2000 + number}")
                   for number in range(30)]
        for course in courses:
            enricher.enqueue(course, ["p"])
        await asyncio.sleep(0)
        for course in reversed(courses[5:]):
            enricher.enqueue_cover(course, ["p"])
        await finish(enricher)
        assert len(started) == len(set(started)) == 30
        assert enricher.diagnostics["catalogs_received"] == 30
        assert not enricher._fetch_waiters and not enricher._active_hosts
        assert enricher._active_fetches == 0
    finally:
        await enricher.close()


@pytest.mark.asyncio
async def test_cancel_drains_active_and_waiting_work_without_late_covers():
    started, filled = [], asyncio.Event()
    covers = []

    async def fetch(course):
        started.append(course["resource_id"])
        if len(started) == 2:
            filled.set()
        await asyncio.Event().wait()
        return metadata(course)

    enricher = HelpfulVideoChapterEnricher(Settings(), POINTS, fetch_catalog=fetch,
        on_cover=lambda *args: covers.append(args))
    for number in range(8):
        enricher.enqueue(resource(number), ["p"])
    await asyncio.wait_for(filled.wait(), .5)
    await enricher.close()
    assert len(started) == 2 and not covers
    assert all(task.done() for task in enricher._tasks)
    assert not enricher._fetch_waiters and not enricher._active_hosts
    assert enricher._active_fetches == 0
    assert enricher.diagnostics["cancelled"] == 8
