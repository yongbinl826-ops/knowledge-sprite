"""Offline boundaries for the shared desktop/mobile project concept limit."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.main import ConfirmProjectRequest
from backend.app.mobile_tasks import MobileTaskPayload
from backend.app.models import SearchRequest
from backend.app.project_models import AnalysisDocument
from backend.app.professional_concepts import reviewed_technologies
from tests.test_projects import analyzed, document, setup


def flat_document(count):
    return {
        "analysis_format": "concept_list_v1", "scope": "离线容量边界测试",
        "technical_plan": "Python 本地数据处理", "assumptions": [],
        "knowledge_points": [{"id": f"k{i}", "name": f"测试概念 {i}",
                              "description": "用于验证知识点容量，不调用外部服务。",
                              "technology": "Python", "selection": "learn"}
                             for i in range(count)],
    }


def test_flat_analysis_accepts_thirty_and_rejects_thirty_one_without_truncation():
    source = flat_document(30)
    assert AnalysisDocument.model_validate(source).model_dump() == source
    with pytest.raises(ValidationError) as exc:
        AnalysisDocument.model_validate(flat_document(31))
    assert any(error["loc"] == ("knowledge_points",) and error["type"] == "too_long"
               for error in exc.value.errors())


def test_historical_graph_supports_thirtieth_order_and_all_twenty_nine_prerequisites():
    source = document(30).model_dump()
    source["knowledge_points"][-1]["prerequisite_ids"] = [f"k{i}" for i in range(29)]
    parsed = AnalysisDocument.model_validate(source)
    assert parsed.knowledge_points[-1].learning_order == 30
    assert parsed.model_dump() == source


def test_reviewed_context_service_guard_uses_the_same_thirty_point_limit():
    points = flat_document(31)["knowledge_points"]
    technologies = {point["name"]: "Python" for point in points}
    with pytest.raises(ValueError, match="bounded name map"):
        reviewed_technologies(technologies, points)


@pytest.mark.parametrize("surface", ["desktop", "mobile"])
def test_confirmation_fields_accept_thirty_and_reject_thirty_one(surface):
    analysis = flat_document(30)
    technologies = {point["name"]: "Python" for point in analysis["knowledge_points"]}
    payload = {"acknowledged_skipped_prerequisites": [f"k{i}" for i in range(30)],
               "reviewed_topic_technologies": technologies}
    if surface == "desktop":
        payload.update(version=1)
        schema = ConfirmProjectRequest
    else:
        payload.update(kind="search", input={"name": "测试项目", "requirements": "本地数据处理"},
                       analysis=analysis)
        schema = MobileTaskPayload
    parsed = schema.model_validate(payload)
    assert len(parsed.acknowledged_skipped_prerequisites) == 30
    assert parsed.reviewed_topic_technologies == technologies
    for field, extra in (("acknowledged_skipped_prerequisites", [f"k{i}" for i in range(31)]),
                         ("reviewed_topic_technologies", {**technologies, "额外概念": "Python"})):
        over_limit = deepcopy(payload)
        over_limit[field] = extra
        with pytest.raises(ValidationError) as exc:
            schema.model_validate(over_limit)
        assert any(error["loc"] == (field,) and error["type"] == "too_long"
                   for error in exc.value.errors())
    if surface == "mobile":
        with pytest.raises(ValidationError) as exc:
            schema.model_validate({**payload, "analysis": flat_document(31)})
        assert any(error["loc"] == ("analysis", "knowledge_points") and error["type"] == "too_long"
                   for error in exc.value.errors())


@pytest.mark.asyncio
async def test_capabilities_and_confirmation_preserve_all_thirty_selected_points(tmp_path):
    _, store, _, projects = setup(tmp_path, fast_video_recommendations_enabled=True)
    try:
        capabilities = projects.capabilities()
        assert capabilities["project_analysis"]["max_knowledge_points"] == 30
        assert capabilities["project_search"]["batch_size"] == 30
        view = await analyzed(projects, 30)
        technologies = {point["name"]: "Python" for point in view["version"]["analysis"]["knowledge_points"]}
        confirmed = projects.confirm(view["project_id"], 1, [], reviewed_topic_technologies=technologies)
        version = confirmed["version"]
        assert version["confirmation"]["selected_ids"] == [f"k{i}" for i in range(30)]
        assert version["confirmation"]["topic_technologies"] == technologies
        assert version["budgets"]["selected_count"] == 30
        assert version["budgets"]["batch_size"] == 30
        assert version["budgets"]["batch_count"] == 1
        assert len(version["analysis"]["knowledge_points"]) == 30
    finally:
        await projects.stop()
        store.close()


@pytest.mark.asyncio
async def test_legacy_search_batch_and_direct_search_limits_remain_five(tmp_path):
    _, store, _, projects = setup(tmp_path)
    try:
        capabilities = projects.capabilities()
        assert capabilities["project_analysis"]["max_knowledge_points"] == 30
        assert capabilities["project_search"]["batch_size"] == 5
        assert len(SearchRequest(knowledge_points=[f"概念{i}" for i in range(5)]).knowledge_points) == 5
        with pytest.raises(ValidationError):
            SearchRequest(knowledge_points=[f"概念{i}" for i in range(6)])
    finally:
        await projects.stop()
        store.close()
