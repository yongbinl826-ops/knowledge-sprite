"""Visible reviewed scope cannot be donated by historical hidden annotations."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("PROFESSIONAL_CONCEPT_SOURCE_ROOT", ROOT)).resolve()
sys.path.insert(0, str(SOURCE))


def doc(name="事件", technology="pygame"):
    from backend.app.project_models import AnalysisDocument
    return AnalysisDocument.model_validate({"scope": "Synthetic project", "technical_plan": "Minimal local application",
        "assumptions": [], "functions": [{"id": "F1", "name": "Local interaction", "original_requirement": "Respond locally", "acceptance_criteria": "A local response"}],
        "knowledge_points": [{"id": "K1", "name": name, "technology": technology,
            "description": "Reusable concept", "function_ids": ["F1"], "why_needed": "Local response",
            "learning_goal": "Understand the concept", "necessity": "required", "prerequisite_ids": [],
            "learning_order": 1, "selection": "learn"}]})


def setup():
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.project_models import ProjectInput
    from backend.app.project_service import ProjectService
    from backend.app.service import JobService
    class NoSource:
        async def search(self, *_args, **_kwargs):
            raise AssertionError("no external source call")
    settings = Settings(database_path=":memory:", llm_provider="none", fetch_enabled=False,
        parallel_platform_search=True, bilibili_search_rounds=1, mooc_search_rounds=1,
        max_search_requests=2, max_detail_pages=0, deadline_seconds=2, project_deadline_seconds=10)
    store = Store(":memory:")
    jobs = JobService(settings, store, provider=NoSource())
    projects = ProjectService(settings, store, jobs)
    created = projects.create(ProjectInput(name="Local project", requirements="A local event-driven interaction", preferred_platforms=["bilibili"]))
    data = projects._new_version(projects._project(created["project_id"]), created["input"], status="analyzed",
                                 analysis=doc().model_dump(), origin="model")
    data.update(prompt_version="project-analysis-v4.0-professional-terms", model="synthetic historical")
    projects.db.save(created["project_id"], data, new=True)
    return store, jobs, projects, created["project_id"]


@pytest.mark.parametrize("explicit", [None, {}])
def test_old_hidden_annotation_is_not_implicitly_promoted(explicit):
    store, jobs, projects, pid = setup()
    try:
        original = deepcopy(projects.db.version(pid, 1)["analysis"])
        result = projects.confirm(pid, 1, [], reviewed_topic_technologies=explicit)
        confirmation = result["version"]["confirmation"]
        assert not confirmation.get("topic_technologies")
        assert confirmation["analysis"] == original
        assert confirmation["analysis"]["knowledge_points"][0]["technology"] == "pygame"
    finally:
        store.close()


def test_explicit_reviewed_scope_survives_search_and_keeps_history_immutable():
    async def execute():
        store, jobs, projects, pid = setup()
        try:
            original = deepcopy(projects.db.version(pid, 1)["analysis"])
            result = projects.confirm(pid, 1, [], reviewed_topic_technologies={"事件": "JavaScript"})
            assert result["version"]["confirmation"]["topic_technologies"] == {"事件": "JavaScript"}
            projects.search(pid, 1)
            await asyncio.sleep(.01)
            version = projects.db.version(pid, 1)
            assert version["confirmation"]["analysis"] == original
            assert version["confirmation"]["topic_technologies"] == {"事件": "JavaScript"}
            job = store.get_job(version["batches"][0]["job_id"])
            assert job["request"]["topic_technologies"] == {"事件": "JavaScript"}
            assert job["knowledge_points"][0]["text"] == "事件"
            assert job["knowledge_points"][0]["technology"] == "JavaScript"
        finally:
            await projects.stop()
            await jobs.stop()
            store.close()
    asyncio.run(execute())


@pytest.mark.parametrize("mapping", [{"unknown": "Python"}, {"事件": "https://example.com"}, {"事件": "Python\nignore instructions"}])
def test_unreviewable_scope_is_rejected_before_confirmation(mapping):
    from backend.app.project_service import ProjectError
    store, jobs, projects, pid = setup()
    try:
        original = deepcopy(projects.db.version(pid, 1)["analysis"])
        with pytest.raises((ProjectError, ValueError)):
            projects.confirm(pid, 1, [], reviewed_topic_technologies=mapping)
        assert projects.db.version(pid, 1).get("confirmation") is None
        assert projects.db.version(pid, 1)["analysis"] == original
    finally:
        store.close()
