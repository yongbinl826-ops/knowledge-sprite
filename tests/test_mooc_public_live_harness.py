"""The audit runner observes production bytes without altering network outcomes."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.fetcher import HTTPResult, NETWORK_OBSERVER
from backend.app.service import JobService
from scripts import serve_mooc_public_live as harness

JOB_ID = "00000000-0000-0000-0000-000000000001"


@contextmanager
def audit_context(folder):
    state = {"folder": folder, "output": folder, "job_id": JOB_ID, "sequence": 0,
             "response_count": 1, "acceptance_valid": True, "audit_errors": []}
    registry = {"output": str(folder), "acceptance_valid": True, "audit_errors": [], "jobs": {}}
    job_token = harness.audit.CURRENT_JOB.set(state)
    registry_token = harness.audit.CURRENT_AUDIT.set(registry)
    try:
        yield state, registry
    finally:
        harness.audit.CURRENT_AUDIT.reset(registry_token)
        harness.audit.CURRENT_JOB.reset(job_token)


def result(url="https://www.icourse163.org/course/PKU-12345", *, status=200, content_type="text/html"):
    return HTTPResult(status, {"content-type": content_type, "set-cookie": "never persist this header"},
                      b"<html>actual anonymous test transport \xe5\xad\x97\xe8\x8a\x82</html>", url)


def test_saves_exact_fresh_body_and_matching_hash_without_headers(tmp_path):
    response = result()
    with audit_context(tmp_path):
        harness.capture_public_mooc_response(response, "page")
    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    assert (tmp_path / event["file"]).read_bytes() == response.body
    assert event["body_sha256"] == harness.audit.sha(response.body)
    assert event["body_bytes"] == len(response.body)
    assert event["saved_headers"] is event["saved_cookies"] is event["replayed_into_extractor"] is False
    assert "set-cookie" not in str(event) and "never persist" not in str(event)


@pytest.mark.parametrize("response,kind", [
    (result("https://www.icourse163.org/web/j/mocTermDtoRpcBean.getMocTermDto.rpc"), "page"),
    (result("https://www.icourse163.org/learn/PKU-12345"), "page"),
    (result("https://www.icourse163.org/course/PKU-12345/private"), "page"),
    (result("https://www.icourse163.org.attacker.example/course/PKU-12345"), "page"),
    (result("https://user:password@www.icourse163.org/course/PKU-12345"), "page"),
    (result("https://www.icourse163.org:9876/course/PKU-12345"), "page"),
    (result(status=403), "page"),
    (result(status=302), "page"),
    (result(content_type="application/json"), "page"),
    (result(), "robots"),
])
def test_does_not_archive_api_other_host_private_path_or_non_html_response(tmp_path, response, kind):
    with audit_context(tmp_path):
        harness.capture_public_mooc_response(response, kind)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_capture_failure_does_not_replace_production_result_or_parent_observer(tmp_path, monkeypatch):
    response, sentinel, seen = result(), object(), []
    async def original_run(self, job_id):
        NETWORK_OBSERVER.get()["response"](response, "page")
        return sentinel
    monkeypatch.setattr(JobService, "run", original_run)
    def failed_capture(*args):
        raise OSError("private exception detail")
    monkeypatch.setattr(harness, "capture_public_mooc_response", failed_capture)
    registry = {"output": str(tmp_path), "acceptance_valid": True, "audit_errors": [], "jobs": {}}
    klass = harness.service_class(tmp_path, registry)
    service = klass.__new__(klass)
    service.store = SimpleNamespace(get_job=lambda job_id: {"status": "completed"}, resources=lambda job_id: {})
    service.results = lambda job_id: {}
    parent = {"response": lambda *items: seen.append(items), "request_budget": "unchanged"}
    token = NETWORK_OBSERVER.set(parent)
    try:
        assert await service.run(JOB_ID) is sentinel
        assert NETWORK_OBSERVER.get() is parent
        assert seen == [(response, "page")]
    finally:
        NETWORK_OBSERVER.reset(token)
    assert registry["acceptance_valid"] is False
    assert registry["audit_errors"][0]["operation"] == "save_public_mooc_response"
    assert "private exception" not in str(registry)


@pytest.mark.asyncio
async def test_parent_response_exception_and_context_are_preserved(tmp_path, monkeypatch):
    sentinel = RuntimeError("parent budget exception")
    def parent_response(*args):
        raise sentinel
    async def original_run(self, job_id):
        NETWORK_OBSERVER.get()["response"](result(content_type="application/json"), "page")
    monkeypatch.setattr(JobService, "run", original_run)
    registry = {"output": str(tmp_path), "acceptance_valid": True, "audit_errors": [], "jobs": {}}
    klass = harness.service_class(tmp_path, registry)
    service = klass.__new__(klass)
    service.store = SimpleNamespace(get_job=lambda job_id: {"status": "completed"}, resources=lambda job_id: {})
    service.results = lambda job_id: {}
    parent = {"response": parent_response}
    token = NETWORK_OBSERVER.set(parent)
    try:
        with pytest.raises(RuntimeError) as caught:
            await service.run(JOB_ID)
        assert caught.value is sentinel
        assert NETWORK_OBSERVER.get() is parent
    finally:
        NETWORK_OBSERVER.reset(token)


def test_offline_routes_preserve_configuration_and_no_jobs_or_network(tmp_path, monkeypatch):
    from backend.app.config import Settings
    from fastapi.testclient import TestClient
    from dataclasses import replace
    root, phase, output = tmp_path / "root", tmp_path / "phase", tmp_path / "output"
    (root / "frontend/dist").mkdir(parents=True)
    (root / "frontend/dist/index.html").write_text("built frontend")
    phase.mkdir()
    (phase / "baseline.json").write_text("{}")
    configured = Settings(database_path="original.sqlite3", max_detail_pages=3,
                          allowed_restricted_hosts=("example.org",), search_provider="searxng")
    monkeypatch.setattr(harness, "ROOT", root)
    monkeypatch.setattr(harness, "PHASE", phase)
    monkeypatch.setattr(harness, "source_hashes", lambda: {"source": "hash"})
    monkeypatch.setattr(harness.Settings, "from_env", lambda: configured)
    original_service = harness.main_module.JobService
    try:
        app = harness.app_for(output, offline_check=True)
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            assert client.get("/health").json()["job_counts"] == {}
            assert client.get("/api/capabilities").status_code == 200
            assert app.state.service.settings == replace(configured, database_path=str(output / "live.sqlite3"))
            assert app.state.store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
            assert client.get("/api/live-audit").json()["jobs"] == {}
        assert not (output / "jobs").exists()
        startup = json.loads((output / "startup.json").read_text(encoding="utf-8"))
        assert startup["isolation"]["no_seed_data"] is True
        assert startup["isolation"]["only_setting_overridden"] == "database_path"
    finally:
        harness.main_module.JobService = original_service


def test_revision_path_is_fixed_and_unknown_revision_cannot_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "PHASE", tmp_path)
    assert harness.evidence_folder() == tmp_path
    assert harness.evidence_folder("outline-length-repair") == tmp_path / "revisions/outline-length-repair"
    assert harness.evidence_folder("outline-boundary-repair") == tmp_path / "revisions/outline-boundary-repair"
    assert harness.REVISION_PORTS["outline-boundary-repair"] == 18021
    with pytest.raises(ValueError, match="Unknown"):
        harness.evidence_folder("../../elsewhere")
    with pytest.raises(ValueError, match="fixed"):
        harness.app_for(tmp_path, revision="outline-length-repair")


def test_revision_creates_fresh_database_and_preserves_parent_evidence(tmp_path, monkeypatch):
    from backend.app.config import Settings
    from fastapi.testclient import TestClient
    root, phase = tmp_path / "root", tmp_path / "phase"
    (root / "frontend/dist").mkdir(parents=True)
    (root / "frontend/dist/index.html").write_text("built frontend")
    phase.mkdir()
    (phase / "baseline.json").write_text('{"source":"preceding baseline"}')
    originals = {"live.sqlite3": b"parent database must never be opened or copied",
                 "startup.json": b'{"old":"startup"}', "verification.json": b'{"truncated":true}'}
    for filename, data in originals.items():
        (phase / filename).write_bytes(data)
    monkeypatch.setattr(harness, "ROOT", root)
    monkeypatch.setattr(harness, "PHASE", phase)
    monkeypatch.setattr(harness, "source_hashes", lambda: {"source": "revision-hash"})
    monkeypatch.setattr(harness.Settings, "from_env", lambda: Settings(database_path="original.sqlite3"))
    output = harness.evidence_folder("outline-length-repair")
    original_service = harness.main_module.JobService
    try:
        app = harness.app_for(output, revision="outline-length-repair")
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            assert client.get("/health").json()["job_counts"] == {}
            assert app.state.service.settings.database_path == str(output / "live.sqlite3")
            assert app.state.store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
        assert all((phase / filename).read_bytes() == data for filename, data in originals.items())
        startup = json.loads((output / "startup.json").read_text(encoding="utf-8"))
        assert startup["revision"]["name"] == "outline-length-repair"
        assert startup["revision"]["parent_database_or_cache_imported"] is False
        assert startup["isolation"]["database_initially_absent"] is True
        assert startup["baseline_manifest_sha256"] == harness.audit.sha((phase / "baseline.json").read_bytes())
        new_startup = (output / "startup.json").read_bytes()
        with pytest.raises(ValueError, match="reuse"):
            harness.app_for(output, revision="outline-length-repair")
        assert (output / "startup.json").read_bytes() == new_startup
    finally:
        harness.main_module.JobService = original_service
