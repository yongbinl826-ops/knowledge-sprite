"""Old advisory metadata is immutable history, never new generation/edit output."""
from copy import deepcopy

import pytest
import pytest_asyncio

from backend.app import project_analysis as module
from backend.app.db import Store
from backend.app.project_analysis import GeneratedConceptList, ProjectAnalyzer
from backend.app.project_models import AnalysisDocument
from backend.app.project_service import ProjectService
from tests.test_project_analysis import flat_analysis_fixture, request, settings


NOTICE = {
    "code": "textbook_operation_bundle", "severity": "low",
    "location": ["knowledge_points", 0, "name"],
    "disposition": "advisory", "evidence": "title_heuristic",
}


@pytest.fixture(autouse=True)
def forbid_name_or_content_judgement(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Generation and student edits must not run naming/content review")
    for name in ("_local_quality_issues", "_partition_quality_issues", "_name_repair_context",
                 "learning_quality_issues", "textbook_concept_issues", "professional_contract_issues",
                 "apply_name_repairs"):
        monkeypatch.setattr(module, name, forbidden, raising=False)


@pytest_asyncio.fixture
async def service(tmp_path):
    configured = settings()
    store = Store(str(tmp_path / "advisory-lifecycle.sqlite3"))
    instance = ProjectService(configured, store, None, ProjectAnalyzer(configured))
    try:
        yield instance
    finally:
        await instance.stop()
        store.close()


def raw_version(service, project_id, version):
    return service.store.connection.execute(
        "SELECT data FROM project_versions WHERE project_id=? AND version=?",
        (project_id, version),
    ).fetchone()[0]


def seed_saved_version(service, notices=None):
    """An old saved document is input data, not a new model generation."""
    project = service.create(request())
    document = GeneratedConceptList.model_validate(flat_analysis_fixture()).to_document()
    data = service._new_version(service.db.project(project["project_id"]), request().model_dump(),
                                status="analyzed", analysis=document.model_dump(), origin="offline_history")
    data["legacy_extension"] = {"must_remain_exact": True}
    if notices is not None:
        data["analysis_advisories"] = deepcopy(notices)
    service.db.save(project["project_id"], data, new=True)
    return project["project_id"]


@pytest.mark.asyncio
async def test_new_generation_records_original_output_without_advisories_and_preserves_history(service, monkeypatch):
    project_id = seed_saved_version(service, [NOTICE])
    historical = raw_version(service, project_id, 1)
    candidate = flat_analysis_fixture()
    candidate["knowledge_points"][0]["name"] = "工作表读取与显示刷新"
    calls = []

    async def offline_reply(*args, **kwargs):
        calls.append(True)
        assert len(calls) == 1, "Single-pass analysis must not spend a repair request"
        return deepcopy(candidate)

    monkeypatch.setattr(module, "complete_json", offline_reply)
    service.analyze(project_id, 1)
    await service.analysis_tasks[(project_id, 2)]
    version = service.db.version(project_id, 2)
    assert version["status"] == "analyzed" and version["error"] is None
    assert "analysis_advisories" not in version
    assert version["analysis_attempts"][0]["outcome"] == "accepted"
    assert "advisories" not in version["analysis_attempts"][0]
    assert version["analysis_attempts"][0]["validation_scope"] == "schema_safety_limits"
    assert version["analysis_attempts"][0]["analysis"] == candidate
    assert version["analysis"]["knowledge_points"][0]["name"] == candidate["knowledge_points"][0]["name"]
    assert len(calls) == 1
    assert raw_version(service, project_id, 1) == historical
    assert service.db.version(project_id, 1)["analysis_advisories"] == [NOTICE]


@pytest.mark.asyncio
async def test_student_edits_never_copy_advisories_and_preserve_every_old_version(service):
    project_id = seed_saved_version(service, [NOTICE])
    before = {1: raw_version(service, project_id, 1)}
    original = service.db.version(project_id, 1)

    # A checkbox change preserves the concept and leaves prior hints in history only.
    selection = deepcopy(original["analysis"])
    selection["knowledge_points"][0]["selection"] = "skip"
    service.edit(project_id, 1, AnalysisDocument.model_validate(selection))
    version2 = service.db.version(project_id, 2)
    assert "analysis_advisories" not in version2
    before[2] = raw_version(service, project_id, 2)

    # Reordering remains an ordinary edit; it does not create a new review pass.
    reordered = deepcopy(version2["analysis"])
    reordered["knowledge_points"].reverse()
    service.edit(project_id, 2, AnalysisDocument.model_validate(reordered))
    version3 = service.db.version(project_id, 3)
    assert "analysis_advisories" not in version3
    assert version3["analysis"]["knowledge_points"][1]["id"] == original["analysis"]["knowledge_points"][0]["id"]
    before[3] = raw_version(service, project_id, 3)

    # User-entered names are preserved without a naming verdict or auto-rewrite.
    renamed = deepcopy(version3["analysis"])
    renamed["knowledge_points"][1]["name"] = "工作表解析"
    service.edit(project_id, 3, AnalysisDocument.model_validate(renamed))
    assert "analysis_advisories" not in service.db.version(project_id, 4)
    assert service.db.version(project_id, 4)["analysis"] == renamed
    for number, raw in before.items():
        assert raw_version(service, project_id, number) == raw


@pytest.mark.asyncio
async def test_replacement_identity_does_not_inherit_notice_for_same_title(service):
    project_id = seed_saved_version(service, [NOTICE])
    historical = raw_version(service, project_id, 1)
    replacement = deepcopy(service.db.version(project_id, 1)["analysis"])
    replacement["knowledge_points"][0]["id"] = "replacement-point"
    service.edit(project_id, 1, AnalysisDocument.model_validate(replacement))
    assert "analysis_advisories" not in service.db.version(project_id, 2)
    assert raw_version(service, project_id, 1) == historical


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [-1, 999, True, False, 0.5, "0", None])
async def test_old_notice_indices_are_never_used_or_carried_to_an_edit(service, index):
    invalid = {**NOTICE, "location": ["knowledge_points", index, "name"]}
    project_id = seed_saved_version(service, [invalid])
    historical = raw_version(service, project_id, 1)
    document = AnalysisDocument.model_validate(service.db.version(project_id, 1)["analysis"])
    service.edit(project_id, 1, document)
    assert "analysis_advisories" not in service.db.version(project_id, 2)
    assert raw_version(service, project_id, 1) == historical


@pytest.mark.asyncio
async def test_editing_legacy_version_without_advisories_does_not_invent_new_findings(service):
    project_id = seed_saved_version(service)
    historical = raw_version(service, project_id, 1)
    document = AnalysisDocument.model_validate(service.db.version(project_id, 1)["analysis"])
    service.edit(project_id, 1, document)
    assert "analysis_advisories" not in service.db.version(project_id, 2)
    assert raw_version(service, project_id, 1) == historical
