"""Offline contracts for bounded project searches and persisted streamed results."""
import asyncio
from copy import deepcopy

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import now
from backend.app.project_service import ProjectService
from backend.app.result_stream import project_snapshot
from backend.app.service import JobService
from test_projects import EmptySearch, NoFetch, OfflineAnalyzer, analyzed, wait_for


def setup(tmp_path):
    settings = Settings(database_path=str(tmp_path / "fast.sqlite3"),
                        fast_video_recommendations_enabled=True, fast_video_deadline_seconds=2)
    store = Store(settings.database_path)
    jobs = JobService(settings, store, provider=EmptySearch(), fetcher=NoFetch())
    projects = ProjectService(settings, store, jobs, analyzer=OfflineAnalyzer())
    return settings, store, jobs, projects


def recommendation(index=1):
    return {"resource": {"resource_id": f"r{index}", "title": "Python 游戏教程",
                         "url": f"https://www.bilibili.com/video/BV1q741157jG?p={index}",
                         "canonical_url": f"https://www.bilibili.com/video/BV1q741157jG?p={index}",
                         "platform": "bilibili", "requires_payment": None, "fetch_status": "not_fetched"},
            "origin": "search", "score": 80, "added_at": now(), "elapsed_seconds": .01}


@pytest.mark.asyncio
async def test_all_points_share_one_budget_stream_and_keep_more_than_five(tmp_path, monkeypatch):
    _, store, jobs, projects = setup(tmp_path)
    calls = []
    published = asyncio.Event()
    release = asyncio.Event()

    async def engine(settings, points, input_data, *, publish, deadline_seconds, catalog_cache, search_cache):
        assert callable(catalog_cache.lookup) and callable(catalog_cache.observe)
        assert search_cache is store
        calls.append((deepcopy(points), deadline_seconds))
        rows = [recommendation(i) for i in range(1, 9)]
        snapshot = {"policy": "helpful-video-v1", "status": "running", "started_at": now(),
                    "recommendations": {p["id"]: deepcopy(rows) for p in points},
                    "progress": {"search_requests": 3, "model_calls": 1, "candidates": 8}, "diagnostics": {}}
        publish(snapshot)
        published.set()
        await release.wait()
        snapshot.update(status="completed", finished_at=now())
        publish(snapshot)
        return snapshot

    monkeypatch.setattr("backend.app.fast_video_search.run_fast_video_search", engine)
    view = await analyzed(projects, 15)
    pid = view["project_id"]
    confirmed = projects.confirm(pid, 1, [])
    assert confirmed["version"]["budgets"]["reserved_detail_pages"] == 0
    assert confirmed["version"]["budgets"]["reserved_task_seconds"] == 2
    projects.search(pid, 1)
    await asyncio.wait_for(published.wait(), 1)
    projects.search(pid, 1)  # No duplicate calls when a client retries.
    first = project_snapshot(projects, store, pid, 1)
    assert len(calls) == 1 and len(calls[0][0]) == 15 and 0 < calls[0][1] <= 2
    assert first["version"]["batches"] == [] and store.job_counts() == {}
    assert first["pipeline"]["displayed"] == 8
    assert first["pipeline"]["covered_points"] == 15
    assert not first["pipeline"]["terminal"]
    assert all(len(p["result"]["video_recommendations"]) == 8 for p in first["points"])
    before = store.connection.total_changes
    again = project_snapshot(projects, store, pid, 1)
    assert store.connection.total_changes == before and again == first
    release.set()
    await asyncio.gather(*projects.tasks.values())
    final = project_snapshot(projects, store, pid, 1)
    assert final["pipeline"]["terminal"] and final["version"]["status"] == "completed"
    assert final["version"]["budgets"]["actual_model_calls"] == 1
    assert first["version"]["status"] == "running"
    await projects.stop()
    store.connection.close()


@pytest.mark.asyncio
async def test_cancel_preserves_visible_results_and_rejects_late_callback(tmp_path, monkeypatch):
    _, store, jobs, projects = setup(tmp_path)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def engine(settings, points, input_data, *, publish, deadline_seconds, catalog_cache, search_cache):
        assert search_cache is store
        snapshot = {"policy": "helpful-video-v1", "status": "running",
                    "recommendations": {p["id"]: [recommendation()] for p in points}, "progress": {}}
        publish(snapshot)
        entered.set()
        try:
            await asyncio.sleep(30)
        finally:
            snapshot["status"] = "completed"
            publish(snapshot)  # A finishing callback must not undo cancellation.
            cancelled.set()

    monkeypatch.setattr("backend.app.fast_video_search.run_fast_video_search", engine)
    pid = (await analyzed(projects, 2))["project_id"]
    projects.confirm(pid, 1, [])
    projects.search(pid, 1)
    await asyncio.wait_for(entered.wait(), 1)
    await projects.cancel(pid, 1)
    assert cancelled.is_set()
    result = project_snapshot(projects, store, pid, 1)
    assert result["version"]["status"] == "cancelled"
    assert result["pipeline"]["terminal"] and result["pipeline"]["displayed"] == 1
    assert projects.db.version(pid, 1)["fast_video_search"]["status"] == "cancelled"
    await projects.stop()
    store.connection.close()


@pytest.mark.asyncio
async def test_restart_retains_fast_results_without_resuming_network(tmp_path, monkeypatch):
    _, store, jobs, projects = setup(tmp_path)
    pid = (await analyzed(projects, 2))["project_id"]
    projects.confirm(pid, 1, [])
    data = projects.db.version(pid, 1)
    data.update(status="running", search_started_at=now(), fast_video_search={
        "policy": "helpful-video-v1", "status": "running", "progress": {},
        "recommendations": {data["analysis"]["knowledge_points"][0]["id"]: [recommendation()]}})
    projects.db.save(pid, data)

    def forbidden(*args, **kwargs):
        raise AssertionError("Restart or read must never submit network work")

    monkeypatch.setattr("backend.app.fast_video_search.run_fast_video_search", forbidden)
    projects.start()
    result = project_snapshot(projects, store, pid, 1)
    assert result["version"]["status"] == "interrupted"
    assert result["pipeline"]["terminal"] and result["pipeline"]["displayed"] == 1
    assert not projects.tasks
    await projects.stop()
    store.connection.close()


def test_fast_deadline_configuration_is_bounded():
    for value in (0, 121, True, 2.5):
        with pytest.raises(ValueError, match="FAST_VIDEO_DEADLINE_SECONDS"):
            Settings(fast_video_deadline_seconds=value).validate()
    assert Settings(fast_video_deadline_seconds=120).validate().fast_video_deadline_seconds == 120


@pytest.mark.asyncio
async def test_catalog_updates_persist_after_video_completion_without_new_search(tmp_path, monkeypatch):
    _, store, _, projects = setup(tmp_path)
    ready, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def engine(settings, points, input_data, *, publish, **kwargs):
        calls.append(1)
        stamp = now()
        snapshot = {"status": "completed", "started_at": stamp, "finished_at": stamp,
                    "elapsed_seconds": .01, "progress": {"search_requests": 1},
                    "recommendations": {p["id"]: [recommendation()] for p in points},
                    "catalog_enrichment": {"status": "running", "started_at": stamp}}
        publish(snapshot)
        ready.set()
        await release.wait()
        for rows in snapshot["recommendations"].values():
            rows[0]["chapters"] = [{"id": "chapter-3", "title": "第三章 事件处理"}]
        # This intentionally changes video timing to prove the persistence
        # boundary independently freezes it during catalog-only updates.
        snapshot.update(elapsed_seconds=999, finished_at=now())
        snapshot["catalog_enrichment"].update(status="completed", finished_at=now())
        publish(snapshot)

    monkeypatch.setattr("backend.app.fast_video_search.run_fast_video_search", engine)
    pid = (await analyzed(projects, 2))["project_id"]
    projects.confirm(pid, 1, [])
    projects.search(pid, 1)
    await asyncio.wait_for(ready.wait(), 1)
    first = project_snapshot(projects, store, pid, 1)
    assert first["pipeline"]["terminal"] and first["pipeline"]["catalog_pending"]
    assert first["pipeline"]["stage"] == "complete"
    projects.search(pid, 1)  # Even a repeated POST must not start another search.
    release.set()
    await asyncio.gather(*projects.tasks.values())
    final = project_snapshot(projects, store, pid, 1)
    assert final["pipeline"]["terminal"] and not final["pipeline"]["catalog_pending"]
    assert len(calls) == 1 and final["version"]["version"] == 1
    assert first["pipeline"]["displayed"] == final["pipeline"]["displayed"] == 1
    for field in ("status", "elapsed_seconds", "finished_at"):
        assert first["version"]["fast_video_search"][field] == final["version"]["fast_video_search"][field]
    assert all(p["result"]["video_recommendations"][0]["chapters"][0]["title"] == "第三章 事件处理"
               for p in final["points"])
    await projects.stop()
    store.connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["cancel", "stop", "failure"])
async def test_background_catalog_cleanup_preserves_completed_recommendations(tmp_path, monkeypatch, end):
    _, store, _, projects = setup(tmp_path)
    ready, release = asyncio.Event(), asyncio.Event()

    async def engine(settings, points, input_data, *, publish, **kwargs):
        snapshot = {"status": "partial", "finished_at": now(), "progress": {},
                    "recommendations": {p["id"]: [recommendation()] for p in points},
                    "catalog_enrichment": {"status": "running", "started_at": now()}}
        publish(snapshot)
        ready.set()
        try:
            await release.wait()
            raise RuntimeError("background catalog failed")
        except asyncio.CancelledError:
            # The real engine publishes cleanup before its owner sees the
            # cancellation. Shutdown and an explicit user cancel stay distinct.
            snapshot["catalog_enrichment"].update(status="cancelled", finished_at=now())
            publish(snapshot)
            raise

    monkeypatch.setattr("backend.app.fast_video_search.run_fast_video_search", engine)
    pid = (await analyzed(projects, 2))["project_id"]
    projects.confirm(pid, 1, [])
    projects.search(pid, 1)
    await asyncio.wait_for(ready.wait(), 1)
    before = project_snapshot(projects, store, pid, 1)
    if end == "cancel":
        await projects.cancel(pid, 1)
    elif end == "stop":
        await projects.stop()
    else:
        release.set()
        await asyncio.gather(*projects.tasks.values())
    final = project_snapshot(projects, store, pid, 1)
    assert final["version"]["status"] == "partial"
    assert final["pipeline"]["terminal"] and not final["pipeline"]["catalog_pending"]
    assert final["pipeline"]["catalog_status"] == {"cancel": "cancelled", "stop": "interrupted", "failure": "failed"}[end]
    assert final["version"]["fast_video_search"]["recommendations"] == before["version"]["fast_video_search"]["recommendations"]
    assert final["pipeline"]["elapsed_seconds"] == before["pipeline"]["elapsed_seconds"]
    await projects.stop()
    store.connection.close()


@pytest.mark.asyncio
async def test_restart_ends_only_pending_catalog_without_resubmission(tmp_path, monkeypatch):
    _, store, _, projects = setup(tmp_path)
    pid = (await analyzed(projects, 2))["project_id"]
    projects.confirm(pid, 1, [])
    data = projects.db.version(pid, 1)
    data.update(status="completed", search_started_at=now(), fast_video_search={
        "status": "completed", "elapsed_seconds": 15, "finished_at": now(),
        "catalog_enrichment": {"status": "running", "started_at": now()},
        "recommendations": {data["analysis"]["knowledge_points"][0]["id"]: [recommendation()]}})
    projects.db.save(pid, data)
    monkeypatch.setattr("backend.app.fast_video_search.run_fast_video_search",
                        lambda *a, **kw: pytest.fail("restart must not resubmit"))
    projects.start()
    final = project_snapshot(projects, store, pid, 1)
    assert final["version"]["status"] == "completed"
    assert final["pipeline"]["catalog_status"] == "interrupted"
    assert not final["pipeline"]["catalog_pending"] and final["pipeline"]["elapsed_seconds"] == 15
    assert final["pipeline"]["displayed"] == 1 and not projects.tasks
    await projects.stop()
    store.connection.close()
