"""Analysis performance observations stay in backend audit, never UI snapshots."""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.snapshot_transport import mobile_snapshot, snapshot_payload


def analysis_snapshot(status="analyzed"):
    trace = {"phase": "generation", "model_elapsed_seconds": 12.5,
             "validation_elapsed_seconds": 0.001,
             "completion": {"usage": {"input_tokens": 800, "output_tokens": 1200,
                                         "reasoning_tokens": 0, "answer_tokens": 1200},
                            "http_headers_seconds": 0.3}}
    return {"project_id": "p", "current_version": 1,
            "versions": [{"version": 1, "status": status, "created_at": "t0"}],
            "version": {"version": 1, "status": status, "created_at": "t0", "batches": [],
                        "analysis": {"knowledge_points": [{"name": "类与对象", "description": "概念与项目用途。"}]},
                        "analysis_timing": {"elapsed_seconds": 12.6, "queue_wait_seconds": 0.002},
                        "analysis_attempts": [trace], "rejected_analysis_attempts": [deepcopy(trace)],
                        "error": {"code": "schema", "message": "输入已保留。",
                                  "diagnostics": [{"type": "attempt_history", "attempts": [deepcopy(trace)]}]}
                        if status == "analysis_failed" else None},
            "points": []}


@pytest.mark.parametrize("status", ["analyzed", "analysis_failed"])
def test_ui_hides_analysis_statistics_without_modifying_full_or_historical_record(status):
    raw = analysis_snapshot(status)
    original = deepcopy(raw)
    ui, full = snapshot_payload(raw, "ui"), snapshot_payload(raw, "full")
    for key in ("analysis_timing", "analysis_attempts", "rejected_analysis_attempts"):
        assert key not in ui["version"]
        assert full["version"][key] == original["version"][key]
    assert ui["version"]["analysis"] == original["version"]["analysis"]
    if status == "analysis_failed":
        assert ui["version"]["error"] == {"code": "schema", "message": "输入已保留。"}
        assert full["version"]["error"]["diagnostics"] == original["version"]["error"]["diagnostics"]
    for hidden in ("reasoning_tokens", "answer_tokens", "model_elapsed_seconds", "http_headers_seconds"):
        assert hidden not in json.dumps(ui)
    assert raw == original


def test_analysis_diagnostics_alone_do_not_change_visible_revision():
    raw = analysis_snapshot("analysis_failed")
    first = snapshot_payload(raw, "ui")["snapshot_revision"]
    raw["version"]["analysis_timing"]["elapsed_seconds"] = 31
    raw["version"]["analysis_attempts"][0]["completion"]["usage"]["output_tokens"] = 3000
    raw["version"]["rejected_analysis_attempts"].append({"phase": "generation", "elapsed_seconds": 32})
    raw["version"]["error"]["diagnostics"].append({"type": "private_performance_observation"})
    assert snapshot_payload(raw, "ui")["snapshot_revision"] == first
    raw["version"]["error"]["message"] = "可重新分析。"
    assert snapshot_payload(raw, "ui")["snapshot_revision"] != first


def test_mobile_ui_projection_uses_same_private_audit_boundary():
    raw = {"status": "completed", "result": analysis_snapshot()}
    original = deepcopy(raw)
    ui = mobile_snapshot(raw, "ui")
    assert "analysis_timing" not in ui["result"]["version"]
    assert "analysis_attempts" not in ui["result"]["version"]
    assert "rejected_analysis_attempts" not in ui["result"]["version"]
    assert mobile_snapshot(raw, "full")["result"]["version"]["analysis_attempts"]
    assert raw == original


@pytest.mark.asyncio
async def test_http_get_and_sse_hide_stats_but_full_read_keeps_audit(tmp_path):
    app = create_app(Settings(database_path=str(tmp_path / "ui-privacy.sqlite3"),
                              fetch_enabled=False, llm_provider="none"))
    raw = analysis_snapshot("analysis_failed")
    async with app.router.lifespan_context(app):
        app.state.projects = SimpleNamespace(results=lambda *_: deepcopy(raw), view=lambda *_: deepcopy(raw))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                     base_url="http://127.0.0.1") as client:
            for path in ("/api/projects/p?projection=ui", "/api/projects/p/results?projection=ui"):
                response = await client.get(path)
                assert response.status_code == 200
                version = response.json()["version"]
                assert "analysis_timing" not in version and "analysis_attempts" not in version
                assert "rejected_analysis_attempts" not in version
                assert "diagnostics" not in version["error"]
            stream = await client.get("/api/projects/p/events?projection=ui")
            assert stream.status_code == 200
            frames = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
            assert frames
            assert all("analysis_timing" not in frame["version"] for frame in frames)
            assert all("analysis_attempts" not in frame["version"] for frame in frames)
            full = await client.get("/api/projects/p")
            assert full.json()["version"]["analysis_attempts"] == raw["version"]["analysis_attempts"]
            assert full.json()["version"]["analysis_timing"] == raw["version"]["analysis_timing"]
            assert app.state.service.queue.empty()
