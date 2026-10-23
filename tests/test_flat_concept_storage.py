"""Offline compatibility tests for flat concepts, historical records and search."""
import asyncio
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from backend.app.mobile_tasks import MobileTaskPayload
from backend.app.project_models import AnalysisDocument, ProjectInput
from tests.test_projects import document as historical_document, setup, settle


POINT_FIELDS = {"id", "name", "description", "technology", "selection"}
DOCUMENT_FIELDS = {"scope", "technical_plan", "assumptions", "analysis_format", "knowledge_points"}


def flat_body():
    names = ["CSV 解析", "缺失值处理", "数值转换", "分组聚合", "数据排序", "柱状图", "文件下载"]
    ids = ["zeta", "alpha", "k7", "k2", "beta", "k1", "omega"]
    return {
        "analysis_format": "concept_list_v1", "scope": "本地读取成绩表并输出统计报告",
        "technical_plan": "使用 Python 处理本地数据", "assumptions": ["数据以 CSV 文件提供"],
        "knowledge_points": [{"id": point_id, "name": name,
                              "description": "学习该数据处理技术，用于输入成绩表的统计与报告输出。",
                              "technology": "Python", "selection": "learn"}
                             for point_id, name in zip(ids, names)],
    }


def test_flat_dump_and_mobile_search_payload_never_restore_legacy_fields():
    source = flat_body()
    parsed = AnalysisDocument.model_validate(source)
    assert parsed.model_dump() == source
    assert json.loads(parsed.model_dump_json()) == source
    assert set(parsed.model_dump()) == DOCUMENT_FIELDS
    assert all(set(point) == POINT_FIELDS for point in parsed.model_dump()["knowledge_points"])
    round_trip = AnalysisDocument.model_validate(parsed.model_dump())
    assert round_trip.model_dump() == source
    mobile = MobileTaskPayload.model_validate({"kind": "search",
        "input": ProjectInput(name="统计工具", requirements="读取成绩并生成报告").model_dump(),
        "analysis": source})
    assert mobile.model_dump()["analysis"] == source


@pytest.mark.parametrize("field,value", [
    ("function_ids", []), ("why_needed", "用于报告"), ("learning_goal", "完成处理"),
    ("necessity", "required"), ("prerequisite_ids", []), ("learning_order", 1),
    ("project_task", None), ("concepts", []), ("learning_skills", []), ("practice_check", None),
])
def test_flat_points_reject_explicit_legacy_fields_even_when_empty(field, value):
    source = flat_body()
    source["knowledge_points"][0][field] = value
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(source)


@pytest.mark.parametrize("change", [
    lambda source: source["knowledge_points"][1].update(id="zeta"),
    lambda source: source["knowledge_points"][1].update(name=" csv   解析 "),
    lambda source: source["knowledge_points"][0].update(description="  "),
    lambda source: source["knowledge_points"][0].update(description="https://untrusted.example/course"),
])
def test_flat_identity_and_safe_text_validation_still_apply(change):
    source = flat_body()
    change(source)
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(source)


@pytest.mark.asyncio
async def test_flat_generation_edit_confirm_and_search_keep_model_array_order(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    source = flat_body()

    class FlatAnalyzer:
        available = True

        async def analyze(self, _input):
            return AnalysisDocument.model_validate(source)

    projects.analyzer = FlatAnalyzer()
    jobs.start()
    try:
        initial = projects.create(ProjectInput(name="统计工具", requirements="读取成绩并生成报告", preferred_platforms=["bilibili"]))
        pid = initial["project_id"]
        projects.analyze(pid, 0)
        await asyncio.gather(*projects.analysis_tasks.values())
        generated = projects.view(pid)["version"]
        assert generated["status"] == "analyzed"
        assert generated["analysis"] == source
        for table in ("project_functions", "project_prerequisites"):
            assert store.connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (pid,)).fetchone()[0] == 0
        edited = deepcopy(source)
        edited["knowledge_points"][1]["selection"] = "skip"
        saved = projects.edit(pid, 1, AnalysisDocument.model_validate(edited))
        assert saved["version"]["analysis"] == edited
        confirmed = projects.confirm(pid, 2, ["unused-legacy-ack"])["version"]["confirmation"]
        selected = [point for point in edited["knowledge_points"] if point["selection"] == "learn"]
        assert confirmed["selected_ids"] == [point["id"] for point in selected]
        assert confirmed["analysis"] == edited
        assert "acknowledged_skipped_prerequisites" not in confirmed
        projects.search(pid, 2)
        await settle(projects)
        result = projects.results(pid, 2)
        assert [point["project_knowledge_point_id"] for point in result["points"]] == [point["id"] for point in edited["knowledge_points"]]
        batches = result["version"]["batches"]
        assert [batch["project_knowledge_point_ids"] for batch in batches] == [
            [point["id"] for point in selected[:5]], [point["id"] for point in selected[5:]]]
        for batch, wanted in zip(batches, [selected[:5], selected[5:]]):
            request = store.get_job(batch["job_id"])["request"]
            assert request["knowledge_points"] == [point["name"] for point in wanted]
            assert request["topic_technologies"] == {point["name"]: "Python" for point in wanted}
        assert projects.view(pid, 1)["version"]["analysis"] == source
        assert result["functions"] == []
    finally:
        await projects.stop()
        await jobs.stop()
        store.close()


@pytest.mark.asyncio
async def test_historical_analysis_and_confirmation_survive_flat_version_without_migration(tmp_path):
    _, store, jobs, projects = setup(tmp_path)
    try:
        legacy = historical_document(3).model_dump()
        legacy["knowledge_points"][0]["learning_order"] = 3
        legacy["knowledge_points"][1]["learning_order"] = 2
        legacy["knowledge_points"][2].update(learning_order=1, prerequisite_ids=["k0"])
        parsed = AnalysisDocument.model_validate(legacy)
        assert parsed.model_dump() == legacy and "analysis_format" not in parsed.model_dump()
        initial = projects.create(ProjectInput(name="历史项目", requirements="读取成绩并生成报告"))
        pid = initial["project_id"]
        version = projects._new_version(projects._project(pid), initial["input"], status="analyzed", analysis=legacy)
        projects.db.save(pid, version, new=True)
        confirmed = projects.confirm(pid, 1, ["ignored"])["version"]["confirmation"]
        assert confirmed["selected_ids"] == ["k0", "k1", "k2"]  # Stored array, not learning_order.
        assert confirmed["analysis"] == legacy
        # Existing historical confirmation fields are retained on later reads.
        old = projects.db.version(pid, 1)
        old["confirmation"]["acknowledged_skipped_prerequisites"] = ["k0"]
        projects.db.save(pid, old)
        original_row = store.connection.execute("SELECT data FROM project_versions WHERE project_id=? AND version=1", (pid,)).fetchone()[0]
        new = projects.edit(pid, 1, AnalysisDocument.model_validate(flat_body()))
        assert new["version"]["analysis"] == flat_body()
        assert projects.view(pid, 1)["version"]["analysis"] == legacy
        assert projects.view(pid, 1)["version"]["confirmation"] == old["confirmation"]
        assert store.connection.execute("SELECT data FROM project_versions WHERE project_id=? AND version=1", (pid,)).fetchone()[0] == original_row
        assert store.connection.execute("SELECT COUNT(*) FROM project_prerequisites WHERE project_id=? AND version=1", (pid,)).fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM project_prerequisites WHERE project_id=? AND version=2", (pid,)).fetchone()[0] == 0
    finally:
        await projects.stop()
        store.close()
