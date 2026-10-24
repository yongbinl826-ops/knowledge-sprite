"""Offline project model override and provenance, independent of search models."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.llm import complete_json
from backend.app.project_analysis import ProjectAnalyzer, concept_normalization_settings, project_analysis_settings
from tests.test_project_analysis import flat_analysis_fixture, request, response
from tests.test_projects import setup


def configured(**changes):
    return replace(Settings(llm_provider="openai_compatible", llm_base_url="https://api.deepseek.com/v1",
                            llm_model="deepseek-flash", llm_api_key="offline-test-token"), **changes)


def test_empty_model_inherits_without_modifying_configured_model_or_options():
    original = configured(llm_thinking_mode="disabled", llm_max_output_tokens=2048)
    original.validate()
    assert original.project_analysis_model == ""
    assert project_analysis_settings(original) is original
    assert concept_normalization_settings(original).llm_model == "deepseek-flash"


@pytest.mark.parametrize("mode,effort", [("disabled", "auto"), ("enabled", "high"), ("provider_default", "provider_default")])
def test_model_only_override_keeps_explicit_inherited_thinking_and_budget(mode, effort):
    original = configured(project_analysis_model="deepseek-v4-pro", llm_thinking_mode=mode,
                          llm_reasoning_effort=effort, llm_max_output_tokens=2048)
    original.validate()
    effective = project_analysis_settings(original)
    assert effective.llm_model == "deepseek-v4-pro"
    assert (effective.llm_thinking_mode, effective.llm_reasoning_effort, effective.llm_max_output_tokens) == (mode, effort, 2048)
    assert original.llm_model == "deepseek-flash"


@pytest.mark.parametrize("value", ["unknown-model", "deepseek-chat", "DEEPSEEK-V4-PRO", " deepseek-v4-pro ", None, True, []])
def test_unknown_or_malformed_model_override_is_rejected(value):
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_MODEL"):
        configured(project_analysis_model=value).validate()


@pytest.mark.parametrize("base", [
    "https://gateway.example/v1", "https://api.deepseek.com.evil.example/v1",
    "http://api.deepseek.com/v1", "https://api.deepseek.com:8443/v1", "https://api.deepseek.com/unknown",
])
def test_explicit_model_override_never_guesses_support_for_other_endpoints(base):
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_MODEL"):
        configured(project_analysis_model="deepseek-v4-pro", llm_base_url=base).validate()


def test_effective_project_model_is_validated_without_requiring_a_shared_search_model():
    original = configured(llm_model="", project_analysis_model="deepseek-v4-pro", project_analysis_reasoning_effort="low")
    original.validate()
    assert ProjectAnalyzer(original).available
    assert project_analysis_settings(original).llm_model == "deepseek-v4-pro"
    assert original.llm_model == ""


def test_environment_model_override_is_explicit_and_empty_is_inheritance(monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: None)
    for name in ("PROJECT_ANALYSIS_MODEL", "PROJECT_ANALYSIS_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env().project_analysis_model == ""
    monkeypatch.setenv("PROJECT_ANALYSIS_MODEL", " deepseek-v4-pro ")
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("LLM_THINKING_MODE", "auto")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "auto")
    loaded = Settings.from_env()
    assert loaded.project_analysis_model == "deepseek-v4-pro" and loaded.llm_model == "deepseek-flash"


@pytest.mark.asyncio
async def test_pro_requests_metadata_and_audit_agree_while_flash_search_and_history_stay_intact(tmp_path):
    settings, store, jobs, projects = setup(tmp_path, llm_provider="openai_compatible",
        llm_base_url="https://api.deepseek.com/v1", llm_model="deepseek-flash", llm_api_key="offline-test-token",
        project_analysis_reasoning_effort="low", project_analysis_max_output_tokens=16000,
        project_analysis_normalization_max_output_tokens=12000,
        project_analysis_timeout_seconds=120, project_analysis_total_timeout_seconds=180)
    calls = []
    def respond(req):
        calls.append(json.loads(req.content))
        # First version passes directly; the second uses its one schema repair.
        replies = [flat_analysis_fixture(), {}, flat_analysis_fixture(), {"ok": True}]
        return response(replies[len(calls) - 1])
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            projects.analyzer = ProjectAnalyzer(settings, client)
            pid = projects.create(request())["project_id"]
            projects.analyze(pid, 0)
            await asyncio.gather(*projects.analysis_tasks.values())
            historical = deepcopy(projects.view(pid, 1)["version"])
            historical_raw = store.connection.execute(
                "SELECT data FROM project_versions WHERE project_id=? AND version=1", (pid,)).fetchone()[0]
            assert historical["model"] == "deepseek-flash" and historical["status"] == "analyzed"
            effective_config = replace(settings, project_analysis_model="deepseek-v4-pro")
            effective_config.validate()
            projects.settings = effective_config
            projects.analyzer = ProjectAnalyzer(effective_config, client)
            assert projects.capabilities()["project_analysis"]["model"] == "deepseek-v4-pro"
            pending = projects.analyze(pid, 1)
            assert pending["version"]["model"] == "deepseek-v4-pro"
            await asyncio.gather(*projects.analysis_tasks.values())
            latest = projects.view(pid, 2)["version"]
            assert latest["model"] == "deepseek-v4-pro" and latest["status"] == "analyzed"
            assert len(latest["analysis_attempts"]) == 2 and len(latest["rejected_analysis_attempts"]) == 1
            assert all(row["model"] == "deepseek-v4-pro" for row in latest["analysis_attempts"] + latest["rejected_analysis_attempts"])
            assert [row["max_output_tokens"] for row in latest["analysis_attempts"]] == [16000, 12000]
            assert projects.view(pid, 1)["version"] == historical
            assert store.connection.execute(
                "SELECT data FROM project_versions WHERE project_id=? AND version=1", (pid,)).fetchone()[0] == historical_raw
            assert await complete_json(effective_config, "Shared search fixture", {}, client) == {"ok": True}
        assert [call["model"] for call in calls] == ["deepseek-flash", "deepseek-v4-pro", "deepseek-v4-pro", "deepseek-flash"]
        for call in calls[:3]:
            assert call["thinking"] == {"type": "enabled"} and call["reasoning_effort"] == "low"
        assert calls[3]["thinking"] == {"type": "disabled"} and "reasoning_effort" not in calls[3]
        assert effective_config.llm_model == settings.llm_model == jobs.settings.llm_model == "deepseek-flash"
        assert settings.project_analysis_model == "" and effective_config.project_analysis_model == "deepseek-v4-pro"
        assert [call["max_tokens"] for call in calls] == [16000, 16000, 12000, 6000]
    finally:
        await projects.stop()
        store.close()
