"""Offline native-catalog binding, scheduling, and optional matching boundaries."""
import asyncio
import json
import time
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app import helpful_video_chapters as chapter_module
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, NETWORK_OBSERVER, FETCH_DEADLINE_AT
from backend.app.helpful_video_chapters import (
    HelpfulVideoChapterEnricher, _CatalogDNSCache, catalog_identity, observed_chapters, specific_chapter_title,
    observed_cover, displayable_cover_url,
)


URL = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
RESOURCE = {"resource_id": "video", "url": URL, "title": "Python 游戏课程"}
POINTS = [{"id": "collision", "name": "碰撞检测"}, {"id": "event", "name": "事件处理"}]
SOURCE = "html.bilibili.__INITIAL_STATE__.videoData.pages"


def metadata(titles=("第3节 碰撞检测", "第4节 事件处理", "第5节 碰撞检测与事件处理")):
    return {"url": URL, "fetched_at": "2026-10-23T01:00:00+00:00", "fetch_status": "fetched",
            "chapters": [{"title": title, "source_url": URL, "source": SOURCE,
                          "page_number": i, "url": URL + f"/?p={i}", "evidence_id": f"e-{i}"}
                         for i, title in enumerate(titles, 3)]}


def cover_metadata(*, source="html.bilibili.__INITIAL_STATE__.videoData.pic", image="https://i0.hdslb.com/bfs/archive/cover.jpg"):
    raw = metadata()
    raw.update(thumbnail_url=image, field_provenance={"thumbnail_url": {
        "source": source, "url": URL, "fetched_at": raw["fetched_at"], "evidence_id": "observed-cover-evidence"}})
    return raw


@pytest.mark.parametrize("source", ["html.bilibili.__INITIAL_STATE__.videoData.pic", "meta.og:image", "meta.og:image:secure_url"])
def test_observed_cover_requires_this_fetched_course_and_keeps_real_source(source):
    raw = cover_metadata(source=source, image="http://i0.hdslb.com/bfs/archive/cover.jpg")
    cover = observed_cover(RESOURCE, raw)
    assert cover["thumbnail_url"] == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert cover["source"] == cover["source_kind"] == source
    assert cover["source_url"] == URL and cover["observed_at"] == raw["fetched_at"]
    assert cover["provenance"]["original_thumbnail_url"] == raw["thumbnail_url"]


@pytest.mark.parametrize("damage", ["paid", "not_found", "captcha", "timeout", "not_fetched", "url", "canonical_url",
                                    "resolved_url", "provenance_url", "search", "jsonld", "no_provenance", "private_image", "http_image"])
def test_unbound_uncertain_or_search_covers_never_publish(damage):
    raw = cover_metadata()
    if damage == "paid": raw["requires_payment"] = True
    elif damage in {"not_found", "captcha", "timeout", "not_fetched"}: raw["fetch_status"] = damage
    elif damage in {"url", "canonical_url", "resolved_url"}: raw[damage] = "https://www.bilibili.com/video/av999"
    elif damage == "provenance_url": raw["field_provenance"]["thumbnail_url"]["url"] = "https://www.bilibili.com/video/av999"
    elif damage == "search": raw["field_provenance"]["thumbnail_url"]["source"] = "search.thumbnail"
    elif damage == "jsonld": raw["field_provenance"]["thumbnail_url"]["source"] = "jsonld.image"
    elif damage == "no_provenance": raw.pop("field_provenance")
    elif damage == "private_image": raw["thumbnail_url"] = "https://127.0.0.1/cover.jpg"
    elif damage == "http_image": raw["thumbnail_url"] = "http://example.com/cover.jpg"
    assert observed_cover(RESOURCE, raw) is None


def test_cover_display_policy_never_upgrades_arbitrary_http_hosts():
    assert displayable_cover_url("http://i2.hdslb.com/a.jpg") == "https://i2.hdslb.com/a.jpg"
    assert displayable_cover_url("http://i2.hdslb.com:81/a.jpg") is None
    assert displayable_cover_url("http://hdslb.com/a.jpg") is None
    assert displayable_cover_url("https://images.example.com/a.jpg") == "https://images.example.com/a.jpg"
    assert observed_cover(dict(RESOURCE, canonical_url="https://www.bilibili.com/video/av999"), cover_metadata()) is None


@pytest.mark.asyncio
async def test_cover_only_real_native_html_parser_requests_page_but_never_image_or_media():
    urls, covers = [], []
    body = ('<html><script>window.__INITIAL_STATE__=' + json.dumps({"videoData": {
        "bvid": "BV1VZ4y1G7YB", "title": "Python 游戏课程", "pic": "http://i0.hdslb.com/real-cover.jpg", "pages": []}})
        + ';</script><a href="/zh-Hans/video/BV1VZ4y1G7YB/">完整目录</a></html>').encode()

    class Transport:
        async def request(self, url, _addresses, _max_bytes):
            urls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            return HTTPResult(200, {"content-type": "text/html"}, body, url)

    async def resolver(_url, _timeout):
        return ["93.184.216.34"]

    enrich = service(cover_only=True, on_cover=lambda *args: covers.append(args), max_http_requests=2,
                     publish=lambda *_: pytest.fail("Cover-only fetch cannot publish a chapter"))
    enrich._fetcher = Fetcher(FetcherConfig(bilibili_public_metadata=True, min_interval_seconds=0),
                              resolver=resolver, http_client=Transport())
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.finish_admission()
        await enrich.run_background_match(collect_seconds=0)
        assert urls == ["https://www.bilibili.com/robots.txt", URL + "/"]
        assert covers[0][1]["thumbnail_url"] == "https://i0.hdslb.com/real-cover.jpg"
        assert covers[0][1]["source"] == "html.bilibili.__INITIAL_STATE__.videoData.pic"
        assert enrich.diagnostics["http_requests"] == 2 and enrich.diagnostics["semantic_calls"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_budget", [2, 3])
async def test_cover_only_empty_ssr_uses_same_video_locale_only_with_remaining_http_budget(http_budget):
    urls, covers = [], []
    shell = (Path(__file__).parent / "fixtures/bilibili-empty-ssr-minimal.html").read_bytes()
    video_url = URL + "/?p=7"
    locale_url = video_url.replace("/video/", "/zh-Hans/video/")
    body = ('<html><script>window.__INITIAL_STATE__=' + json.dumps({"videoData": {
        "bvid": "BV1VZ4y1G7YB", "title": "Python 游戏课程", "pic": "http://i0.hdslb.com/locale-cover.jpg",
        "pages": [{"page": 7, "part": "碰撞检测", "duration": 180}]}}) + ';</script></html>').encode()

    class Transport:
        async def request(self, url, _addresses, _max_bytes):
            urls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            assert url in {video_url, locale_url}
            return HTTPResult(200, {"content-type": "text/html"}, shell if url == video_url else body, url)

    async def resolver(_url, _timeout):
        return ["93.184.216.34"]

    async def forbidden_match(*_args):
        pytest.fail("Cover fallback cannot call the chapter model")

    enrich = service(cover_only=True, on_cover=lambda *args: covers.append(args), max_http_requests=http_budget,
                     match=forbidden_match, publish=lambda *_: pytest.fail("Cover fallback cannot publish chapters"))
    enrich._fetcher = Fetcher(FetcherConfig(bilibili_public_metadata=True, min_interval_seconds=0),
                              resolver=resolver, http_client=Transport())
    try:
        enrich.enqueue(dict(RESOURCE, url=URL + "?p=7"), ["collision"])
        enrich.finish_admission()
        await enrich.run_background_match(collect_seconds=0)
        expected = ["https://www.bilibili.com/robots.txt", video_url, locale_url]
        assert urls == expected[:http_budget]
        assert enrich.diagnostics["http_requests"] == http_budget
        assert enrich.diagnostics["fetch_attempts"] == 1 and enrich.diagnostics["semantic_calls"] == 0
        if http_budget == 3:
            assert covers[0][1]["thumbnail_url"] == "https://i0.hdslb.com/locale-cover.jpg"
            # The extractor records its canonical same-BV source identity;
            # request diagnostics retain the actual locale acquisition route.
            assert covers[0][1]["source_url"] == video_url
            assert covers[0][1]["source"] == "html.bilibili.__INITIAL_STATE__.videoData.pic"
            assert enrich.diagnostics["resources"][0]["status"] == "cover_received"
            assert enrich.diagnostics["resources"][0]["request_route"] == "bilibili_locale"
        else:
            assert not covers
            assert enrich.diagnostics["resources"][0]["catalog_status"] == "budget_limited"
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_cover_only_mooc_still_disables_separate_catalog_followups():
    class FetcherProbe:
        async def enrich(self, resource, *, catalog_budget_hook):
            assert catalog_budget_hook is None
            return {"url": resource["url"], "fetch_status": "fetched", "chapters": []}

    enrich = service(cover_only=True)
    enrich._fetcher = FetcherProbe()
    try:
        enrich.enqueue(dict(RESOURCE, url="https://www.icourse163.org/course/BIT-1001873001"), ["collision"])
        enrich.finish_admission()
        await enrich.run_background_match(collect_seconds=0)
        assert enrich.diagnostics["fetch_attempts"] == 1
        assert enrich.diagnostics["errors"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chapter", "cover_only", "cached_cover_refresh"])
async def test_only_dedicated_cover_work_has_room_for_two_existing_page_read_windows(mode):
    urls, covers = [], []
    shell = (Path(__file__).parent / "fixtures/bilibili-empty-ssr-minimal.html").read_bytes()
    video_url, locale_url = URL + "/", URL.replace("/video/", "/zh-Hans/video/") + "/"
    body = ('<html><script>window.__INITIAL_STATE__=' + json.dumps({"videoData": {
        "bvid": "BV1VZ4y1G7YB", "title": "Python 游戏课程", "pic": "https://i0.hdslb.com/cover.jpg",
        "pages": []}}) + ';</script></html>').encode()

    class Transport:
        async def request(self, url, _addresses, _max_bytes):
            urls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            await asyncio.sleep(.04)
            return HTTPResult(200, {"content-type": "text/html"}, shell if url == video_url else body, url)

    async def resolver(_url, _timeout):
        return ["93.184.216.34"]

    enrich = service(cover_only=mode == "cover_only", per_resource_timeout=.06,
                     load_cached_catalog=(lambda _: metadata()) if mode == "cached_cover_refresh" else None,
                     on_cover=lambda *args: covers.append(args))
    assert enrich._fetcher.config.timeout_seconds == .06
    enrich._fetcher = Fetcher(FetcherConfig(bilibili_public_metadata=True, min_interval_seconds=0, timeout_seconds=.06),
                              resolver=resolver, http_client=Transport())
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        if mode == "cached_cover_refresh":
            await enrich.drain(.1)
            enrich.expand_background(max_resources=12, max_http_requests=18, max_semantic_batches=3,
                                     deadline=time.monotonic() + 1)
            assert enrich.enqueue_cover(RESOURCE, ["collision"])
        enrich.finish_admission()
        await asyncio.wait_for(enrich.run_background_match(), .5)
        detail = enrich.diagnostics["resources"][0]
        assert urls == ["https://www.bilibili.com/robots.txt", video_url, locale_url]
        assert enrich._fetcher.config.timeout_seconds == .06
        assert enrich.diagnostics["http_requests"] == 3
        assert detail["course_timeout_seconds"] == (.06 if mode == "chapter" else .12)
        if mode == "chapter":
            assert detail["status"] == "timeout" and not covers
        else:
            assert detail["status"] == "cover_received" and len(covers) == 1
        if mode == "cached_cover_refresh":
            assert len(enrich._records[catalog_identity(URL)]["chapters"]) == 3
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_extended_cover_window_still_obeys_owner_deadline_and_cleans_up():
    async def fetch(_resource):
        await asyncio.sleep(100)

    enrich = service(cover_only=True, fetch_catalog=fetch, per_resource_timeout=.5,
                     deadline=time.monotonic() + .04)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.finish_admission()
        await asyncio.wait_for(enrich.run_background_match(), .2)
        assert enrich.diagnostics["resources"][0]["course_timeout_seconds"] <= .04
        assert enrich.diagnostics["cancelled"] + enrich.diagnostics["timeouts"] == 1
        assert all(task.done() for task in enrich._tasks)
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_cover_course_window_cannot_exceed_24_seconds_or_raise_http_timeout():
    async def fetch(_resource):
        return cover_metadata()

    enrich = service(cover_only=True, per_resource_timeout=999)
    assert enrich._fetcher.config.timeout_seconds == Settings().fetch_timeout_seconds
    enrich.fetch_catalog = fetch
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.finish_admission()
        await enrich.run_background_match()
        assert enrich.diagnostics["resources"][0]["course_timeout_seconds"] == 24
        assert enrich._fetcher.config.timeout_seconds == Settings().fetch_timeout_seconds
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_cover_only_uses_cover_cache_and_never_publishes_or_matches_chapters():
    covers = []

    async def forbidden(*_args):
        pytest.fail("Cached cover mode must not fetch or call the model")

    enrich = service(cover_only=True, fetch_catalog=forbidden, match=forbidden,
                     load_cached_catalog=lambda _: cover_metadata(), on_cover=lambda *args: covers.append(args),
                     publish=lambda *_: pytest.fail("Cover mode must preserve existing chapter annotations"),
                     max_resources=0, max_http_requests=0)
    try:
        assert enrich.enqueue(RESOURCE, ["collision"])
        enrich.enqueue(dict(RESOURCE, resource_id="alias", url=URL + "?p=5"), ["event"])
        enrich.finish_admission()
        await enrich.run_background_match(collect_seconds=0)
        assert {row[0] for row in covers} == {"video", "alias"}
        assert enrich.diagnostics["covers_received"] == 1
        assert enrich.diagnostics["cover_updates"] == 2
        assert enrich.diagnostics["fetch_attempts"] == enrich.diagnostics["semantic_calls"] == 0
        assert enrich.diagnostics["catalogs_received"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_cover_only_ignores_old_directory_cache_without_cover_and_saves_native_cover():
    calls, covers, saved = [], [], []

    async def fetch(resource):
        calls.append(resource["resource_id"])
        return cover_metadata()

    enrich = service(cover_only=True, fetch_catalog=fetch, load_cached_catalog=lambda _: metadata(),
                     on_cover=lambda *args: covers.append(args), save_catalog=lambda *args: saved.append(args),
                     publish=lambda *_: pytest.fail("Cover mode cannot alter chapters"))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.finish_admission()
        await enrich.run_background_match(collect_seconds=0)
        assert calls == ["video"] and len(covers) == len(saved) == 1
        assert enrich.diagnostics["network_scheduled_resources"] == enrich.diagnostics["fetch_attempts"] == 1
        assert enrich.diagnostics["semantic_calls"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_already_loaded", [False, True])
async def test_background_cover_refreshes_a_directory_cache_once_and_preserves_chapters(cache_already_loaded):
    calls, covers, published = [], [], []

    async def fetch(resource):
        calls.append(resource["resource_id"])
        return {**cover_metadata(), "chapters": []}

    enrich = service(fetch_catalog=fetch, load_cached_catalog=lambda _: metadata(),
                     on_cover=lambda *args: covers.append(args), publish=lambda *args: published.append(args))
    try:
        assert enrich.enqueue(RESOURCE, ["collision"])
        assert not enrich.enqueue_cover(RESOURCE, ["collision"])
        if cache_already_loaded:
            await enrich.drain(.1)
            assert published and not calls
        enrich.expand_background(max_resources=12, max_http_requests=18, max_semantic_batches=3,
                                 deadline=time.monotonic() + 1)
        assert enrich.enqueue_cover(RESOURCE, ["collision"])
        assert enrich.enqueue_cover(RESOURCE, ["collision"])
        enrich.finish_admission()
        await enrich.run_background_match(collect_seconds=0)
        assert calls == ["video"] and len(covers) == 1
        assert published and len(published[0][2]) == 2
        record = enrich._records[catalog_identity(URL)]
        assert len(record["chapters"]) == 3
        assert enrich.diagnostics["cover_refreshes"] == 1
        assert enrich.diagnostics["network_scheduled_resources"] == enrich.diagnostics["fetch_attempts"] == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("resources,http", [(0, 18), (12, 0)])
async def test_old_catalog_cover_refresh_obeys_existing_resource_and_http_budgets(resources, http):
    async def fetch(*_args):
        pytest.fail("Cover refresh cannot exceed the owner allowance")

    enrich = service(fetch_catalog=fetch, load_cached_catalog=lambda _: metadata(),
                     max_resources=resources, max_http_requests=http)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        enrich.expand_background(max_resources=resources, max_http_requests=http, max_semantic_batches=3,
                                 deadline=time.monotonic() + 1)
        assert not enrich.enqueue_cover(RESOURCE, ["collision"])
        assert enrich.diagnostics["fetch_attempts"] == 0
        assert enrich.diagnostics["network_scheduled_resources"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_normal_native_catalog_fetch_publishes_cover_without_additional_fetch():
    calls, covers, chapters = [], [], []

    async def fetch(resource):
        calls.append(resource["resource_id"])
        return cover_metadata()

    enrich = service(fetch_catalog=fetch, on_cover=lambda *args: covers.append(args), publish=lambda *args: chapters.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert calls == ["video"] and covers and chapters
        assert enrich.diagnostics["cover_refreshes"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["timeout", "access_denied", "not_found", "fetched"])
async def test_cover_refresh_retries_only_a_transient_native_failure(status, monkeypatch):
    calls = []

    async def fetch(resource):
        calls.append(resource["resource_id"])
        return {"url": resource["url"], "fetch_status": status, "chapters": []}

    enrich = service(fetch_catalog=fetch, background_mode=True)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        if status == "timeout":
            monkeypatch.setattr(chapter_module, "COVER_TRANSIENT_RETRY_BACKOFF_SECONDS", .01)
            assert enrich.enqueue_cover(RESOURCE, ["collision"])
            enrich.finish_admission()
            await enrich.run_background_match(collect_seconds=0)
            assert calls == ["video", "video"]
            assert enrich.diagnostics["cover_retry_attempts"] == enrich.diagnostics["cover_retry_exhausted"] == 1
        else:
            assert not enrich.enqueue_cover(RESOURCE, ["collision"])
            assert calls == ["video"]
        assert enrich.diagnostics["cover_refreshes"] == 0
    finally:
        await enrich.close()


def service(**kwargs):
    return HelpfulVideoChapterEnricher(Settings(), POINTS, **kwargs)


def test_background_expansion_preserves_used_budgets_and_obeys_hard_limits():
    enrich = service(fetch_catalog=lambda _: None)
    assert enrich.background_mode is False
    assert (enrich.max_resources, enrich.max_http_requests, enrich.max_semantic_batches) == (12, 18, 3)
    enrich.diagnostics.update(network_scheduled_resources=12, http_requests=18, semantic_calls=3)
    enrich.expand_background(max_resources=999, max_http_requests=999, max_semantic_batches=999,
                             deadline=time.monotonic() + 5000)
    assert enrich.background_mode is enrich.diagnostics["background_mode"] is True
    assert (enrich.max_resources, enrich.max_http_requests, enrich.max_semantic_batches) == (96, 384, 32)
    assert (enrich.diagnostics["network_scheduled_resources"], enrich.diagnostics["http_requests"],
            enrich.diagnostics["semantic_calls"]) == (12, 18, 3)
    assert 899 < enrich.deadline - time.monotonic() <= 900
    enrich.finish_admission(deadline=time.monotonic() + 5000)
    assert 899 < enrich.deadline - time.monotonic() <= 900
    constructed = service(fetch_catalog=lambda _: None, max_resources=999, max_http_requests=999,
                          max_semantic_batches=999, deadline=time.monotonic() + 5000)
    assert (constructed.max_resources, constructed.max_http_requests, constructed.max_semantic_batches) == (96, 384, 32)
    assert 899 < constructed.deadline - time.monotonic() <= 900
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            service(fetch_catalog=lambda _: None, deadline=value)


@pytest.mark.asyncio
async def test_background_batches_52_delayed_single_chapter_courses_within_remaining_calls(monkeypatch):
    # Scale the 5/20s collection windows while preserving separately arriving,
    # serialized native catalogs and three calls already spent by recommendations.
    monkeypatch.setattr(chapter_module, "BACKGROUND_CATALOG_COLLECT_SECONDS", .01)
    monkeypatch.setattr(chapter_module, "BACKGROUND_CATALOG_MAX_COLLECT_SECONDS", .04)
    payloads, published = [], []

    async def fetch(resource):
        await asyncio.sleep(.004)
        raw = metadata(("Bounding box intersection",))
        raw["url"] = resource["url"]
        for chapter in raw["chapters"]:
            chapter.update(source_url=resource["url"], url=resource["url"] + "/?p=3")
        return raw

    async def match(_prompt, payload, _timeout):
        payloads.append(payload)
        await asyncio.sleep(.001)
        return {"matches": [{"resource_id": row["resource_id"], "point_id": "collision",
                             "chapter_ids": [row["chapters"][0]["chapter_id"]]}
                            for row in payload["resources"]]}

    enrich = service(fetch_catalog=fetch, match=match, background_mode=True,
                     max_resources=96, max_semantic_batches=24, deadline=time.monotonic() + 2,
                     publish=lambda *args: published.append(args))
    enrich.diagnostics["semantic_calls"] = 3
    try:
        for number in range(52):
            assert enrich.enqueue(dict(RESOURCE, resource_id=f"video-{number}",
                                       url=f"https://www.bilibili.com/video/av{number + 1}"), ["collision"])
        enrich.finish_admission()
        await asyncio.wait_for(enrich.run_background_match(collect_seconds=0, timeout_seconds=.05), 1.5)
        ids = [row["resource_id"] for payload in payloads for row in payload["resources"]]
        assert len(ids) == len(set(ids)) == len(published) == 52
        assert "video-51" in ids and len(payloads) <= 21
        assert enrich.diagnostics["semantic_calls"] <= 24
        assert enrich.diagnostics["semantic_unprocessed_pairs"] == 0
        assert not enrich.diagnostics["semantic_budget_reached"]
        assert any(len(payload["resources"]) >= 3 for payload in payloads)
        assert any(batch["collection"]["seconds"] > 0 for batch in enrich.diagnostics["semantic_batches"])
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_background_short_deadline_leaves_time_to_match_ready_catalog():
    matched_at = []
    deadline = time.monotonic() + .09

    async def fetch(resource):
        if resource["resource_id"] == "slow":
            await asyncio.sleep(100)
        return metadata(("Bounding box intersection",))

    async def match(*_args):
        matched_at.append(time.monotonic())
        return {"matches": []}

    enrich = service(fetch_catalog=fetch, match=match, background_mode=True, deadline=deadline)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.enqueue(dict(RESOURCE, resource_id="slow", url="https://www.bilibili.com/video/av999"), ["collision"])
        enrich.finish_admission()
        await asyncio.wait_for(enrich.run_background_match(), .3)
        assert len(matched_at) == 1 and matched_at[0] < deadline - .02
        assert enrich.diagnostics["semantic_processed_pairs"] == 1
        assert enrich.diagnostics["deadline_reached"]
        assert all(task.done() for task in enrich._tasks)
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("chapter_count,slow_fetch,reason", [(1, False, "loads_finished"), (240, True, "payload_full")])
async def test_background_flushes_complete_or_full_payload_without_collection_delay(chapter_count, slow_fetch, reason):
    matching = asyncio.Event()

    async def fetch(resource):
        if resource["resource_id"] == "slow":
            await asyncio.sleep(100)
        return metadata(tuple(f"Bounding box intersection {number}" for number in range(chapter_count)))

    async def match(*_args):
        matching.set()
        return {"matches": []}

    enrich = service(fetch_catalog=fetch, match=match, background_mode=True)
    background = None
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        if slow_fetch:
            enrich.enqueue(dict(RESOURCE, resource_id="slow", url="https://www.bilibili.com/video/av999"), ["collision"])
        enrich.finish_admission()
        background = asyncio.create_task(enrich.run_background_match())
        await asyncio.wait_for(matching.wait(), .15)
        await asyncio.sleep(0)
        assert enrich.diagnostics["semantic_batches"][0]["collection"]["reason"] == reason
        assert enrich.diagnostics["semantic_batches"][0]["collection"]["seconds"] < .05
    finally:
        if background:
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)
        await enrich.close()


@pytest.mark.asyncio
async def test_recommendation_collection_keeps_caller_window_before_background_expansion():
    matched = asyncio.Event()
    observed_at, matched_at = [], []

    async def fetch(resource):
        if resource["resource_id"] == "slow":
            await asyncio.sleep(100)
        observed_at.append(time.monotonic())
        return metadata(("Bounding box intersection",))

    async def match(*_args):
        matched_at.append(time.monotonic())
        matched.set()
        return {"matches": []}

    enrich = service(fetch_catalog=fetch, match=match)
    enrich.enqueue(RESOURCE, ["collision"])
    enrich.enqueue(dict(RESOURCE, resource_id="slow", url="https://www.bilibili.com/video/av999"), ["collision"])
    background = asyncio.create_task(enrich.run_background_match(collect_seconds=.025))
    try:
        await asyncio.wait_for(matched.wait(), .15)
        assert .02 <= matched_at[0] - observed_at[0] < .12
        assert not enrich.background_mode
        assert "collection" not in enrich.diagnostics["semantic_batches"][0]
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        await enrich.close()


@pytest.mark.asyncio
async def test_close_interrupts_background_collection_without_spending_a_call():
    ready = asyncio.Event()

    async def fetch(resource):
        if resource["resource_id"] == "slow":
            await asyncio.sleep(100)
        ready.set()
        return metadata(("Bounding box intersection",))

    async def match(*_args):
        pytest.fail("Closing during collection must not invoke matching")

    enrich = service(fetch_catalog=fetch, match=match, background_mode=True)
    enrich.enqueue(RESOURCE, ["collision"])
    enrich.enqueue(dict(RESOURCE, resource_id="slow", url="https://www.bilibili.com/video/av999"), ["collision"])
    background = asyncio.create_task(enrich.run_background_match())
    try:
        await asyncio.wait_for(ready.wait(), .1)
        await asyncio.sleep(.01)
        await enrich.close()
        await asyncio.wait_for(background, .1)
        assert enrich.diagnostics["semantic_calls"] == 0
        assert all(task.done() for task in enrich._tasks)
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        await enrich.close()


@pytest.mark.asyncio
async def test_long_cached_catalog_finishes_remaining_chunks_after_expansion_without_repeats():
    payloads = []
    raw = metadata(tuple(f"Collision subtopic {number}" for number in range(1000)))

    async def fetch(_resource):
        pytest.fail("Cached native catalog must not use network quota")

    async def match(_prompt, payload, _timeout):
        payloads.append(payload)
        return {"matches": []}

    enrich = service(fetch_catalog=fetch, load_cached_catalog=lambda _: raw, match=match,
                     max_resources=0, max_http_requests=0)
    try:
        assert enrich.enqueue_cached(RESOURCE, ["collision", "event"])
        for _ in range(3):
            # Parsing 1,000 cached rows is real CPU work; this test verifies
            # chunk admission, not a 100 ms machine-performance threshold.
            await enrich.drain(.5)
        assert enrich.diagnostics["semantic_calls"] == 3
        assert enrich.diagnostics["semantic_chapters_omitted"] == 280
        assert enrich.diagnostics["semantic_unprocessed_pairs"] == 560
        assert enrich.diagnostics["semantic_budget_reached"]
        enrich.expand_background(max_resources=0, max_http_requests=0, max_semantic_batches=24,
                                 deadline=time.monotonic() + 1)
        assert not enrich.diagnostics["semantic_budget_reached"]
        enrich.finish_admission()
        await asyncio.wait_for(enrich.run_background_match(collect_seconds=0), .5)
        ids = [chapter["chapter_id"] for payload in payloads for row in payload["resources"] for chapter in row["chapters"]]
        assert len(ids) == len(set(ids)) == 1000
        assert [sum(len(row["chapters"]) for row in payload["resources"]) for payload in payloads] == [240, 240, 240, 240, 40]
        assert enrich.diagnostics["semantic_processed_pairs"] == 2000
        assert enrich.diagnostics["semantic_unprocessed_pairs"] == enrich.diagnostics["semantic_chapters_omitted"] == 0
        assert enrich.diagnostics["http_requests"] == enrich.diagnostics["fetch_attempts"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "invalid_response", "timeout"])
async def test_failed_semantic_pairs_are_attempted_at_most_twice_and_remain_visible_in_diagnostics(failure):
    calls = []

    async def fetch(_resource):
        return metadata(("Bounding box intersection",))

    async def match(_prompt, payload, _timeout):
        calls.append(payload)
        if failure == "exception":
            raise RuntimeError("offline model failure")
        if failure == "timeout":
            await asyncio.Event().wait()
        return {"matches": "invalid"}

    enrich = service(fetch_catalog=fetch, match=match, max_semantic_batches=24)
    try:
        enrich.enqueue(RESOURCE, ["collision", "event"])
        enrich.finish_admission(deadline=time.monotonic() + 1)
        await asyncio.wait_for(enrich.run_background_match(collect_seconds=0, timeout_seconds=.01), .5)
        assert len(calls) == 2 and calls[0] == calls[1]
        assert enrich.diagnostics["semantic_processed_pairs"] == 0
        assert enrich.diagnostics["semantic_unprocessed_pairs"] == enrich.diagnostics["semantic_retry_exhausted_pairs"] == 2
        assert enrich.diagnostics["semantic_unprocessed_chapters"] == enrich.diagnostics["semantic_chapters_omitted"] == 1
        assert enrich.diagnostics["semantic_pending_pairs"] == 0
        assert not enrich.diagnostics["semantic_budget_reached"]
        await enrich.drain(.01)
        assert len(calls) == 2
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_failed_semantic_batch_can_recover_once_then_success_is_not_repeated():
    calls, published = [], []

    async def fetch(_resource):
        return metadata(("Bounding box intersection",))

    async def match(_prompt, payload, _timeout):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("temporary offline failure")
        row = payload["resources"][0]
        return {"matches": [{"resource_id": row["resource_id"], "point_id": "collision",
                             "chapter_ids": [row["chapters"][0]["chapter_id"]]}]}

    enrich = service(fetch_catalog=fetch, match=match, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.finish_admission(deadline=time.monotonic() + 1)
        await asyncio.wait_for(enrich.run_background_match(collect_seconds=0), .5)
        assert len(calls) == 2 and len(published) == 1
        assert enrich.diagnostics["semantic_unprocessed_pairs"] == 0
        assert enrich.diagnostics["semantic_processed_pairs"] == 1
        assert [row["status"] for row in enrich.diagnostics["semantic_batches"]] == ["failed", "completed"]
        await enrich.drain(.01)
        assert len(calls) == 2
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_expansion_clears_current_skipped_count_only_when_owner_enqueues_that_course():
    calls = []

    async def fetch(resource):
        calls.append(resource)
        return metadata()

    enrich = service(fetch_catalog=fetch, max_resources=0)
    try:
        assert not enrich.enqueue(RESOURCE, ["collision"])
        assert enrich.diagnostics["budget_skipped"] == enrich.diagnostics["budget_skipped_total"] == 1
        enrich.expand_background(max_resources=1, max_http_requests=18, max_semantic_batches=3,
                                 deadline=time.monotonic() + 1)
        await asyncio.sleep(0)
        assert calls == [] and enrich.diagnostics["budget_skipped"] == 1
        assert enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert len(calls) == 1 and enrich.diagnostics["budget_skipped"] == 0
        assert enrich.diagnostics["budget_skipped_total"] == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_owner_reenqueue_resumes_only_budget_stopped_native_fetch_with_used_http_preserved():
    calls = []
    body = ('<html><script>window.__INITIAL_STATE__=' + json.dumps({"videoData": {
        "bvid": "BV1VZ4y1G7YB", "title": "Python 游戏课程", "pages": [{"page": 3, "part": "碰撞检测", "duration": 1}]}})
        + ';</script></html>').encode()

    class Transport:
        async def request(self, url, _addresses, _max_bytes):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            return HTTPResult(200, {"content-type": "text/html"}, body, url)

    async def resolver(_url, _timeout):
        return ["93.184.216.34"]

    enrich = service(max_http_requests=1)
    enrich._fetcher = Fetcher(FetcherConfig(bilibili_public_metadata=True, min_interval_seconds=0),
                              resolver=resolver, http_client=Transport())
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert enrich.diagnostics["http_requests"] == 1
        assert enrich.diagnostics["resources"][0]["status"] == "budget_limited"
        enrich.expand_background(max_resources=12, max_http_requests=4, max_semantic_batches=3,
                                 deadline=time.monotonic() + 1)
        await asyncio.sleep(0)
        assert len(calls) == 1
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert len(calls) == enrich.diagnostics["http_requests"] == 2
        assert enrich.diagnostics["catalogs_received"] == enrich.diagnostics["budget_resumptions"] == 1
        assert enrich.diagnostics["network_scheduled_resources"] == 1
        assert enrich.diagnostics["fetch_attempts"] == 2
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["fetched", "timeout", "access_denied", "captcha", "policy_unreviewed", "not_found"])
async def test_expansion_and_reenqueue_never_retry_a_nonbudget_native_outcome(status):
    calls = []

    async def fetch(resource):
        calls.append(resource)
        return {"url": resource["url"], "fetch_status": status, "chapters": []}

    enrich = service(fetch_catalog=fetch)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        enrich.expand_background(max_resources=96, max_http_requests=288, max_semantic_batches=24,
                                 deadline=time.monotonic() + 1)
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert len(calls) == 1 and enrich.diagnostics["budget_resumptions"] == 0
    finally:
        await enrich.close()


def test_native_parts_keep_observed_number_title_link_and_provenance():
    raw = metadata()
    chapters = observed_chapters(RESOURCE, raw)
    assert [c["index"] for c in chapters] == [3, 4, 5]
    assert chapters[0]["title"] == "第3节 碰撞检测"
    assert chapters[0]["url"] == URL + "/?p=3"
    assert chapters[0]["observed_at"] == raw["fetched_at"]
    assert chapters[0]["provenance"]["evidence_id"] == "e-3"
    assert observed_chapters(RESOURCE, raw) == chapters


@pytest.mark.parametrize("change", [
    {"source": "search"}, {"source": "ai"}, {"source": "html.visible_course_outline"},
    {"source": "html.icourse163.course_outline.text"},
    {"source_url": "https://www.bilibili.com/video/BV1eu4y1y7pb"},
    {"url": "https://www.bilibili.com/video/BV1eu4y1y7pb/?p=3"},
    {"url": "javascript:alert(1)"}, {"source_url": None}, {"title": ""},
])
def test_unbound_or_non_native_catalog_never_becomes_a_chapter(change):
    raw = metadata(("碰撞检测",))
    raw["chapters"][0].update(change)
    assert observed_chapters(RESOURCE, raw) == []


@pytest.mark.parametrize("change", [
    {"requires_payment": True}, {"catalog_fetch_status": "catalog_limit_exceeded"},
    {"fetch_status": "captcha"}, {"url": "https://www.bilibili.com/video/BV1eu4y1y7pb"},
])
def test_failed_paid_or_redirected_resource_does_not_supply_chapters(change):
    raw = metadata()
    raw.update(change)
    assert observed_chapters(RESOURCE, raw) == []


def test_mooc_text_catalog_keeps_unknown_chapter_url_empty():
    url = "https://www.icourse163.org/course/TEST-100001"
    row = {"title": "第四章 栈与队列", "source": "html.icourse163.course_outline.text", "source_url": url}
    found = observed_chapters({"url": url}, {"url": url, "chapters": [row]})
    assert found[0]["url"] is None
    assert found[0]["index"] == 1
    assert found[0]["title"] == row["title"]


def test_catalog_identity_deduplicates_parts_but_not_different_courses_or_terms():
    assert catalog_identity(URL) == catalog_identity(URL + "/?p=7")
    assert catalog_identity(URL) == catalog_identity(URL.replace("/video/", "/zh-Hans/video/"))
    assert catalog_identity(URL) != catalog_identity("https://www.bilibili.com/video/BV1eu4y1y7pb")
    assert catalog_identity("https://www.icourse163.org/course/TEST-100001?tid=3") != catalog_identity("https://www.icourse163.org/course/TEST-100001?tid=4")
    assert catalog_identity("http://127.0.0.1/video/BV1VZ4y1G7YB") is None


@pytest.mark.parametrize("title", [
    "模块 1 ：游戏编程的基本概念和 Pygame 库基础知识", "第1章 Python 编程基础",
    "Chapter 1: Introduction to Python Programming", "模块2：课程概述", "游戏开发入门",
    "Getting started with Pygame",
])
def test_generic_chapter_headings_cannot_establish_specific_concepts(title):
    assert not specific_chapter_title(title, ["Python", "Pygame"])


@pytest.mark.parametrize("title", [
    "模块2：游戏场景构建和事件处理机制", "模块4：用精灵实现动画、精灵冲突机制",
    "第3章 Python 变量与赋值", "Chapter 2: Python functions", "第5章 二叉树基础", "第6章 栈",
])
def test_specific_concepts_survive_generic_heading_filter(title):
    assert specific_chapter_title(title, ["Python", "Pygame"])


@pytest.mark.asyncio
async def test_semantic_match_cannot_promote_generic_native_chapter_even_with_valid_id():
    titles = ("模块 1 ：游戏编程的基本概念和 Pygame 库基础知识", "模块2：游戏场景构建和事件处理机制")
    raw = metadata(titles)
    generic_id = observed_chapters(RESOURCE, raw)[0]["chapter_id"]
    published = []

    async def fetch(_resource):
        return raw

    async def match(_prompt, payload, _timeout):
        supplied = payload["resources"][0]["chapters"]
        assert [chapter["title"] for chapter in supplied] == [titles[1]]
        return {"matches": [
            {"resource_id": "video", "point_id": "variable", "chapter_ids": [generic_id]},
            {"resource_id": "video", "point_id": "event", "chapter_ids": [supplied[0]["chapter_id"]]},
        ]}

    enrich = HelpfulVideoChapterEnricher(Settings(), [
        {"id": "variable", "name": "变量与赋值", "technology": "Python"},
        {"id": "event", "name": "事件循环", "technology": "Pygame"},
    ], fetch_catalog=fetch, match=match, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["variable", "event"])
        await enrich.drain()
        assert [row[1] for row in published] == ["event"]
        assert enrich.diagnostics["generic_chapters_excluded"] == 1
        assert enrich.diagnostics["catalogs_received"] == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_enqueue_returns_immediately_and_publishes_distinct_chapters_per_point():
    gate, calls, published = asyncio.Event(), [], []

    async def fetch(resource):
        calls.append(resource)
        await gate.wait()
        return metadata()

    enrich = service(fetch_catalog=fetch, publish=lambda *args: published.append(args))
    try:
        assert enrich.enqueue(RESOURCE, ["collision", "event"])
        assert calls == [] and published == []
        await asyncio.sleep(0)
        gate.set()
        await enrich.drain()
        by_point = {p: chapters for _, p, chapters in published}
        assert [c["index"] for c in by_point["collision"]] == [3, 5]
        assert [c["index"] for c in by_point["event"]] == [4, 5]
        assert by_point["collision"][1]["chapter_id"] == by_point["event"][1]["chapter_id"]
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_one_fetch_for_multiple_selected_parts_and_late_subscriber():
    calls, published = [], []

    async def fetch(resource):
        calls.append(resource)
        return metadata()

    enrich = service(fetch_catalog=fetch, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.enqueue(dict(RESOURCE, resource_id="part", url=URL + "?p=5"), ["event"])
        await enrich.drain()
        enrich.enqueue(dict(RESOURCE, resource_id="late", url=URL + "/?p=3"), ["collision"])
        assert len(calls) == 1
        assert {row[0] for row in published} == {"video", "part", "late"}
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_semantic_matching_only_in_drain_and_only_supplied_ids_can_publish():
    events, published = [], []

    async def fetch(_resource):
        events.append("fetch")
        return metadata(("Bounding box intersection",))

    async def match(_prompt, payload, _timeout):
        events.append("match")
        chapter_id = payload["resources"][0]["chapters"][0]["chapter_id"]
        return {"matches": [
            {"resource_id": "video", "point_id": "collision", "chapter_ids": [chapter_id, "invented"]},
            {"resource_id": "video", "point_id": "invented", "chapter_ids": [chapter_id]},
            {"resource_id": "other-video", "point_id": "event", "chapter_ids": [chapter_id]},
            {"resource_id": [], "point_id": "event", "chapter_ids": [chapter_id]},
        ]}

    enrich = service(fetch_catalog=fetch, match=match, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision", "event"])
        await asyncio.sleep(0.01)
        assert events == ["fetch"] and not published
        await enrich.drain()
        await enrich.drain()
        assert events == ["fetch", "match"]
        assert len(published) == 1
        assert published[0][1] == "collision"
        assert published[0][2][0]["title"] == "Bounding box intersection"
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_semantic_payload_only_contains_current_batch_terms_without_project_descriptions():
    calls = []
    points = [
        {"id": "keyboard", "name": "按键状态查询", "technology": "pygame",
         "description": "通过方向键修改横坐标，使对象连续移动", "project_role": "移动挡板"},
        {"id": "coordinates", "name": "二维笛卡尔坐标系", "technology": "pygame",
         "description": "用来定位游戏对象", "selection": "learn"},
        {"id": "unsubscribed", "name": "碰撞检测", "technology": "pygame"},
    ]

    async def fetch(_resource):
        return metadata(("2.游戏中的坐标系", "Keyboard state polling"))

    async def match(_prompt, payload, _timeout):
        calls.append(payload)
        return {"matches": []}

    enrich = HelpfulVideoChapterEnricher(Settings(), points, fetch_catalog=fetch, match=match)
    try:
        enrich.enqueue(RESOURCE, ["keyboard"])
        await enrich.drain(.1)
        enrich.enqueue(RESOURCE, ["coordinates"])
        await enrich.drain(.1)
        assert [call["points"] for call in calls] == [
            [{"id": "keyboard", "name": "按键状态查询", "technology": "pygame"}],
            [{"id": "coordinates", "name": "二维笛卡尔坐标系", "technology": "pygame"}],
        ]
        assert [call["resources"][0]["point_ids"] for call in calls] == [["keyboard"], ["coordinates"]]
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_restricted_term_payload_still_allows_one_chapter_that_teaches_two_points():
    published = []

    async def fetch(_resource):
        return metadata(("Variables and functions",))

    async def match(_prompt, payload, _timeout):
        assert {point["id"] for point in payload["points"]} == {"variables", "functions"}
        row = payload["resources"][0]
        return {"matches": [{"resource_id": row["resource_id"], "point_id": point,
                             "chapter_ids": [row["chapters"][0]["chapter_id"]]}
                            for point in row["point_ids"]]}

    enrich = HelpfulVideoChapterEnricher(Settings(), [
        {"id": "variables", "name": "变量", "technology": "Python"},
        {"id": "functions", "name": "函数", "technology": "Python"},
    ], fetch_catalog=fetch, match=match, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["variables", "functions"])
        await enrich.drain(.1)
        assert {row[1] for row in published} == {"variables", "functions"}
        assert len({row[2][0]["chapter_id"] for row in published}) == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_optional_failures_and_timeout_do_not_publish_or_escape():
    published = []

    async def fetch(resource):
        if resource["resource_id"] == "bad":
            raise ValueError("synthetic unavailable catalog")
        await asyncio.sleep(10)

    enrich = service(fetch_catalog=fetch, per_resource_timeout=.02, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.enqueue(dict(RESOURCE, resource_id="bad", url="https://www.bilibili.com/video/BV1eu4y1y7pb"), ["collision"])
        await enrich.drain(.1)
        assert enrich.diagnostics["timeouts"] == 1
        assert enrich.diagnostics["errors"] == 1
        assert published == []
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_catalog_model_failure_is_silent_and_literal_results_remain():
    published = []

    async def fetch(_resource):
        return metadata()

    async def match(*_args):
        raise RuntimeError("catalog model unavailable")

    enrich = service(fetch_catalog=fetch, match=match, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision", "event"])
        await enrich.drain()
        assert len(published) == 2
        assert enrich.diagnostics["errors"] == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_limits_bound_fetches_concurrency_and_semantic_payload():
    active = peak = calls = 0
    payloads = []

    async def fetch(resource):
        nonlocal active, peak, calls
        active += 1
        calls += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        raw = metadata(tuple(f"Catalog entry {i}" for i in range(30)))
        raw["url"] = resource["url"]
        for chapter in raw["chapters"]:
            chapter["source_url"] = resource["url"]
            chapter["url"] = None
        return raw

    async def match(_prompt, payload, _timeout):
        payloads.append(payload)
        return {"matches": []}

    enrich = service(fetch_catalog=fetch, match=match, max_resources=3, concurrency=2, max_match_chapters=11)
    try:
        for number in range(8):
            host = "www.bilibili.com" if number % 2 == 0 else "bilibili.com"
            enrich.enqueue(dict(RESOURCE, resource_id=f"video-{number}", url=f"https://{host}/video/av{1000 + number}"), ["collision"])
        await enrich.drain()
        assert calls == 3 and peak == 2
        assert sum(len(r["chapters"]) for r in payloads[0]["resources"]) == 11
        assert enrich.diagnostics["semantic_chapters_omitted"] == 79
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_same_host_queue_wait_does_not_consume_each_course_timeout():
    async def fetch(resource):
        await asyncio.sleep(.04)
        raw = metadata()
        raw["url"] = resource["url"]
        for chapter in raw["chapters"]:
            chapter.update(source_url=resource["url"], url=None)
        return raw

    enrich = service(fetch_catalog=fetch, per_resource_timeout=.08)
    try:
        for number in range(3):
            enrich.enqueue(dict(RESOURCE, resource_id=str(number), url=f"https://www.bilibili.com/video/av{1000 + number}"), ["collision"])
        await enrich.drain(1)
        assert enrich.diagnostics["catalogs_received"] == 3
        assert enrich.diagnostics["timeouts"] == 0
        assert enrich.diagnostics["resources"][-1]["queue_seconds"] >= .06
        assert all(row["status"] == "catalog_received" for row in enrich.diagnostics["resources"])
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_slow_queued_catalog_does_not_consume_ready_catalog_semantic_budget():
    matches = []

    async def fetch(resource):
        if resource["resource_id"] == "slow":
            await asyncio.sleep(100)
        return metadata(("Bounding box intersection",))

    async def match(_prompt, payload, timeout):
        matches.append((payload, timeout))
        return {"matches": []}

    enrich = service(fetch_catalog=fetch, match=match)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.enqueue(dict(RESOURCE, resource_id="slow", url="https://www.bilibili.com/video/av999"), ["collision"])
        await asyncio.sleep(.01)
        await enrich.drain(.2)
        assert len(matches) == 1
        assert matches[0][1] >= .13
        assert matches[0][0]["resources"][0]["resource_id"] == "video"
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_catalog_dns_reuses_only_valid_positive_results_within_one_job():
    calls, hits = [], []

    async def resolve(url, timeout):
        calls.append(url)
        return ["93.184.216.34"]

    cached = _CatalogDNSCache(resolve, lambda: hits.append(True))
    assert await cached(URL, 8) == ["93.184.216.34"]
    assert await cached(URL + "/?p=2", 8) == ["93.184.216.34"]
    assert len(calls) == 1 and len(hits) == 1
    cached.entries["www.bilibili.com"] = (0, ["93.184.216.34"])
    await cached(URL, 8)
    assert len(calls) == 2
    new_job = _CatalogDNSCache(resolve, lambda: None)
    await new_job(URL, 8)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_catalog_dns_failure_is_not_cached_and_private_address_is_rejected():
    calls = []

    async def resolve(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("offline DNS failure")
        return ["127.0.0.1"]

    cached = _CatalogDNSCache(resolve, lambda: None)
    with pytest.raises(OSError):
        await cached(URL, 8)
    from backend.app.url_utils import UnsafeURL
    with pytest.raises(UnsafeURL):
        await cached(URL, 8)
    assert len(calls) == 2 and cached.entries == {}


@pytest.mark.asyncio
async def test_close_cancels_fetch_and_rejects_new_work():
    cancelled = asyncio.Event()

    async def fetch(_resource):
        try:
            await asyncio.sleep(100)
        finally:
            cancelled.set()

    enrich = service(fetch_catalog=fetch)
    enrich.enqueue(RESOURCE, ["collision"])
    await asyncio.sleep(.01)
    await enrich.close()
    assert cancelled.is_set()
    assert not enrich.enqueue(RESOURCE, ["event"])


@pytest.mark.asyncio
async def test_already_observed_native_catalog_does_not_trigger_a_refetch():
    async def fetch(_resource):
        pytest.fail("A retained same-video native catalog must not trigger HTTP")

    published = []
    enrich = service(fetch_catalog=fetch, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(dict(RESOURCE, **metadata()), ["collision"])
        await enrich.drain()
        assert published
        assert enrich.diagnostics["fetch_attempts"] == 0
        assert enrich.diagnostics["already_observed_catalogs"] == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_cache_lookup_bypasses_busy_host_and_network_slot_preserving_observation_time():
    entered, calls, published = asyncio.Event(), [], []
    cached_resource = dict(RESOURCE, resource_id="cached", url="https://www.bilibili.com/video/av222")
    cached = metadata(("碰撞检测",))
    cached["url"] = cached_resource["url"]
    cached["chapters"][0].update(source_url=cached_resource["url"], url=None)

    async def fetch(resource):
        calls.append(resource["resource_id"])
        entered.set()
        await asyncio.sleep(100)

    def lookup(resource):
        return cached if resource["resource_id"] == "cached" else None

    enrich = service(fetch_catalog=fetch, load_cached_catalog=lookup, concurrency=1,
                     max_http_requests=0, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await entered.wait()
        enrich.enqueue(cached_resource, ["collision"])
        await asyncio.sleep(.01)
        assert calls == ["video"]
        assert len(published) == 1 and published[0][0] == "cached"
        assert published[0][2][0]["observed_at"] == cached["fetched_at"]
        assert enrich.diagnostics["cache_hits"] == 1
        assert enrich.diagnostics["resources"][1]["queue_seconds"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_thirteenth_cached_course_is_allowed_after_twelve_network_reservations():
    published, lookups = [], []
    cached_resource = dict(RESOURCE, resource_id="cached-thirteenth", url="https://www.bilibili.com/video/av999999")
    cached = metadata(("碰撞检测",))
    cached["url"] = cached_resource["url"]
    cached["chapters"][0].update(source_url=cached_resource["url"], url=None)

    async def fetch(_resource):
        await asyncio.sleep(100)

    def lookup(resource):
        lookups.append(resource["url"])
        return cached if resource["resource_id"] == "cached-thirteenth" else None

    enrich = service(fetch_catalog=fetch, load_cached_catalog=lookup,
                     publish=lambda *args: published.append(args))
    try:
        for number in range(12):
            resource = dict(RESOURCE, resource_id=str(number), url=f"https://www.bilibili.com/video/av{1000+number}")
            assert not enrich.enqueue_cached(resource, ["collision"])
            assert enrich.enqueue(resource, ["collision"])
        assert enrich.diagnostics["network_scheduled_resources"] == 12
        assert enrich.enqueue_cached(cached_resource, ["collision"])
        await asyncio.sleep(.01)
        assert len(published) == 1 and published[0][0] == "cached-thirteenth"
        assert enrich.diagnostics["scheduled_resources"] == 13
        assert enrich.diagnostics["network_scheduled_resources"] == 12
        assert enrich.diagnostics["http_requests"] == 0
        assert len(lookups) == 13, "One local lookup per discovered course, including remembered misses"
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_foreign_cached_catalog_is_ignored_and_only_valid_network_catalog_saved():
    saved, calls = [], []
    foreign = metadata()
    foreign["url"] = "https://www.bilibili.com/video/av999"

    async def fetch(resource):
        calls.append(resource)
        return metadata()

    enrich = service(fetch_catalog=fetch, load_cached_catalog=lambda _resource: foreign,
                     save_catalog=lambda *args: saved.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain()
        assert len(calls) == len(saved) == 1
        assert saved[0][0]["url"] == URL
        assert saved[0][1]["chapters"][0]["source"] == SOURCE
        assert enrich.diagnostics["cache_hits"] == 0
        assert enrich.diagnostics["cache_saves"] == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_cache_callback_failures_do_not_drop_valid_chapter_recommendations():
    published = []

    def broken(*_args):
        raise ValueError("offline cache error")

    async def fetch(_resource):
        return metadata()

    enrich = service(fetch_catalog=fetch, load_cached_catalog=broken, save_catalog=broken,
                     publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain()
        assert published
        assert enrich.diagnostics["cache_errors"] == 2
        assert enrich.diagnostics["cache_saves"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("network_metadata", [{"url": URL, "chapters": []}, dict(metadata(), requires_payment=True)])
async def test_missing_or_paid_native_catalog_is_never_saved(network_metadata):
    saved = []

    async def fetch(_resource):
        return network_metadata

    enrich = service(fetch_catalog=fetch, save_catalog=lambda *args: saved.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain()
        assert saved == []
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_background_matches_ready_and_late_catalogs_without_waiting_for_slow_fetch():
    calls, published = [], []
    first_match, slow_release = asyncio.Event(), asyncio.Event()
    points = [{"id": "collision", "name": "碰撞检测", "technology": "Pygame"}]

    async def fetch(resource):
        if resource["resource_id"] == "slow":
            await slow_release.wait()
        titles = ("Getting started with Pygame",) if resource["resource_id"] == "generic" else ("Bounding box intersection",)
        raw = metadata(titles)
        raw["url"] = resource["url"]
        for row in raw["chapters"]:
            row.update(source_url=resource["url"], url=None)
        return raw

    async def match(_prompt, payload, _timeout):
        calls.append(payload)
        first_match.set()
        return {"matches": [{"resource_id": row["resource_id"], "point_id": "collision",
                             "chapter_ids": [row["chapters"][0]["chapter_id"]]}
                            for row in payload["resources"]]}

    enrich = HelpfulVideoChapterEnricher(Settings(), points, fetch_catalog=fetch, match=match,
                                       publish=lambda *args: published.append(args))
    background = asyncio.create_task(enrich.run_background_match(collect_seconds=.01))
    try:
        enrich.enqueue(dict(RESOURCE, resource_id="generic"), ["collision"])
        await asyncio.sleep(.02)
        assert calls == []
        enrich.enqueue(dict(RESOURCE, resource_id="specific", url="https://www.bilibili.com/video/av333"), ["collision"])
        enrich.enqueue(dict(RESOURCE, resource_id="slow", url="https://www.bilibili.com/video/av444"), ["collision"])
        await asyncio.wait_for(first_match.wait(), .2)
        assert len(calls) == 1
        assert [row["resource_id"] for row in calls[0]["resources"]] == ["specific"]
        assert not background.done()
        # Recommendation completion closes admission, not admitted catalog work.
        enrich.finish_admission(deadline=time.monotonic() + 1)
        assert not enrich.enqueue(dict(RESOURCE, resource_id="new", url="https://www.bilibili.com/video/av555"), ["collision"])
        slow_release.set()
        await asyncio.wait_for(background, .5)
        assert len(calls) == 2
        assert [row["resource_id"] for row in calls[1]["resources"]] == ["slow"]
        assert {row[0] for row in published} == {"specific", "slow"}
        assert enrich.diagnostics["cancelled"] == 0
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        await enrich.close()
    assert enrich.diagnostics["cancelled"] == 0


@pytest.mark.asyncio
async def test_background_batches_are_bounded_and_never_repeat_chapter_point_pairs():
    calls = []

    async def fetch(_resource):
        return metadata(tuple(f"Collision algorithm {number}" for number in range(4)))

    async def match(_prompt, payload, _timeout):
        calls.append(payload)
        return {"matches": []}

    enrich = service(fetch_catalog=fetch, match=match, max_match_chapters=1)
    try:
        enrich.enqueue(RESOURCE, ["collision", "event"])
        enrich.finish_admission(deadline=time.monotonic() + 1)
        await asyncio.wait_for(enrich.run_background_match(collect_seconds=0), .5)
        pairs = [(row["resource_id"], point, chapter["chapter_id"])
                 for payload in calls for row in payload["resources"]
                 for point in row["point_ids"] for chapter in row["chapters"]]
        assert len(calls) == 3
        assert len(pairs) == len(set(pairs)) == 6
        assert enrich.diagnostics["semantic_budget_reached"] is True
        assert enrich.diagnostics["semantic_chapters_omitted"] == 1
        assert [batch["status"] for batch in enrich.diagnostics["semantic_batches"]] == ["completed"] * 3
        await enrich.drain(.01)
        assert len(calls) == 3
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_new_subscription_during_match_gets_only_new_pairs_and_alias_reuses_result():
    calls, published = [], []
    first_started, release_match = asyncio.Event(), asyncio.Event()
    raw = metadata(("Bounding box intersection and event dispatch",))

    async def fetch(_resource):
        pytest.fail("Retained native catalog must not trigger a network fetch")

    async def match(_prompt, payload, _timeout):
        calls.append(payload)
        if len(calls) == 1:
            first_started.set()
            await release_match.wait()
        return {"matches": [{"resource_id": row["resource_id"], "point_id": point,
                             "chapter_ids": [chapter["chapter_id"] for chapter in row["chapters"]]}
                            for row in payload["resources"] for point in row["point_ids"]]}

    enrich = service(fetch_catalog=fetch, load_cached_catalog=lambda _resource: raw,
                     match=match, publish=lambda *args: published.append(args), max_resources=0)
    background = asyncio.create_task(enrich.run_background_match(collect_seconds=0))
    try:
        assert enrich.enqueue_cached(RESOURCE, ["collision"])
        await asyncio.wait_for(first_started.wait(), .2)
        assert enrich.enqueue_cached(RESOURCE, ["event"])
        release_match.set()
        # Wait for both batches while admission remains open so a later alias
        # can consume the already observed semantic result without a third call.
        async def wait_for_both():
            while len(published) < 2:
                await asyncio.sleep(0)
        await asyncio.wait_for(wait_for_both(), .2)
        alias = dict(RESOURCE, resource_id="part", url=URL + "?p=3")
        assert enrich.enqueue_cached(alias, ["collision"])
        enrich.finish_admission(deadline=time.monotonic() + 1)
        await asyncio.wait_for(background, .5)
        assert [payload["resources"][0]["point_ids"] for payload in calls] == [["collision"], ["event"]]
        assert {(row[0], row[1]) for row in published} == {
            ("video", "collision"), ("video", "event"), ("part", "collision")}
        assert all(row[2][0]["observed_at"] == raw["fetched_at"] for row in published)
        assert enrich.diagnostics["fetch_attempts"] == 0
        assert enrich.diagnostics["network_scheduled_resources"] == 0
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        await enrich.close()


@pytest.mark.asyncio
async def test_background_deadline_cancels_active_and_queued_catalogs():
    started = asyncio.Event()

    async def fetch(_resource):
        started.set()
        await asyncio.sleep(100)

    enrich = service(fetch_catalog=fetch, per_resource_timeout=1)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        enrich.enqueue(dict(RESOURCE, resource_id="queued", url="https://www.bilibili.com/video/av999"), ["collision"])
        enrich.finish_admission(deadline=time.monotonic() + .06)
        await asyncio.wait_for(enrich.run_background_match(), .3)
        assert started.is_set()
        assert enrich.diagnostics["deadline_reached"] is True
        # The course timeout and owner deadline can finish in either order.
        # Both active and queued loads must end, with no live fetch left behind.
        assert enrich.diagnostics["cancelled"] + enrich.diagnostics["timeouts"] == 2
        assert {row["status"] for row in enrich.diagnostics["resources"]} <= {"cancelled", "cancelled_queued", "timeout", "deadline"}
        assert all(task.done() for task in enrich._tasks)
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_deadline_extension_wakes_idle_loop_and_finish_stops_it_early():
    published = []
    enrich = service(deadline=time.monotonic() + .04,
                     load_cached_catalog=lambda _resource: metadata(),
                     publish=lambda *args: published.append(args))
    background = asyncio.create_task(enrich.run_background_match())
    try:
        await asyncio.sleep(.01)
        enrich.update_deadline(time.monotonic() + 1)
        await asyncio.sleep(.05)
        assert not background.done()
        assert enrich.enqueue_cached(RESOURCE, ["collision"])
        enrich.finish_admission(deadline=time.monotonic() + 500)
        assert 499 < enrich.deadline - time.monotonic() <= 500
        await asyncio.wait_for(background, .2)
        assert published and enrich.diagnostics["deadline_reached"] is False
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        await enrich.close()


@pytest.mark.asyncio
async def test_close_wakes_generic_only_catalog_loop_without_spending_model_calls():
    async def fetch(_resource):
        return metadata(("Getting started with Pygame",))

    async def match(*_args):
        pytest.fail("Generic headings must not spend a semantic batch")

    enrich = HelpfulVideoChapterEnricher(Settings(), [dict(POINTS[0], technology="Pygame")],
                                       fetch_catalog=fetch, match=match)
    background = asyncio.create_task(enrich.run_background_match())
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await asyncio.wait_for(asyncio.gather(*enrich._tasks), .2)
        assert not background.done()
        await enrich.close()
        await asyncio.wait_for(background, .2)
        assert enrich.diagnostics["semantic_calls"] == 0
        assert enrich.diagnostics["semantic_budget_reached"] is False
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        await enrich.close()


@pytest.mark.asyncio
async def test_cancelling_owner_during_semantic_call_leaves_no_unowned_fetches():
    matching = asyncio.Event()

    async def fetch(resource):
        if resource["resource_id"] == "slow":
            await asyncio.sleep(100)
        return metadata(("Bounding box intersection",))

    async def match(*_args):
        matching.set()
        await asyncio.sleep(100)

    enrich = service(fetch_catalog=fetch, match=match)
    background = asyncio.create_task(enrich.run_background_match(collect_seconds=0))
    enrich.enqueue(RESOURCE, ["collision"])
    enrich.enqueue(dict(RESOURCE, resource_id="slow", url="https://www.bilibili.com/video/av999"), ["collision"])
    try:
        await asyncio.wait_for(matching.wait(), .2)
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        await enrich.close()
    assert enrich.diagnostics["semantic_batches"][0]["status"] == "cancelled"
    assert enrich.diagnostics["cancelled"] == 1
    assert all(task.done() for task in enrich._tasks)


@pytest.mark.asyncio
async def test_page_timeout_does_not_report_previous_robots_404_as_page_status():
    class Transport:
        async def request(self, url, _addresses, _max_bytes):
            if url.endswith("/robots.txt"):
                return HTTPResult(404, {"content-type": "text/plain"}, b"", url)
            await asyncio.sleep(100)

    async def resolver(_url, _timeout):
        return ["93.184.216.34"]

    enrich = service(per_resource_timeout=.03)
    enrich._fetcher = Fetcher(FetcherConfig(bilibili_public_metadata=True, min_interval_seconds=0),
                              resolver=resolver, http_client=Transport())
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        detail = enrich.diagnostics["resources"][0]
        assert detail["status"] == "timeout"
        assert detail["http_status"] is None
        assert detail["last_completed_http_status"] == 404
        assert detail["request_route"] == "bilibili_video"
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("url,expected", [
    (URL + "?p=7", URL + "/?p=7"),
    ("https://www.icourse163.org/course/BIT-1001873001", "https://www.icourse163.org/course/BIT-1001873001"),
])
async def test_native_fetch_uses_bilibili_slash_without_changing_part_or_mooc_slug(url, expected):
    calls = []

    class FakeFetcher:
        async def enrich(self, resource, **_kwargs):
            calls.append(resource)
            return {"url": resource["url"], "chapters": []}

    enrich = service()
    enrich._fetcher = FakeFetcher()
    resource = dict(RESOURCE, url=url)
    try:
        enrich.enqueue(resource, ["collision"])
        await enrich.drain()
        assert calls[0]["url"] == expected
        assert resource["url"] == url
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_catalog_budget_skipped_counts_distinct_courses_not_repeated_points():
    enrich = service(max_resources=0)
    try:
        for point_id in ("collision", "event"):
            enrich.enqueue(RESOURCE, [point_id])
            enrich.enqueue(dict(RESOURCE, url=URL + "?p=7"), [point_id])
        assert enrich.diagnostics["budget_skipped"] == 1
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_literal_matching_does_not_confuse_negated_or_compound_terms():
    async def fetch(_resource):
        return metadata(("不讲碰撞检测", "三角函数与循环神经网络", "第7节 函数"))

    published = []
    enrich = HelpfulVideoChapterEnricher(Settings(), [*POINTS, {"id": "function", "name": "函数"},
        {"id": "loop", "name": "循环"}], fetch_catalog=fetch, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision", "function", "loop"])
        await enrich.drain()
        assert len(published) == 1 and published[0][1] == "function"
        assert published[0][2][0]["title"] == "第7节 函数"
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_native_payment_notice_notifies_all_subscribers_without_chapters():
    paid, published = [], []

    async def fetch(_resource):
        return dict(metadata(), requires_payment=True)

    enrich = service(fetch_catalog=fetch, on_paid=paid.append, publish=lambda *args: published.append(args))
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain()
        enrich.enqueue(dict(RESOURCE, resource_id="late"), ["event"])
        assert paid == ["video", "late"]
        assert published == []
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_native_not_found_notifies_existing_and_late_course_aliases_without_rechecking():
    unavailable, published, fetched, saved = [], [], [], []
    gate = asyncio.Event()

    async def fetch(resource):
        fetched.append(resource["resource_id"])
        await gate.wait()
        return dict(metadata(), fetch_status="not_found")

    async def match(*_args):
        pytest.fail("A missing video cannot supply chapters to the model")

    enrich = service(fetch_catalog=fetch, match=match, on_unavailable=unavailable.append,
                     publish=lambda *args: published.append(args), save_catalog=lambda *args: saved.append(args))
    try:
        assert enrich.enqueue(RESOURCE, ["collision"])
        assert enrich.enqueue(dict(RESOURCE, resource_id="part", url=URL + "?p=4"), ["event"])
        assert unavailable == [] and fetched == []
        gate.set()
        await enrich.drain(.1)
        assert unavailable == ["video", "part"]
        assert enrich.enqueue_cached(dict(RESOURCE, resource_id="late", url=URL + "?p=5"), ["event"])
        assert unavailable == ["video", "part", "late"]
        assert fetched == ["video"] and not published and not saved
        assert enrich.diagnostics["unavailable_resources"] == 1
        assert enrich.diagnostics["resources"][0]["status"] == "not_found"
        assert enrich.diagnostics["semantic_calls"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"url": None}, {"url": "https://www.bilibili.com/video/av999"},
    {"resolved_url": "https://www.bilibili.com/video/av999"},
    {"resolved_url": "https://www.bilibili.com/404"},
])
async def test_not_found_without_same_course_identity_never_withdraws_a_card(change):
    unavailable = []

    async def fetch(_resource):
        return {"url": URL, "fetch_status": "not_found", **change}

    enrich = service(fetch_catalog=fetch, on_unavailable=unavailable.append)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert unavailable == [] and enrich.diagnostics["unavailable_resources"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["fetched", "no_catalog", "timeout", "access_denied",
                                    "captcha", "login_required", "error_page", "raised_timeout"])
async def test_missing_catalog_or_uncertain_availability_never_withdraws_a_card(status):
    unavailable = []

    async def fetch(_resource):
        if status == "raised_timeout":
            await asyncio.sleep(100)
        return {"url": URL, "fetch_status": status, "chapters": []}

    enrich = service(fetch_catalog=fetch, on_unavailable=unavailable.append, per_resource_timeout=.01)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert unavailable == [] and enrich.diagnostics["unavailable_resources"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
async def test_not_found_callback_is_optional_for_existing_callers():
    async def fetch(_resource):
        return {"url": URL, "fetch_status": "not_found"}

    enrich = service(fetch_catalog=fetch)
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain(.1)
        assert enrich.diagnostics["unavailable_resources"] == 1
        assert enrich.diagnostics["errors"] == 0
    finally:
        await enrich.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_budget", [1, 2])
async def test_native_fetcher_reuses_public_html_parser_without_media_or_playback(http_budget):
    calls, published = [], []
    payload = {"videoData": {"bvid": "BV1VZ4y1G7YB", "title": "Python 游戏课程", "pages": [
        {"page": 7, "part": "碰撞检测", "duration": 180}]}}
    body = ("<html><script>window.__INITIAL_STATE__=" + json.dumps(payload) + ";</script></html>").encode()

    class Transport:
        async def request(self, url, _addresses, _max_bytes):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return HTTPResult(200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /", url)
            return HTTPResult(200, {"content-type": "text/html"}, body, url)

    async def resolver(_url, _timeout):
        return ["93.184.216.34"]

    enrich = service(publish=lambda *args: published.append(args), max_http_requests=http_budget)
    enrich._fetcher = Fetcher(FetcherConfig(bilibili_public_metadata=True, min_interval_seconds=0),
                              resolver=resolver, http_client=Transport())
    outer_observer, outer_deadline = NETWORK_OBSERVER.get(), FETCH_DEADLINE_AT.get()
    try:
        enrich.enqueue(RESOURCE, ["collision"])
        await enrich.drain()
        assert calls == ["https://www.bilibili.com/robots.txt", URL + "/"][:http_budget]
        if http_budget == 2:
            assert published[0][2][0]["index"] == 7
            assert published[0][2][0]["url"] == URL + "/?p=7"
        else:
            assert not published
        assert enrich.diagnostics["http_requests"] == http_budget
        assert NETWORK_OBSERVER.get() is outer_observer
        assert FETCH_DEADLINE_AT.get() is outer_deadline
    finally:
        await enrich.close()
