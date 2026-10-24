"""Regression of actual r2 title holes; syntax is parsed, never executed."""
import json

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from tests.professional_contract_support import unrepaired_quality_response
from tests.test_professional_knowledge_contract import body, config, project, response


@pytest.mark.parametrize("title,code", [
    ("Python 基础知识", "broad_subject"),
    ("英语基础", "broad_subject"),
    ("English basics", "broad_subject"),
    ("Ｅｎｇｌｉｓｈ　ｂａｓｉｃｓ", "broad_subject"),
    ("score = 0", "syntax_fragment"),
    ("x = x + 1", "syntax_fragment"),
    ("print('hello')", "syntax_fragment"),
    ("lives -= 1", "syntax_fragment"),
    ("count: int = 0", "syntax_fragment"),
    ("sensors.read()", "syntax_fragment"),
    ("result = measure()", "syntax_fragment"),
    ("pygame.time.Clock()", "syntax_fragment"),
    ("分数 = 0", "syntax_fragment"),
])
@pytest.mark.asyncio
async def test_observed_broad_or_whole_statement_title_gets_bounded_quality_repair(title, code):
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    calls = []
    def reply(req):
        calls.append(json.loads(req.content))
        return response(supplied if len(calls) == 1 else body())
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await ProjectAnalyzer(config(), client).analyze(project())
    assert len(calls) == 2
    assert result.knowledge_points[0].name == body()["knowledge_points"][0]["name"]
    repair = json.loads(calls[1]["messages"][1]["content"])
    assert repair["validation_feedback"][0]["type"] == "knowledge_term_quality"
    assert repair["validation_feedback"][0]["code"] == code
    assert repair["previous_analysis"]["knowledge_points"][0]["name"] == title
    assert module.ANALYSIS_MAX_MODEL_CALLS == 2
    assert module.ANALYSIS_MAX_ATTEMPTS == 2


@pytest.mark.parametrize("title", [
    "状态机", "Python 基础数据类型的数值转换",
    "英语音标", "pygame.Rect", "pandas.to_datetime 日期时间解析",
    "函数调用", "变量作用域", "JavaScript 严格相等比较",
    "占空比", "React useState 状态管理", "矩形碰撞检测",
    "函数调用 (Function Call)", "CSS: Grid", "HTML: forms",
    # A syntax check cannot decide whether ordinary conjunctions describe one
    # coherent topic; these names are not a claim of semantic certification.
    "Python 列表与循环的游戏状态建模", "英语音标与重音规则",
    "函数调用与参数传递", "变量作用域与状态建模", "PWM 占空比与亮度控制",
])
@pytest.mark.asyncio
async def test_professional_topics_are_not_rejected_for_substrings_or_api_identifiers(title, monkeypatch):
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    calls = []
    def no_expanded_gate(*_args, **_kwargs):
        pytest.fail("Expanded pedagogical gates are outside the current contract")
    monkeypatch.setattr(module, "learning_quality_issues", no_expanded_gate)
    def reply(req):
        calls.append(req)
        return response(supplied)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await ProjectAnalyzer(config(), client).analyze(project())
    assert len(calls) == 1 and result.knowledge_points[0].name == title
    assert result.knowledge_points[0].learning_skills == []


@pytest.mark.asyncio
async def test_repeated_single_statement_is_rejected_after_last_quality_correction():
    supplied = body()
    supplied["knowledge_points"][0]["name"] = "x = x + 1"
    calls = []
    def reply(req):
        calls.append(req)
        payload = json.loads(json.loads(req.content)["messages"][1]["content"])
        return response(unrepaired_quality_response(payload, supplied, project()))
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(AnalysisError) as error:
            await ProjectAnalyzer(config(), client).analyze(project())
    assert len(calls) == 2 and error.value.code == "quality"
    assert error.value.diagnostics[0]["code"] == "syntax_fragment"
    history = error.value.diagnostics[-1]["attempts"]
    assert [row["phase"] for row in history] == ["generation", "repair"]
    assert [row["category"] for row in history] == ["quality", "quality"]
