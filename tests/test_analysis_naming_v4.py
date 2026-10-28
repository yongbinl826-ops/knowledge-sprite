"""Unchanged saved v4 replay; no live inference or synthetic name replacement."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from backend.app import project_analysis as module
from backend.app.config import Settings
from backend.app.project_models import ProjectInput
from tests.test_analysis_compact import fake_clock


RECORD = json.loads((Path(__file__).parent / "fixtures/analysis-naming-v4.json").read_text(encoding="utf-8"))


def configured(**changes):
    base = Settings(llm_provider="openai_compatible", llm_base_url="https://api.deepseek.com/v1",
                    llm_api_key="offline-only", llm_model="deepseek-flash",
                    project_analysis_reasoning_effort="low",
                    project_analysis_max_output_tokens=16000,
                    project_analysis_normalization_max_output_tokens=16000)
    return replace(base, **changes)


@pytest.fixture(autouse=True)
def forbid_quality_checks_and_repair(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Saved v4 must not enter any semantic/name review or repair")
    for name in ("_local_quality_issues", "_partition_quality_issues", "_name_repair_context",
                 "learning_quality_issues", "textbook_concept_issues", "professional_contract_issues",
                 "apply_name_repairs"):
        monkeypatch.setattr(module, name, forbidden, raising=False)


def assert_original_fields(result):
    assert len(result.knowledge_points) == len(RECORD["analysis"]["knowledge_points"]) == 18
    assert result.scope == RECORD["analysis"]["scope"]
    assert result.technical_plan == RECORD["analysis"]["technical_plan"]
    assert result.assumptions == RECORD["analysis"]["assumptions"]
    for saved, point in zip(RECORD["analysis"]["knowledge_points"], result.knowledge_points):
        actual = point.model_dump()
        assert {field: actual[field] for field in saved} == saved


@pytest.mark.asyncio
async def test_recorded_v4_is_accepted_unchanged_in_one_generation(monkeypatch):
    original = deepcopy(RECORD)
    calls, audit, rejected = [], [], []

    async def complete(settings, prompt, payload, *_args, **options):
        calls.append((settings, prompt, deepcopy(payload), options))
        assert len(calls) == 1
        return deepcopy(RECORD["analysis"])

    monkeypatch.setattr(module, "complete_json", complete)
    result = await module.ProjectAnalyzer(configured()).analyze(
        ProjectInput.model_validate(RECORD["input"]), on_analysis_attempt=audit.append,
        on_rejected_attempt=rejected.append)
    assert_original_fields(result)
    assert RECORD == original
    assert len(calls) == len(audit) == 1 and rejected == []
    assert audit[0]["outcome"] == "accepted" and audit[0]["phase"] == "generation"
    assert audit[0]["validation_scope"] == "schema_safety_limits"
    assert audit[0]["analysis"] == RECORD["analysis"]
    assert not {"advisories", "issues", "repair_format", "repair_response"} & audit[0].keys()
    sent_settings, _prompt, payload, options = calls[0]
    assert payload["project"] == RECORD["input"]
    assert not {"validation_feedback", "previous_analysis", "repair_targets", "repair_format", "repair_required"} & payload.keys()
    assert sent_settings.llm_max_output_tokens == 16000
    assert sent_settings.llm_reasoning_effort == "low" and sent_settings.llm_thinking_mode == "enabled"
    assert 0 < options["timeout_seconds"] <= 60


@pytest.mark.asyncio
@pytest.mark.parametrize("simulated_seconds", [29.9, 57.69])
async def test_saved_v4_latency_is_preserved_and_not_relabelled_as_thirty_seconds(monkeypatch, simulated_seconds):
    clock, calls, audit = fake_clock(monkeypatch), [], []

    async def complete(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.now += simulated_seconds
        return deepcopy(RECORD["analysis"])

    monkeypatch.setattr(module, "complete_json", complete)
    result = await module.ProjectAnalyzer(configured()).analyze(
        ProjectInput.model_validate(RECORD["input"]), on_analysis_attempt=audit.append)
    assert_original_fields(result)
    assert len(calls) == len(audit) == 1
    assert audit[0]["outcome"] == "accepted"
    assert audit[0]["model_elapsed_seconds"] == pytest.approx(simulated_seconds)
    assert audit[0]["elapsed_seconds"] == pytest.approx(simulated_seconds)
    if simulated_seconds > 30:
        assert audit[0]["elapsed_seconds"] > 30


@pytest.mark.asyncio
async def test_saved_v4_after_total_deadline_is_retained_but_not_delivered(monkeypatch):
    clock, calls, audit = fake_clock(monkeypatch), [], []

    async def complete(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.now += 61
        return deepcopy(RECORD["analysis"])

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(module.AnalysisError) as error:
        await module.ProjectAnalyzer(configured()).analyze(
            ProjectInput.model_validate(RECORD["input"]), on_analysis_attempt=audit.append)
    assert error.value.code == "timeout" and len(calls) == 1
    assert calls[0] <= 60
    assert audit[0]["outcome"] == "rejected" and audit[0]["category"] == "timeout"
    assert audit[0]["analysis"] == RECORD["analysis"]


@pytest.mark.asyncio
async def test_v4_replay_still_omits_sensitive_output_without_retry(monkeypatch):
    settings = configured()
    candidate = deepcopy(RECORD["analysis"])
    candidate["scope"] += settings.llm_api_key
    calls, audit = [], []

    async def complete(*args, **kwargs):
        calls.append(True)
        return deepcopy(candidate)

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(module.AnalysisError) as error:
        await module.ProjectAnalyzer(settings).analyze(
            ProjectInput.model_validate(RECORD["input"]), on_analysis_attempt=audit.append)
    assert error.value.code == "schema" and len(calls) == 1
    assert audit[0]["analysis"] is None
    assert audit[0]["omitted_reason"] == "sensitive_model_output"
    assert settings.llm_api_key not in json.dumps(audit) + json.dumps(error.value.diagnostics)
