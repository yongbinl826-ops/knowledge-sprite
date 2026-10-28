"""Offline project-only reasoning policy, budget and failure contracts."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.llm import complete_json
from backend.app.project_analysis import (
    AnalysisError, ProjectAnalyzer, concept_normalization_settings, project_analysis_settings,
)
from tests.test_project_analysis import flat_analysis_fixture, request, response
from tests.test_projects import setup


def configured(**changes):
    return replace(Settings(llm_provider="openai_compatible", llm_base_url="https://api.deepseek.com/v1",
                            llm_model="deepseek-flash", llm_api_key="offline-test-token"), **changes)


@pytest.mark.parametrize("thinking,effort", [
    ("auto", "auto"), ("disabled", "auto"), ("enabled", "high"),
    ("enabled", "low"), ("provider_default", "provider_default"),
])
def test_inherit_keeps_explicit_operator_modes_and_independent_budgets(thinking, effort):
    original = configured(llm_thinking_mode=thinking, llm_reasoning_effort=effort,
                          llm_max_output_tokens=2048, project_analysis_normalization_max_output_tokens=4096)
    original.validate()
    assert project_analysis_settings(original) is original
    repair = concept_normalization_settings(original)
    assert (repair.llm_thinking_mode, repair.llm_reasoning_effort, repair.llm_max_output_tokens) == (thinking, effort, 4096)
    assert original.llm_max_output_tokens == 2048


@pytest.mark.parametrize("thinking,effort", [
    ("disabled", "auto"), ("provider_default", "auto"),
    ("enabled", "high"), ("enabled", "provider_default"),
])
def test_low_rejects_conflicting_explicit_operator_modes_without_silently_replacing_them(thinking, effort):
    original = configured(project_analysis_reasoning_effort="low", llm_thinking_mode=thinking, llm_reasoning_effort=effort)
    with pytest.raises(ValueError, match="conflicts with explicit global"):
        original.validate()
    with pytest.raises(ValueError, match="conflicts with explicit global"):
        project_analysis_settings(original)
    assert (original.llm_thinking_mode, original.llm_reasoning_effort) == (thinking, effort)


@pytest.mark.parametrize("base,model", [
    ("https://gateway.example/v1", "deepseek-flash"),
    ("https://api.deepseek.com/v1", "deepseek-chat"),
    ("https://api.deepseek.com/v1", "future-model"),
    ("https://api.deepseek.com.evil.example/v1", "deepseek-flash"),
    ("https://api.deepseek.com:8443/v1", "deepseek-flash"),
    ("http://api.deepseek.com/v1", "deepseek-flash"),
    ("https://api.deepseek.com/unrecognized", "deepseek-flash"),
])
def test_low_never_guesses_extensions_for_unsupported_provider_or_endpoint(base, model):
    original = configured(project_analysis_reasoning_effort="low", llm_base_url=base, llm_model=model)
    with pytest.raises(ValueError, match="documented official DeepSeek"):
        original.validate()


@pytest.mark.parametrize("base,model", [
    ("https://api.deepseek.com", "deepseek-flash"),
    ("https://API.DEEPSEEK.COM:443/v1/", "deepseek-v4-pro"),
])
def test_low_uses_only_its_configured_generation_budget_and_keeps_repair_budget(base, model):
    original = configured(project_analysis_reasoning_effort="low", llm_base_url=base, llm_model=model,
                          llm_max_output_tokens=2048, project_analysis_max_output_tokens=9000,
                          project_analysis_normalization_max_output_tokens=4096)
    original.validate()
    generation, repair = project_analysis_settings(original), concept_normalization_settings(original)
    assert [generation.llm_max_output_tokens, repair.llm_max_output_tokens] == [9000, 4096]
    assert generation.llm_thinking_mode == repair.llm_thinking_mode == "enabled"
    assert generation.llm_reasoning_effort == repair.llm_reasoning_effort == "low"
    assert (original.llm_thinking_mode, original.llm_reasoning_effort, original.llm_max_output_tokens) == ("auto", "auto", 2048)


@pytest.mark.parametrize("value", ["", "high", "auto", None, True, []])
def test_invalid_project_reasoning_mode_is_rejected(value):
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_REASONING_EFFORT"):
        configured(project_analysis_reasoning_effort=value).validate()


@pytest.mark.parametrize("value", [255, 16001, True, None, "12000", 12000.0])
def test_invalid_project_generation_budget_is_rejected(value):
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_MAX_OUTPUT_TOKENS"):
        configured(project_analysis_max_output_tokens=value).validate()


def test_environment_opt_in_is_explicit_and_preserves_exact_budget(monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    for name in ("PROJECT_ANALYSIS_REASONING_EFFORT", "PROJECT_ANALYSIS_MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings.from_env()
    assert defaults.project_analysis_reasoning_effort == "inherit"
    assert defaults.project_analysis_max_output_tokens == 16000
    monkeypatch.setenv("PROJECT_ANALYSIS_REASONING_EFFORT", " LOW ")
    monkeypatch.setenv("PROJECT_ANALYSIS_MAX_OUTPUT_TOKENS", "4096")
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("LLM_THINKING_MODE", "auto")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "auto")
    loaded = Settings.from_env()
    assert loaded.project_analysis_reasoning_effort == "low"
    assert project_analysis_settings(loaded).llm_max_output_tokens == 4096
    monkeypatch.setenv("PROJECT_ANALYSIS_MAX_OUTPUT_TOKENS", "typo")
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_MAX_OUTPUT_TOKENS"):
        Settings.from_env()


@pytest.mark.asyncio
async def test_analysis_alone_enables_low_and_telemetry_records_actual_settings():
    original = configured(project_analysis_reasoning_effort="low", llm_max_output_tokens=2048,
                          project_analysis_max_output_tokens=9000, project_analysis_normalization_max_output_tokens=4096)
    calls, audit = [], []
    def respond(req):
        calls.append(json.loads(req.content))
        replies = [flat_analysis_fixture(), {"ok": True}]
        return response(replies[len(calls) - 1])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(original, client).analyze(request(), on_analysis_attempt=audit.append)
        assert await complete_json(original, "Unchanged shared search fixture", {}, client) == {"ok": True}
    assert len(result.knowledge_points) == 2 and len(calls) == 2
    generation_payload = json.loads(calls[0]["messages"][1]["content"])
    assert "repair_required" not in generation_payload and "validation_feedback" not in generation_payload
    assert "implementation_inventory" not in generation_payload
    assert all("implementation_inventory" not in row for row in audit)
    assert [call["max_tokens"] for call in calls] == [9000, 2048]
    assert calls[0]["thinking"] == {"type": "enabled"} and calls[0]["reasoning_effort"] == "low"
    assert calls[1]["thinking"] == {"type": "disabled"} and "reasoning_effort" not in calls[1]
    assert [row["max_output_tokens"] for row in audit] == [9000]
    assert [row["thinking_mode"] for row in audit] == ["enabled"]
    assert [row["reasoning_effort"] for row in audit] == ["low"]
    assert audit[0]["validation_scope"] == "schema_safety_limits"
    assert all(row["elapsed_seconds"] >= 0 and row["model_elapsed_seconds"] >= 0 for row in audit)


@pytest.mark.asyncio
async def test_low_does_not_accept_or_repair_truncated_even_valid_json():
    calls, audit = [], []
    def respond(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {
            "content": json.dumps(flat_analysis_fixture())}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as exc:
            await ProjectAnalyzer(configured(project_analysis_reasoning_effort="low"), client).analyze(
                request(), on_analysis_attempt=audit.append)
    assert exc.value.code == "output_truncated" and len(calls) == 1
    assert calls[0]["max_tokens"] == 16000
    assert len(audit) == 1 and audit[0]["outcome"] == "rejected" and audit[0]["analysis"] is None


@pytest.mark.asyncio
async def test_low_schema_failure_stops_without_repair_regardless_of_remaining_budget(monkeypatch):
    calls = []
    async def complete(_settings, *_args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        if len(calls) == 1:
            await asyncio.sleep(0.6)
            return {}
        await asyncio.Event().wait()
    monkeypatch.setattr("backend.app.project_analysis.complete_json", complete)
    original = configured(project_analysis_reasoning_effort="low", project_analysis_timeout_seconds=1,
                          project_analysis_total_timeout_seconds=1)
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(original).analyze(request())
    assert exc.value.code == "schema" and len(calls) == 1
    assert calls[0] <= 1
    assert not any(item.get("type") == "repair_skipped" for item in exc.value.diagnostics)


@pytest.mark.asyncio
async def test_legacy_pro_wait_budget_is_clamped_to_sixty_seconds_for_one_generation(monkeypatch):
    from types import SimpleNamespace
    from backend.app import project_analysis as module
    # Advance only the analyzer's elapsed-time source, without a real model call.
    clock = SimpleNamespace(elapsed=0.0)
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(
        get_running_loop=lambda: SimpleNamespace(time=lambda: clock.elapsed),
        timeout=asyncio.timeout, sleep=asyncio.sleep, CancelledError=asyncio.CancelledError))
    calls = []
    proposal = flat_analysis_fixture()

    async def complete(call_settings, _prompt, payload, *_args, **kwargs):
        calls.append((kwargs["timeout_seconds"], call_settings.llm_max_output_tokens,
                      call_settings.llm_model, call_settings.llm_reasoning_effort))
        assert len(calls) == 1
        assert "repair_required" not in payload
        assert "implementation_inventory" not in payload
        clock.elapsed = 58.0
        return proposal

    monkeypatch.setattr(module, "complete_json", complete)
    original = configured(project_analysis_model="deepseek-v4-pro", project_analysis_reasoning_effort="low",
                          project_analysis_timeout_seconds=180, project_analysis_total_timeout_seconds=300,
                          project_analysis_max_output_tokens=16000, project_analysis_normalization_max_output_tokens=12000)
    original.validate()
    result = await ProjectAnalyzer(original).analyze(request())
    assert result.knowledge_points
    assert calls == [(60, 16000, "deepseek-v4-pro", "low")]
    assert original.llm_model == "deepseek-flash"


@pytest.mark.asyncio
async def test_capabilities_publish_project_policy_and_effective_budgets(tmp_path):
    _, store, _, projects = setup(tmp_path, llm_provider="openai_compatible", llm_base_url="https://api.deepseek.com/v1",
                                   llm_model="deepseek-flash", project_analysis_reasoning_effort="low",
                                   project_analysis_max_output_tokens=9000, project_analysis_normalization_max_output_tokens=4096)
    try:
        capability = projects.capabilities()["project_analysis"]
        assert capability["reasoning_policy"] == "low"
        assert capability["generation_max_output_tokens"] == 9000
        assert capability["repair_max_output_tokens"] == 4096
        assert capability["generation_thinking_mode"] == capability["repair_thinking_mode"] == "enabled"
        assert capability["generation_reasoning_effort"] == capability["repair_reasoning_effort"] == "low"
        assert capability["max_model_calls"] == 1 and capability["repair_max_calls"] == 0
        assert capability["generation_stages"] == ["compact_generation"]
        assert capability["local_checks_enabled"] is False and capability["schema_safety_checks_enabled"] is True
        assert capability["conditional_repair_enabled"] is False
        assert capability["total_timeout_seconds"] <= 60
    finally:
        await projects.stop()
        store.close()
