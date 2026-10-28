"""Offline continuation contracts: ready videos never wait for native catalogs."""
import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from backend.app import fast_video_search as fast
from backend.app.helpful_video_chapters import HelpfulVideoChapterEnricher, observed_chapters
from backend.app.mobile_tasks import MobileTasks, MobileTaskPayload
from backend.app.result_stream import project_snapshot
from test_fast_project_search import recommendation, setup as project_setup
from test_fast_video_search import Provider, completion, factory, settings, video
from test_mobile_backend import document as mobile_document
from test_projects import analyzed


POINTS = [{"id": "loop", "name": "循环结构", "technology": "Python"}]
INPUT = {"name": "Offline catalog continuation", "requirements": "Learn Python iteration",
         "preferred_platforms": ["bilibili"]}
SOURCE = "html.bilibili.__INITIAL_STATE__.videoData.pages"


def catalog(resource, title="循环结构", index=2):
    url = resource["url"]
    return {"url": url, "fetch_status": "fetched", "fetched_at": "2026-10-23T01:00:00+00:00",
            "chapters": [{"title": title, "page_number": index, "url": url.partition("?")[0] + f"?p={index}",
                          "source_url": url, "source": SOURCE}]}


@pytest.fixture(autouse=True)
def no_live_supplier_or_fetch(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Catalog continuation tests must inject all supplier/model/page operations")
    monkeypatch.setattr(fast, "build_provider", forbidden)
    monkeypatch.setattr(fast, "complete_json", forbidden)
    monkeypatch.setattr("backend.app.fetcher.Fetcher.enrich", forbidden)


def cards(snapshot):
    return snapshot["recommendations"]["loop"]


@pytest.mark.asyncio
async def test_more_than_twelve_missing_covers_continue_after_video_terminal_without_search():
    terminal, release = asyncio.Event(), asyncio.Event()
    snapshots, fetched, enrichers = [], [], []
    candidates = [video(2000 + n, title=f"Python 循环结构教程 {n}", snippet="循环结构") for n in range(16)]
    provider = Provider(lambda _: candidates)

    async def fetch(resource):
        await release.wait()
        fetched.append(resource["url"])
        return catalog(resource)

    def make_enricher(*args, **kwargs):
        instance = HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)
        assert (instance.max_resources, instance.max_http_requests, instance.max_semantic_batches) == (12, 18, 0)
        enrichers.append(instance)
        return instance

    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["status"] != "running":
            terminal.set()

    task = asyncio.create_task(fast.run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=1, catalog_deadline_seconds=1, provider_factory=factory(provider),
        complete=completion(), chapter_enricher_factory=make_enricher))
    try:
        await asyncio.wait_for(terminal.wait(), 1)
        first = next(row for row in snapshots if row["status"] != "running")
        assert len(cards(first)) == 16 and all(not row["matched_chapters"] for row in cards(first))
        assert first["catalog_enrichment"]["status"] == "running" and not task.done()
        assert first["diagnostics"]["chapters"]["network_scheduled_resources"] <= 12
        searches = len(provider.calls)
        model_calls = first["progress"]["recommendation_model_calls"]
        release.set()
        result = await asyncio.wait_for(task, 1)
        assert len(fetched) == len(set(fetched)) == 16
        assert len(cards(result)) == 16 and all(not row["matched_chapters"] for row in cards(result))
        assert len(provider.calls) == searches
        assert result["progress"]["recommendation_model_calls"] == model_calls
        assert {k: result[k] for k in ("status", "finished_at", "elapsed_seconds")} == {
            k: first[k] for k in ("status", "finished_at", "elapsed_seconds")}
        assert all(child.done() for enricher in enrichers for child in enricher._tasks)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_four_late_metadata_waves_never_call_a_chapter_model():
    terminal = asyncio.Event()
    releases = [asyncio.Event() for _ in range(4)]
    snapshots, catalog_calls, submitted_pairs, fetch_order = [], [], [], []
    candidates = [video(2100 + n, title=f"Python 循环结构教程 {n}", snippet="循环结构") for n in range(4)]
    provider = Provider(lambda _: candidates)
    ordinary = completion()

    async def fetch(resource):
        wave = len(fetch_order)
        fetch_order.append(resource["url"])
        await releases[wave].wait()
        if wave + 1 < len(releases):
            releases[wave + 1].set()
        return catalog(resource, title="Iterative processing")

    async def model(config, prompt, data, **kwargs):
        if data["task"] != "match_video_chapters":
            return await ordinary(config, prompt, data, **kwargs)
        assert terminal.is_set()
        catalog_calls.append(deepcopy(data))
        matches = []
        for row in data["resources"]:
            for point in row["point_ids"]:
                submitted_pairs.extend((row["resource_id"], point, chapter["chapter_id"]) for chapter in row["chapters"])
                matches.append({"resource_id": row["resource_id"], "point_id": point,
                                "chapter_ids": [chapter["chapter_id"] for chapter in row["chapters"]]})
        if len(catalog_calls) < 4:
            releases[len(catalog_calls)].set()
        return {"matches": matches}

    def publish(snapshot):
        snapshots.append(snapshot)
        if snapshot["status"] != "running":
            terminal.set()
            releases[0].set()

    result = await fast.run_fast_video_search(settings(), POINTS, INPUT, publish=publish,
        deadline_seconds=1, catalog_deadline_seconds=1, provider_factory=factory(provider), complete=model,
        chapter_enricher_factory=lambda *args, **kwargs: HelpfulVideoChapterEnricher(
            *args, **kwargs, fetch_catalog=fetch))
    first = next(row for row in snapshots if row["status"] != "running")
    assert len(fetch_order) == 4
    assert catalog_calls == submitted_pairs == []
    assert all(not row["matched_chapters"] for row in cards(result))
    assert result["progress"]["catalog_model_calls"] == 0
    assert result["progress"]["recommendation_model_calls"] == first["progress"]["recommendation_model_calls"]
    assert result["progress"]["search_requests"] == first["progress"]["search_requests"]
    assert result["catalog_enrichment"]["status"] == "completed"


@pytest.mark.parametrize("resources,http_limit,model_limit", [(96, 288, 24), (20, 60, 8)])
def test_project_confirmation_and_mobile_reserve_cover_requests_but_no_chapter_models(tmp_path, resources, http_limit, model_limit):
    config, store, jobs, projects = project_setup(tmp_path)
    config = replace(config, catalog_background_max_resources=resources,
                     catalog_background_max_http_requests=http_limit, catalog_background_max_model_calls=model_limit)
    projects.settings = config
    payload = MobileTaskPayload.model_validate({"kind": "search", "input": INPUT,
                                                "analysis": mobile_document().model_dump()})
    points = payload.analysis.model_dump()["knowledge_points"]
    manager = MobileTasks.__new__(MobileTasks)
    manager.settings, manager.projects = config, projects
    try:
        budget = projects._budget(points, ["bilibili"])
        costs = manager._costs(payload, points)
        assert budget["reserved_catalog_model_calls"] == 0
        assert budget["reserved_model_calls"] == fast.MAX_MODEL_CALLS
        assert budget["optional_catalog_resources"] == resources
        assert budget["catalog_http_requests"] == http_limit
        assert costs["model_calls"] == fast.MAX_MODEL_CALLS
        assert costs["detail_http"] == http_limit
        assert costs["search_requests"] == config.project_max_search_requests
        assert costs["detail_pages"] == 0
    finally:
        store.close()


def saved_state(point_id="loop"):
    return {"policy": "targeted-video-v2", "status": "completed", "started_at": "2026-10-23T01:00:00+00:00",
            "finished_at": "2026-10-23T01:00:10+00:00", "elapsed_seconds": 10,
            "recommendations": {point_id: [dict(recommendation(), matched_chapters=[])]},
            "progress": {"search_requests": 23, "recommendation_model_calls": 4,
                         "catalog_model_calls": 3, "model_calls": 7, "candidates": 1},
            "diagnostics": {"searches": [{"query": "original discovery", "provider": "offline", "status": "completed"}],
                            "model_batches": [], "chapters": {"semantic_budget_reached": True}},
            "catalog_enrichment": {"status": "partial", "started_at": "2026-10-23T01:00:00+00:00",
                                   "finished_at": "2026-10-23T01:00:11+00:00", "elapsed_seconds": 11}}


@pytest.mark.asyncio
async def test_resume_helper_only_enriches_existing_cards_and_keeps_discovery_history_and_timing():
    state = saved_state()
    original = deepcopy(state)
    fetched, calls, snapshots = [], [], []

    async def fetch(resource):
        fetched.append(resource["url"])
        return catalog(resource, "Iterative processing")

    async def model(_settings, _prompt, data, **_kwargs):
        assert data["task"] == "match_video_chapters", "Resume cannot plan or judge more videos"
        calls.append(data)
        return {"matches": [{"resource_id": row["resource_id"], "point_id": point,
                             "chapter_ids": [chapter["chapter_id"] for chapter in row["chapters"]]}
                            for row in data["resources"] for point in row["point_ids"]]}

    result = await asyncio.wait_for(fast.resume_video_catalogs(settings(),
        [*POINTS, {"id": "empty", "name": "事件处理", "technology": "Python"}], state,
        publish=snapshots.append, complete=model,
        chapter_enricher_factory=lambda *args, **kwargs: HelpfulVideoChapterEnricher(
            *args, **kwargs, fetch_catalog=fetch)), 2)
    assert fetched == [original["recommendations"]["loop"][0]["resource"]["url"]]
    assert calls == []
    assert set(result["recommendations"]) == {"loop"}
    assert len(cards(result)) == 1 and not cards(result)[0]["matched_chapters"]
    assert result["diagnostics"]["searches"] == original["diagnostics"]["searches"]
    for field in ("status", "started_at", "finished_at", "elapsed_seconds"):
        assert result[field] == original[field]
    for field in ("search_requests", "recommendation_model_calls", "candidates"):
        assert result["progress"][field] == original["progress"][field]
    assert cards(result)[0]["added_at"] == cards(original)[0]["added_at"]
    assert result["catalog_enrichment"]["status"] == "completed"
    assert snapshots and snapshots[0]["catalog_enrichment"]["status"] == "running"


@pytest.mark.asyncio
async def test_resume_reuses_remaining_version_allowance_instead_of_resetting_spend():
    state = saved_state()
    second = deepcopy(cards(state)[0])
    second["resource"].update(resource_id="r2", url="https://www.bilibili.com/video/av2299")
    cards(state).append(second)
    state["progress"].update(catalog_model_calls=23, model_calls=27)
    state["diagnostics"]["covers"] = {"network_scheduled_resources": 95, "http_requests": 287}
    options, fetched, calls = [], [], []

    async def fetch(resource):
        fetched.append(resource["url"])
        return catalog(resource, "Iterative processing")

    def make_enricher(*args, **kwargs):
        options.append({key: kwargs[key] for key in ("max_resources", "max_http_requests", "max_semantic_batches")})
        return HelpfulVideoChapterEnricher(*args, **kwargs, fetch_catalog=fetch)

    async def model(_settings, _prompt, data, **_kwargs):
        assert data["task"] == "match_video_chapters"
        calls.append(data)
        return {"matches": [{"resource_id": row["resource_id"], "point_id": "loop",
                             "chapter_ids": [chapter["chapter_id"] for chapter in row["chapters"]]}
                            for row in data["resources"]]}

    result = await asyncio.wait_for(fast.resume_video_catalogs(settings(), POINTS, state,
        publish=lambda _: None, complete=model, chapter_enricher_factory=make_enricher), 2)
    assert options == [{"max_resources": 1, "max_http_requests": 1, "max_semantic_batches": 0}]
    assert len(fetched) == 1 and not calls
    assert len(cards(result)) == 2 and not any(row["matched_chapters"] for row in cards(result))
    assert result["progress"]["catalog_model_calls"] == 23
    assert result["progress"]["model_calls"] == 27
    assert result["progress"]["search_requests"] == 23
    assert result["diagnostics"]["covers"]["network_scheduled_resources"] == 96
    assert result["catalog_enrichment"]["status"] == "partial"


@pytest.mark.asyncio
async def test_resume_keeps_existing_chapter_and_historical_pending_counts_without_new_matches():
    state = saved_state()
    resource = cards(state)[0]["resource"]
    raw = catalog(resource, "For statement", 2)
    raw["chapters"].extend(catalog(resource, "While statement", 3)["chapters"])
    old_chapter = observed_chapters(resource, raw)[0]
    cards(state)[0]["matched_chapters"] = [deepcopy(old_chapter)]
    state["diagnostics"]["chapters"].update(semantic_chapters_omitted=11,
                                            semantic_unprocessed_chapters=11,
                                            semantic_unprocessed_pairs=11)
    fetched, calls = [], []

    async def fetch(item):
        fetched.append(item["url"])
        return deepcopy(raw)

    async def model(_settings, _prompt, data, **_kwargs):
        assert data["task"] == "match_video_chapters"
        calls.append(data)
        return {"matches": [{"resource_id": row["resource_id"], "point_id": "loop",
                             "chapter_ids": [chapter["chapter_id"] for chapter in row["chapters"]
                                             if chapter["index"] == 3]}
                            for row in data["resources"]]}

    result = await asyncio.wait_for(fast.resume_video_catalogs(settings(), POINTS, state,
        publish=lambda _: None, complete=model,
        chapter_enricher_factory=lambda *args, **kwargs: HelpfulVideoChapterEnricher(
            *args, **kwargs, fetch_catalog=fetch)), 2)
    assert fetched == [resource["url"]] and not calls
    chapters = cards(result)[0]["matched_chapters"]
    assert [chapter["title"] for chapter in chapters] == ["For statement"]
    assert chapters[0] == old_chapter
    assert len({chapter["chapter_id"] for chapter in chapters}) == 1
    assert result["diagnostics"]["chapters"]["semantic_chapters_omitted"] == 11
    assert result["diagnostics"]["chapters"]["semantic_unprocessed_chapters"] == 11
    assert result["diagnostics"]["chapters"]["semantic_unprocessed_pairs"] == 11
    assert {key: result[key] for key in ("status", "started_at", "finished_at", "elapsed_seconds")} == {
        key: state[key] for key in ("status", "started_at", "finished_at", "elapsed_seconds")}
    assert state["diagnostics"]["chapters"]["semantic_chapters_omitted"] == 11
    assert cards(state)[0]["matched_chapters"] == [old_chapter]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["complete", "cancel", "stop"])
async def test_project_resume_is_idempotent_and_cancelled_catalog_cannot_revive_or_research(tmp_path, monkeypatch, finish):
    _, store, _, projects = project_setup(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def resume(_settings, points, state, *, publish, **_kwargs):
        calls.append(deepcopy(state))
        working = deepcopy(state)
        working["catalog_enrichment"]["status"] = "running"
        publish(working)
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # A stale child callback must not erase retained recommendations.
            working["recommendations"] = {}
            working["catalog_enrichment"]["status"] = "completed"
            publish(working)
            raise
        for entries in working["recommendations"].values():
            entries[0]["matched_chapters"] = [{"chapter_id": "c2", "title": "循环结构"}]
        working["catalog_enrichment"]["status"] = "completed"
        publish(working)
        return working

    monkeypatch.setattr(fast, "resume_video_catalogs", resume)
    monkeypatch.setattr(fast, "run_fast_video_search", lambda *a, **kw: pytest.fail("Resume must not rediscover videos"))
    try:
        pid = (await analyzed(projects, 2))["project_id"]
        projects.confirm(pid, 1, [])
        data = projects.db.version(pid, 1)
        point_id = data["analysis"]["knowledge_points"][0]["id"]
        state = saved_state(point_id)
        data.update(status="completed", search_started_at=state["started_at"], fast_video_search=state)
        projects.db.save(pid, data)
        before = project_snapshot(projects, store, pid, 1)
        projects.resume_catalogs(pid, 1)
        projects.resume_catalogs(pid, 1)
        await asyncio.wait_for(entered.wait(), 1)
        pending = project_snapshot(projects, store, pid, 1)
        assert pending["pipeline"]["terminal"] and pending["pipeline"]["catalog_pending"]
        if finish == "complete":
            release.set()
            await asyncio.wait_for(asyncio.gather(*projects.tasks.values()), 1)
        elif finish == "cancel":
            await projects.cancel(pid, 1)
            await projects.cancel(pid, 1)
        else:
            await projects.stop()
        final = project_snapshot(projects, store, pid, 1)
        assert len(calls) == 1 and final["current_version"] == final["version"]["version"] == 1
        assert final["version"]["status"] == "completed"
        assert final["pipeline"]["terminal"] and not final["pipeline"]["catalog_pending"]
        assert final["pipeline"]["catalog_status"] == {"complete": "completed", "cancel": "cancelled", "stop": "interrupted"}[finish]
        for field in ("status", "started_at", "finished_at", "elapsed_seconds"):
            assert final["version"]["fast_video_search"][field] == state[field]
        assert final["version"]["fast_video_search"]["diagnostics"]["searches"] == state["diagnostics"]["searches"]
        assert final["pipeline"]["displayed"] == before["pipeline"]["displayed"] == 1
        assert final["version"]["search_started_at"] == data["search_started_at"]
        projects.start()
        await asyncio.sleep(0)
        assert len(calls) == 1 and not any(not task.done() for task in projects.tasks.values())
    finally:
        await projects.stop()
        store.close()
