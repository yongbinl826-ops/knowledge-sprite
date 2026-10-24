"""Offline cover-only continuation and immutable recommendation contracts."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from backend.app import fast_video_search as fast
from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher
from backend.app.result_stream import project_snapshot
from test_fast_project_search import setup as project_setup
from test_fast_video_search import settings, Provider, factory, completion, video
from test_catalog_continuation import saved_state, POINTS
from test_projects import analyzed


IMAGE = "https://i0.hdslb.com/bfs/archive/observed-cover.jpg"


def without_cover_state(row):
    value = deepcopy(row)
    for key in ("cover_status", "cover_error_code"):
        value["resource"].pop(key, None)
    return value


@pytest.fixture(autouse=True)
def no_real_operations(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Cover tests must not search, call a model, or fetch a real page")
    monkeypatch.setattr(fast, "build_provider", forbidden)
    monkeypatch.setattr(fast, "complete_json", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr("backend.app.fetcher.Fetcher.enrich", forbidden)


def state_with_cards(count=3):
    state = saved_state()
    template = state["recommendations"]["loop"][0]
    state["recommendations"]["loop"] = []
    for index in range(count):
        row = deepcopy(template)
        row["resource"].update(resource_id=f"r{index}", url=f"https://www.bilibili.com/video/av{50100 + index}",
                               canonical_url=f"https://www.bilibili.com/video/av{50100 + index}", thumbnail_url=None)
        row["matched_chapters"] = [{"chapter_id": "reviewed", "title": "人工审查的章节", "index": 7,
                                     "source_url": row["resource"]["url"]}]
        state["recommendations"]["loop"].append(row)
    state["progress"].update(catalog_model_calls=32, model_calls=36, covered_points=1)
    state["diagnostics"]["chapters"] = {"http_requests": 288, "network_scheduled_resources": 96,
                                          "semantic_calls": 32, "semantic_budget_reached": True}
    state["diagnostics"]["page_requests"] = 288
    return state


def cover(resource, image=IMAGE, source_url=None):
    return {"thumbnail_url": image, "source": "html.bilibili.__INITIAL_STATE__.videoData.pic",
            "source_kind": "native_catalog", "source_url": source_url or resource["url"],
            "observed_at": "2026-10-23T10:00:00+00:00",
            "provenance": {"source_url": source_url or resource["url"]}}


class CoverEnricher:
    instances = []

    def __init__(self, _settings, _points, *, match, publish, on_paid, on_cover, cover_only,
                 max_resources, max_http_requests, max_semantic_batches, **_kwargs):
        assert cover_only and match is None and max_semantic_batches == 0
        self.on_cover, self.publish = on_cover, publish
        self.resources, self.closed = [], False
        self.max_resources, self.max_http_requests = max_resources, max_http_requests
        self.diagnostics = {"network_scheduled_resources": 0, "http_requests": 0,
                            "fetch_attempts": 0, "covers_received": 0, "budget_skipped": 0}
        self.instances.append(self)

    def enqueue(self, resource, point_ids):
        if len(self.resources) >= min(self.max_resources, self.max_http_requests):
            self.diagnostics["budget_skipped"] += 1
            return False
        self.resources.append((deepcopy(resource), list(point_ids)))
        self.diagnostics["network_scheduled_resources"] += 1
        return True

    def finish_admission(self, **_kwargs):
        pass

    async def run_background_match(self, **_kwargs):
        for resource, point_ids in self.resources:
            self.diagnostics["fetch_attempts"] += 1
            self.diagnostics["http_requests"] += 1
            self.on_cover(resource["resource_id"], cover(resource))
            # Even an old/misbehaving injection cannot alter reviewed chapters
            # through the cover-only helper's guarded chapter callback.
            self.publish(resource["resource_id"], point_ids[0], [{"chapter_id": "unexpected", "title": "Wrong"}])
            self.diagnostics["covers_received"] += 1

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_cover_resume_has_independent_budget_and_keeps_all_video_and_chapter_fields():
    state = state_with_cards()
    state["recommendations"]["loop"][0]["resource"]["thumbnail_url"] = "https://i1.hdslb.com/existing.jpg"
    state["recommendations"]["loop"][2]["resource"]["thumbnail_url"] = "http://127.0.0.1/private.jpg"
    original, snapshots = deepcopy(state), []
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=snapshots.append,
                                           chapter_enricher_factory=CoverEnricher)
    instance = CoverEnricher.instances[-1]
    assert instance.max_resources == 96 and instance.max_http_requests == 288
    assert [resource["resource_id"] for resource, _ in instance.resources] == ["r1", "r2"]
    assert without_cover_state(result["recommendations"]["loop"][0]) == original["recommendations"]["loop"][0]
    assert result["recommendations"]["loop"][0]["resource"]["cover_status"] == "ready"
    for before, after in zip(original["recommendations"]["loop"], result["recommendations"]["loop"]):
        assert after["matched_chapters"] == before["matched_chapters"]
        assert after["added_at"] == before["added_at"]
        assert after["resource"]["title"] == before["resource"]["title"]
    for row in result["recommendations"]["loop"][1:]:
        assert row["resource"]["thumbnail_url"] == IMAGE
        assert row["resource"]["thumbnail_provenance"]["source_kind"] == "native_catalog"
    for key in ("status", "started_at", "finished_at", "elapsed_seconds", "progress"):
        assert result[key] == original[key]
    assert result["diagnostics"]["chapters"] == original["diagnostics"]["chapters"]
    assert result["diagnostics"]["searches"] == original["diagnostics"]["searches"]
    assert result["diagnostics"]["covers"]["http_requests"] == 2
    assert result["diagnostics"]["page_requests"] == 290
    assert result["catalog_enrichment"]["mode"] == "covers_only"
    assert result["catalog_enrichment"]["status"] == "completed" and instance.closed


@pytest.mark.asyncio
async def test_cover_allowance_is_cumulative_across_resume_rounds():
    state = state_with_cards(2)
    state["diagnostics"]["covers"] = {"network_scheduled_resources": 95, "http_requests": 287}
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None,
                                           chapter_enricher_factory=CoverEnricher)
    assert CoverEnricher.instances[-1].max_resources == CoverEnricher.instances[-1].max_http_requests == 1
    assert result["diagnostics"]["covers"]["network_scheduled_resources"] == 96
    assert result["diagnostics"]["covers"]["http_requests"] == 288
    assert result["diagnostics"]["chapters"] == state["diagnostics"]["chapters"]
    assert result["progress"] == state["progress"]
    assert result["catalog_enrichment"]["status"] == "partial"


@pytest.mark.parametrize("image,source", [("http://localhost/a.jpg", None), (IMAGE, "https://www.bilibili.com/video/av999999")])
def test_untrusted_image_or_unbound_cover_never_changes_card(image, source):
    state = state_with_cards(1)
    original = deepcopy(state)
    resource = state["recommendations"]["loop"][0]["resource"]
    assert not fast._apply_observed_cover(state["recommendations"], "r0", cover(resource, image, source))
    assert state == original


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["complete", "cancel", "stop"])
async def test_cover_service_uses_same_version_owner_and_blocks_cancelled_callbacks(tmp_path, monkeypatch, finish):
    _, store, _, projects = project_setup(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def resume(_settings, _points, state, *, publish, **_kwargs):
        calls.append(deepcopy(state))
        entered.set()
        working = deepcopy(state)
        try:
            await release.wait()
        except asyncio.CancelledError:
            working["recommendations"] = {}
            working["catalog_enrichment"]["status"] = "completed"
            publish(working)
            raise
        working["recommendations"][next(iter(working["recommendations"]))][0]["resource"]["thumbnail_url"] = IMAGE
        working["catalog_enrichment"]["status"] = "completed"
        publish(working)
        return working

    monkeypatch.setattr(fast, "resume_video_covers", resume)
    monkeypatch.setattr(fast, "resume_video_catalogs", lambda *_args, **_kwargs: pytest.fail("Cover route must use cover-only helper"))
    try:
        pid = (await analyzed(projects, 2))["project_id"]
        projects.confirm(pid, 1, [])
        data = projects.db.version(pid, 1)
        point_id = data["analysis"]["knowledge_points"][0]["id"]
        state = state_with_cards(1)
        state["recommendations"][point_id] = state["recommendations"].pop("loop")
        data.update(status="completed", search_started_at=state["started_at"], fast_video_search=state)
        projects.db.save(pid, data)
        projects.resume_covers(pid, 1)
        projects.resume_covers(pid, 1)
        await asyncio.wait_for(entered.wait(), 1)
        pending = project_snapshot(projects, store, pid, 1)
        assert pending["pipeline"]["terminal"] and pending["pipeline"]["catalog_pending"]
        assert pending["version"]["fast_video_search"]["catalog_enrichment"]["mode"] == "covers_only"
        if finish == "complete":
            release.set()
            await asyncio.gather(*projects.tasks.values())
        elif finish == "cancel":
            await projects.cancel(pid, 1)
        else:
            await projects.stop()
        final = project_snapshot(projects, store, pid, 1)
        actual = final["version"]["fast_video_search"]
        assert len(calls) == 1 and final["current_version"] == 1
        assert len(actual["recommendations"][point_id]) == 1
        assert not final["pipeline"]["catalog_pending"]
        assert final["pipeline"]["catalog_status"] == {"complete": "completed", "cancel": "cancelled", "stop": "interrupted"}[finish]
        for key in ("status", "started_at", "finished_at", "elapsed_seconds", "progress"):
            assert actual[key] == state[key]
        assert actual["recommendations"][point_id][0]["matched_chapters"] == state["recommendations"][point_id][0]["matched_chapters"]
        assert final["version"]["budgets"]["reserved_cover_model_calls"] == 0
        assert final["version"]["budgets"]["reserved_cover_http_requests"] == 288
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_later_search_result_can_fill_missing_cover_without_replacing_first_arrival():
    count = 0
    def search(_query):
        nonlocal count
        count += 1
        candidate = video(10, title="Python 循环结构", snippet="循环结构")
        if count > 1:
            candidate.thumbnail_url = IMAGE
        return [candidate]
    snapshots = []
    result = await fast.run_fast_video_search(settings(), POINTS,
        {"preferred_platforms": ["bilibili"], "name": "offline"}, publish=snapshots.append,
        provider_factory=factory(Provider(search)), complete=completion(), deadline_seconds=.5)
    row = result["recommendations"]["loop"][0]
    assert row["resource"]["thumbnail_url"] == IMAGE
    assert row["resource"]["thumbnail_provenance"]["source_kind"] == "search_result"
    arrivals = [snapshot["recommendations"]["loop"][0]["added_at"] for snapshot in snapshots
                if snapshot["recommendations"]["loop"]]
    assert len(set(arrivals)) == 1


def native_metadata(resource, *, with_image=True):
    url = resource["url"]
    result = {"url": url, "resolved_url": url, "fetch_status": "fetched",
              "fetched_at": "2026-10-23T10:00:00+00:00",
              "chapters": [{"title": "循环结构", "page_number": 2, "url": url + "?p=2",
                            "source_url": url, "source": "html.bilibili.__INITIAL_STATE__.videoData.pages"}]}
    if with_image:
        result.update(thumbnail_url=IMAGE, field_provenance={"thumbnail_url": {
            "source": "html.bilibili.__INITIAL_STATE__.videoData.pic", "url": url,
            "fetched_at": result["fetched_at"]}})
    return result


@pytest.mark.asyncio
async def test_real_enricher_cover_only_never_publishes_its_chapters_or_calls_a_model():
    state = state_with_cards(1)
    fetched = []
    async def fetch(resource):
        fetched.append(resource["url"])
        return native_metadata(resource)
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None,
        chapter_enricher_factory=lambda *args, **kwargs: HelpfulVideoChapterEnricher(
            *args, **kwargs, fetch_catalog=fetch))
    assert len(fetched) == 1
    assert result["recommendations"]["loop"][0]["resource"]["thumbnail_url"] == IMAGE
    assert result["recommendations"]["loop"][0]["matched_chapters"] == state["recommendations"]["loop"][0]["matched_chapters"]
    assert result["progress"] == state["progress"]
    assert result["diagnostics"]["chapters"] == state["diagnostics"]["chapters"]
    assert result["diagnostics"]["covers"]["cover_only"] is True
    assert result["diagnostics"]["covers"]["semantic_calls"] == 0


@pytest.mark.asyncio
async def test_normal_run_refreshes_missing_cached_cover_during_matching_with_one_fetch():
    terminal, matching, cover_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    snapshots, fetched = [], []
    class Cache:
        def lookup(self, resource):
            return native_metadata(resource, with_image=False)
        def observe(self, *_args):
            pass
    async def fetch(resource):
        await asyncio.wait_for(matching.wait(), .2)
        assert not terminal.is_set(), "The cover should arrive alongside candidate matching"
        fetched.append(resource["url"])
        cover_ready.set()
        return native_metadata(resource)
    ordinary = completion()
    async def complete(config, prompt, payload, **kwargs):
        if payload["task"] == "match_video_chapters":
            assert any(call["task"] == "match_helpful_videos" for call in ordinary.calls)
            return {"matches": []}
        if payload["task"] == "match_helpful_videos":
            matching.set()
            await asyncio.wait_for(cover_ready.wait(), .2)
        return await ordinary(config, prompt, payload, **kwargs)
    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["status"] != "running":
            terminal.set()
    result = await fast.run_fast_video_search(settings(), POINTS,
        {"preferred_platforms": ["bilibili"], "name": "offline"}, publish=publish,
        provider_factory=factory(Provider(lambda _: [video(12, title="Python 循环结构", snippet="循环结构")])),
        complete=complete, deadline_seconds=.5, catalog_deadline_seconds=.5, catalog_cache=Cache(),
        chapter_enricher_factory=lambda *args, **kwargs: HelpfulVideoChapterEnricher(
            *args, **kwargs, fetch_catalog=fetch))
    first = next(snapshot for snapshot in snapshots if snapshot["status"] != "running")
    assert first["recommendations"]["loop"][0]["resource"]["thumbnail_url"] == IMAGE
    assert first["recommendations"]["loop"][0]["resource"]["cover_status"] == "ready"
    assert len(fetched) == 1
    assert result["recommendations"]["loop"][0]["resource"]["thumbnail_url"] == IMAGE
    assert result["elapsed_seconds"] == first["elapsed_seconds"]
    assert result["finished_at"] == first["finished_at"]
    assert result["progress"]["recommendation_model_calls"] == len(ordinary.calls) == 2
    assert result["progress"]["catalog_model_calls"] == 1  # Existing directory matching, after admission.
    assert result["diagnostics"]["chapters"]["network_scheduled_resources"] == 1
    assert result["diagnostics"]["chapters"]["fetch_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cover_only", "exception"])
async def test_early_cover_response_preserves_cached_native_chapters(outcome):
    cover_ready = asyncio.Event()
    fetched = []
    class Cache:
        def lookup(self, resource):
            return native_metadata(resource, with_image=False)
        def observe(self, *_args):
            pass
    async def fetch(resource):
        fetched.append(resource["url"])
        observation = native_metadata(resource)
        observation["chapters"] = []
        cover_ready.set()
        if outcome == "exception":
            raise RuntimeError("Offline speculative page failure")
        return observation
    ordinary = completion()
    async def complete(config, prompt, payload, **kwargs):
        if payload["task"] == "match_video_chapters":
            return {"matches": []}
        if payload["task"] == "match_helpful_videos":
            await asyncio.wait_for(cover_ready.wait(), .2)
        return await ordinary(config, prompt, payload, **kwargs)
    result = await fast.run_fast_video_search(settings(), POINTS,
        {"preferred_platforms": ["bilibili"], "name": "offline"}, publish=lambda _: None,
        provider_factory=factory(Provider(lambda _: [video(12, title="Python 循环结构", snippet="循环结构")])),
        complete=complete, deadline_seconds=.5, catalog_deadline_seconds=.5, catalog_cache=Cache(),
        chapter_enricher_factory=lambda *args, **kwargs: HelpfulVideoChapterEnricher(
            *args, **kwargs, fetch_catalog=fetch))
    card = result["recommendations"]["loop"][0]
    assert [chapter["title"] for chapter in card["matched_chapters"]] == ["循环结构"]
    assert card["matched_chapters"][0]["observed_at"] == "2026-10-23T10:00:00+00:00"
    assert card["resource"]["thumbnail_url"] == (IMAGE if outcome == "cover_only" else None)
    assert card["resource"]["cover_status"] == ("ready" if outcome == "cover_only" else "failed")
    assert result["diagnostics"]["chapters"]["resources"][0]["catalog_source"] == "retained_catalog"
    assert len(fetched) == 1


@pytest.mark.asyncio
async def test_safe_existing_course_image_fills_other_alias_without_fetching():
    state = state_with_cards(2)
    rows = state["recommendations"]["loop"]
    rows[0]["resource"]["thumbnail_url"] = IMAGE
    rows[1]["resource"]["url"] = rows[0]["resource"]["url"] + "?p=2"
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None,
                                           chapter_enricher_factory=CoverEnricher)
    assert CoverEnricher.instances[-1].resources == []
    assert result["recommendations"]["loop"][1]["resource"]["thumbnail_url"] == IMAGE
    assert without_cover_state(result["recommendations"]["loop"][0]) == state["recommendations"]["loop"][0]
    assert result["recommendations"]["loop"][0]["resource"]["cover_status"] == "ready"
    assert result["diagnostics"]["covers"]["http_requests"] == 0


@pytest.mark.asyncio
async def test_non_displayable_http_cover_is_missing_but_bilibili_http_cover_is_reusable():
    state = state_with_cards(2)
    rows = state["recommendations"]["loop"]
    rows[0]["resource"]["thumbnail_url"] = "http://images.example.org/image.jpg"
    rows[1]["resource"]["thumbnail_url"] = "http://i2.hdslb.com/bfs/archive/existing.jpg"
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None,
                                           chapter_enricher_factory=CoverEnricher)
    assert [resource["resource_id"] for resource, _ in CoverEnricher.instances[-1].resources] == ["r0"]
    assert result["recommendations"]["loop"][0]["resource"]["thumbnail_url"] == IMAGE
    assert without_cover_state(result["recommendations"]["loop"][1]) == state["recommendations"]["loop"][1]
    assert result["recommendations"]["loop"][1]["resource"]["cover_status"] == "ready"


@pytest.mark.asyncio
async def test_cancelled_cover_helper_blocks_close_time_late_image():
    entered = asyncio.Event()
    snapshots = []
    class SlowCover(CoverEnricher):
        async def run_background_match(self, **_kwargs):
            entered.set()
            await asyncio.Event().wait()
        async def close(self):
            resource, _ = self.resources[0]
            self.on_cover(resource["resource_id"], cover(resource))
            await super().close()
    task = asyncio.create_task(fast.resume_video_covers(settings(), POINTS, state_with_cards(1),
        publish=snapshots.append, chapter_enricher_factory=SlowCover))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert CoverEnricher.instances[-1].closed
    assert snapshots[-1]["catalog_enrichment"]["status"] == "cancelled"
    assert snapshots[-1]["recommendations"]["loop"][0]["resource"]["thumbnail_url"] is None


@pytest.mark.parametrize("source,accepted", [
    ("https://www.bilibili.com/zh-Hans/video/BV1VZ4y1G7YB/", True),
    ("https://www.bilibili.com/video/BV1VZ4y1G7YB/", True),
    ("https://www.bilibili.com/zh-Hans/video/BV1VZ4y1G7YB/?p=2", True),
    ("https://www.bilibili.com/zh-Hans/video/BV1q741157jG/", False),
])
def test_cover_binding_accepts_native_locale_aliases_but_never_another_video(source, accepted):
    state = state_with_cards(1)
    resource = state["recommendations"]["loop"][0]["resource"]
    resource["url"] = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    original_url = resource["url"]
    assert fast._apply_observed_cover(state["recommendations"], "r0", cover(resource, source_url=source)) is accepted
    assert resource["thumbnail_url"] == (IMAGE if accepted else None)
    assert resource["url"] == original_url


@pytest.mark.parametrize("source,accepted", [
    ("https://www.icourse163.org/course/0809BIT021E-1001873001?tid=456", True),
    ("https://www.icourse163.org/course/BIT-1001873001?tid=789", False),
    ("https://www.icourse163.org/course/BIT-1001873002?tid=456", False),
])
def test_cover_binding_keeps_mooc_course_and_term_identity(source, accepted):
    state = state_with_cards(1)
    resource = state["recommendations"]["loop"][0]["resource"]
    resource["url"] = "https://www.icourse163.org/course/BIT-1001873001?tid=456"
    assert fast._apply_observed_cover(state["recommendations"], "r0", cover(resource, source_url=source)) is accepted
    assert resource["thumbnail_url"] == (IMAGE if accepted else None)


@pytest.mark.asyncio
async def test_native_locale_cover_receipt_reaches_existing_card_and_alias_sync_skips_fetch():
    state = state_with_cards(2)
    rows = state["recommendations"]["loop"]
    canonical = "https://www.bilibili.com/video/BV1VZ4y1G7YB"
    localized = "https://www.bilibili.com/zh-Hans/video/BV1VZ4y1G7YB/"
    rows[0]["resource"].update(url=canonical, canonical_url=canonical)
    rows[1]["resource"].update(url=localized, canonical_url=localized)
    fetched = []
    async def fetch(resource):
        fetched.append(resource["url"])
        metadata = native_metadata(resource)
        metadata.update(url=localized, resolved_url=localized)
        metadata["field_provenance"]["thumbnail_url"]["url"] = localized
        return metadata
    result = await fast.resume_video_covers(settings(), POINTS, state, publish=lambda _: None,
        chapter_enricher_factory=lambda *args, **kwargs: HelpfulVideoChapterEnricher(
            *args, **kwargs, fetch_catalog=fetch))
    assert len(fetched) == 1
    assert result["diagnostics"]["covers"]["covers_received"] == 1
    assert all(row["resource"]["thumbnail_url"] == IMAGE for row in result["recommendations"]["loop"])
    assert [row["resource"]["url"] for row in result["recommendations"]["loop"]] == [canonical, localized]
    # A subsequent existing-card alias can reuse the same image without a page.
    result["recommendations"]["loop"][1]["resource"]["thumbnail_url"] = None
    result = await fast.resume_video_covers(settings(), POINTS, result, publish=lambda _: None,
                                           chapter_enricher_factory=CoverEnricher)
    assert CoverEnricher.instances[-1].resources == []
    assert all(row["resource"]["thumbnail_url"] == IMAGE for row in result["recommendations"]["loop"])
