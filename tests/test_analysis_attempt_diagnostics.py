"""Offline transport and prompt-contract checks; no model-semantic pass claims."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.analysis_review import SYSTEM_REVIEW_PROMPT, REVIEW_PROMPT_VERSION
from backend.app.llm import LLMCompletionTruncated, LLMResponseTooLarge
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer, SYSTEM_PROMPT
from tests.test_project_analysis import flat_analysis_fixture as analysis_fixture, settings, request, response


def history(error):
    rows = [d for d in error.diagnostics if d.get("type") == "attempt_history"]
    assert len(rows) == 1
    return rows[0]["attempts"]


def without_timing(row):
    """Inspect fixed diagnostic fields while retaining the new timing envelope."""
    timing_fields = {
        "started_at", "finished_at", "elapsed_seconds", "model_started_at", "model_finished_at",
        "model_elapsed_seconds", "validation_started_at", "validation_finished_at",
        "validation_elapsed_seconds", "max_output_tokens", "thinking_mode", "reasoning_effort",
    }
    assert timing_fields <= row.keys()
    assert row["started_at"] and row["finished_at"] and row["elapsed_seconds"] >= 0
    return {key: value for key, value in row.items() if key not in timing_fields}


async def run_failure(replies, *, review=False):
    calls = []

    def respond(req):
        calls.append(json.loads(req.content))
        item = replies[len(calls) - 1]
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("private-offline-token untrusted exception text", request=req)
        return response(item)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as failure:
            await ProjectAnalyzer(replace(settings(), project_semantic_review_enabled=review), client).analyze(request())
    return failure.value, calls


@pytest.mark.asyncio
async def test_json_then_schema_keeps_both_reasons_and_json_coordinates():
    invalid = '{\n  "private-user-text": }'
    error, calls = await run_failure([invalid, {"scope": "An incomplete document"}])
    assert error.code == "schema" and len(calls) == 2
    rows = history(error)
    try:
        json.loads(invalid)
    except json.JSONDecodeError as expected:
        assert without_timing(rows[0]) == {"attempt": 1, "phase": "generation", "category": "invalid_json",
                           "exception_type": "JSONDecodeError", "line": expected.lineno,
                           "column": expected.colno, "position": expected.pos}
    assert rows[1]["category"] == "schema"
    assert any(x["location"] == ["technical_plan"] and x["type"] == "missing" for x in rows[1]["errors"])
    assert error.diagnostics[0]["type"] == "missing"  # existing final feedback stays first
    assert "private-user-text" not in json.dumps(error.diagnostics)


@pytest.mark.asyncio
async def test_unknown_extra_key_is_masked_in_feedback_history_and_repair_payload():
    bad = analysis_fixture()
    bad["private-user-field-key"] = "private-user-field-value"
    bad["knowledge_points"][0]["name"] = ["private-user-invalid-value"]
    error, calls = await run_failure([bad, "not-json"])
    first = history(error)[0]
    assert first["category"] == "schema"
    assert {"location": ["<unknown_field>"], "type": "extra_forbidden"} in first["errors"]
    assert {"location": ["knowledge_points", 0, "name"], "type": "string_type"} in first["errors"]
    retained = json.dumps(error.diagnostics) + calls[1]["messages"][1]["content"]
    assert all(word not in retained for word in ["private-user-field-key", "private-user-field-value", "private-user-invalid-value"])


@pytest.mark.asyncio
async def test_two_json_errors_preserve_distinct_locations_without_raw_response():
    error, calls = await run_failure(['{\n"secret-body-one": }', '[\n\n private-body-two'])
    assert error.code == "invalid_json" and len(calls) == 2
    rows = history(error)
    assert [x["attempt"] for x in rows] == [1, 2]
    assert [x["line"] for x in rows] == [2, 3]
    assert not any(text in json.dumps(error.diagnostics) for text in ["secret-body-one", "private-body-two"])


@pytest.mark.asyncio
async def test_schema_then_read_timeout_preserves_first_failure_without_third_call():
    error, calls = await run_failure([{}, httpx.ReadTimeout])
    assert error.code == "timeout" and len(calls) == 2
    assert [x["category"] for x in history(error)] == ["schema", "timeout"]
    assert "private-offline-token" not in json.dumps(error.diagnostics)


@pytest.mark.asyncio
async def test_connect_failure_uses_existing_two_attempt_budget_only():
    error, calls = await run_failure([httpx.ConnectError, "invalid-json"])
    assert error.code == "invalid_json" and len(calls) == 2
    assert [x["category"] for x in history(error)] == ["connection_unavailable", "invalid_json"]


@pytest.mark.asyncio
async def test_title_quality_then_json_repair_retains_both_generation_attempts():
    bad = analysis_fixture()
    bad["knowledge_points"][0]["name"] = "Python基础"
    error, calls = await run_failure([bad, "bad-json"], review=True)
    rows = history(error)
    assert error.code == "invalid_json" and len(calls) == 2
    assert [(r["attempt"], r["phase"], r["category"]) for r in rows] == [
        (1, "generation", "quality"), (2, "repair", "invalid_json")]
    repair = json.loads(calls[1]["messages"][1]["content"])
    assert repair["previous_analysis"]["knowledge_points"]
    assert repair["validation_feedback"][0]["code"] == "broad_subject"
    assert repair["validation_feedback"][0]["type"] == "knowledge_term_quality"


@pytest.mark.asyncio
async def test_two_title_rejections_keep_quality_code_and_two_generation_call_cap():
    bad = analysis_fixture()
    bad["knowledge_points"][0]["name"] = "Python基础"
    error, calls = await run_failure([bad, bad], review=True)
    assert error.code == "quality" and len(calls) == 2
    assert error.diagnostics[0]["code"] == "broad_subject"
    assert [x["attempt"] for x in history(error)] == [1, 2]
    assert [x["phase"] for x in history(error)] == ["generation", "repair"]
    assert [c["max_tokens"] for c in calls] == [6000, 12000]


@pytest.mark.asyncio
async def test_retained_review_setting_does_not_invoke_auxiliary_transport():
    from tests.professional_contract_support import projected_once
    result, calls = await projected_once(analysis_fixture(), request(),
        replace(settings(), project_semantic_review_enabled=True))
    assert result.knowledge_points and len(calls) == 1


@pytest.mark.asyncio
async def test_configured_secret_echo_gets_only_fixed_invalid_analysis_summary():
    body = analysis_fixture()
    body["scope"] = "private-offline-token"
    error, calls = await run_failure([body, "invalid-json"])
    assert without_timing(history(error)[0]) == {"attempt": 1, "phase": "generation", "category": "invalid_analysis"}
    assert "private-offline-token" not in json.dumps(error.diagnostics)
    repair = json.loads(calls[1]["messages"][1]["content"])["validation_feedback"]
    message = repair[0]["message"]
    assert "flat concept-list schema" in message
    assert all(word not in message for word in ("graph", "selection", "prerequisite", "learning_order"))


@pytest.mark.asyncio
@pytest.mark.parametrize("exception_type,code", [
    (LLMCompletionTruncated, "output_truncated"),
    (LLMResponseTooLarge, "response_too_large"),
    (httpx.HTTPError, "unavailable"),
])
async def test_terminal_provider_failure_keeps_first_schema_reason_and_no_body(monkeypatch, exception_type, code):
    calls = []
    async def generate(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {}
        raise exception_type("private-provider-body private-offline-token")
    monkeypatch.setattr(module, "complete_json", generate)
    with pytest.raises(AnalysisError) as error:
        await ProjectAnalyzer(settings()).analyze(request())
    assert error.value.code == code and len(calls) == 2
    rows = history(error.value)
    assert rows[0]["category"] == "schema"
    assert rows[1]["category"] == ("http_unavailable" if code == "unavailable" else code)
    assert all(s not in json.dumps(error.value.diagnostics) for s in ["private-provider-body", "private-offline-token"])


@pytest.mark.asyncio
async def test_successful_json_repair_returns_only_flat_concept_document():
    from tests.professional_contract_support import assert_v1_projection
    calls = []
    def respond(req):
        calls.append(req)
        return response("invalid-json" if len(calls) == 1 else analysis_fixture())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(settings(), client).analyze(request())
    assert len(calls) == 2
    assert "attempt_history" not in result.model_dump()
    assert_v1_projection(result, analysis_fixture())


@pytest.mark.asyncio
async def test_shared_deadline_still_bounds_generation_and_records_phase(monkeypatch):
    calls = []
    async def slow_generate(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        await asyncio.sleep(10)
    monkeypatch.setattr(module, "complete_json", slow_generate)
    monkeypatch.setattr(module, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", .02)
    with pytest.raises(AnalysisError) as error:
        await ProjectAnalyzer(replace(settings(), project_semantic_review_enabled=True)).analyze(request())
    assert error.value.code == "timeout"
    assert len(calls) == 1 and calls[0] <= .02
    assert history(error.value)[0]["phase"] == "generation"


def test_schema_summary_is_bounded_and_does_not_echo_unknown_fields():
    from pydantic import ValidationError
    from backend.app.project_models import AnalysisDocument
    bad = {f"opaque-provider-field-{i}": "untrusted-value" for i in range(100)}
    with pytest.raises(ValidationError) as exc:
        AnalysisDocument.model_validate(bad)
    details = module._safe_schema_error_details(exc.value)
    assert len(details) == 20 and all(len(d["location"]) <= 8 for d in details)
    assert "opaque-provider-field" not in json.dumps(details)
    assert "untrusted-value" not in json.dumps(details)


def test_prompt_contract_uses_professional_terms_and_untrusted_project_data():
    from tests.professional_contract_support import assert_simple_generation_schema
    assert module.ANALYSIS_PROMPT_VERSION == "project-analysis-v5.22-program-state-description-checks"
    assert "untrusted project data" in SYSTEM_PROMPT
    assert "concise established textbook noun or technical term" in SYSTEM_PROMPT
    assert "Never invent courses, video links, chapters or source evidence" in SYSTEM_PROMPT
    assert "The student only decides which concepts to learn" in SYSTEM_PROMPT
    assert "Do not infer mastery" in SYSTEM_PROMPT
    assert "project_task, concepts, learning_skills, practice_check or learner_profile" in SYSTEM_PROMPT
    assert_simple_generation_schema()
