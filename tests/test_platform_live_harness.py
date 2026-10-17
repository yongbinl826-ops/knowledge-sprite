"""Offline fault injection for the live audit side channel; no HTTP is sent."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from backend.app.config import Settings
from backend.app.fetcher import FetchStopped, HTTPResult, NETWORK_OBSERVER
from backend.app.service import JobService
from scripts import serve_platform_live_chain as harness

JOB_ID = "00000000-0000-0000-0000-000000000001"


@contextmanager
def audit_context(folder):
    state = {"folder": folder, "output": folder, "job_id": JOB_ID, "sequence": 0,
             "response_count": 0, "acceptance_valid": True, "audit_errors": []}
    registry = {"output": str(folder), "acceptance_valid": True, "audit_errors": [], "jobs": {}}
    job_token, registry_token = harness.CURRENT_JOB.set(state), harness.CURRENT_AUDIT.set(registry)
    try:
        yield state, registry
    finally:
        harness.CURRENT_AUDIT.reset(registry_token)
        harness.CURRENT_JOB.reset(job_token)


def unavailable(*args, **kwargs):
    raise OSError("sensitive error text must not enter logs")


def fake_fetcher(request, policy=lambda url: "allowed"):
    fetcher = SimpleNamespace(_request=request, _site_policy=policy, request_trace=[])
    def trace(event, url, **fields):
        fetcher.request_trace.append({"event": event, "url": url, **fields})
        return "original-trace-return"
    fetcher._trace = trace
    harness.instrument_fetcher(fetcher)
    return fetcher


@pytest.mark.asyncio
async def test_all_disk_failures_do_not_change_http_return_or_parent_callbacks(tmp_path, monkeypatch):
    result = HTTPResult(200, {}, b"actual test transport bytes", "https://example.org/course")
    parent_seen = []
    async def request(url, max_bytes, *, kind):
        NETWORK_OBSERVER.get()["response"](result, kind)
        return result
    fetcher = fake_fetcher(request)
    token = NETWORK_OBSERVER.set({"response": lambda response, kind: parent_seen.append((response, kind))})
    try:
        with audit_context(tmp_path) as (state, registry):
            monkeypatch.setattr(Path, "open", unavailable)
            assert await fetcher._request(result.url, 1000, kind="page") is result
            assert fetcher._trace("http_completed", result.url) == "original-trace-return"
            assert fetcher._site_policy(result.url) == "allowed"
            assert parent_seen == [(result, "page")]
            assert state["acceptance_valid"] is registry["acceptance_valid"] is False
            assert registry["audit_errors"] and state["audit_errors"]
            assert all(row["error_type"] == "OSError" for row in state["audit_errors"])
            assert "sensitive" not in str(registry)
    finally:
        NETWORK_OBSERVER.reset(token)


def test_original_policy_exception_survives_observer_exception(tmp_path, monkeypatch):
    original = FetchStopped("site_policy_blocked", "original policy outcome", {"basis": "real policy"})
    def denied(url):
        raise original
    fetcher = fake_fetcher(None, denied)
    monkeypatch.setattr(harness, "append_event", unavailable)
    with audit_context(tmp_path) as (state, _):
        with pytest.raises(FetchStopped) as caught:
            fetcher._site_policy("https://example.org/course")
        assert caught.value is original
        assert not state["acceptance_valid"]
    errors = [json.loads(line) for line in (tmp_path / "audit-errors.jsonl").read_text().splitlines()]
    assert errors[0]["operation"] == "policy_blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["returned", "error", "cancelled"])
async def test_dns_trace_is_copied_after_mutation_and_original_outcome_survives(tmp_path, outcome):
    record = {"status": "running", "http_status": None}
    sentinel = RuntimeError("production exception") if outcome == "error" else asyncio.CancelledError()
    parent_seen = []
    result = object()
    async def request(url, max_bytes, *, kind):
        NETWORK_OBSERVER.get()["dns_trace"](record)
        try:
            if outcome != "returned":
                raise sentinel
            return result
        finally:
            record.update(status={"returned": "completed", "error": "failed", "cancelled": "cancelled"}[outcome],
                          http_status=200 if outcome == "returned" else None, elapsed_seconds=0.123)
    fetcher = fake_fetcher(request)
    token = NETWORK_OBSERVER.set({"dns_trace": parent_seen.append})
    try:
        with audit_context(tmp_path):
            if outcome == "returned":
                assert await fetcher._request("https://example.org/course", 1000, kind="page") is result
            else:
                with pytest.raises(type(sentinel)) as caught:
                    await fetcher._request("https://example.org/course", 1000, kind="page")
                assert caught.value is sentinel
        assert parent_seen == [record]
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        start, final = events
        assert start["event_type"] == "dns_http_trace_started"
        assert start["snapshot_stage"] == "started_not_terminal"
        assert start["trace"]["status"] == "running"
        assert final["event_type"] == "dns_http_trace_final"
        assert final["terminal_status_observed"] is True
        assert final["trace"] == record
        assert final["trace"]["elapsed_seconds"] == 0.123
    finally:
        NETWORK_OBSERVER.reset(token)


@pytest.mark.asyncio
async def test_dns_parent_exception_is_not_swallowed_and_running_final_is_not_claimed_complete(tmp_path):
    original = RuntimeError("parent budget hook failed")
    def parent(record):
        raise original
    async def request(url, max_bytes, *, kind):
        NETWORK_OBSERVER.get()["dns_trace"]({"status": "running"})
    fetcher = fake_fetcher(request)
    token = NETWORK_OBSERVER.set({"dns_trace": parent})
    try:
        with audit_context(tmp_path):
            with pytest.raises(RuntimeError) as caught:
                await fetcher._request("https://example.org/course", 1000, kind="page")
            assert caught.value is original
        final = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[-1])
        assert final["snapshot_stage"] == "request_finally"
        assert final["terminal_status_observed"] is False
    finally:
        NETWORK_OBSERVER.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["returned", "error", "cancelled"])
async def test_job_export_failure_never_replaces_production_return_or_exception(tmp_path, monkeypatch, outcome):
    result = object()
    sentinel = RuntimeError("production error") if outcome == "error" else asyncio.CancelledError()
    async def original_run(self, job_id):
        if outcome != "returned":
            raise sentinel
        return result
    monkeypatch.setattr(JobService, "run", original_run)
    monkeypatch.setattr(harness, "write_json", unavailable)
    audited = harness.service_class(tmp_path)
    service = audited.__new__(audited)
    service.store = SimpleNamespace(get_job=lambda job_id: {"status": "completed"}, resources=lambda job_id: {})
    service.results = lambda job_id: {}
    if outcome == "returned":
        assert await service.run(JOB_ID) is result
    else:
        with pytest.raises(type(sentinel)) as caught:
            await service.run(JOB_ID)
        assert caught.value is sentinel
    assert harness.CURRENT_JOB.get() is None
    assert harness.CURRENT_AUDIT.get() is None
    errors = [json.loads(line) for line in (tmp_path / "audit-errors.jsonl").read_text().splitlines()]
    assert {row["operation"] for row in errors} >= {"write_input", "export_job", "write_audit_status"}
    assert all(row["acceptance_valid"] is False for row in errors)


def test_write_json_failure_sets_memory_and_best_effort_invalid_record(tmp_path, monkeypatch):
    original_open = Path.open
    def fail_main_only(path, *args, **kwargs):
        if path.name == "result.json":
            raise OSError("main audit storage failure")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_main_only)
    with audit_context(tmp_path) as (state, registry):
        assert harness.write_json(tmp_path / "result.json", {"value": 1}) is None
        assert not state["acceptance_valid"] and not registry["acceptance_valid"]
    assert (tmp_path / "audit-errors.jsonl").is_file()


def database(path, status):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE jobs(id TEXT,status TEXT,data TEXT)")
        connection.execute("INSERT INTO jobs VALUES(?,?,?)", (JOB_ID, status, "{}"))


@pytest.mark.parametrize("status", ["queued", "running"])
def test_resume_refuses_active_jobs_without_mutation(tmp_path, status):
    path = tmp_path / "live.sqlite3"
    database(path, status)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="queued or running"):
        harness.check_resume_database(path)
    assert path.read_bytes() == before


def test_resume_requires_database(tmp_path):
    with pytest.raises(ValueError, match="existing live database"):
        harness.check_resume_database(tmp_path / "live.sqlite3")


def test_resume_preserves_original_startup_and_job_evidence(tmp_path, monkeypatch):
    root, phase = tmp_path / "repo", tmp_path / "phase"
    (root / "frontend/dist").mkdir(parents=True)
    (root / "frontend/dist/index.html").write_text("production frontend")
    (phase / "baseline").mkdir(parents=True)
    (phase / "baseline/manifest.json").write_text("{}")
    (phase / "startup.json").write_text('{"original": true}')
    (phase / "jobs" / JOB_ID).mkdir(parents=True)
    evidence = phase / "jobs" / JOB_ID / "events.jsonl"
    evidence.write_text('{"existing_network_evidence": true}\n')
    database(phase / "live.sqlite3", "completed")
    before = {path: path.read_bytes() for path in (phase / "startup.json", phase / "live.sqlite3", evidence)}
    monkeypatch.setattr(harness, "ROOT", root)
    monkeypatch.setattr(harness, "PHASE", phase)
    monkeypatch.setattr(harness, "source_hashes", lambda: {"backend/app/service.py": "current-source-sha"})
    monkeypatch.setattr(harness.Settings, "from_env", lambda: Settings(searxng_url="http://127.0.0.1:18780"))
    original_service = harness.main_module.JobService
    try:
        with pytest.raises(ValueError, match="reuse"):
            harness.app_for(phase)
        app = harness.app_for(phase, resume=True)
        assert all(path.read_bytes() == content for path, content in before.items())
        resumes = list(phase.glob("resume-*.json"))
        assert len(resumes) == 1
        manifest = json.loads(resumes[0].read_text(encoding="utf-8"))
        assert manifest["source_hashes"] == {"backend/app/service.py": "current-source-sha"}
        assert manifest["resume"]["original_startup_sha256"] == harness.sha(before[phase / "startup.json"])
        assert manifest["resume"]["no_queued_or_running_jobs"] is True
        assert app.state.live_chain_audit_registry["acceptance_valid"] is True
    finally:
        harness.main_module.JobService = original_service
