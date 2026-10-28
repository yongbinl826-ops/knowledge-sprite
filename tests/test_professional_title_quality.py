"""Single-pass title preservation; prior quality categories are no longer gates."""
from copy import deepcopy
import json

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.project_analysis import ProjectAnalyzer
from backend.app.project_models import ProjectInput
from tests.test_professional_knowledge_contract import body, config, project, response


async def generate_once(supplied, source=None):
    calls, audit, rejected = [], [], []
    original = deepcopy(supplied)
    source = source or project()
    def reply(req):
        calls.append(json.loads(req.content))
        assert len(calls) == 1, "Analysis must not start a repair request"
        return response(supplied)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await ProjectAnalyzer(config(), client).analyze(
            source, on_analysis_attempt=audit.append, on_rejected_attempt=rejected.append)
    assert len(calls) == len(audit) == 1 and rejected == []
    assert audit[0]["phase"] == "generation" and audit[0]["outcome"] == "accepted"
    assert audit[0]["validation_scope"] == "schema_safety_limits"
    assert "advisories" not in audit[0] and "issues" not in audit[0]
    assert audit[0]["analysis"] == original and supplied == original
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert sent["project"] == source.model_dump()
    assert not {"validation_feedback", "repair_targets", "previous_analysis", "repair_required"} & set(sent)
    assert [p.name for p in result.knowledge_points] == [p["name"] for p in supplied["knowledge_points"]]
    assert [p.description for p in result.knowledge_points] == [p["description"] for p in supplied["knowledge_points"]]
    assert [p.technology for p in result.knowledge_points] == [p.get("technology", "") for p in supplied["knowledge_points"]]
    return result, calls


@pytest.mark.parametrize("title", [
    "Python基础", "Python 基础视频", "python-basics", "Programming basics",
    "Arduino基础", "网页开发", "变量名", "Python变量名", "print 语句",
    "assignment_statement", "for循环语法",
])
@pytest.mark.asyncio
async def test_whole_course_or_micro_title_is_preserved_without_judgement(title, monkeypatch):
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    def forbidden(*_a, **_kw):
        pytest.fail("Naming/content judgement must not run")
    monkeypatch.setattr(module, "_local_quality_issues", forbidden)
    source = ProjectInput(name="Python基础", requirements="用 Python 完成本地表格读取和统计")
    await generate_once(supplied, source)


@pytest.mark.parametrize("title", ["pygame事件处理", "矩形碰撞检测", "有限状态机", "pandas分组聚合",
                                  "变量作用域", "JavaScript DOM事件监听", "状态转移", "变量"])
@pytest.mark.asyncio
async def test_professional_terms_are_not_rejected_or_expanded(title, monkeypatch):
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    def forbidden(*_a, **_kw):
        pytest.fail("No teaching-unit quality check is allowed")
    monkeypatch.setattr(module, "learning_quality_issues", forbidden)
    result, _ = await generate_once(supplied)
    assert not result.knowledge_points[0].learning_skills and result.learner_profile is None


@pytest.mark.parametrize("title", ["Python基础", "变量名"])
@pytest.mark.asyncio
async def test_prior_rejection_labels_do_not_create_advisories_or_retry(title):
    supplied = body()
    supplied["knowledge_points"][0]["name"] = title
    await generate_once(supplied)
