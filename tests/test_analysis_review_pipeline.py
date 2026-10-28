"""Single-generation boundaries with offline transport explicitly isolated."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from backend.app.config import Settings
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from backend.app.project_models import AnalysisDocument
from tests.test_project_analysis import flat_analysis_fixture as analysis_fixture, settings, request, response
from tests.professional_contract_support import coverage_completion, semantic_review_pass_for_payload


def configured():
    return replace(settings(), project_semantic_review_enabled=True)


PASS = {"passed": True, "issues": []}
FAIL = {"passed": False, "issues": [{"severity": "medium", "code": "numeric_boundary",
        "location": "functions.f1.acceptance_criteria", "message": "Preserve equality allowed by the original requirements."}]}


@pytest.mark.asyncio
async def test_valid_terms_finish_once_even_with_legacy_review_setting():
    from tests.professional_contract_support import projected_once
    assert Settings().project_semantic_review_enabled is True  # historical config remains readable
    result, calls = await projected_once(analysis_fixture(), request(), configured())
    assert result.knowledge_points and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("unused_later_reply", [analysis_fixture(), {}])
async def test_structural_failure_stops_without_requesting_a_later_proposal(unused_later_reply):
    calls = []
    replies = [{}, unused_later_reply]
    def respond(req):
        calls.append(json.loads(req.content))
        assert len(calls) <= len(replies)
        return response(replies[len(calls)-1])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        analyzer = ProjectAnalyzer(configured(), client)
        with pytest.raises(AnalysisError) as failure:
            await analyzer.analyze(request())
        assert failure.value.code == "schema"
        assert failure.value.diagnostics[0]["type"] == "missing"
    assert len(calls) == 1
    assert [c["max_tokens"] for c in calls] == [6000]
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert sent["project"] == request().model_dump()
    assert "previous_analysis" not in sent and "repair_required" not in sent


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,code", [(httpx.ReadTimeout, "quality_review_unavailable"),
                                           (httpx.ConnectTimeout, "quality_review_unavailable"),
                                           (ValueError, "quality_review_invalid")])
async def test_generation_transport_or_schema_failure_never_becomes_a_valid_proposal(failure, code):
    calls = []
    def respond(req):
        calls.append(req)
        if failure is ValueError:
            return response({"passed": True, "issues": FAIL["issues"]})
        raise failure("private-offline-token untrusted failure", request=req)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as raised:
            await ProjectAnalyzer(configured(), client).analyze(request())
    expected = "schema" if failure is ValueError else "unavailable" if failure is httpx.ConnectTimeout else "timeout"
    assert raised.value.code == expected
    assert len(calls) == 1
    assert "private-offline-token" not in raised.value.message
    assert "untrusted failure" not in json.dumps(raised.value.diagnostics)


@pytest.mark.asyncio
async def test_generation_cannot_escape_shared_wall_clock_budget(monkeypatch):
    from backend.app import project_analysis as module
    calls = []
    async def slow_generate(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        await asyncio.sleep(10)
    monkeypatch.setattr(module, "complete_json", slow_generate)
    monkeypatch.setattr(module, "ANALYSIS_TOTAL_TIMEOUT_SECONDS", .02)
    with pytest.raises(AnalysisError) as raised:
        await ProjectAnalyzer(configured()).analyze(request())
    assert raised.value.code == "timeout"
    assert len(calls) == 1 and calls[0] <= .02


@pytest.mark.parametrize("value", ["typo", "", "sometimes"])
def test_invalid_review_setting_does_not_silently_disable_guard(monkeypatch, value):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("PROJECT_SEMANTIC_REVIEW_ENABLED", value)
    with pytest.raises(ValueError, match="PROJECT_SEMANTIC_REVIEW_ENABLED"):
        Settings.from_env()


@pytest.mark.parametrize("value,expected", [("false", False), ("true", True)])
def test_operator_review_setting_is_explicit(monkeypatch, value, expected):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("PROJECT_SEMANTIC_REVIEW_ENABLED", value)
    assert Settings.from_env().project_semantic_review_enabled is expected
