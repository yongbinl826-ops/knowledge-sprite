"""Recorded v9-v11 drafts, replayed offline; no claim about later LLM output."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app import project_analysis as module
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from backend.app.project_models import ProjectInput
from tests.test_project_analysis import settings
from tests.professional_contract_support import unrepaired_quality_response


FIXTURES = Path(__file__).parent / "fixtures" / "textbook-live-20261023"


def recorded(version):
    return json.loads((FIXTURES / f"draft-v{version}.json").read_text(encoding="utf-8"))


def install_same_reply(monkeypatch, analysis):
    calls = []

    async def complete(_settings, _prompt, payload, *_args, **_kwargs):
        calls.append(deepcopy(payload))
        assert len(calls) <= 2
        return unrepaired_quality_response(payload, analysis, payload["project"])

    monkeypatch.setattr(module, "complete_json", complete)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("version,expected", [
    (9, {"textbook_mechanism_application_bundle", "textbook_descriptive_name", "textbook_operation_label"}),
    (10, {"textbook_mechanism_application_bundle", "textbook_operation_bundle", "textbook_operation_label", "frame_rate_independence"}),
    (11, {"textbook_operation_label"}),
])
async def test_full_recorded_draft_must_enter_conditional_repair_and_cannot_be_accepted_unchanged(
        monkeypatch, version, expected):
    record = recorded(version)
    original = deepcopy(record)
    calls = install_same_reply(monkeypatch, record["analysis"])
    attempts = []
    with pytest.raises(AnalysisError) as caught:
        await ProjectAnalyzer(settings()).analyze(
            ProjectInput.model_validate(record["input"]), on_analysis_attempt=attempts.append)
    assert caught.value.code == "quality" and len(calls) == 2
    assert [(attempt["phase"], attempt["outcome"]) for attempt in attempts] == [
        ("generation", "rejected"), ("repair", "rejected")]
    assert expected <= {issue["code"] for issue in calls[1]["validation_feedback"]}
    assert calls[1]["repair_required"] is True
    assert expected <= {issue["code"] for issue in calls[1]["validation_feedback"]}
    assert calls[1]["previous_analysis"] == record["analysis"]
    assert calls[1]["project"] == record["input"]
    assert record == original


@pytest.mark.asyncio
@pytest.mark.parametrize("version,name,code,field", [
    (9, "事件队列与键盘输入", "textbook_mechanism_application_bundle", "name"),
    (9, "基于时间步长的运动更新", "textbook_descriptive_name", "name"),
    (9, "矩形表示与矩形碰撞检测", "textbook_mechanism_application_bundle", "name"),
    (9, "游戏状态重置", "textbook_operation_label", "name"),
    (9, "文本渲染与分数显示", "textbook_mechanism_application_bundle", "name"),
    (10, "矩形表示与绘制", "textbook_mechanism_application_bundle", "name"),
    (10, "计数器与累加", "textbook_operation_bundle", "name"),
    (10, "游戏重置", "textbook_operation_label", "name"),
    (10, "帧率控制", "frame_rate_independence", "description"),
    (11, "状态重置", "textbook_operation_label", "name"),
])
async def test_each_recorded_problem_independently_triggers_repair(monkeypatch, version, name, code, field):
    record = recorded(version)
    analysis = deepcopy(record["analysis"])
    analysis["knowledge_points"] = [next(
        point for point in analysis["knowledge_points"] if point["name"] == name)]
    calls = install_same_reply(monkeypatch, analysis)
    with pytest.raises(AnalysisError) as caught:
        await ProjectAnalyzer(settings()).analyze(ProjectInput.model_validate(record["input"]))
    assert caught.value.code == "quality" and len(calls) == 2
    assert any(issue["code"] == code and issue["location"] == ["knowledge_points", 0, field]
               for issue in calls[1]["validation_feedback"])
    assert calls[1]["previous_analysis"] == analysis
