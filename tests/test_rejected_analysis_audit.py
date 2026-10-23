"""Offline audit retention checks; rejected drafts never become usable analyses."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.db import Store
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from backend.app.project_models import ProjectInput
from backend.app.project_service import ProjectService
from tests.test_project_analysis import flat_analysis_fixture as analysis_fixture, request, settings


def rejected_document(marker="rejected-original"):
    body = analysis_fixture()
    body["scope"] = marker
    body["knowledge_points"][0]["name"] = "Python基础"
    return body


def install_replies(monkeypatch, replies):
    calls = []

    async def generate(*args, **kwargs):
        calls.append((args, kwargs))
        item = replies[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return deepcopy(item)

    monkeypatch.setattr(module, "complete_json", generate)
    return calls


def start_analysis(service, project_input):
    project = service.create(project_input)
    service.analyze(project["project_id"], 0)
    return project["project_id"], service.analysis_tasks[(project["project_id"], 1)]


@pytest.mark.asyncio
async def test_rejected_full_document_survives_successful_repair_and_persistence(monkeypatch):
    bad = rejected_document()
    calls = install_replies(monkeypatch, [bad, analysis_fixture()])
    configured = settings()
    store = Store(":memory:")
    service = ProjectService(configured, store, None, ProjectAnalyzer(configured))
    try:
        project_id, task = start_analysis(service, request())
        await task
        version = service.view(project_id)["version"]
        assert version["status"] == "analyzed" and version["error"] is None
        entries = version["rejected_analysis_attempts"]
        assert len(entries) == 1 and len(calls) == 2
        entry = entries[0]
        assert entry["analysis"] == bad  # Preserve the complete rejected flat proposal.
        assert set(entry["analysis"]) == {"scope", "technical_plan", "assumptions", "knowledge_points"}
        assert entry["attempt"] == 1 and entry["category"] == "quality"
        assert entry["project_id"] == project_id and entry["version"] == 1
        assert entry["prompt_version"] == module.ANALYSIS_PROMPT_VERSION
        assert entry["model"] == configured.llm_model and entry["recorded_at"]
        assert version["analysis"]["knowledge_points"][0]["name"] != "Python基础"
        assert "learner_profile" not in version["analysis"]
        attempts = version["analysis_attempts"]
        assert [(row["phase"], row["outcome"]) for row in attempts] == [
            ("generation", "rejected"), ("normalization", "accepted")]
        assert [row["analysis"] for row in attempts] == [bad, analysis_fixture()]
        assert all(row["project_id"] == project_id and row["version"] == 1 for row in attempts)
        assert service.db.version(project_id, 1)["analysis_attempts"] == attempts
    finally:
        await service.stop()
        store.close()


@pytest.mark.asyncio
async def test_two_rejected_drafts_retain_distinct_complete_candidates(monkeypatch):
    first, second = rejected_document("first-complete-draft"), rejected_document("second-complete-draft")
    install_replies(monkeypatch, [first, second])
    entries = []
    with pytest.raises(AnalysisError) as failure:
        await ProjectAnalyzer(settings()).analyze(request(), on_rejected_attempt=entries.append)
    assert failure.value.code == "quality"
    assert [entry["attempt"] for entry in entries] == [1, 2]
    assert [entry["analysis"] for entry in entries] == [first, second]
    assert all(entry["category"] == "quality" for entry in entries)
    diagnostics = json.dumps(failure.value.diagnostics, ensure_ascii=False)
    assert "first-complete-draft" not in diagnostics and "second-complete-draft" not in diagnostics


@pytest.mark.asyncio
async def test_timeout_after_rejection_does_not_reuse_previous_candidate(monkeypatch):
    bad = rejected_document("first-draft-before-timeout")
    install_replies(monkeypatch, [bad, httpx.ReadTimeout("private timeout response")])
    entries = []
    with pytest.raises(AnalysisError) as failure:
        await ProjectAnalyzer(settings()).analyze(request(), on_rejected_attempt=entries.append)
    assert failure.value.code == "timeout"
    assert [entry["category"] for entry in entries] == ["quality", "timeout"]
    assert entries[0]["analysis"] == bad
    assert entries[1].get("analysis") is None
    assert "private timeout response" not in json.dumps(entries) + json.dumps(failure.value.diagnostics)


@pytest.mark.asyncio
@pytest.mark.parametrize("secret_field", ["llm_api_key", "tavily_api_key", "serper_api_key"])
@pytest.mark.parametrize("suffix", ["plain", 'quote"key', r"backslash\key"])
async def test_configured_secret_is_omitted_from_drafts_and_diagnostics(monkeypatch, secret_field, suffix):
    secret = "audit-test-secret-" + secret_field + suffix
    configured = replace(settings(), **{secret_field: secret})
    bad = rejected_document(secret)
    install_replies(monkeypatch, [bad, bad])
    entries, attempts = [], []
    with pytest.raises(AnalysisError) as failure:
        await ProjectAnalyzer(configured).analyze(request(), on_rejected_attempt=entries.append,
                                                 on_analysis_attempt=attempts.append)
    assert len(entries) == 2
    assert len(attempts) == 2 and all(entry["outcome"] == "rejected" for entry in attempts)
    assert all(entry.get("analysis") is None for entry in entries)
    assert all(entry.get("analysis") is None for entry in attempts)
    assert all(entry.get("omitted_reason") for entry in entries)
    assert secret not in json.dumps(entries) + json.dumps(attempts) + json.dumps(failure.value.diagnostics)


@pytest.mark.asyncio
async def test_concurrent_service_analyses_keep_rejected_drafts_in_their_own_versions(monkeypatch):
    counts = {}
    second_calls = set()
    both_second_calls = asyncio.Event()

    async def generate(_settings, _prompt, payload, *_args, **_kwargs):
        name = payload["project"]["name"]
        counts[name] = counts.get(name, 0) + 1
        if counts[name] == 1:
            return rejected_document("private-draft-" + name)
        second_calls.add(name)
        if len(second_calls) == 2:
            both_second_calls.set()
        await asyncio.wait_for(both_second_calls.wait(), 2)
        body = analysis_fixture()
        body["scope"] = "accepted-" + name
        return body

    monkeypatch.setattr(module, "complete_json", generate)
    configured = settings()
    store = Store(":memory:")
    service = ProjectService(configured, store, None, ProjectAnalyzer(configured))
    try:
        first_id, first_task = start_analysis(service, ProjectInput(name="project-a", requirements=request().requirements))
        second_id, second_task = start_analysis(service, ProjectInput(name="project-b", requirements=request().requirements))
        await asyncio.gather(first_task, second_task)
        for project_id, name, other in [(first_id, "project-a", "project-b"), (second_id, "project-b", "project-a")]:
            version = service.view(project_id)["version"]
            assert version["status"] == "analyzed"
            entries = version["rejected_analysis_attempts"]
            assert len(entries) == 1
            assert entries[0]["project_id"] == project_id and entries[0]["version"] == 1
            assert entries[0]["analysis"]["scope"] == "private-draft-" + name
            assert "private-draft-" + other not in json.dumps(entries)
            attempts = version["analysis_attempts"]
            assert [entry["outcome"] for entry in attempts] == ["rejected", "accepted"]
            assert [entry["analysis"]["scope"] for entry in attempts] == ["private-draft-" + name, "accepted-" + name]
            assert all(entry["project_id"] == project_id and entry["version"] == 1 for entry in attempts)
            assert "private-draft-" + other not in json.dumps(attempts)
            assert "accepted-" + other not in json.dumps(attempts)
    finally:
        await service.stop()
        store.close()


@pytest.mark.asyncio
async def test_first_rejection_is_saved_before_repair_and_survives_cancel_recovery(monkeypatch):
    second_started = asyncio.Event()
    never_finish = asyncio.Event()
    bad = rejected_document("preserve-before-cancel")
    call_count = 0

    async def generate(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return deepcopy(bad)
        second_started.set()
        await never_finish.wait()

    monkeypatch.setattr(module, "complete_json", generate)
    configured = settings()
    store = Store(":memory:")
    service = ProjectService(configured, store, None, ProjectAnalyzer(configured))
    try:
        project_id, task = start_analysis(service, request())
        await asyncio.wait_for(second_started.wait(), 2)
        stored = service.db.version(project_id, 1)
        assert stored["status"] == "analyzing" and stored["analysis"] is None
        assert stored["rejected_analysis_attempts"][0]["analysis"] == bad
        assert len(stored["analysis_attempts"]) == 1
        assert stored["analysis_attempts"][0]["outcome"] == "rejected"
        assert stored["analysis_attempts"][0]["analysis"] == bad
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        service.db.recover_analysis()
        recovered = service.view(project_id)["version"]
        assert recovered["status"] == "analysis_failed"
        assert recovered["error"]["code"] == "interrupted"
        assert recovered["analysis"] is None
        assert recovered["rejected_analysis_attempts"] == stored["rejected_analysis_attempts"]
        assert recovered["analysis_attempts"] == stored["analysis_attempts"]
        for table in ("project_functions", "project_knowledge_points", "project_prerequisites"):
            assert store.connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project_id,)).fetchone()[0] == 0
    finally:
        await service.stop()
        store.close()
