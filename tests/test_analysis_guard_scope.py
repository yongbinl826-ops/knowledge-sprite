"""Offline detector/privacy regressions, not a claim of successful live generation."""
import json
from dataclasses import replace

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.project_models import AnalysisDocument, ProjectInput
from tests.test_project_analysis import analysis_fixture, settings, response


@pytest.mark.parametrize("text", [
    "区分暂停玩法逻辑与退出主循环",
    "区分退出主循环与暂停玩法逻辑",
    "比较暂停状态更新与退出主循环的区别",
    "按 Esc 退出主循环，R 重置比赛数据。",
    "按下 Escape 时退出游戏主循环。",
    "点击关闭窗口时退出主循环；获胜只暂停物理更新。",
    "关闭窗口时退出主循环；获胜只暂停物理更新。",
    "处理 pygame.QUIT 事件时退出主循环。",
    "When Escape is pressed exit the main game loop.",
    "Exit the main game loop when Escape is pressed.",
    "不要停止整个主循环，获胜只暂停计分与物理更新。",
    "停止主循环的物理更新，继续处理重开按键。",
    "Stop the main game loop's physics updates, keep events running.",
])
def test_comparison_and_explicit_quit_are_not_restart_contradictions(text):
    assert module._stops_whole_game_loop(text) is False


@pytest.mark.parametrize("text", [
    "获胜时退出主循环，然后按 R 重开。",
    "游戏结束时停止主循环，等待 R 重开。",
    "按 Esc 退出主循环；获胜后停止主循环等待 R。",
    "区分暂停玩法逻辑与退出主循环；获胜后退出主循环。",
    "按 Esc 退出主循环，获胜后停止游戏主循环并等待按键。",
    "获胜后退出主循环，再点击关闭窗口退出应用。",
    "When game over exit the main game loop then wait for R to restart.",
    "Exit the main game loop; press Escape to quit.",
    "按 Esc 退出主循环然后等待 R 重开。",
])
def test_actual_loop_stop_waiting_for_restart_still_rejected_locally(text):
    assert module._stops_whole_game_loop(text) is True


def game_request():
    return ProjectInput(name="pygame 比赛", requirements="获胜暂停玩法；按 R 键重新开始，Esc 退出游戏。")


def test_quality_guard_reports_exact_server_owned_skill_path():
    body = analysis_fixture()
    body["knowledge_points"][1]["learning_skills"][1] = "获胜时退出主循环，然后按 R 重开。"
    issues = module.learning_quality_issues(game_request(), AnalysisDocument.model_validate(body))
    issue = next(x for x in issues if x["code"] == "unresponsive_game_restart")
    assert issue["location"] == ["knowledge_points", 1, "learning_skills", 1]
    assert issue["rule"] == "whole_game_loop_stop"


@pytest.mark.parametrize("field", ["scope", "technical_plan"])
def test_top_level_guard_reports_exact_field_path(field):
    body = analysis_fixture()
    body[field] = "获胜后停止主循环等待重开。"
    issues = module.learning_quality_issues(game_request(), AnalysisDocument.model_validate(body))
    issue = next(x for x in issues if x["code"] == "unresponsive_game_restart")
    assert issue["location"] == [field]
    assert issue["rule"] == "whole_game_loop_stop"


def test_feature_guard_reports_actual_acceptance_path():
    body = analysis_fixture()
    body["functions"][1]["acceptance_criteria"] = "获胜后停止主循环等待重开。"
    issues = module.learning_quality_issues(game_request(), AnalysisDocument.model_validate(body))
    issue = next(x for x in issues if x["code"] == "unresponsive_game_restart")
    assert issue["location"] == ["functions", 1, "acceptance_criteria"]


def attempt_rows(error):
    return next(x["attempts"] for x in error.diagnostics if x.get("type") == "attempt_history")


@pytest.mark.asyncio
async def test_title_quality_then_bad_json_retains_safe_first_location_not_draft():
    body = analysis_fixture()
    body["knowledge_points"][1]["name"] = "Python基础"
    body["knowledge_points"][1]["project_task"] = "untrusted-draft-marker"
    replies = [body, '{"untrusted-response-marker":}']
    calls = []
    def respond(req):
        calls.append(req)
        return response(replies[len(calls)-1])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(module.AnalysisError) as error:
            await module.ProjectAnalyzer(settings(), client).analyze(game_request())
    assert len(calls) == 2 and error.value.code == "invalid_json"
    rows = attempt_rows(error.value)
    assert rows[0]["issues"] == [{"code": "broad_subject", "severity": "medium", "location": ["knowledge_points", 1]}]
    retained = json.dumps(error.value.diagnostics)
    assert "untrusted-draft-marker" not in retained and "untrusted-response-marker" not in retained
    assert "message" not in rows[0]["issues"][0]
    assert "untrusted-draft-marker" not in calls[1].content.decode()


@pytest.mark.asyncio
async def test_mastery_then_bad_json_retains_fixed_code_and_safe_location_only():
    body = analysis_fixture()
    body["knowledge_points"][1]["selection"] = "mastered"
    body["knowledge_points"][1]["project_task"] = "untrusted-review-message-marker"
    replies = [body, "bad-json"]
    calls = []
    def respond(req):
        calls.append(req)
        return response(replies[len(calls)-1])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(module.AnalysisError) as error:
            await module.ProjectAnalyzer(replace(settings(), project_semantic_review_enabled=True), client).analyze(
                ProjectInput(name="成绩分析", requirements="读取本地 Excel 成绩并统计平均分"))
    assert len(calls) == 2 and error.value.code == "invalid_json"
    rows = attempt_rows(error.value)
    assert rows[0]["issues"] == [{"code": "model_selected_mastery", "severity": "medium", "location": ["knowledge_points", 1]}]
    retained = json.dumps(error.value.diagnostics) + calls[1].content.decode()
    assert "untrusted-review-message-marker" not in retained
    assert "message" not in rows[0]["issues"][0]


@pytest.mark.parametrize("location,expected", [
    ("knowledge_points[0].learning_skills[1]", ["knowledge_points", 0, "learning_skills", 1]),
    ("functions.f1.acceptance_criteria", ["functions", 0, "acceptance_criteria"]),
    ("scope", ["scope"]),
    ("knowledge_points[50000].description", ["<unknown_field>"]),
    ("knowledge_points.k1.private_provider_key", ["<unknown_field>"]),
    ("Bearer private-provider-key", ["<unknown_field>"]),
    (["knowledge_points", True, "description"], ["<unknown_field>"]),
])
def test_history_location_is_real_schema_path_not_free_provider_text(location, expected):
    assert module._safe_issue_location(location, AnalysisDocument.model_validate(analysis_fixture())) == expected


def test_history_is_bounded_and_does_not_echo_unknown_rule_or_code():
    document = AnalysisDocument.model_validate(analysis_fixture())
    issues = [{"code": "untrusted-code", "rule": "untrusted-rule", "message": "private-message",
               "location": "private_path", "severity": "medium"}] * 40
    details = module._safe_quality_issue_details(issues, document)
    assert len(details) == 20
    assert details[0] == {"code": "quality_issue", "severity": "medium", "location": ["<unknown_field>"]}
    assert "untrusted" not in json.dumps(details) and "private" not in json.dumps(details)


def test_two_generation_budget_preserves_complete_json_and_closed_schema():
    from tests.professional_contract_support import assert_simple_generation_schema
    assert module.ANALYSIS_MAX_ATTEMPTS == 2 and module.ANALYSIS_MAX_MODEL_CALLS == 2
    assert settings().project_analysis_total_timeout_seconds == 120
    assert "one valid JSON object only" in module.SYSTEM_PROMPT
    assert "Escape strings correctly" in module.SYSTEM_PROMPT
    assert_simple_generation_schema()


def test_generation_scope_excludes_compulsory_expanded_breakdown_and_critic():
    from tests.professional_contract_support import assert_simple_generation_schema
    assert "compulsory project-task/skills/practice breakdown" in module.SYSTEM_PROMPT
    assert "or add a separate semantic-review report" in module.SYSTEM_PROMPT
    assert module.ANALYSIS_MAX_ATTEMPTS == 2 and module.ANALYSIS_MAX_MODEL_CALLS == 2
    assert_simple_generation_schema()


@pytest.mark.parametrize("text", [
    "区分暂停玩法逻辑与退出主循环再等待R",
    "按Esc退出主循环并在获胜时停止主循环等待R",
    "按Esc退出主循环且游戏结束时退出主循环等待R重开",
    "按Esc或游戏结束时退出主循环",
    "When Escape is pressed or game over exit the main game loop.",
    "Exit the main game loop when Escape is pressed or game over.",
    "处理 quitters 时停止主循环等待 R",
    "按 Escapee 时退出主循环等待 R",
    "收到 QUIT_WRAPPER 事件时退出主循环",
])
def test_comparison_or_quit_cannot_excuse_real_restart_stop(text):
    assert module._stops_whole_game_loop(text) is True


def test_generation_version_names_the_professional_term_contract():
    assert module.ANALYSIS_PROMPT_VERSION == "project-analysis-v4.1-coherent-professional-terms"


@pytest.mark.parametrize("text", ["按Esc退出主循环后等待R", "Exit the main game loop when Escape is pressed then wait for R key"])
def test_quit_cannot_wait_for_another_in_game_key(text):
    assert module._stops_whole_game_loop(text) is True


def test_actual_application_quit_can_finish_cleanup_without_waiting_for_key():
    assert module._stops_whole_game_loop("按Esc退出主循环后等待后台保存结束") is False
