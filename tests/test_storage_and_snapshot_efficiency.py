import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest

from backend.app.config import Settings
from backend.app.db import Store, dumps
from backend.app.main import create_app
from backend.app.project_db import ProjectStore
from backend.app.snapshot_transport import snapshot_payload
from backend.app.snapshot_updates import CoalescedPublisher


def version():
    return {"version": 1, "status": "analyzed", "input": {"name": "Demo"},
            "created_at": "2026-10-24T00:00:00+00:00", "model": "fixture", "prompt_version": "p1",
            "analysis": {"knowledge_points": [{"id": "k1", "name": "Arrays"}], "functions": []},
            "batches": []}


def test_summary_migration_preserves_history_and_avoids_payload_reads(tmp_path):
    store = Store(str(tmp_path / "history.sqlite3"))
    projects = ProjectStore(store)
    projects.create("p", {"name": "Demo"})
    row = version()
    row["diagnostics"] = "x" * 200_000
    projects.save("p", row, new=True)
    original = store.connection.execute("SELECT data FROM project_versions").fetchone()[0]
    store.connection.execute("DROP TABLE project_version_summaries")
    projects = ProjectStore(store)
    assert store.connection.execute("SELECT data FROM project_versions").fetchone()[0] == original
    queries = []
    store.connection.set_trace_callback(queries.append)
    assert projects.versions("p") == [{"version": 1, "status": "analyzed", "created_at": row["created_at"],
                                       "model": "fixture", "prompt_version": "p1"}]
    assert all("FROM project_versions " not in sql for sql in queries)
    # First post-migration save establishes the fingerprint, later progress does
    # not rewrite the same immutable analysis child rows.
    projects.save("p", row)
    queries.clear()
    row["status"] = "completed"
    projects.save("p", row)
    assert not any("INSERT OR IGNORE INTO project_knowledge_points" in sql for sql in queries)
    assert projects.versions("p")[0]["status"] == "completed"
    plan = store.connection.execute("EXPLAIN QUERY PLAN SELECT data FROM search_attempts WHERE job_id=? ORDER BY id", ("j",)).fetchall()
    assert any("search_attempts_job_id" in item[3] for item in plan)
    store.close()


def test_summary_rows_follow_mobile_project_deletion():
    store = Store(":memory:")
    projects = ProjectStore(store)
    projects.create("p", {"name": "Demo"})
    row = version()
    row["analysis"] = None
    projects.save("p", row, new=True)
    store.connection.execute("DELETE FROM project_versions WHERE project_id='p'")
    assert store.connection.execute("SELECT COUNT(*) FROM project_version_summaries").fetchone()[0] == 0
    store.close()


def test_bounded_cache_reclamation_honors_stale_grace_and_preserves_history(monkeypatch):
    monkeypatch.setattr("backend.app.db.time.time", lambda: 1000)
    store = Store(":memory:", cache_stale_grace_seconds=100, cache_prune_batch=2)
    store.save_job({"job_id": "history", "status": "completed"})
    for key, kind, expires in [("recent", "search", 950), ("old1", "search", 800),
                               ("old2", "page", 800), ("old3", "fast-video-search-v2", 800),
                               ("unknown", "future_kind", 800)]:
        store.connection.execute("INSERT INTO cache VALUES(?,?,?,?,?)", (key, kind, 700, expires, dumps({"source": key})))
    assert store.cache_get("recent") is None
    assert store.cache_get("recent", allow_stale=True)["cache"]["stale"]
    assert store.cache_get("old1", allow_stale=True) is None
    store.cache_set("new", "search", {"result": "new"}, 20)
    assert store.connection.execute("SELECT COUNT(*) FROM cache WHERE key LIKE 'old%'").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM cache WHERE key='unknown'").fetchone()[0] == 1
    assert store.get_job("history")["status"] == "completed"
    assert store.cache_get("recent", allow_stale=True)
    store.cache_set("new2", "search", {}, 20)
    assert store.connection.execute("SELECT COUNT(*) FROM cache WHERE key LIKE 'old%'").fetchone()[0] == 1
    store.close()


@pytest.mark.asyncio
async def test_progress_is_coalesced_but_cards_and_terminal_flush_immediately():
    writes = []
    publisher = CoalescedPublisher(lambda value: writes.append(deepcopy(value)), interval=.03)
    base = {"status": "running", "recommendations": {}, "progress": {"requests": 0},
            "catalog_enrichment": {"status": "running"}}
    publisher(deepcopy(base))
    for i in range(1, 8):
        publisher({**base, "progress": {"requests": i}})
    assert len(writes) == 1
    await asyncio.sleep(.05)
    assert len(writes) == 2 and writes[-1]["progress"]["requests"] == 7
    publisher({**base, "recommendations": {"k1": [{"url": "https://example.org/course"}]}})
    assert len(writes) == 3
    publisher({**base, "status": "cancelled", "catalog_enrichment": {"status": "cancelled"}})
    assert writes[-1]["status"] == "cancelled"
    publisher.close()
    saved = len(writes)
    await asyncio.sleep(.04)
    assert len(writes) == saved


def raw_snapshot():
    resource = {"resource_id": "r1", "url": "https://example.org/course", "title": "Arrays",
                "thumbnail_url": None, "cover_status": "failed", "cover_error_code": "timeout",
                "field_provenance": {"title": {"source_url": "https://example.org/course"}}}
    return {"project_id": "p", "updated_at": "t1", "current_version": 1,
            "version": {"version": 1, "status": "completed", "updated_at": "t1", "budgets": {},
                        "fast_video_search": {"status": "completed", "elapsed_seconds": 2,
                            "recommendations": {"k1": [{"resource": resource}]},
                            "progress": {"search_requests": 1}, "diagnostics": {"payload": "x" * 10000},
                            "catalog_enrichment": {"status": "partial"}}},
            "points": [{"result": {"video_recommendations": [{"resource": resource}],
                                   "evidence": [{"source": "page", "text": "Arrays"}]}}]}


def test_ui_projection_keeps_evidence_and_stable_content_revision():
    raw = raw_snapshot()
    first = snapshot_payload(raw, "ui")
    assert "recommendations" not in first["version"]["fast_video_search"]
    assert "diagnostics" not in first["version"]["fast_video_search"]
    assert first["points"] == raw["points"]
    raw["updated_at"] = raw["version"]["updated_at"] = "t2"
    raw["version"]["fast_video_search"]["diagnostics"] = {"different": True}
    assert snapshot_payload(raw, "ui")["snapshot_revision"] == first["snapshot_revision"]
    raw["points"][0]["result"]["video_recommendations"][0]["resource"]["cover_status"] = "available"
    assert snapshot_payload(raw, "ui")["snapshot_revision"] != first["snapshot_revision"]
    assert "diagnostics" in snapshot_payload(raw)["version"]["fast_video_search"]


@pytest.mark.asyncio
async def test_get_etag_and_sse_share_ui_projection_without_starting_work(tmp_path):
    app = create_app(Settings(database_path=str(tmp_path / "api.sqlite3"), fetch_enabled=False, llm_provider="none"))
    raw = raw_snapshot()
    async with app.router.lifespan_context(app):
        app.state.projects = SimpleNamespace(results=lambda *_: deepcopy(raw), view=lambda *_: deepcopy(raw))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                     base_url="http://127.0.0.1") as client:
            path = "/api/projects/p/results?projection=ui"
            response = await client.get(path)
            assert response.status_code == 200
            etag = response.headers["etag"]
            assert etag == '"' + response.json()["snapshot_revision"] + '"'
            same = await client.get(path, headers={"If-None-Match": "W/" + etag})
            assert same.status_code == 304 and same.content == b""
            full = await client.get("/api/projects/p/results", headers={"If-None-Match": etag})
            assert full.status_code == 200 and "diagnostics" in full.json()["version"]["fast_video_search"]
            stream = await client.get("/api/projects/p/events?projection=ui")
            frames = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
            assert frames[0]["snapshot_revision"] == response.json()["snapshot_revision"]
            assert "diagnostics" not in frames[0]["version"]["fast_video_search"]
            assert app.state.service.queue.empty()


@pytest.mark.asyncio
async def test_mobile_etag_never_bypasses_capability_or_expiry_checks(tmp_path):
    from scripts.validate_mobile_boundary import create_fixture_app, Ticket, LoopbackOnly
    with LoopbackOnly() as guard:
        app = create_fixture_app(Path(__file__).resolve().parents[1], tmp_path / "mobile", {"hold_search": True})
        ticket, wrong = Ticket.fresh(), Ticket.fresh()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                         base_url="http://127.0.0.1") as client:
                payload = {"kind": "direct_search", "request": {"knowledge_points": ["Python list indexing"],
                           "preferred_platforms": ["bilibili"]}}
                assert (await client.post(ticket.path, headers=ticket.headers, json=payload)).status_code == 202
                await client.post(ticket.path + "/cancel", headers=ticket.headers)
                path = ticket.path + "?projection=ui"
                response = await client.get(path, headers=ticket.headers)
                assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
                headers = {**ticket.headers, "If-None-Match": response.headers["etag"]}
                assert (await client.get(path, headers=headers)).status_code == 304
                assert (await client.get(path, headers={**wrong.headers, "If-None-Match": response.headers["etag"]})).status_code == 404
                assert (await client.get(path + "&token=forbidden", headers=headers)).status_code == 404
                stream = await client.get(ticket.path + "/events?projection=ui", headers=ticket.headers)
                assert stream.status_code == 200 and "event: complete" in stream.text
                record = app.state.mobile.records[ticket.task_id]
                app.state.mobile.clock = lambda: record["expires_at"] + 1
                assert (await client.get(path, headers=headers)).status_code == 404
        assert guard.blocked == 0
