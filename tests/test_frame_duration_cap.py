"""Offline regression for a clock cap's frame-duration direction."""
from copy import deepcopy

import pytest

from backend.app import project_analysis as module
from backend.app.config import Settings
from backend.app.project_analysis import AnalysisError, GeneratedConceptList, ProjectAnalyzer
from backend.app.project_models import ProjectInput


OBSERVED = "游戏主循环反复处理输入、更新状态并绘制画面，通常配合时钟对象限制每帧耗时上限。"
CORRECT = "游戏主循环反复处理输入、更新状态并绘制画面，配合 Clock.tick 限制帧率上限；它无法保证单帧耗时上限。"


def project():
    return ProjectInput(name="用Python做一个接球小游戏", requirements="用方向键移动挡板接住下落的小球并记录分数，漏接后可以重新开始。")


def proposal(text):
    return {"scope": "键盘控制的接球小游戏。", "technical_plan": "使用 pygame 接收输入、更新游戏状态并绘图。",
            "assumptions": [], "knowledge_points": [
                {"name": "游戏主循环", "technology": "pygame", "description": text}]}


def findings(text):
    document = GeneratedConceptList.model_validate(proposal(text)).to_document()
    return [issue for issue in module.professional_contract_issues(project(), document)
            if issue["code"] == "frame_duration_upper_bound"]


@pytest.mark.parametrize("text", [
    OBSERVED,
    "Clock.tick 保证单帧执行耗时上限。",
    "通过时钟对象设置每帧时间最大值。",
    "Clock.tick 保证每帧耗时不超过16毫秒。",
    "Clock.tick guarantees a maximum frame duration of 16 milliseconds.",
    "Use Clock.tick to enforce an upper bound on frame duration.",
    "Clock.tick limits each frame to at most 16 milliseconds.",
])
def test_frame_rate_cap_cannot_guarantee_a_maximum_frame_duration(text):
    issues = findings(text)
    assert len(issues) == 1
    assert issues[0]["location"] == ["knowledge_points", 0, "description"]
    assert issues[0]["point_id"] == "k1"


@pytest.mark.parametrize("text", [
    CORRECT,
    "Clock.tick 限制帧率上限，让过快的帧等待。",
    "时钟对象通过延时让每帧至少经过目标帧间隔。",
    "Clock.tick 返回经过时间，用于测量每帧耗时并记录最大耗时。",
    "Clock.tick does not guarantee a maximum frame duration.",
    "Clock.tick cannot enforce an upper bound on frame duration.",
    "Clock.tick limits the frame rate but cannot guarantee a maximum frame duration.",
    "时钟对象不能保证单帧耗时上限。",
    "认为 Clock.tick 保证每帧耗时上限是不正确的。",
    "“时钟对象限制每帧耗时上限”是错误说法，帧率上限与帧耗时上限不同。",
    "Clock.tick caps the frame rate, giving a target minimum frame duration.",
])
def test_measurement_minimum_frame_duration_and_explicit_negation_are_allowed(text):
    assert findings(text) == []


def test_same_error_in_selected_technical_plan_is_rejected():
    raw = proposal(CORRECT)
    raw["technical_plan"] += OBSERVED
    document = GeneratedConceptList.model_validate(raw).to_document()
    issues = [issue for issue in module.professional_contract_issues(project(), document)
              if issue["code"] == "frame_duration_upper_bound"]
    assert len(issues) == 1 and issues[0]["location"] == ["technical_plan"]


def test_unrelated_execution_time_limit_is_not_reclassified_as_a_frame_cap():
    assert findings("运行时使用独立超时机制限制计算耗时上限。") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("repaired", [True, False])
async def test_invalid_cap_is_repaired_or_rejected_but_never_delivered(monkeypatch, repaired):
    calls, audits = [], []
    replies = [proposal(OBSERVED), proposal(CORRECT if repaired else OBSERVED)]

    async def complete(_settings, _prompt, payload, *_args, **_kwargs):
        calls.append(deepcopy(payload))
        return deepcopy(replies[len(calls) - 1])

    monkeypatch.setattr(module, "complete_json", complete)
    settings = Settings(llm_provider="openai_compatible", llm_base_url="https://offline.invalid/v1",
                        llm_api_key="synthetic", llm_model="synthetic")
    analyzer = ProjectAnalyzer(settings)
    if repaired:
        result = await analyzer.analyze(project(), on_analysis_attempt=audits.append)
        assert result.knowledge_points[0].description == CORRECT
        assert audits[-1]["outcome"] == "accepted"
    else:
        with pytest.raises(AnalysisError) as error:
            await analyzer.analyze(project(), on_analysis_attempt=audits.append)
        assert error.value.code == "quality"
        assert audits[-1]["outcome"] == "rejected"
    assert len(calls) == 2
    assert audits[0]["outcome"] == "rejected"
    assert any(row["code"] == "frame_duration_upper_bound" for row in calls[1]["validation_feedback"])
    assert any(row["code"] == "frame_duration_upper_bound" for row in audits[0]["issues"])
