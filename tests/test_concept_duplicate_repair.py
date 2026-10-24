"""The bounded generation path reports duplicates without dropping their uses."""
from copy import deepcopy

import pytest

from backend.app import project_analysis as module
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from backend.app.project_models import AnalysisDocument
from tests.test_project_analysis import flat_analysis_fixture, request, settings


def proposal(points):
    body = flat_analysis_fixture()
    body["knowledge_points"] = [
        {"name": name, "description": description, "technology": technology}
        for name, description, technology in points
    ]
    return body


def duplicate_proposal():
    return proposal([
        ("Python 列表索引", "学习按索引定位元素，用于访问输入列表中的项目。", "Python"),
        ("列表索引", "学习按索引定位元素，用于访问结果列表中的项目。", "Python"),
    ])


def install(monkeypatch, replies):
    requests = []

    async def generate(_settings, _prompt, payload, *_args, **_kwargs):
        requests.append(deepcopy(payload))
        return deepcopy(replies[len(requests) - 1])

    monkeypatch.setattr(module, "complete_json", generate)
    return requests


@pytest.mark.asyncio
async def test_duplicate_repair_retains_full_rejected_proposal_and_both_coordinates(monkeypatch):
    bad = duplicate_proposal()
    merged = proposal([
        ("列表索引", "学习按索引定位元素，用于访问输入列表和结果列表中的项目。", "Python"),
    ])
    calls = install(monkeypatch, [bad, merged])
    audit = []
    result = await ProjectAnalyzer(settings()).analyze(request(), on_rejected_attempt=audit.append)
    assert len(calls) == 2 and len(audit) == 1
    assert audit[0]["analysis"] == bad
    assert audit[0]["category"] == "quality"
    assert {tuple(issue["location"]) for issue in audit[0]["issues"]} == {
        ("knowledge_points", 0, "name"), ("knowledge_points", 1, "name"),
    }
    assert {issue["code"] for issue in audit[0]["issues"]} == {"duplicate_concept_name"}
    assert calls[1]["previous_analysis"] == bad
    assert len(calls[1]["validation_feedback"]) == 2
    assert len(result.knowledge_points) == 1
    assert result.knowledge_points[0].description == merged["knowledge_points"][0]["description"]
    assert set(result.model_dump()["knowledge_points"][0]) == {
        "id", "name", "description", "technology", "selection",
    }


@pytest.mark.asyncio
async def test_repeated_duplicate_failure_never_silently_deletes_points_or_calls_again(monkeypatch):
    bad = duplicate_proposal()
    calls = install(monkeypatch, [bad, bad])
    audit = []
    with pytest.raises(AnalysisError) as caught:
        await ProjectAnalyzer(settings()).analyze(request(), on_rejected_attempt=audit.append)
    assert caught.value.code == "quality"
    assert len(calls) == 2
    assert [entry["analysis"] for entry in audit] == [bad, bad]
    # This is a generation-only check; the existing historical read path is unchanged.
    retained = {**bad, "analysis_format": "concept_list_v1", "knowledge_points": [
        {"id": f"k{i + 1}", **point, "selection": "learn"}
        for i, point in enumerate(bad["knowledge_points"])
    ]}
    assert len(AnalysisDocument.model_validate(retained).knowledge_points) == 2


@pytest.mark.asyncio
async def test_different_validation_mechanisms_and_cohesive_term_remain_independent(monkeypatch):
    body = proposal([
        ("JSON Schema 校验", "学习用声明式模式约束对象字段和类型，用于校验输入结构。", "Python"),
        ("跨字段业务约束", "学习字段之间的逻辑谓词，用于校验起止日期关系。", "Python"),
        ("发布与订阅模式", "学习发布者和订阅者的解耦通信，用于传递事件。", ""),
    ])
    calls = install(monkeypatch, [body, body])
    result = await ProjectAnalyzer(settings()).analyze(request())
    assert len(calls) == 1
    assert [p.name for p in result.knowledge_points] == [p["name"] for p in body["knowledge_points"]]
