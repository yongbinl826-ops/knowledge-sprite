"""Project-only provider/thinking routing; all credentials and responses are fake."""
from dataclasses import replace
import json

import pytest

from backend.app import project_analysis as module
from backend.app.config import Settings, official_bailian_endpoint
from tests.test_project_analysis import flat_analysis_fixture, request


def configured(**changes):
    return replace(Settings(llm_provider="openai_compatible", llm_base_url="https://api.deepseek.com/v1",
                            llm_model="deepseek-flash", llm_api_key="offline-global-key",
                            project_analysis_reasoning_effort="low"), **changes)


def bailian(**changes):
    return configured(project_analysis_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                      project_analysis_api_key="offline-project-key", project_analysis_model="qwen3.8-max",
                      project_analysis_thinking_mode="disabled", **changes)


def test_disabled_project_mode_is_independent_of_global_search_options():
    original = configured(project_analysis_thinking_mode="disabled", llm_thinking_mode="enabled",
                          llm_reasoning_effort="high", llm_max_output_tokens=2048)
    original.validate()
    effective = module.project_analysis_settings(original)
    assert effective is not original
    assert (effective.llm_thinking_mode, effective.llm_reasoning_effort, effective.llm_max_output_tokens) == (
        "disabled", "provider_default", 16000)
    assert (original.llm_thinking_mode, original.llm_reasoning_effort, original.llm_max_output_tokens) == (
        "enabled", "high", 2048)
    assert effective.llm_model == original.llm_model == "deepseek-flash"


def test_bailian_override_preserves_shared_provider_and_uses_its_own_credentials():
    original = bailian()
    original.validate()
    effective = module.project_analysis_settings(original)
    assert effective.llm_provider == "openai_compatible"
    assert effective.llm_base_url == original.project_analysis_base_url
    assert effective.llm_model == "qwen3.8-max"
    assert effective.llm_api_key == "offline-project-key"
    assert effective.uses_official_bailian_qwen_model()
    assert not effective.uses_official_deepseek_model()
    assert original.llm_base_url == "https://api.deepseek.com/v1"
    assert original.llm_api_key == "offline-global-key"
    assert original.llm_model == "deepseek-flash"
    assert original.project_analysis_api_key not in repr(original)


def test_project_only_provider_can_be_available_without_a_configured_search_model():
    original = bailian(llm_provider="none", llm_api_key="", llm_model="")
    original.validate()
    assert module.ProjectAnalyzer(original).available
    assert original.llm_provider == "none" and original.llm_api_key == original.llm_model == ""


@pytest.mark.parametrize("changes", [
    {"project_analysis_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    {"project_analysis_api_key": "offline-project-key"},
    {"project_analysis_base_url": None},
    {"project_analysis_api_key": []},
])
def test_unpaired_or_malformed_endpoint_credentials_fail_before_any_transport(changes):
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_BASE_URL"):
        module.project_analysis_settings(configured(**changes))


@pytest.mark.parametrize("key", [" ", "offline\nkey", "offline key", "offline\x00key"])
def test_project_credential_cannot_contain_whitespace_or_control_characters(key):
    settings = replace(bailian(), project_analysis_api_key=key)
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_API_KEY"):
        settings.validate()


@pytest.mark.parametrize("model", ["qwen3.8-max", "qwen3.8-max-0902", "qwen3.8-max-2026-09-02", "qwen3.8-flash"])
def test_explicit_official_qwen_models_are_supported(model):
    original = replace(bailian(), project_analysis_model=model)
    original.validate()
    assert module.project_analysis_settings(original).llm_model == model


@pytest.mark.parametrize("endpoint", [
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/",
    "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
    "https://workspace-123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "https://workspace-123.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "https://workspace-123.us-east-1.maas.aliyuncs.com/compatible-mode/v1",
    "https://workspace-123.cn-hongkong.maas.aliyuncs.com/compatible-mode/v1",
    "https://workspace-123.ap-northeast-1.maas.aliyuncs.com:443/compatible-mode/v1",
])
def test_documented_bailian_hosts_are_exactly_bound(endpoint):
    assert official_bailian_endpoint(endpoint)
    replace(bailian(), project_analysis_base_url=endpoint).validate()


@pytest.mark.parametrize("endpoint", [
    "https://dashscope.aliyuncs.com.evil.example/compatible-mode/v1",
    "https://dashscope.aliyuncs.com/unknown", "https://gateway.example/compatible-mode/v1",
    "http://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope.aliyuncs.com:8443/compatible-mode/v1",
    "https://key@dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1?key=hidden",
    "https://workspace.unknown.maas.aliyuncs.com/compatible-mode/v1",
])
def test_unverified_destinations_never_receive_project_credentials(endpoint):
    assert not official_bailian_endpoint(endpoint)
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_MODEL"):
        replace(bailian(), project_analysis_base_url=endpoint).validate()


@pytest.mark.parametrize("mode", ["", "auto", "enabled", "none", None, True, []])
def test_invalid_project_thinking_switch_is_rejected(mode):
    with pytest.raises(ValueError, match="PROJECT_ANALYSIS_THINKING_MODE"):
        configured(project_analysis_thinking_mode=mode).validate()


def test_environment_reads_project_overrides_without_changing_shared_fields(monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config, "load_dotenv", lambda *_a, **_k: None)
    values = {
        "LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": "https://api.deepseek.com/v1",
        "LLM_MODEL": "deepseek-flash", "LLM_API_KEY": "offline-global-key",
        "LLM_THINKING_MODE": "auto", "LLM_REASONING_EFFORT": "auto",
        "PROJECT_ANALYSIS_THINKING_MODE": " DISABLED ", "PROJECT_ANALYSIS_REASONING_EFFORT": "low",
        "PROJECT_ANALYSIS_BASE_URL": " https://dashscope.aliyuncs.com/compatible-mode/v1/ ",
        "PROJECT_ANALYSIS_API_KEY": "offline-project-key", "PROJECT_ANALYSIS_MODEL": "qwen3.8-max",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    loaded = Settings.from_env()
    loaded.validate()
    assert loaded.project_analysis_thinking_mode == "disabled"
    assert module.project_analysis_settings(loaded).llm_api_key == "offline-project-key"
    assert loaded.llm_api_key == "offline-global-key" and loaded.llm_model == "deepseek-flash"


@pytest.mark.asyncio
@pytest.mark.parametrize("leaked_key", ["offline-global-key", "offline-project-key"])
async def test_each_configured_provider_key_is_omitted_from_analysis_audit(monkeypatch, leaked_key):
    original = bailian()
    response = flat_analysis_fixture()
    response["scope"] += leaked_key
    calls, audit = [], []

    async def complete(effective, *_args, **_kwargs):
        calls.append(effective)
        return response

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(module.AnalysisError):
        await module.ProjectAnalyzer(original).analyze(request(), on_analysis_attempt=audit.append)
    assert len(calls) == len(audit) == 1
    assert calls[0].llm_api_key == "offline-project-key"
    assert audit[0]["analysis"] is None and audit[0]["omitted_reason"] == "sensitive_model_output"
    assert leaked_key not in json.dumps(audit)
