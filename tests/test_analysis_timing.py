"""Analysis timing survives later actions and includes time in the local queue."""
import asyncio
from datetime import datetime

import pytest

from backend.app.project_analysis import AnalysisError
from backend.app.project_models import ProjectInput
from test_projects import setup


@pytest.mark.asyncio
async def test_analysis_timing_includes_queue_and_is_immutable_after_confirmation(tmp_path):
    _, store, _, projects = setup(tmp_path)
    await projects.analysis_slots.acquire()
    await projects.analysis_slots.acquire()
    project_id = projects.create(ProjectInput(name="本地统计", requirements="读取成绩并统计"))["project_id"]
    projects.analyze(project_id, 0)
    await asyncio.sleep(.02)
    waiting = projects.db.version(project_id, 1)["analysis_timing"]
    assert waiting["finished_at"] is None and waiting["queue_wait_seconds"] is None
    assert projects.analyzer.calls == 0
    projects.analysis_slots.release()
    await asyncio.gather(*projects.analysis_tasks.values())
    view = projects.view(project_id)
    timing = view["version"]["analysis_timing"]
    assert view["version"]["status"] == "analyzed"
    assert timing["queue_wait_seconds"] >= .01
    assert timing["elapsed_seconds"] >= timing["queue_wait_seconds"]
    assert timing["processing_seconds"] >= 0
    assert timing["elapsed_seconds"] == pytest.approx(
        (datetime.fromisoformat(timing["finished_at"]) - datetime.fromisoformat(timing["started_at"])).total_seconds(), abs=1e-6)
    projects.confirm(project_id, 1, [])
    assert projects.view(project_id)["version"]["analysis_timing"] == timing
    changes = store.connection.total_changes
    projects.results(project_id, 1)
    assert store.connection.total_changes == changes
    projects.analysis_slots.release()
    await projects.stop()
    store.connection.close()


@pytest.mark.asyncio
async def test_failed_analysis_has_terminal_timing_without_usable_analysis(tmp_path):
    _, store, _, projects = setup(tmp_path)

    class FailingAnalyzer:
        available = True

        async def analyze(self, project):
            raise AnalysisError("quality", "知识点名称未通过校验")

    projects.analyzer = FailingAnalyzer()
    project_id = projects.create(ProjectInput(name="本地统计", requirements="读取成绩并统计"))["project_id"]
    projects.analyze(project_id, 0)
    await asyncio.gather(*projects.analysis_tasks.values())
    version = projects.view(project_id)["version"]
    assert version["status"] == "analysis_failed" and version["analysis"] is None
    assert version["analysis_timing"]["finished_at"]
    assert version["analysis_timing"]["elapsed_seconds"] >= 0
    await projects.stop()
    store.connection.close()
