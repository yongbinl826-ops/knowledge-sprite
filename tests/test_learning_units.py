"""Learning contract/guard tests. Synthetic fixtures are not live integration."""
import json
import asyncio
import time
from argparse import Namespace
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from tests.professional_contract_support import draft_with_inventory, flat_proposal
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.project_analysis import (
    ANALYSIS_MAX_ATTEMPTS, ANALYSIS_PROMPT_VERSION, SYSTEM_PROMPT, AnalysisError,
    ProjectAnalyzer, generation_schema, learning_quality_issues,
)
from backend.app.project_models import AnalysisDocument, ProjectInput
from scripts.accept_learning_units import CASES, assess, case_input, offline_reference_document, replay_evidence


def fixture():
    return offline_reference_document(CASES[0], "beginner").model_dump()


def professional_fixture():
    # Explicit mock v5 proposal. fixture() stays the archived task-shaped example
    # for legacy schema, expanded-quality and historical semantic controls.
    from tests.professional_contract_support import concept_proposal
    return concept_proposal(fixture(), {"k1": "事件循环", "k2": "二维坐标系", "k3": "碰撞检测", "k4": "状态机"})


def browser_restart_fixture():
    """Six-unit shape of the independently reviewed real v5 game analysis.

    The feature f5 wording below is the exact observed semantic defect; k6
    already teaches the correct state-based restart, exposing the contradiction.
    This local snapshot makes regression independent of mutable browser reports.
    """
    units = [
        ("pygame 窗口与游戏主循环", "创建能刷新并正常关闭的窗口", ["事件队列", "帧率控制"], [], "窗口能刷新且关闭按钮正常退出。"),
        ("Rect 矩形与坐标定位绘制", "在窗口中绘制挡板和小球", ["屏幕坐标系", "矩形位置与尺寸"], ["k1"], "挡板与静止小球同时可见。"),
        ("键盘长按移动挡板与边界限制", "用方向键连续移动挡板并限制边界", ["按键状态", "逐帧位移与边界"], ["k2"], "挡板平滑移动并停在左右边界。"),
        ("小球下落更新与 Rect 碰撞检测", "更新下落坐标并在接到后重置小球", ["坐标增量", "矩形碰撞与复位"], ["k2"], "接住后小球返回顶部继续下落。"),
        ("分数统计与文字显示", "接到小球时计分并绘制分数字体", ["计分状态", "字体渲染"], ["k4"], "接球次数与显示分数一致。"),
        ("游戏结束、空格重开与状态管理", "结束时暂停更新，按空格重置球与分数", ["游戏状态", "KEYDOWN 空格重置"], ["k4", "k5"], "漏接后出现结束提示且游戏暂停；按空格分数归零并重新开始下落。"),
    ]
    body = fixture()
    body.update(scope="本地 Python 接球游戏，方向键控制、计分、漏接结束和空格重开。",
                technical_plan="使用 pygame；事件与绘制循环保持运行，通过游戏状态暂停物理更新。")
    function_specs = [
        ("游戏窗口与主循环", "在本机做一个图形小游戏", "运行脚本后出现窗口，持续刷新且可正常关闭。"),
        ("方向键移动挡板", "方向键移动挡板", "方向键连续移动挡板，且不越出窗口边界。"),
        ("小球下落与接住判定", "接住下落的小球", "小球每帧下落，与挡板重叠时判定接住。"),
        ("接住加分", "接到后加分", "接住一次分数加1，并显示当前分数。"),
        ("漏接游戏结束", "漏接则游戏结束", "球越过挡板底部后停止游戏循环，并显示游戏结束提示。"),
        ("空格重新开始", "按空格可以重新开始", "结束后按空格分数清零、球与挡板复位并继续游戏。"),
    ]
    body["functions"] = [{"id": f"f{index}", "name": name, "original_requirement": requirement,
                           "acceptance_criteria": check}
                          for index, (name, requirement, check) in enumerate(function_specs, 1)]
    body["knowledge_points"] = []
    mappings = [["f1"], ["f1", "f2", "f3"], ["f2"], ["f3"], ["f4"], ["f5", "f6"]]
    learning_skills = [
        ["pygame 窗口事件与持续刷新", "pygame 帧率控制与退出事件"],
        ["pygame 矩形几何与坐标定位", "pygame 基础形状绘制"],
        ["pygame 持续按键读取与位移", "pygame 边界限制"],
        ["pygame 物体位置更新", "pygame 矩形碰撞与对象复位"],
        ["Python 事件计数状态", "pygame 字体渲染与文字显示"],
        ["pygame 游戏状态驱动更新", "pygame 按键事件与数据重置"],
    ]
    for index, (title, task, concepts, prerequisites, check) in enumerate(units, 1):
        body["knowledge_points"].append({"id": f"k{index}", "name": title, "description": task,
            "function_ids": mappings[index - 1], "why_needed": "该子任务用于完成接球游戏对应功能。",
            "learning_goal": f"理解相关技能并能完成：{task}。", "project_task": task,
            "technology": "pygame", "concepts": concepts, "learning_skills": learning_skills[index - 1], "practice_check": check, "necessity": "required",
            "prerequisite_ids": prerequisites, "learning_order": index, "selection": "learn"})
    body["functions"][4]["acceptance_criteria"] = "球越过挡板底部后停止游戏循环，并显示游戏结束提示。"
    return body


def restart_project():
    return ProjectInput(name="Python 接球小游戏", requirements="方向键移动挡板，接球加分，漏接结束；按空格重新开始。不做登录和联网。")


def settings():
    return Settings(llm_provider="openai_compatible", llm_base_url="https://model.example/v1",
                    llm_api_key="offline-private-token", llm_model="offline-model", project_semantic_review_enabled=False)


def response(body):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]})


def test_default_level_is_beginner_without_inventing_background():
    project = ProjectInput(name="小项目", requirements="做一个本地待办清单")
    assert project.student_level == "beginner"
    assert not project.project_context


def test_saved_v1_analysis_remains_readable_with_explicit_missing_details():
    body = fixture()
    body.pop("learner_profile")
    for point in body["knowledge_points"]:
        for field in ("technology", "project_task", "concepts", "practice_check"):
            point.pop(field)
    restored = AnalysisDocument.model_validate(body)
    assert restored.learner_profile is None
    assert restored.knowledge_points[0].project_task is None
    assert restored.knowledge_points[0].concepts == []
    assert restored.knowledge_points[0].practice_check is None
    assert restored.knowledge_points[0].technology == ""
    # Backward-compatible reading does not make an old analysis fresh v2 output.
    assert {issue["code"] for issue in learning_quality_issues(case_input(CASES[0], "beginner"), restored)} == {
        "missing_learner_profile", "incomplete_learning_unit"}


def test_generation_schema_uses_v1_terms_without_removing_optional_historical_storage():
    from tests.professional_contract_support import assert_simple_generation_schema
    assert_simple_generation_schema()
    storage = AnalysisDocument.model_json_schema()
    assert "learner_profile" in storage["properties"] and "learner_profile" not in storage["required"]
    point = storage["$defs"]["ProjectKnowledgePoint"]
    assert {"technology", "project_task", "concepts", "learning_skills", "practice_check"} <= set(point["properties"])
    assert not {"technology", "project_task", "concepts", "learning_skills", "practice_check"} & set(point["required"])
    assert point["properties"]["technology"]["maxLength"] == 80


def test_compact_prompt_uses_project_relevant_names_and_modifiable_technology_assumptions():
    assert ANALYSIS_PROMPT_VERSION == "project-analysis-v8-compact-foundations"
    assert "Honor its technologies and constraints" in SYSTEM_PROMPT
    assert "label necessary unspecified choices as modifiable assumptions" in SYSTEM_PROMPT
    assert "optional technology" in SYSTEM_PROMPT
    assert "invent courses, URLs or evidence" in SYSTEM_PROMPT
    assert "concise established concept names" in SYSTEM_PROMPT
    assert "Work backwards from each required behavior to the mechanisms it depends on" in SYSTEM_PROMPT


@pytest.mark.parametrize("technology", ["", "Python", "pygame", "turtle", "pandas", "Arduino", "ASP.NET", "Socket.IO", "x" * 80])
def test_explicit_technology_accepts_general_concepts_or_a_bounded_target(technology):
    body = fixture()
    body["knowledge_points"][0]["technology"] = technology
    document = AnalysisDocument.model_validate(body, context={"fresh_generation": True})
    assert document.knowledge_points[0].technology == technology
    assert "technology" in document.knowledge_points[0].model_fields_set


@pytest.mark.parametrize("technology", [None, 42, [], {}, "   ", "x" * 81])
def test_technology_rejects_wrong_types_whitespace_and_overlong_targets(technology):
    body = fixture()
    body["knowledge_points"][0]["technology"] = technology
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(body)


def test_empty_target_permission_does_not_allow_other_blank_analysis_fields():
    body = fixture()
    body["knowledge_points"][0].update(technology="", description=" ")
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(body)


def test_historical_analysis_without_technology_remains_readable_without_a_fresh_requirement():
    body = fixture()
    for point in body["knowledge_points"]:
        point.pop("technology")
    for context in (None, {"fresh_generation": True}):
        historical = AnalysisDocument.model_validate(body, context=context)
        assert all(point.technology == "" for point in historical.knowledge_points)
        assert all("technology" not in point.model_fields_set for point in historical.knowledge_points)
        assert not learning_quality_issues(case_input(CASES[0], "beginner"), historical)


@pytest.mark.parametrize("missing_all", [False, True], ids=["one-unit", "all-units"])
@pytest.mark.asyncio
async def test_optional_missing_technology_needs_no_generation_repair(missing_all):
    from tests.professional_contract_support import projected_once
    body = professional_fixture()
    affected = body["knowledge_points"] if missing_all else body["knowledge_points"][:1]
    for point in affected:
        point.pop("technology")
    result, calls = await projected_once(body, case_input(CASES[0], "beginner"), settings())
    assert len(calls) == 1
    assert all(point.technology == "" for point in result.knowledge_points[:len(affected)])


@pytest.mark.asyncio
async def test_omitted_technology_is_not_invented_from_other_units_or_a_later_proposal():
    from tests.professional_contract_support import projected_once
    body = professional_fixture()
    body["knowledge_points"][0].pop("technology")
    result, calls = await projected_once(body, case_input(CASES[0], "beginner"), settings())
    assert len(calls) == 1 and result.knowledge_points[0].technology == ""
    assert [p.technology for p in result.knowledge_points[1:]] == [p["technology"] for p in body["knowledge_points"][1:]]


@pytest.mark.asyncio
async def test_fresh_explicitly_general_target_remains_empty_without_repair():
    body = professional_fixture()
    body["knowledge_points"][0].update(
        name="Screen coordinates", technology="",
        project_task="Calculate the player's initial position and movement within the screen.",
        concepts=["Two dimensional coordinates", "Distance per frame"],
        learning_goal="Relate coordinate changes to visible movement.",
        practice_check="Predict the new position after three frames and verify the arithmetic.")
    body = flat_proposal(body)
    project = case_input(CASES[0], "beginner")
    calls = []
    def respond(req):
        calls.append(req)
        return response(body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(settings(), client).analyze(project)
    assert len(calls) == 1
    assert result.knowledge_points[0].technology == ""


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
@pytest.mark.parametrize("level", ["beginner", "intermediate"])
def test_representative_synthetic_rubric_covers_tasks_and_background(case, level):
    project = case_input(case, level)
    document = offline_reference_document(case, level)
    result = assess(case, project, document)
    assert result["automated_passed"]
    assert result["manual_review_required"]
    assert document.learner_profile.student_level == level
    assert all(point.project_task and point.practice_check and len(point.concepts) >= 2 for point in document.knowledge_points)


@pytest.mark.parametrize("name", ["Python", "Python 基础", "Python 基础语法", "Python基础视频", "Python fundamentals", "数据库", "Arduino 基础"])
def test_guard_rejects_whole_subject_substitutes(name):
    body = fixture()
    body["knowledge_points"][0]["name"] = name
    issues = learning_quality_issues(case_input(CASES[0], "beginner"), AnalysisDocument.model_validate(body))
    assert any(issue["code"] == "broad_subject" for issue in issues)


@pytest.mark.parametrize("name", ["变量名", "Python print 语句", "Python if语句", "赋值语句"])
def test_guard_rejects_isolated_syntax_fragments(name):
    body = fixture()
    body["knowledge_points"][0]["name"] = name
    assert any(issue["code"] == "syntax_fragment" for issue in
               learning_quality_issues(case_input(CASES[0], "beginner"), AnalysisDocument.model_validate(body)))


@pytest.mark.parametrize("name", ["Python 列表与循环管理下落金币", "turtle 键盘事件与角色移动", "pygame 事件循环与画面刷新", "Arduino digitalWrite 与阈值提示"])
def test_guard_accepts_coherent_tasks_and_does_not_force_a_framework(name):
    body = fixture()
    body["knowledge_points"][0]["name"] = name
    assert not learning_quality_issues(case_input(CASES[0], "beginner"), AnalysisDocument.model_validate(body))


@pytest.mark.parametrize("field", ["technology", "project_task", "practice_check", "concepts"])
def test_new_fields_cannot_introduce_fabricated_source_links(field):
    body = fixture()
    body["knowledge_points"][0][field] = ["https://example.org/course", "事件队列"] if field == "concepts" else "https://example.org/course"
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(body)


def test_duplicate_concepts_are_rejected_and_overlong_lists_need_regeneration():
    body = fixture()
    body["knowledge_points"][0]["concepts"] = ["事件队列", "  事件队列  "]
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(body)
    body["knowledge_points"][0]["concepts"] = [f"概念 {index}" for index in range(7)]
    assert any(issue["code"] == "incomplete_learning_unit" for issue in
               learning_quality_issues(case_input(CASES[0], "beginner"), AnalysisDocument.model_validate(body)))


def test_rubric_exposes_unrelated_but_structurally_valid_analysis():
    irrelevant = offline_reference_document(CASES[1], "beginner")
    result = assess(CASES[0], case_input(CASES[0], "beginner"), irrelevant)
    assert not result["automated_passed"]
    assert any(not check["passed"] for check in result["required_behaviors"])


@pytest.mark.asyncio
async def test_absent_expanded_profile_and_task_are_not_new_generation_errors():
    from tests.professional_contract_support import projected_once
    body = professional_fixture()
    body.pop("learner_profile")
    body["knowledge_points"][0].pop("project_task")
    result, calls = await projected_once(body, case_input(CASES[0], "beginner"), settings())
    assert len(calls) == 1 and result.learner_profile is None
    assert all(p.project_task is None and p.concepts == [] and p.learning_skills == [] for p in result.knowledge_points)


@pytest.mark.asyncio
async def test_quality_repair_gets_controlled_feedback_and_returns_specific_units():
    original = flat_proposal(professional_fixture())
    invalid = deepcopy(original)
    invalid["knowledge_points"][0]["name"] = "Python基础"
    invalid["knowledge_points"][0]["description"] = "UNTRUSTED_PRIVATE_VALUE"
    project = case_input(CASES[0], "beginner")
    calls = []
    def respond(req):
        calls.append(json.loads(req.content))
        return response([invalid, original][len(calls) - 1])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(settings(), client).analyze(project)
    assert len(calls) == 2
    assert result.knowledge_points[0].name == original["knowledge_points"][0]["name"]
    feedback = json.loads(calls[1]["messages"][1]["content"])["validation_feedback"]
    assert feedback[0]["code"] == "broad_subject"
    assert "UNTRUSTED_PRIVATE_VALUE" not in json.dumps(feedback)
    # The validated draft is now supplied as untrusted proposal data so the
    # model can correct that exact plan. It never becomes repair instructions.
    repair = json.loads(calls[1]["messages"][1]["content"])
    assert "project_task" not in repair["previous_analysis"]["knowledge_points"][0]
    assert repair["previous_analysis"]["knowledge_points"][0]["description"] == "UNTRUSTED_PRIVATE_VALUE"


@pytest.mark.asyncio
async def test_explicit_input_stage_is_preserved_without_generated_learner_profile_gate():
    from tests.professional_contract_support import projected_once
    project = case_input(CASES[0], "intermediate")
    assert project.student_level == "intermediate"
    result, calls = await projected_once(professional_fixture(), project, settings())
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["project"]["student_level"] == "intermediate"
    assert result.learner_profile is None
    assert project.student_level == "intermediate"


@pytest.mark.asyncio
async def test_live_harness_stops_at_the_provider_request_budget(monkeypatch):
    import scripts.accept_learning_units as harness
    real_client = httpx.AsyncClient
    monkeypatch.setattr(harness.Settings, "from_env", lambda: settings())
    monkeypatch.setattr(harness, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(harness.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda _: response(draft_with_inventory(
            flat_proposal(professional_fixture()), case_input(CASES[0], "beginner")))), **kwargs))
    evidence = await harness.run(Namespace(live=True, case=None, levels=["beginner"],
        env_file=Path("unused.env"), max_cases=4, max_requests=1))
    assert evidence["provider_requests"] == 1
    assert len(evidence["records"]) == 1
    assert evidence["records"][0]["status"] == "failed"
    assert evidence["records"][0]["error_code"] == "request_budget_exhausted"
    assert evidence["records"][0]["provider_requests"] == 1
    assert "analysis" not in evidence["records"][0]  # A rejected legacy wrapper is never delivered.
    assert not evidence["automated_passed"]


@pytest.mark.asyncio
async def test_repair_uses_remaining_total_budget_instead_of_a_second_full_timeout(monkeypatch):
    import backend.app.project_analysis as analysis
    monkeypatch.setattr(analysis, "ANALYSIS_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(analysis, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", 0.3)
    # Scale the optional-repair admission margin with the tiny test deadline.
    monkeypatch.setattr(analysis, "ANALYSIS_MIN_REPAIR_SECONDS", 0.05)
    seen_timeouts = []
    async def slow_response(*args, **kwargs):
        seen_timeouts.append(kwargs["timeout_seconds"])
        await asyncio.sleep(0.16)
        return {}  # First result needs a structural repair.
    monkeypatch.setattr(analysis, "complete_json", slow_response)
    started = time.monotonic()
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(settings()).analyze(case_input(CASES[0], "beginner"))
    assert exc.value.code == "timeout"
    assert len(seen_timeouts) == 2
    assert seen_timeouts[0] == pytest.approx(0.2)
    assert 0 < seen_timeouts[1] < 0.16
    assert time.monotonic() - started < 0.6


@pytest.mark.asyncio
async def test_timeout_configuration_is_used_without_retrying_slow_provider(monkeypatch):
    from dataclasses import replace
    import backend.app.project_analysis as analysis
    seen_timeouts = []
    async def timeout_response(*args, **kwargs):
        seen_timeouts.append(kwargs["timeout_seconds"])
        raise TimeoutError
    monkeypatch.setattr(analysis, "complete_json", timeout_response)
    configured = replace(settings(), project_analysis_timeout_seconds=37, project_analysis_total_timeout_seconds=49)
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(configured).analyze(case_input(CASES[0], "beginner"))
    assert exc.value.code == "timeout"
    assert seen_timeouts == [37]


@pytest.mark.asyncio
async def test_flat_analysis_uses_the_configured_token_limit_without_extra_calls():
    from dataclasses import replace
    calls = []
    project = case_input(CASES[0], "beginner")
    proposal = flat_proposal(professional_fixture())
    def respond(req):
        calls.append(json.loads(req.content))
        return response(proposal)
    configured = replace(settings(), llm_max_output_tokens=3210)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        document = await ProjectAnalyzer(configured, client).analyze(project)
    assert len(calls) == 1
    assert [call["max_tokens"] for call in calls] == [3210]
    assert len(document.knowledge_points) == 4


@pytest.mark.asyncio
async def test_token_limit_truncation_is_not_accepted_or_repaired_even_with_valid_json():
    calls = []
    def truncated(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {
            "content": json.dumps(fixture(), ensure_ascii=False)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(truncated)) as client:
        with pytest.raises(AnalysisError) as exc:
            await ProjectAnalyzer(settings(), client).analyze(case_input(CASES[0], "beginner"))
    assert exc.value.code == "output_truncated"
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == settings().llm_max_output_tokens


@pytest.mark.parametrize("parser", ["Serial.parseInt", "Serial.readString", "Serial.readStringUntil"])
def test_responsive_hardware_task_cannot_claim_default_blocking_parser_is_immediate(parser):
    body = offline_reference_document(CASES[3], "beginner").model_dump()
    body["knowledge_points"][-1]["concepts"] = [parser, "阈值更新", "输入范围检查"]
    body["knowledge_points"][-1]["project_task"] = f"用 {parser} 读取新阈值并立即响应。"
    issues = learning_quality_issues(case_input(CASES[3], "beginner"), AnalysisDocument.model_validate(body))
    assert any(issue["code"] == "blocking_input_for_responsive_task" for issue in issues)


@pytest.mark.parametrize("mitigation", ["Serial.read 字符缓冲区与行结束判断", "Serial.setTimeout 设置有界超时并测试响应上限"])
def test_hardware_guard_allows_explained_buffered_or_bounded_input(mitigation):
    body = offline_reference_document(CASES[3], "intermediate").model_dump()
    body["knowledge_points"][-1]["concepts"] = ["Serial.parseInt 的阻塞风险", mitigation]
    assert not learning_quality_issues(case_input(CASES[3], "intermediate"), AnalysisDocument.model_validate(body))


def test_blocking_parser_is_not_rejected_when_responsiveness_was_not_required():
    body = offline_reference_document(CASES[3], "beginner").model_dump()
    body["knowledge_points"][-1]["concepts"] = ["Serial.parseInt", "输入阈值"]
    project = ProjectInput(name="Arduino 串口实验", requirements="在串口输入阈值后检查 LED 状态。")
    assert not learning_quality_issues(project, AnalysisDocument.model_validate(body))


def test_replay_rechecks_saved_responses_and_preserves_failures_without_new_requests(tmp_path):
    body = offline_reference_document(CASES[3], "beginner").model_dump()
    body["knowledge_points"][-1]["concepts"] = ["Serial.parseInt", "输入范围检查"]
    saved = {"prompt_version": "old-test-prompt", "provider_requests": 2, "records": [
        {"case": "arduino", "level": "beginner", "status": "completed", "elapsed_seconds": 30,
         "input": case_input(CASES[3], "beginner").model_dump(), "analysis": body},
        {"case": "web_app", "level": "beginner", "status": "failed", "error_code": "timeout"},
    ]}
    path = tmp_path / "saved_fixture.json"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    evidence = replay_evidence([path])
    assert not evidence["network_used"]
    assert evidence["provider_requests"] == 0
    assert evidence["source_provider_requests"] == 2
    assert not evidence["automated_passed"]
    assert evidence["records"][0]["assessment"]["quality_issues"][0]["code"] == "blocking_input_for_responsive_task"
    assert evidence["records"][1]["error_code"] == "timeout"


@pytest.mark.parametrize("criterion", [
    "球越过挡板底部后停止游戏循环，并显示游戏结束提示。",
    "漏接后退出整个游戏主循环，等待按空格重新开始。",
    "漏接后终止主循环，然后通过空格重开。",
    "Stop the main game loop, then wait for Space to restart.",
])
def test_key_restart_rejects_ending_the_whole_loop_in_feature_acceptance(criterion):
    body = browser_restart_fixture()
    body["functions"][4]["acceptance_criteria"] = criterion
    issues = learning_quality_issues(restart_project(), AnalysisDocument.model_validate(body))
    assert any(issue["code"] == "unresponsive_game_restart" and issue.get("function_id") == "f5" for issue in issues)


@pytest.mark.parametrize("criterion", [
    "漏接后停止下落更新与计分，继续处理事件并绘制结束画面。",
    "漏接后停止游戏主循环中的物理更新，继续处理空格和关闭事件。",
    "漏接后暂停运行中状态，事件循环继续处理按键并绘制结束提示。",
    "不要停止主循环，否则无法接收空格重开；只暂停球的更新。",
    "理解停止主循环与暂停游戏状态的区别；结束时保持事件处理。",
    "退出主循环会导致无法接收重开按键，因此只暂停状态更新。",
    "停止游戏循环，外层事件循环继续处理空格和窗口绘制。",
    "Stop the main game loop's physics updates; keep processing events and rendering.",
])
def test_key_restart_accepts_state_pauses_and_continued_event_handling(criterion):
    body = browser_restart_fixture()
    body["functions"][4]["acceptance_criteria"] = criterion
    assert not learning_quality_issues(restart_project(), AnalysisDocument.model_validate(body))


def test_key_restart_guard_also_checks_learning_tasks_and_skips_games_without_restart():
    body = browser_restart_fixture()
    body["functions"][4]["acceptance_criteria"] = "漏接后暂停物理更新，仍处理空格事件。"
    body["knowledge_points"][-1]["project_task"] = "漏接后退出整个游戏主循环，等待空格重新开始。"
    issues = learning_quality_issues(restart_project(), AnalysisDocument.model_validate(body))
    assert any(issue["code"] == "unresponsive_game_restart" and issue.get("point_id") == "k6" for issue in issues)
    no_restart = ProjectInput(name="一次性游戏", requirements="方向键控制，结束后关闭，不需要重开。")
    assert not any(issue["code"] == "unresponsive_game_restart" for issue in
                   learning_quality_issues(no_restart, AnalysisDocument.model_validate(body)))


@pytest.mark.asyncio
async def test_legacy_restart_fixture_is_projected_without_claiming_new_semantic_approval():
    from tests.professional_contract_support import projected_once
    body = browser_restart_fixture()
    # The known contradiction remains in this archived semantic example.
    # The restored term generator does not certify or silently fix that behavior.
    document, calls = await projected_once(body, restart_project(), settings(), concept_names={"k1": "事件循环", "k2": "二维坐标系", "k3": "按键状态", "k4": "碰撞检测", "k5": "文本渲染", "k6": "状态机"})
    assert len(calls) == 1
    assert "functions" not in document.model_dump()
    assert body["functions"][4]["acceptance_criteria"] == "球越过挡板底部后停止游戏循环，并显示游戏结束提示。"

