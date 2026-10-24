import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.result_stream import attempts_limited, event, job_snapshot, pipeline, project_snapshot, result_events


class Connection:
    disconnected = False

    async def is_disconnected(self):
        return self.disconnected


@pytest.mark.asyncio
async def test_terminal_recommendations_keep_stream_for_late_catalog_and_reconnect():
    initial = {"pipeline": {"terminal": True, "catalog_pending": True}, "title": "课程"}
    state = {"revision": 0, "value": initial}
    stream = result_events(Connection(), lambda: deepcopy(state["value"]), lambda: state["revision"],
                           deepcopy(initial), initial_revision=0, interval=.001, heartbeat=.002)
    assert "event: snapshot" in await anext(stream)
    assert await anext(stream) == ": keep-alive\n\n"  # Not prematurely complete.
    state["value"] = {"pipeline": {"terminal": True, "catalog_pending": True}, "title": "课程 · 第三章"}
    state["revision"] += 1
    assert '课程 · 第三章' in await anext(stream)
    await stream.aclose()
    # GET reconnection reads current data and continues metadata updates only.
    stream = result_events(Connection(), lambda: deepcopy(state["value"]), lambda: state["revision"],
                           deepcopy(state["value"]), initial_revision=1, interval=.001)
    assert "event: snapshot" in await anext(stream)
    state["value"]["pipeline"]["catalog_pending"] = False
    state["revision"] += 1
    assert '"catalog_pending":false' in await anext(stream)
    assert "event: complete" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_stream_yields_candidates_before_completion_and_skips_idle_reads():
    state = {"revision": 0, "reads": 0, "value": {"pipeline": {"terminal": False}, "cards": []}}

    def read():
        state["reads"] += 1
        return deepcopy(state["value"])

    stream = result_events(Connection(), read, lambda: state["revision"], read(), initial_revision=0,
                           interval=.001, heartbeat=.005)
    assert '"cards":[]' in await anext(stream)
    assert await anext(stream) == ": keep-alive\n\n"
    assert state["reads"] == 1
    state["value"]["cards"] = ["bilibili"]
    state["revision"] += 1
    assert '"cards":["bilibili"]' in await anext(stream)
    state["value"] = {"pipeline": {"terminal": True}, "cards": ["bilibili", "outline-verified-mooc"]}
    state["revision"] += 1
    assert "event: snapshot" in await anext(stream)
    assert "event: complete" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert state["reads"] == 3


@pytest.mark.asyncio
async def test_disconnect_does_not_read_or_submit_work():
    request = Connection()
    request.disconnected = True
    def forbidden():
        raise AssertionError("No snapshot read after disconnect")
    stream = result_events(request, forbidden, lambda: 0, {"pipeline": {"terminal": False}}, interval=.001)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


def test_pipeline_counts_unique_cards_and_separates_unknown_from_filtering():
    group = {"discovery_only": True, "discovery_items": [{"resource": {"canonical_url": "https://example/a"}}],
             "mooc_relevance": {"status_counts": {"rejected": 2, "outline_no_match": 1, "outline_partial": 1,
                                                  "outline_unavailable": 3, "search_candidate": 2}}}
    job = {"status": "running", "phase": "searching", "progress": {"search_requests": 4,
           "resources_discovered": 20, "details_attempted": 3, "details_completed": 1},
           "budgets": {"max_search_requests": 16}, "errors": [{"code": "rate_limited"}]}
    result = pipeline([group, {**group, "mooc_relevance": {}}], [job], terminal=False)
    assert (result["displayed"], result["filtered"], result["unknown"], result["checking"]) == (1, 4, 5, 2)
    assert result["source_limited"] and result["stage"] == "searching"
    assert pipeline([group], [job], terminal=True)["checking"] == 0


def test_deferred_followup_is_not_terminal_and_new_snapshot_does_not_mutate_service_data():
    raw = {"groups": [], "search_attempts": []}
    job = {"status": "completed", "phase": "awaiting_followup"}
    result = job_snapshot(SimpleNamespace(results=lambda _: raw), SimpleNamespace(get_job=lambda _: job), "a")
    assert not result["pipeline"]["terminal"]
    assert "pipeline" not in raw


def test_project_job_budgets_not_duplicated_and_scope_hidden_results_not_counted():
    raw = {"version": {"status": "running", "batches": [{"job_id": "a"}, {"job_id": "a"}]},
           "points": [{"result": {"discovery_only": True, "discovery_items": []}}]}
    job = {"status": "running", "progress": {"search_requests": 7}, "budgets": {"max_search_requests": 16}}
    result = project_snapshot(SimpleNamespace(results=lambda *_: raw),
                              SimpleNamespace(get_job=lambda _: job, attempts=lambda _: []), "p")
    assert result["pipeline"]["search_requests"] == 7
    assert result["pipeline"]["search_budget"] == 16
    assert not result["pipeline"]["terminal"]
    assert result["pipeline"]["displayed"] == 0


@pytest.mark.asyncio
async def test_http_events_terminal_snapshot_reconnect_no_new_search_and_404(tmp_path):
    settings = Settings(database_path=str(tmp_path / "stream.sqlite"), fetch_enabled=False,
                        llm_provider="none", teaching_match_enabled=False)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        job = {"job_id": "saved", "status": "cancelled", "phase": "done", "knowledge_points": [],
               "progress": {}, "budgets": {}, "warnings": [], "errors": []}
        app.state.store.save_job(job)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                                     base_url="http://127.0.0.1") as client:
            for _ in range(2):
                response = await client.get("/api/search-jobs/saved/events", headers={"Last-Event-ID": "old"})
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.headers["x-accel-buffering"] == "no"
                assert response.text.count("event: snapshot") == 1
                assert response.text.count("event: complete") == 1
                assert '"terminal":true' in response.text
            result = (await client.get("/api/search-jobs/saved/results")).json()
            assert result["job"]["job_id"] == "saved"
            assert result["pipeline"]["terminal"]
            assert (await client.get("/api/search-jobs/missing/events")).status_code == 404
            assert app.state.service.queue.empty()


def test_sse_json_escapes_multiline_data():
    value = event("snapshot", {"title": "课程\nevent: complete\n"})
    assert value.count("\ndata:") == 1
    assert value.count("\nevent:") == 1


@pytest.mark.parametrize("status", ["completed", "partial", "failed", "cancelled", "interrupted"])
def test_terminal_job_states_are_terminal_even_with_null_optional_counters(status):
    job = {"status": status, "phase": "done", "progress": None, "budgets": None, "errors": None}
    snapshot = job_snapshot(SimpleNamespace(results=lambda _: {"groups": []}),
                            SimpleNamespace(get_job=lambda _: job), "a")
    assert snapshot["pipeline"]["terminal"]
    assert snapshot["pipeline"]["checking"] == snapshot["pipeline"]["search_budget"] == 0


@pytest.mark.parametrize("status,terminal,stage", [
    ("analysis_failed", True, "complete"), ("analyzing", False, "analyzing"), ("draft", True, "complete")])
def test_analysis_without_search_budget_is_a_valid_project_snapshot(status, terminal, stage):
    raw = {"version": {"version": 1, "status": status, "budgets": None, "batches": []}, "points": []}
    result = project_snapshot(SimpleNamespace(results=lambda *_: raw), SimpleNamespace(), "p")
    assert result["pipeline"]["terminal"] is terminal
    assert result["pipeline"]["stage"] == stage
    assert result["pipeline"]["search_budget"] == result["pipeline"]["search_requests"] == 0


@pytest.mark.parametrize("attempt", [
    {"error_code": "quota_exhausted"},
    {"error": {"code": "captcha"}},
    {"error_code": "query_budget_exhausted", "provider_requests": [{"error_code": "rate_limited"}]},
])
def test_project_and_job_report_source_limits_even_when_original_error_is_wrapped(attempt):
    job = {"status": "partial", "phase": "done", "errors": []}
    raw = {"version": {"status": "partial", "batches": [{"job_id": "a"}, {"job_id": "a"}]}, "points": []}
    reads = []

    def attempts(job_id):
        reads.append(job_id)
        return [attempt]

    store = SimpleNamespace(get_job=lambda _: job, attempts=attempts)
    project = project_snapshot(SimpleNamespace(results=lambda *_: raw), store, "p")
    single = job_snapshot(SimpleNamespace(results=lambda _: {"groups": [], "search_attempts": [attempt]}), store, "a")
    assert project["pipeline"]["source_limited"] and single["pipeline"]["source_limited"]
    assert reads == ["a"]
    assert not attempts_limited([{"error_code": "timeout", "provider_requests": []}])


@pytest.mark.asyncio
@pytest.mark.parametrize("pass_revision", [True, False])
async def test_final_write_before_generator_start_cannot_be_lost(pass_revision):
    initial = {"pipeline": {"terminal": False}, "cards": []}
    final = {"pipeline": {"terminal": True}, "cards": ["verified"]}
    reads = []

    def read():
        reads.append(1)
        return final

    # The route read initial at revision zero. The final write happened before
    # the streaming response began consuming this async generator.
    kwargs = {"initial_revision": 0} if pass_revision else {}
    stream = result_events(Connection(), read, lambda: 1, initial, interval=.001, **kwargs)
    assert '"terminal":false' in await anext(stream)
    assert '"terminal":true' in await asyncio.wait_for(anext(stream), timeout=.1)
    assert "event: complete" in await anext(stream)
    assert reads == [1]
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_disconnect_after_initial_frame_prevents_more_projection_reads():
    request = Connection()

    def forbidden():
        raise AssertionError("disconnected client must not read another snapshot or revision")

    stream = result_events(request, forbidden, forbidden, {"pipeline": {"terminal": False}},
                           initial_revision=0, interval=.001)
    assert "event: snapshot" in await anext(stream)
    request.disconnected = True
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_cancelled_reader_releases_idle_generator():
    stream = result_events(Connection(), lambda: pytest.fail("idle stream should not project"), lambda: 0,
                           {"pipeline": {"terminal": False}}, initial_revision=0, interval=1)
    await anext(stream)
    reading = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    reading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reading
    await stream.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_deleted_job_ends_stream_with_error_without_new_work():
    stream = result_events(Connection(), lambda: None, lambda: 1,
                           {"pipeline": {"terminal": False}}, initial_revision=0, interval=.001)
    await anext(stream)
    assert "event: error" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_project_stream_pins_initial_version_when_new_analysis_becomes_current(tmp_path):
    app = create_app(Settings(database_path=str(tmp_path / "unused.sqlite"), llm_provider="none"))
    state = {"current": 7, "status": {7: "running", 8: "analyzing"}}
    reads = []

    def results(project_id, version=None):
        reads.append((project_id, version))
        chosen = state["current"] if version is None else version
        return {"version": {"version": chosen, "status": state["status"][chosen], "batches": [], "budgets": None},
                "points": []}

    connection = SimpleNamespace(total_changes=0)
    app.state.projects = SimpleNamespace(results=results)
    app.state.store = SimpleNamespace(connection=connection)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/projects/{project_id}/events")
    response = await endpoint(Connection(), "project", None)
    assert '"version":7' in await anext(response.body_iterator)
    state["current"], state["status"][7] = 8, "completed"
    connection.total_changes = 1
    changed = await asyncio.wait_for(anext(response.body_iterator), timeout=1)
    data = json.loads(next(line[6:] for line in changed.splitlines() if line.startswith("data: ")))
    assert data["version"]["version"] == 7 and data["pipeline"]["terminal"]
    assert reads == [("project", None), ("project", 7)]
    assert "event: complete" in await anext(response.body_iterator)
    await response.body_iterator.aclose()
