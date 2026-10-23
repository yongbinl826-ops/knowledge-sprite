"""Bounded title granularity only; no task/skill/practice/critic contract."""
import json

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from backend.app.project_models import ProjectInput
from tests.test_professional_knowledge_contract import body, config, project, response


@pytest.mark.parametrize("title,expected_code", [
    ("Python基础", "broad_subject"), ("Python 基础视频", "broad_subject"),
    ("python-basics", "broad_subject"), ("Programming basics", "broad_subject"),
    ("Arduino基础", "broad_subject"), ("网页开发", "broad_subject"),
    ("变量名", "syntax_fragment"), ("Python变量名", "syntax_fragment"),
    ("print 语句", "syntax_fragment"), ("assignment_statement", "syntax_fragment"),
    ("for循环语法", "syntax_fragment"),
])
@pytest.mark.asyncio
async def test_whole_course_or_micro_title_gets_one_controlled_quality_repair(title, expected_code):
    calls = []
    bad = body()
    bad["knowledge_points"][0]["name"] = title

    def reply(req):
        calls.append(json.loads(req.content))
        return response(bad if len(calls) == 1 else body())

    # An input explicitly naming a broad course is not a title-quality exemption.
    source = ProjectInput(name="Python基础", requirements="用 Python 学习必要知识，完成本地表格读取和统计")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        document = await ProjectAnalyzer(config(), client).analyze(source)
    assert len(calls) == 2 and document.knowledge_points[0].name == body()["knowledge_points"][0]["name"]
    sent = json.loads(calls[1]["messages"][1]["content"])
    assert sent["project"] == source.model_dump()
    assert sent["validation_feedback"][0]["type"] == "knowledge_term_quality"
    assert sent["validation_feedback"][0]["code"] == expected_code
    assert sent["previous_analysis"]["knowledge_points"][0]["name"] == title
    assert "learner_profile" not in sent["output_schema"]["properties"]


@pytest.mark.parametrize("title", ["pygame事件处理", "矩形碰撞检测", "有限状态机", "pandas分组聚合",
                                      "变量作用域", "JavaScript DOM事件监听", "状态转移", "变量"])
@pytest.mark.asyncio
async def test_coherent_professional_terms_are_not_rejected_or_expanded(title, monkeypatch):
    calls = []
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    def forbidden(*_a, **_kw):
        pytest.fail("No expanded teaching-unit check is allowed")
    monkeypatch.setattr(module, "learning_quality_issues", forbidden)
    def reply(req):
        calls.append(req)
        return response(supplied)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        document = await ProjectAnalyzer(config(), client).analyze(project())
    assert len(calls) == 2 and document.knowledge_points[0].name == title
    assert not document.knowledge_points[0].learning_skills and document.learner_profile is None


@pytest.mark.parametrize("mutation,expected", [
    (lambda p: p.update(name="Python基础"), "broad_subject"),
    (lambda p: p.update(name="变量名"), "syntax_fragment"),
])
@pytest.mark.asyncio
async def test_repeated_title_or_selection_failure_is_quality_with_safe_diagnostics(mutation, expected):
    sample = body()
    mutation(sample["knowledge_points"][0])
    calls = []
    def reply(req):
        calls.append(req)
        return response(sample)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(AnalysisError) as error:
            await ProjectAnalyzer(config(), client).analyze(project())
    assert len(calls) == 2 and error.value.code == "quality"
    assert "结构校验失败" not in error.value.message
    history = error.value.diagnostics[-1]["attempts"]
    assert [row["category"] for row in history] == ["quality", "quality"]
    assert history[0]["issues"][0]["code"] == expected
    assert history[0]["issues"][0]["location"] == ["knowledge_points", 0]
    assert "previous_analysis" not in json.dumps(error.value.diagnostics)
