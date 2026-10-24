"""No mandatory semantic-model stage in the compact runtime.

Historical semantic report/reference validation stays in test_analysis_semantics.
These tests check transport boundaries, not model-generated factual correctness.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from tests.professional_contract_support import coverage_completion, draft_with_inventory, semantic_review_pass
from tests.test_project_analysis import flat_analysis_fixture, request, response, settings


async def run_attempts(replies, *, configured=None):
    calls, audits = [], []

    def handler(req):
        calls.append(json.loads(req.content))
        assert len(calls) <= len(replies), "Unexpected additional model request"
        item = replies[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, httpx.Response) else response(item)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        try:
            result = await ProjectAnalyzer(configured or settings(), client).analyze(
                request(), on_analysis_attempt=audits.append)
        except AnalysisError as error:
            return error, calls, audits
    return result, calls, audits


@pytest.mark.parametrize("legacy_review_flag", [False, True])
@pytest.mark.asyncio
async def test_legacy_semantic_flag_cannot_add_a_review_request(legacy_review_flag):
    proposal = flat_analysis_fixture()
    result, calls, audits = await run_attempts([proposal],
        configured=replace(settings(), project_semantic_review_enabled=legacy_review_flag))
    assert not isinstance(result, AnalysisError) and len(calls) == 1
    assert [entry["outcome"] for entry in audits] == ["accepted"]
    assert audits[0]["validation_scope"] == "local_checks"
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert set(payload) == {"project", "output_schema", "limits"}
    assert "passed" not in payload["output_schema"]["properties"]
    assert "semantic_review" not in audits[0]


@pytest.mark.parametrize("claim_kind", ["report", "correction", "passed", "semantic_review", "resolutions"])
@pytest.mark.asyncio
async def test_semantic_wrappers_or_claims_cannot_override_the_flat_contract(claim_kind):
    proposal = flat_analysis_fixture()
    inventory = draft_with_inventory(proposal, request())["inventory"]
    report = semantic_review_pass(proposal, inventory)
    correction = coverage_completion(proposal, request(), inventory=inventory)
    correction["resolutions"] = []
    body = {"report": report, "correction": correction,
            "passed": {**proposal, "passed": True},
            "semantic_review": {**proposal, "semantic_review": report},
            "resolutions": {**proposal, "resolutions": []}}[claim_kind]
    result, calls, audits = await run_attempts([body, body])
    assert isinstance(result, AnalysisError) and result.code == "schema" and len(calls) == 2
    assert [entry["phase"] for entry in audits] == ["generation", "repair"]
    assert all(entry["outcome"] == "rejected" for entry in audits)


@pytest.mark.parametrize("fixed", [False, True])
@pytest.mark.asyncio
async def test_local_defects_are_not_discarded_and_only_one_correction_is_available(fixed):
    proposal = flat_analysis_fixture()
    bad = deepcopy(proposal)
    bad["knowledge_points"][0]["name"] = "读取文件+统计平均分"
    result, calls, audits = await run_attempts([bad, proposal if fixed else bad])
    assert len(calls) == 2
    payload = json.loads(calls[1]["messages"][1]["content"])
    assert payload["previous_analysis"] == bad
    assert payload["repair_targets"] and payload["repair_required"] is True
    assert any(item["code"] == "task_bundle_name" for item in payload["validation_feedback"])
    assert audits[0]["outcome"] == "rejected" and audits[0]["category"] == "quality"
    if fixed:
        assert not isinstance(result, AnalysisError) and audits[1]["outcome"] == "accepted"
        assert audits[1]["analysis"] == proposal
    else:
        assert isinstance(result, AnalysisError) and result.code == "quality"
        assert not any(entry["outcome"] == "accepted" for entry in audits)


@pytest.mark.asyncio
async def test_optional_repair_uses_actual_project_model_budgets_and_original_source():
    proposal = flat_analysis_fixture()
    configured = replace(settings(), llm_base_url="https://api.deepseek.com",
        project_analysis_model="deepseek-v4-pro", project_analysis_reasoning_effort="low",
        project_analysis_max_output_tokens=16000, project_analysis_normalization_max_output_tokens=12000)
    result, calls, audits = await run_attempts([{}, proposal], configured=configured)
    assert not isinstance(result, AnalysisError) and len(calls) == 2
    assert [entry["phase"] for entry in audits] == ["generation", "repair"]
    assert [entry["max_output_tokens"] for entry in audits] == [16000, 12000]
    assert {call["model"] for call in calls} == {"deepseek-v4-pro"}
    assert all(call["reasoning_effort"] == "low" for call in calls)
    assert configured.llm_model == "offline-test-model"
    assert len({entry["source_sha256"] for entry in audits}) == 1
    assert all(json.loads(call["messages"][1]["content"])["project"] == request().model_dump() for call in calls)


@pytest.mark.parametrize("defect,code", [("schema", "schema"), ("quality", "quality"),
    ("secret", "schema"), ("cap", "too_large"), ("timeout", "timeout"), ("truncated", "output_truncated")])
@pytest.mark.asyncio
async def test_failed_repair_never_calls_a_third_stage_or_returns_the_prior_candidate(defect, code):
    bad = flat_analysis_fixture()
    bad["knowledge_points"][0]["name"] = "Python基础"
    repaired = flat_analysis_fixture()
    if defect == "schema":
        repaired = {"analysis": repaired}
    elif defect == "quality":
        repaired = deepcopy(bad)
    elif defect == "secret":
        repaired["knowledge_points"][0]["description"] = settings().llm_api_key
    elif defect == "cap":
        repaired["knowledge_points"] *= 16
    elif defect == "timeout":
        repaired = httpx.ReadTimeout("offline timeout")
    else:
        repaired = httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {
            "content": json.dumps(repaired)}}]})
    result, calls, audits = await run_attempts([bad, repaired])
    assert isinstance(result, AnalysisError) and result.code == code and len(calls) == 2
    assert [entry["attempt"] for entry in audits] == [1, 2]
    assert all(entry["outcome"] == "rejected" for entry in audits)
    assert settings().llm_api_key not in json.dumps(result.diagnostics)
    if defect in {"secret", "timeout", "truncated"}:
        assert audits[1]["analysis"] is None
    if defect == "secret":
        assert settings().llm_api_key not in json.dumps(audits)
    if defect == "cap":
        assert len(audits[1]["analysis"]["knowledge_points"]) == 32


@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.asyncio
async def test_validation_crossing_total_deadline_cannot_accept(monkeypatch, stage):
    import backend.app.project_analysis as module
    state = SimpleNamespace(now=100.0)
    replacements = {name: getattr(asyncio, name) for name in dir(asyncio)}
    replacements["get_running_loop"] = lambda: SimpleNamespace(time=lambda: state.now)
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(**replacements))
    original = module._local_quality_issues

    def slow_validation(*args, **kwargs):
        issues = original(*args, **kwargs)
        state.now += 61
        return issues

    monkeypatch.setattr(module, "_local_quality_issues", slow_validation)
    replies = [flat_analysis_fixture()] if stage == 1 else [{}, flat_analysis_fixture()]
    result, calls, audits = await run_attempts(replies)
    assert isinstance(result, AnalysisError) and result.code == "timeout"
    assert len(calls) == stage and audits[-1]["outcome"] == "rejected"
    assert audits[-1]["category"] == "timeout"
    assert not any(entry["outcome"] == "accepted" for entry in audits)
