"""Historical repair-coordinate helpers and current single-generation boundaries."""
from copy import deepcopy

import pytest

from backend.app.config import Settings
from backend.app.project_analysis import GeneratedConceptList, ProjectAnalyzer, _quality_repair_targets
from backend.app.project_models import ProjectInput
from tests.professional_contract_support import coverage_completion, draft_with_inventory, is_semantic_review_payload, semantic_review_pass_for_payload, successful_analysis_response, unrepaired_quality_response


PROJECT = ProjectInput(name="本地图表", requirements="按类别统计数据并显示柱状图")


def proposal():
    return {"scope": "本地数据图表", "technical_plan": "使用 JavaScript 和 ECharts", "assumptions": [],
            "knowledge_points": [
                {"name": "数组", "description": "理解有序数据集合，用于保存观测数据。", "technology": "JavaScript"},
                {"name": "分组聚合", "description": "按类别归并记录，计算各组的统计结果。", "technology": "JavaScript"},
                {"name": "柱状图", "description": "用矩形长度编码数值，比较各类别的数量。", "technology": "ECharts"}]}


def targets(issues, draft=None):
    draft = draft or proposal()
    return _quality_repair_targets(issues, draft, GeneratedConceptList.model_validate(draft).to_document())


def test_targets_resolve_zero_based_indices_point_ids_and_existing_candidate_values():
    issues = [
        {"code": "broad_subject", "point_id": "k1", "message": "Use a specific concept."},
        {"code": "invalid_topic_technology", "point_id": "k2",
         "location": ["knowledge_points", "k2", "technology"], "message": "Use literal technology."},
        {"code": "frame_duration_upper_bound", "point_id": "k3",
         "location": "knowledge_points[2].description", "message": "Describe the mechanism accurately."},
    ]
    draft = proposal()
    assert targets(issues, draft) == [
        {"location": ["knowledge_points", index, field], "current_value": draft["knowledge_points"][index][field],
         "code": issue["code"], "message": issue["message"]}
        for index, (field, issue) in enumerate(zip(("name", "technology", "description"), issues))]
    assert draft == proposal()


@pytest.mark.parametrize("issue", [
    {"code": "broad_subject", "point_id": "k99"},
    {"code": "broad_subject", "point_id": "k1", "location": ["knowledge_points", 2, "name"]},
    {"code": "broad_subject", "point_id": "k1", "location": ["knowledge_points", 99, "name"]},
    {"code": "broad_subject", "point_id": "k1", "location": ["knowledge_points", 0, "id"]},
    {"code": "broad_subject", "point_id": "k1", "location": ["knowledge_points", 0, "selection"]},
    {"code": "broad_subject", "location": ["scope"]},
    {"code": "numeric_api_contract", "point_id": "k1"},
])
def test_unlocatable_or_ambiguous_feedback_never_invents_a_candidate_target(issue):
    assert targets([{**issue, "message": "Original static feedback."}]) == []


def test_targets_are_bounded_and_never_copy_missing_or_oversized_values():
    issue = {"code": "broad_subject", "point_id": "k1", "message": "Original static feedback."}
    assert len(targets([issue] * 100)) == 30
    draft = proposal()
    document = GeneratedConceptList.model_validate(draft).to_document()
    for field, oversized in (("name", "n" * 81), ("technology", "t" * 49), ("description", "d" * 801)):
        for present in (True, False):
            changed = deepcopy(draft)
            if present:
                changed["knowledge_points"][0][field] = oversized
            else:
                changed["knowledge_points"][0].pop(field)
            assert _quality_repair_targets([{**issue, "location": ["knowledge_points", 0, field]}], changed, document) == []


async def run_analyzer(monkeypatch, responses, quality_issues=None):
    calls = []
    async def complete(_settings, _prompt, payload, _client, **_options):
        calls.append(deepcopy(payload))
        if is_semantic_review_payload(payload):
            assert len(calls) == 2
            return semantic_review_pass_for_payload(payload)
        return successful_analysis_response(payload, responses[len(calls) - 1], PROJECT)
    monkeypatch.setattr("backend.app.project_analysis.complete_json", complete)
    if quality_issues is not None:
        def forbidden_quality_gate(*_args, **_kwargs):
            pytest.fail("Single-generation analysis must not run a content quality gate")
        monkeypatch.setattr("backend.app.project_analysis.professional_contract_issues", forbidden_quality_gate)
    settings = Settings(llm_provider="openai_compatible", llm_base_url="https://offline.invalid/v1",
                        llm_api_key="offline-test-token", llm_model="offline-model")
    result = await ProjectAnalyzer(settings).analyze(PROJECT)
    return result, calls


@pytest.mark.asyncio
async def test_valid_first_draft_needs_no_extra_call_or_repair_targets(monkeypatch):
    result, calls = await run_analyzer(monkeypatch, [proposal()])
    assert len(calls) == 1
    assert "repair_targets" not in calls[0]
    assert "previous_analysis" not in calls[0]
    assert "implementation_inventory" not in calls[0]
    assert len(result.knowledge_points) == 3


@pytest.mark.asyncio
async def test_generation_retains_a_formerly_rejected_name_without_repair_payload(monkeypatch):
    rejected = proposal()
    rejected["knowledge_points"][0]["name"] = "Python入门"
    draft = draft_with_inventory(rejected, PROJECT)
    result, calls = await run_analyzer(monkeypatch, [rejected, proposal()])
    assert len(calls) == 1
    assert "repair_targets" not in calls[0]
    assert "previous_analysis" not in calls[0] and "validation_feedback" not in calls[0]
    assert "implementation_inventory" not in calls[0]
    assert result.knowledge_points[0].name == "Python入门"
    assert result.knowledge_points[0].description == rejected["knowledge_points"][0]["description"]


@pytest.mark.asyncio
async def test_generation_does_not_invoke_legacy_content_issues_or_invent_feedback(monkeypatch):
    issue = {"code": "numeric_api_contract", "point_id": "k99", "message": "Original static feedback."}
    draft = draft_with_inventory(proposal(), PROJECT)
    _, calls = await run_analyzer(monkeypatch, [proposal(), proposal()], [issue])
    assert len(calls) == 1
    assert "validation_feedback" not in calls[0]
    assert "repair_targets" not in calls[0]
    assert "previous_analysis" not in calls[0]


def test_successful_name_patch_fixture_changes_only_authorized_names():
    original, repaired = proposal(), proposal()
    original["knowledge_points"][0]["name"] = "Python入门"
    repaired["knowledge_points"][2]["name"] = "未授权名称不会进入补丁"
    payload = {"repair_format": "name_patch", "previous_analysis": original,
               "allowed_indices": [0, 1], "required_indices": [0]}
    assert successful_analysis_response(payload, repaired, PROJECT) == {"name_repairs": [
        {"index": 0, "original_name": "Python入门", "name": "数组"}]}
    assert unrepaired_quality_response(payload, repaired, PROJECT) == {"name_repairs": [
        {"index": 0, "original_name": "Python入门", "name": "Python入门"}]}
