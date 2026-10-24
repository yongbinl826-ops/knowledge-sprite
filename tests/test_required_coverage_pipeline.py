"""Compact flow regressions replacing mandatory inventory/completion calls.

Local acceptance is not proof of semantic completeness. Historical coverage
report parsing and reference checks remain in test_analysis_coverage.py.
"""
import asyncio
from copy import deepcopy
import hashlib
import json

import httpx
import pytest

from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from tests.professional_contract_support import coverage_completion, draft_with_inventory
from tests.test_project_analysis import flat_analysis_fixture, request, response, settings


@pytest.mark.asyncio
async def test_valid_flat_response_stops_after_generation_without_coverage_claims():
    source, original, calls, audits = flat_analysis_fixture(), request(), [], []

    def respond(req):
        calls.append(json.loads(req.content))
        assert len(calls) == 1, "Valid flat responses must not start a mandatory review"
        return response(source)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(settings(), client).analyze(original, on_analysis_attempt=audits.append)
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["project"] == original.model_dump()
    assert set(payload["output_schema"]["properties"]) == {"scope", "technical_plan", "assumptions", "knowledge_points"}
    assert [row["phase"] for row in audits] == ["generation"]
    assert [row["outcome"] for row in audits] == ["accepted"]
    assert audits[0]["analysis"] == source
    assert audits[0]["validation_scope"] == "local_checks"
    expected_hash = hashlib.sha256(json.dumps(original.model_dump(), ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert audits[0]["source_sha256"] == expected_hash
    for obsolete in ("implementation_inventory", "coverage_review", "semantic_review", "passed"):
        assert obsolete not in payload and obsolete not in audits[0] and obsolete not in result.model_dump()


@pytest.mark.parametrize("envelope_kind", ["inventory", "coverage", "flat_with_coverage", "flat_with_inventory"])
@pytest.mark.asyncio
async def test_coverage_envelopes_and_extra_claims_cannot_be_projected_into_an_accepted_analysis(envelope_kind):
    source = flat_analysis_fixture()
    draft = draft_with_inventory(source, request())
    completion = coverage_completion(source, request(), draft["inventory"])
    proposal = {"inventory": draft, "coverage": completion,
                "flat_with_coverage": {**source, "coverage": completion["coverage"]},
                "flat_with_inventory": {**source, "inventory": draft["inventory"]}}[envelope_kind]
    calls, audits = [], []

    def respond(req):
        calls.append(req)
        assert len(calls) <= 2
        return response(proposal)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as error:
            await ProjectAnalyzer(settings(), client).analyze(request(), on_analysis_attempt=audits.append)
    assert error.value.code == "schema" and len(calls) == 2
    assert [row["phase"] for row in audits] == ["generation", "repair"]
    assert all(row["outcome"] == "rejected" and row["analysis"] == proposal for row in audits)


@pytest.mark.asyncio
async def test_schema_repair_uses_original_requirements_without_a_reconstructed_inventory():
    source = flat_analysis_fixture()
    bad = draft_with_inventory(source, request())
    bad["inventory"]["mechanisms"][0]["source_quote"] = "an invented source excerpt"
    original, calls, audits = request(), [], []

    def respond(req):
        payload = json.loads(json.loads(req.content)["messages"][1]["content"])
        calls.append(payload)
        if len(calls) == 1:
            return response(bad)
        assert payload["project"] == original.model_dump()
        assert payload["repair_required"] is True and payload["validation_feedback"]
        assert "implementation_inventory" not in payload and "reconstructed_inventory" not in payload
        assert "previous_analysis" not in payload
        assert "an invented source excerpt" not in json.dumps(payload)
        return response(source)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(settings(), client).analyze(original, on_analysis_attempt=audits.append)
    assert len(calls) == 2 and len(result.knowledge_points) == len(source["knowledge_points"])
    assert [row["outcome"] for row in audits] == ["rejected", "accepted"]
    assert audits[0]["source_sha256"] == audits[1]["source_sha256"]


@pytest.mark.asyncio
async def test_local_repair_preserves_unrelated_concepts_and_explanations():
    source = flat_analysis_fixture()
    bad = deepcopy(source)
    bad["knowledge_points"][0]["name"] = "Python基础"
    frozen = deepcopy(bad)
    calls, audits = [], []

    def respond(req):
        payload = json.loads(json.loads(req.content)["messages"][1]["content"])
        calls.append(payload)
        if len(calls) == 1:
            return response(bad)
        assert payload["previous_analysis"] == bad
        assert payload["repair_targets"] and payload["project"] == request().model_dump()
        assert any(item["code"] == "broad_subject" for item in payload["validation_feedback"])
        fixed = deepcopy(payload["previous_analysis"])
        fixed["knowledge_points"][0]["name"] = source["knowledge_points"][0]["name"]
        return response(fixed)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(settings(), client).analyze(request(), on_analysis_attempt=audits.append)
    assert len(calls) == 2 and bad == frozen
    assert audits[-1]["analysis"] == source
    assert result.knowledge_points[1].description == source["knowledge_points"][1]["description"]
    assert result.knowledge_points[0].description == source["knowledge_points"][0]["description"]
    assert [row["outcome"] for row in audits] == ["rejected", "accepted"]


@pytest.mark.asyncio
async def test_cancellation_during_optional_repair_never_delivers_the_rejected_draft(monkeypatch):
    bad, calls, audits = flat_analysis_fixture(), [], []
    bad["knowledge_points"][0]["name"] = "Python基础"
    repairing = asyncio.Event()

    async def complete(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return bad
        repairing.set()
        await asyncio.Future()

    monkeypatch.setattr("backend.app.project_analysis.complete_json", complete)
    task = asyncio.create_task(ProjectAnalyzer(settings()).analyze(request(), on_analysis_attempt=audits.append))
    await asyncio.wait_for(repairing.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 2
    assert [row["category"] for row in audits] == ["quality", "cancelled"]
    assert all(row["outcome"] != "accepted" for row in audits)
    assert audits[0]["analysis"] == bad and audits[1]["analysis"] is None


@pytest.mark.asyncio
async def test_audit_overflow_fails_instead_of_accepting_without_retained_evidence(monkeypatch):
    calls, audits = [], []

    async def oversized(*args, **kwargs):
        calls.append(1)
        return {"untrusted": "x" * 120_001}

    monkeypatch.setattr("backend.app.project_analysis.complete_json", oversized)
    with pytest.raises(AnalysisError) as error:
        await ProjectAnalyzer(settings()).analyze(request(), on_analysis_attempt=audits.append)
    assert error.value.code == "response_too_large" and len(calls) == 1
    assert audits[-1]["outcome"] == "rejected" and audits[-1]["analysis"] is None
