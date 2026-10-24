"""Offline replay of the observed clock-cap claim and correct timing boundaries."""
from copy import deepcopy

import pytest

from backend.app import project_analysis as module
from backend.app.project_analysis import AnalysisError, GeneratedConceptList, ProjectAnalyzer
from backend.app.project_models import ProjectInput
from tests.test_project_analysis import settings
from tests.professional_contract_support import unchanged_quality_correction, is_semantic_review_payload, semantic_review_pass, draft_with_inventory, coverage_completion


OBSERVED_CLAIM = "配合时钟限制帧率使运动速度与硬件性能无关。"
CORRECT_MOTION = "用 Clock.tick 获取实际经过时间 dt，按速度乘 dt 更新位置，使运动速度与帧率无关。"


def project():
    # The live input requested Python; pygame was chosen by the model's route.
    return ProjectInput(name="用Python做一个接球小游戏", requirements="左右键移动挡板接住下落的小球，接住加分，漏接后可以重新开始。")


def proposal(text):
    return {
        "scope": "本地键盘控制的接球小游戏。",
        "technical_plan": "使用 pygame 接收输入、更新游戏状态并绘制画面。",
        "assumptions": [],
        "knowledge_points": [
            {"name": "游戏主循环", "technology": "pygame", "description": text},
            {"name": "键盘输入", "technology": "pygame", "description": "查询左右键状态，每帧按固定像素步长改变挡板位置。"},
        ],
    }


def findings(text, *, other_description=None):
    raw = proposal(text)
    if other_description:
        raw["knowledge_points"][1]["description"] = other_description
    document = GeneratedConceptList.model_validate(raw).to_document()
    return [issue for issue in module.professional_contract_issues(project(), document)
            if issue["code"] == "frame_rate_independence"]


@pytest.mark.parametrize("text", [
    OBSERVED_CLAIM,
    "通过 Clock.tick 限制帧率，保证移动速度与机器性能无关。",
    "Use Clock.tick to ensure movement speed is independent of hardware performance.",
    "Clock.tick 限制帧率，每帧按固定步长更新位置，使移动速度与帧率无关。",
    "Use Clock.tick and update position by a fixed step each frame to ensure movement speed is independent of frame rate.",
    "帧率控制通过限制每帧最大执行次数使游戏运行速度稳定、减少 CPU 空转。本项目使用时钟对象限制每秒循环次数，使挡板移动和下落动画速度在不同机器上基本一致，而不是随循环速度任意变化。",
    "时钟对象限制每秒循环次数。这样可以保证动画速度在不同设备上基本一致。",
    "Limit loop iterations per second. This ensures movement speed is consistent across different machines.",
])
def test_frame_cap_and_per_render_step_do_not_establish_speed_independence(text):
    issues = findings(text)
    assert len(issues) == 1
    assert issues[0]["point_id"] == "k1"
    assert issues[0]["location"] == ["knowledge_points", 0, "description"]


@pytest.mark.parametrize("text", [
    "配合时钟限制帧率，减少过度刷新。",
    "使用 Clock.tick 设置每秒最大帧数。",
    "仅靠时钟限制帧率不能使运动速度与硬件性能无关。",
    "Clock.tick cannot ensure movement speed is independent of hardware performance.",
    "Clock.tick alone does not make movement speed independent of machine performance.",
    CORRECT_MOTION,
    "用 Clock.tick 获取经过时间，更新位置时乘以 dt，使运动速度与硬件性能无关。",
    "Clock.tick 返回实际经过时间，累积器按固定时间步长更新位置，使移动速度与帧率无关。",
    "Use Clock.tick to get elapsed time, update position using dt, and ensure movement speed is independent of hardware performance.",
    "Clock.tick 用于限制帧率，使移动对象独立于摄像机。",
    "时钟对象限制每秒循环次数，但不能使动画速度在不同机器上基本一致。",
    "时钟对象限制每秒循环次数。这样不能保证动画速度在不同设备上基本一致。",
    "时钟对象限制每秒循环次数。位置按速度乘实际时间差更新，使移动速度在不同机器上基本一致。",
    "Limit loop iterations per second. This cannot ensure movement speed is consistent across different machines.",
])
def test_modest_claim_negation_or_applied_elapsed_time_stays_allowed(text):
    assert findings(text) == []


def test_a_different_point_time_quantity_does_not_excuse_the_bad_claim():
    assert findings(OBSERVED_CLAIM, other_description=CORRECT_MOTION)


def test_technical_plan_claim_has_its_own_timing_scope_and_location():
    raw = proposal(CORRECT_MOTION)
    raw["technical_plan"] = "使用 pygame，通过时钟对象限制每秒循环次数，使动画速度在不同机器上基本一致。"
    document = GeneratedConceptList.model_validate(raw).to_document()
    issues = module.professional_contract_issues(project(), document)
    assert any(issue["code"] == "frame_rate_independence" and issue["location"] == ["technical_plan"]
               for issue in issues)


@pytest.mark.parametrize("route_source", ["project", "technical_plan", "point_technology"])
def test_pygame_timing_contract_applies_to_explicit_or_model_chosen_route(route_source):
    raw = proposal(OBSERVED_CLAIM)
    raw["technical_plan"] = "使用 Python 完成本地交互。"
    for point in raw["knowledge_points"]:
        point["technology"] = "Python"
    source = project()
    if route_source == "project":
        source = ProjectInput(name="pygame 接球小游戏", requirements=source.requirements)
    elif route_source == "technical_plan":
        raw["technical_plan"] = "使用 pygame 接收输入并绘制画面。"
    else:
        raw["knowledge_points"][0]["technology"] = "pygame"
    document = GeneratedConceptList.model_validate(raw).to_document()
    issues = module.professional_contract_issues(source, document)
    assert any(issue["code"] == "frame_rate_independence" for issue in issues)


def install_replies(monkeypatch, replies):
    calls = []

    async def complete(_settings, _prompt, payload, *_args, **_kwargs):
        calls.append(deepcopy(payload))
        assert len(calls) <= 2
        return deepcopy(replies[len(calls) - 1])

    monkeypatch.setattr(module, "complete_json", complete)
    return calls


@pytest.mark.asyncio
async def test_observed_hardware_claim_requires_a_quality_repair_before_delivery(monkeypatch):
    bad, good = proposal(OBSERVED_CLAIM), proposal(CORRECT_MOTION)
    good["knowledge_points"][1]["description"] = "查询左右键状态确定移动方向，具体位移由主循环按速度与 dt 计算。"
    calls = install_replies(monkeypatch, [bad, good])
    audit = []
    result = await ProjectAnalyzer(settings()).analyze(project(), on_analysis_attempt=audit.append)
    assert len(calls) == 2
    assert [(row["phase"], row["outcome"]) for row in audit] == [
        ("generation", "rejected"), ("repair", "accepted")]
    assert any(row["code"] == "frame_rate_independence" for row in calls[1]["validation_feedback"])
    assert calls[1]["previous_analysis"] == bad
    assert result.knowledge_points[0].description == CORRECT_MOTION


@pytest.mark.asyncio
async def test_repeated_hardware_claim_is_terminal_quality_failure(monkeypatch):
    bad = proposal(OBSERVED_CLAIM)
    calls = install_replies(monkeypatch, [bad, bad])
    audit = []
    with pytest.raises(AnalysisError) as caught:
        await ProjectAnalyzer(settings()).analyze(project(), on_analysis_attempt=audit.append)
    assert caught.value.code == "quality" and len(calls) == 2
    assert [row["outcome"] for row in audit] == [
        "rejected", "rejected"]
    assert any(row["code"] == "frame_rate_independence" for row in calls[-1]["validation_feedback"])
    issue = next(row for row in caught.value.diagnostics if row.get("code") == "frame_rate_independence")
    assert issue["location"] == ["knowledge_points", 0, "description"]
