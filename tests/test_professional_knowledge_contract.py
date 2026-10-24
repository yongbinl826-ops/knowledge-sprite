"""Simple-term protocol and retained protections; offline synthetic fixtures only."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from backend.app import project_analysis as module
from backend.app.config import Settings
from backend.app.llm import LLMCompletionTruncated, LLMResponseTooLarge
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer, generation_schema
from backend.app.project_models import AnalysisDocument, ProjectInput
from tests.professional_contract_support import flat_proposal, assert_simple_generation_schema


FIXTURE = json.loads((Path(__file__).parent / "fixtures/professional_knowledge/original_v1_fixture.json").read_text(encoding="utf-8"))
EXPANDED = {"project_task", "concepts", "learning_skills", "practice_check"}


def historical_body():
    # The raw original_v1_fixture remains unchanged for historical reads.
    # New-generation protocol fixtures use independent concept labels.
    result = deepcopy(FIXTURE["analysis"])
    result["knowledge_points"][1]["name"] = "pandas 缺失值处理"
    return result


def body():
    return flat_proposal(historical_body())


def config():
    # True deliberately proves that the abandoned mandatory critic is no longer
    # part of term generation, even with a retained historical operator setting.
    return Settings(llm_provider="openai_compatible", llm_base_url="https://offline.example/v1",
                    llm_api_key="synthetic-model-key", tavily_api_key="synthetic-search-key",
                    llm_model="offline-fixture", project_semantic_review_enabled=True)


def project():
    return ProjectInput(name="离线表格统计工具", requirements="读取本地表格并统计有效记录的平均值")


def response(value):
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


async def analyze_replies(replies, *, settings=None):
    calls = []

    def reply(req):
        calls.append(json.loads(req.content))
        assert len(calls) <= 2
        item = replies[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return response(item)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await ProjectAnalyzer(settings or config(), client).analyze(project())
    return result, calls


def test_schema_contains_only_base_document_and_points_with_optional_technology():
    assert_simple_generation_schema()


@pytest.mark.asyncio
async def test_flat_payload_works_without_expanded_fields_or_critic(monkeypatch):
    def forbidden(*_a, **_k):
        pytest.fail("The abandoned learning-unit quality checklist must not gate term generation")

    monkeypatch.setattr(module, "learning_quality_issues", forbidden)
    result, calls = await analyze_replies([body(), body()])
    assert len(calls) == 1 and result.learner_profile is None
    assert result.knowledge_points[0].technology == ""
    assert all(p.learning_skills == [] and p.concepts == [] and p.project_task is None and p.practice_check is None
               for p in result.knowledge_points)
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert sent["output_schema"] == generation_schema() and sent["project"] == project().model_dump()
    assert calls[0]["messages"][0]["content"] == module.SYSTEM_PROMPT
    assert calls[0]["max_tokens"] == config().llm_max_output_tokens
    assert module.ANALYSIS_MAX_MODEL_CALLS == module.ANALYSIS_MAX_ATTEMPTS == 2
    assert "established textbook noun or technical term" in module.SYSTEM_PROMPT
    assert "Use a reusable mechanism" in module.SYSTEM_PROMPT


@pytest.mark.parametrize("name", ["pygame事件处理", "矩形碰撞检测", "有限状态机", "pandas分组聚合"])
@pytest.mark.asyncio
async def test_professional_term_names_are_accepted_without_mandatory_tool_or_skills(name):
    sample = body()
    sample["knowledge_points"][0]["name"] = name
    result, calls = await analyze_replies([sample, sample])
    assert result.knowledge_points[0].name == name and len(calls) == 1


@pytest.mark.asyncio
async def test_technology_is_optional_but_supported_when_explicit():
    sample = body()
    sample["knowledge_points"][0]["technology"] = "pandas"
    result, calls = await analyze_replies([sample, sample])
    assert len(calls) == 1 and result.knowledge_points[0].technology == "pandas"


@pytest.mark.parametrize("extra", sorted(EXPANDED) + ["learner_profile"])
@pytest.mark.asyncio
async def test_unrequested_known_legacy_fields_are_rejected_not_projected_out(extra):
    sample = body()
    if extra == "learner_profile":
        sample[extra] = None
    else:
        sample["knowledge_points"][0][extra] = [] if extra in {"concepts", "learning_skills"} else "旧的项目任务拆解"
    result, calls = await analyze_replies([sample, body()])
    assert len(calls) == 2 and result.knowledge_points
    feedback = json.loads(calls[1]["messages"][1]["content"])["validation_feedback"]
    assert any(item["type"] == "extra_forbidden" for item in feedback)
    assert "learner_profile" not in result.model_dump()
    assert all(set(p) == {"id", "name", "description", "technology", "selection"}
               for p in result.model_dump()["knowledge_points"])



@pytest.mark.parametrize("extra", sorted(EXPANDED))
@pytest.mark.asyncio
async def test_unsafe_known_legacy_fields_cannot_hide_behind_projection(extra):
    sample = body()
    value = "https://untrusted.example/course"
    sample["knowledge_points"][0][extra] = [value] if extra in {"concepts", "learning_skills"} else value
    result, calls = await analyze_replies([sample, body()])
    assert len(calls) == 2 and result.knowledge_points
    assert value not in json.dumps(result.model_dump())


def historical_document():
    historical = AnalysisDocument.model_validate(historical_body()).model_dump()
    historical["learner_profile"] = {"student_level": "beginner", "assumed_knowledge": ["会运行脚本"],
                                    "adjustment_note": "可修改的旧版本假设"}
    for p in historical["knowledge_points"]:
        p.update(technology="pandas", project_task="保留的历史项目任务", concepts=["工作表读取", "有效记录统计"],
                 learning_skills=["保留的历史技能"], practice_check="保留的历史练习检查")
    return historical


def test_historical_expanded_fields_roundtrip_unchanged_with_free_reordering():
    historical = historical_document()
    original = deepcopy(historical)
    assert AnalysisDocument.model_validate(historical).model_dump() == original
    reordered = deepcopy(historical)
    reordered["knowledge_points"][0]["learning_order"] = 2
    reordered["knowledge_points"][1]["learning_order"] = 1
    parsed = AnalysisDocument.model_validate(reordered).model_dump()
    assert parsed == reordered
    assert parsed["knowledge_points"][1]["prerequisite_ids"] == ["k1"]
    assert historical == original  # no in-place migration or rename


@pytest.mark.parametrize("kind", ["missing_ref", "self_ref", "cycle", "duplicate_id", "duplicate_name", "bad_function", "order_zero", "order_large", "order_type"])
def test_history_and_edit_keep_reference_and_range_protections(kind):
    sample = historical_document()
    p, q = sample["knowledge_points"]
    if kind == "missing_ref": p["prerequisite_ids"] = ["missing"]
    elif kind == "self_ref": p["prerequisite_ids"] = ["k1"]
    elif kind == "cycle": p["prerequisite_ids"] = ["k2"]
    elif kind == "duplicate_id": q["id"] = p["id"]
    elif kind == "duplicate_name": q["name"] = p["name"]
    elif kind == "bad_function": p["function_ids"] = ["missing"]
    elif kind == "order_zero": p["learning_order"] = 0
    elif kind == "order_large": p["learning_order"] = 25
    else: p["learning_order"] = "1"
    with pytest.raises(ValidationError): AnalysisDocument.model_validate(sample)


@pytest.mark.parametrize("kind", ["url", "model_secret", "search_secret", "model_mastery", "broad_subject", "unknown_field", "invalid_graph"])
@pytest.mark.asyncio
async def test_unsafe_or_invalid_generation_is_repaired_within_two_calls(kind):
    sample = body()
    if kind == "url": sample["knowledge_points"][0]["description"] = "https://invalid.example/course"
    elif kind == "model_secret": sample["scope"] = config().llm_api_key
    elif kind == "search_secret": sample["scope"] = config().tavily_api_key
    elif kind == "model_mastery": sample["knowledge_points"][0]["selection"] = "mastered"
    elif kind == "broad_subject": sample["knowledge_points"][0]["name"] = "Python"
    elif kind == "invalid_graph": sample["knowledge_points"][0]["prerequisite_ids"] = ["k2"]
    else: sample["opaque-user-injected-field"] = "opaque-user-injected-value"
    result, calls = await analyze_replies([sample, body()])
    assert len(calls) == 2 and result.knowledge_points[0].selection == "learn"
    repair = calls[1]["messages"][1]["content"]
    assert all(x not in repair for x in [config().llm_api_key, config().tavily_api_key,
                                       "opaque-user-injected-field", "opaque-user-injected-value"])


@pytest.mark.parametrize("field,value", [("name", "Python"), ("selection", "mastered"), ("selection", "skip")])
@pytest.mark.asyncio
async def test_original_v1_title_and_mastery_rejection_remains_terminal_after_two_attempts(field, value):
    sample = body()
    sample["knowledge_points"][0][field] = value
    calls = []
    def reply(req):
        calls.append(req)
        return response(sample)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(AnalysisError) as error:
            await ProjectAnalyzer(config(), client).analyze(project())
    assert len(calls) == 2 and error.value.code == ("quality" if field == "name" else "schema")


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
@pytest.mark.asyncio
async def test_http_failures_are_safe_and_not_retried(status):
    calls = []
    def reply(req):
        calls.append(req)
        return httpx.Response(status, text="synthetic-model-key raw provider response")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(AnalysisError) as error:
            await ProjectAnalyzer(config(), client).analyze(project())
    assert error.value.code == "unavailable" and len(calls) == 1
    assert "raw provider" not in str(error.value.diagnostics) + error.value.message


@pytest.mark.parametrize("failure,expected,calls_expected", [
    (httpx.ConnectError, "unavailable", 2), (httpx.ReadTimeout, "timeout", 1),
    (LLMCompletionTruncated, "output_truncated", 1), (LLMResponseTooLarge, "response_too_large", 1),
])
@pytest.mark.asyncio
async def test_transport_error_boundaries_and_safe_observation_are_preserved(monkeypatch, failure, expected, calls_expected):
    count = []
    async def fail(*_a, **_kw):
        count.append(1)
        raise failure("synthetic-model-key opaque-provider-body")
    monkeypatch.setattr(module, "complete_json", fail)
    with pytest.raises(AnalysisError) as error:
        await ProjectAnalyzer(config()).analyze(project())
    assert error.value.code == expected and len(count) == calls_expected
    assert "synthetic-model-key" not in json.dumps(error.value.diagnostics)
    assert "opaque-provider-body" not in json.dumps(error.value.diagnostics)
    assert error.value.diagnostics[-1]["type"] == "attempt_history"


@pytest.mark.asyncio
async def test_shared_total_deadline_still_bounds_the_generation(monkeypatch):
    count = []
    async def slow(*_a, **_kw):
        count.append(1)
        await asyncio.sleep(10)
    monkeypatch.setattr(module, "complete_json", slow)
    monkeypatch.setattr(module, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(AnalysisError) as error:
        await ProjectAnalyzer(config()).analyze(project())
    assert error.value.code == "timeout" and len(count) == 1


@pytest.mark.asyncio
async def test_schema_repair_never_exceeds_two_attempts_and_does_not_echo_raw_values():
    calls = []
    def reply(req):
        calls.append(json.loads(req.content))
        assert len(calls) <= 2
        return response({"untrusted-extra-name": "untrusted-extra-value"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(AnalysisError) as error:
            await ProjectAnalyzer(config(), client).analyze(project())
    assert error.value.code == "schema" and len(calls) == 2
    retained = json.dumps(error.value.diagnostics) + calls[1]["messages"][1]["content"]
    assert "untrusted-extra-name" not in retained and "untrusted-extra-value" not in retained
