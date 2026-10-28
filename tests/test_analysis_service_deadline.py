"""Offline queue, persistence and history checks for the one-minute analysis budget."""
import asyncio
import time

import pytest

from backend.app import project_service as module
from backend.app.project_analysis import ProjectAnalyzer
from backend.app.project_models import ProjectInput
from tests.test_projects import document, setup


def create(projects):
    return projects.create(ProjectInput(name="本地统计", requirements="读取成绩并统计"))["project_id"]


async def finish(projects):
    await asyncio.gather(*list(projects.analysis_tasks.values()))


@pytest.mark.asyncio
async def test_queue_timeout_finishes_without_calling_analyzer(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", 0.05)
    _, store, _, projects = setup(tmp_path)
    await projects.analysis_slots.acquire()
    await projects.analysis_slots.acquire()
    try:
        pid = create(projects)
        projects.analyze(pid, 0)
        await finish(projects)
        result = projects.db.version(pid, 1)
        assert projects.analyzer.calls == 0
        assert result["status"] == "analysis_failed" and result["analysis"] is None
        assert result["error"]["code"] == "timeout"
        timing = result["analysis_timing"]
        assert timing["finished_at"] and timing["processing_seconds"] is None
        assert timing["queue_wait_seconds"] == timing["elapsed_seconds"]
        assert projects.analysis_slots.locked()
    finally:
        projects.analysis_slots.release()
        projects.analysis_slots.release()
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_queue_consumes_same_deadline_and_old_version_bytes_are_unchanged(tmp_path, monkeypatch):
    settings, store, _, projects = setup(tmp_path)
    pid = create(projects)
    projects.analyze(pid, 0)
    await finish(projects)
    original = store.connection.execute(
        "SELECT data FROM project_versions WHERE project_id=? AND version=1", (pid,)).fetchone()[0]
    monkeypatch.setattr(module, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", 0.5)

    class Recorder(ProjectAnalyzer):
        async def analyze(self, project, *, deadline, **_callbacks):
            self.deadline = deadline
            self.received_at = asyncio.get_running_loop().time()
            return document()

    projects.analyzer = Recorder(settings)
    await projects.analysis_slots.acquire()
    await projects.analysis_slots.acquire()
    try:
        started = asyncio.get_running_loop().time()
        projects.analyze(pid, 1)
        await asyncio.sleep(0.03)
        projects.analysis_slots.release()
        await finish(projects)
        recorder = projects.analyzer
        # The absolute deadline was set at admission, rather than after the queue.
        assert 0 < recorder.deadline - recorder.received_at < 0.475
        assert recorder.deadline - started <= 0.48
        assert projects.db.version(pid, 2)["status"] == "analyzed"
        assert projects.db.version(pid, 2)["analysis_timing"]["queue_wait_seconds"] >= 0.02
        assert store.connection.execute(
            "SELECT data FROM project_versions WHERE project_id=? AND version=1", (pid,)).fetchone()[0] == original
    finally:
        projects.analysis_slots.release()
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_processing_timeout_cancels_work_and_releases_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", 0.05)
    _, store, _, projects = setup(tmp_path)

    class WaitingAnalyzer:
        available = True
        cancelled = False

        async def analyze(self, _project):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    projects.analyzer = WaitingAnalyzer()
    try:
        pid = create(projects)
        projects.analyze(pid, 0)
        await finish(projects)
        result = projects.db.version(pid, 1)
        assert result["status"] == "analysis_failed" and result["error"]["code"] == "timeout"
        assert result["analysis"] is None and result["analysis_timing"]["finished_at"]
        assert projects.analyzer.cancelled and projects.analysis_slots._value == 2
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_synchronous_validation_overrun_never_becomes_success(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", 0.04)
    _, store, _, projects = setup(tmp_path)
    original_context = module.generated_context

    def delayed_context(value):
        time.sleep(0.06)
        return original_context(value)

    monkeypatch.setattr(module, "generated_context", delayed_context)
    try:
        pid = create(projects)
        projects.analyze(pid, 0)
        await finish(projects)
        result = projects.db.version(pid, 1)
        assert result["status"] == "analysis_failed" and result["error"]["code"] == "timeout"
        assert result["analysis"] is None and "validated_concept_context" not in result
        assert projects.analysis_slots._value == 2
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_explicit_cancellation_keeps_terminal_timing_and_releases_slot(tmp_path):
    _, store, _, projects = setup(tmp_path)
    started = asyncio.Event()

    class WaitingAnalyzer:
        available = True

        async def analyze(self, _project):
            started.set()
            await asyncio.Event().wait()

    projects.analyzer = WaitingAnalyzer()
    try:
        pid = create(projects)
        projects.analyze(pid, 0)
        await started.wait()
        task = next(iter(projects.analysis_tasks.values()))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = projects.db.version(pid, 1)
        assert result["error"]["code"] == "cancelled" and result["status"] == "cancelled"
        assert result["cancel_requested"] is True
        assert result["analysis"] is None and result["analysis_timing"]["finished_at"]
        assert projects.analysis_slots._value == 2
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_legacy_large_settings_cannot_extend_admission_deadline(tmp_path):
    settings, store, _, projects = setup(tmp_path, project_analysis_timeout_seconds=180,
                                       project_analysis_total_timeout_seconds=600)

    class Recorder(ProjectAnalyzer):
        async def analyze(self, project, *, deadline, **_callbacks):
            self.remaining = deadline - asyncio.get_running_loop().time()
            return document()

    projects.analyzer = Recorder(settings)
    try:
        pid = create(projects)
        projects.analyze(pid, 0)
        await finish(projects)
        assert 0 < projects.analyzer.remaining <= 59.5
        assert projects.db.version(pid, 1)["analysis_timing"]["budget_seconds"] == 60
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_capabilities_describe_compact_checks_without_claiming_semantic_review(tmp_path):
    _, store, _, projects = setup(tmp_path)
    try:
        capability = projects.capabilities()["project_analysis"]
        assert capability["generation_stages"] == ["compact_generation"]
        assert capability["max_model_calls"] == 1 and capability["repair_max_calls"] == 0
        assert not capability["local_checks_enabled"] and capability["coverage_self_check"] == "disabled"
        assert capability["schema_safety_checks_enabled"]
        assert not capability["semantic_completeness_certified"]
        assert not any(capability[key] for key in (
            "semantic_review_enabled", "coverage_review_enabled", "implementation_inventory_enabled"))
        assert all(capability[key] == 0 for key in (
            "review_max_calls", "coverage_completion_max_calls", "semantic_correction_max_calls"))
        assert capability["timeout_includes_queue"]
        assert capability["total_timeout_seconds"] <= 60 and capability["per_call_timeout_seconds"] <= 60
    finally:
        await projects.stop()
        store.close()
