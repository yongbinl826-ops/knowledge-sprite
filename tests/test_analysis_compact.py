"""Offline compact-flow contracts; synthetic responses do not prove model quality."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.analysis_compact import COMPACT_SYSTEM_PROMPT
from backend.app.config import Settings
from backend.app.llm import complete_json
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from backend.app.project_models import ProjectInput
from tests.test_project_analysis import flat_analysis_fixture, request, response


def configured(**changes):
    base = Settings(llm_provider="openai_compatible", llm_base_url="https://api.deepseek.com/v1",
                    llm_model="deepseek-flash", llm_api_key="offline-compact-token",
                    project_analysis_reasoning_effort="low", project_analysis_max_output_tokens=16000)
    return replace(base, **changes)


def fake_clock(monkeypatch):
    """Advance the analyzer's monotonic clock without a minute-long test sleep."""
    state = SimpleNamespace(now=100.0)
    replacements = {name: getattr(asyncio, name) for name in dir(asyncio)}
    replacements["get_running_loop"] = lambda: SimpleNamespace(time=lambda: state.now)
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(**replacements))
    return state


@pytest.fixture(autouse=True)
def forbid_semantic_review_or_repair(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Single-pass analysis must not judge names/content or repair the response")
    for name in ("_local_quality_issues", "_partition_quality_issues", "_name_repair_context",
                 "learning_quality_issues", "textbook_concept_issues", "professional_contract_issues",
                 "apply_name_repairs"):
        monkeypatch.setattr(module, name, forbidden, raising=False)


def test_prompt_is_flat_conditional_and_independent_of_the_dashboard():
    assert module.SYSTEM_PROMPT == module.GENERATION_PROMPT == COMPACT_SYSTEM_PROMPT
    assert module.ANALYSIS_PROMPT_VERSION.startswith("project-analysis-v9")
    assert module.ANALYSIS_MAX_MODEL_CALLS == module.ANALYSIS_MAX_ATTEMPTS == 1
    assert "30 knowledge points" in COMPACT_SYSTEM_PROMPT
    assert "no target count" in COMPACT_SYSTEM_PROMPT
    assert "conditional checks" in COMPACT_SYSTEM_PROMPT
    assert "non-programming projects" in COMPACT_SYSTEM_PROMPT
    assert "parameters, return values or side effects" in COMPACT_SYSTEM_PROMPT
    assert "receiving, parsing and readiness" in COMPACT_SYSTEM_PROMPT
    assert "Mentioning it only in technical_plan" in COMPACT_SYSTEM_PROMPT
    assert "Generate the requested analysis once" in COMPACT_SYSTEM_PROMPT
    for dashboard_specific in ("520d138a", "就业数据", "ECharts", "GeoJSON", "ResizeObserver"):
        assert dashboard_specific not in COMPACT_SYSTEM_PROMPT
    schema = module.generation_schema()
    assert set(schema["properties"]) == {"scope", "technical_plan", "assumptions", "knowledge_points"}
    assert schema["properties"]["knowledge_points"]["maxItems"] == 30


@pytest.mark.asyncio
async def test_first_valid_flat_response_is_delivered_without_review_calls():
    calls, audit = [], []
    original = request()

    def respond(req):
        calls.append(json.loads(req.content))
        return response(flat_analysis_fixture())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(configured(), client).analyze(original, on_analysis_attempt=audit.append)
    assert len(calls) == len(audit) == 1
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["project"] == original.model_dump()
    assert set(payload["output_schema"]["properties"]) == {"scope", "technical_plan", "assumptions", "knowledge_points"}
    assert "implementation_inventory" not in payload and "coverage_review_required" not in payload
    assert [point.id for point in result.knowledge_points] == ["k1", "k2"]
    assert all(point.selection == "learn" for point in result.knowledge_points)
    assert audit[0]["outcome"] == "accepted" and audit[0]["phase"] == "generation"
    assert audit[0]["analysis"]["knowledge_points"] == flat_analysis_fixture()["knowledge_points"]
    assert audit[0]["validation_scope"] == "schema_safety_limits"
    assert "advisories" not in audit[0]
    assert calls[0]["max_tokens"] == 16000
    assert calls[0]["thinking"] == {"type": "enabled"}
    assert calls[0]["reasoning_effort"] == "low"
    assert not {"repair_required", "repair_targets", "validation_feedback", "previous_analysis"} & payload.keys()


@pytest.mark.parametrize("invalid_kind", ["schema", "invalid_json"])
@pytest.mark.asyncio
async def test_unreadable_output_fails_once_without_retry(invalid_kind):
    calls, audit, rejected = [], [], []
    bad = flat_analysis_fixture()
    if invalid_kind == "schema":
        bad.pop("technical_plan")
    else:
        bad = '{"scope":'

    def respond(req):
        calls.append(json.loads(req.content))
        assert len(calls) == 1
        return response(bad)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as caught:
            await ProjectAnalyzer(configured(), client).analyze(
                request(), on_analysis_attempt=audit.append, on_rejected_attempt=rejected.append)
    assert caught.value.code == invalid_kind
    assert "未自动重试" in caught.value.message
    assert len(calls) == len(audit) == len(rejected) == 1
    assert [entry["outcome"] for entry in audit] == ["rejected"]
    assert rejected[0]["category"] == invalid_kind


@pytest.mark.asyncio
async def test_incomplete_schema_never_starts_another_call_or_returns_the_draft():
    calls = []

    def respond(req):
        calls.append(req)
        return response({"scope": "结构不完整的离线响应"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as exc:
            await ProjectAnalyzer(configured(), client).analyze(request())
    assert exc.value.code == "schema" and len(calls) == 1


@pytest.mark.parametrize("count", [1, 2, 30])
@pytest.mark.asyncio
async def test_point_count_has_no_padding_or_preferred_count(count):
    # Isolate the count/transport boundary; these numbered fixtures are not
    # evidence of semantic completeness or good concept names.
    source = flat_analysis_fixture()
    source["knowledge_points"] = [{"name": f"离线容量概念 {i}", "description": "仅用于容量边界测试。"}
                                  for i in range(count)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response(source))) as client:
        result = await ProjectAnalyzer(configured(), client).analyze(request())
    assert len(result.knowledge_points) == count
    assert [p.name for p in result.knowledge_points] == [p["name"] for p in source["knowledge_points"]]


@pytest.mark.asyncio
async def test_thirty_one_points_is_rejected_without_truncation_or_repair():
    source = flat_analysis_fixture()
    source["knowledge_points"] = [{"name": f"离线容量概念 {i}", "description": "仅用于容量边界测试。"}
                                  for i in range(31)]
    calls, audit = [], []

    def respond(req):
        calls.append(req)
        return response(source)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as exc:
            await ProjectAnalyzer(configured(), client).analyze(request(), on_analysis_attempt=audit.append)
    assert exc.value.code == "too_large" and len(calls) == 1
    assert len(audit[0]["analysis"]["knowledge_points"]) == len(source["knowledge_points"]) == 31
    assert audit[0]["outcome"] == "rejected"


@pytest.mark.parametrize("project,proposal", [
    (request(), flat_analysis_fixture()),
    (ProjectInput(name="盐水配制", requirements="根据指定质量分数配制盐水"), {
        "scope": "根据给定总质量和质量分数配制盐水。", "technical_plan": "计算盐和水的质量，称量后混合。",
        "assumptions": ["总质量和质量分数由使用者提供。"], "knowledge_points": [
            {"name": "质量分数", "description": "质量分数是溶质质量占溶液总质量的比值。本项目由该比例计算盐的质量。"},
            {"name": "质量守恒", "description": "混合前后总质量保持相等。本项目用总质量减去盐的质量确定水的质量。"}]}),
    (ProjectInput(name="纸质海报", requirements="为课程活动设计层次清晰的纸质海报"), {
        "scope": "设计课程活动纸质海报的文字和版式。", "technical_plan": "根据主次信息调整标题和正文的大小与对比。",
        "assumptions": ["活动文字和纸张尺寸由使用者提供。"], "knowledge_points": [
            {"name": "视觉层级", "description": "视觉层级利用大小与位置区分信息主次。本项目突出活动标题并组织正文。"},
            {"name": "对比度", "description": "明暗差异影响文字与背景的可辨识程度。本项目选择能清晰呈现活动文字的配色。"}]}),
])
@pytest.mark.asyncio
async def test_programming_and_nonprogramming_flat_fixtures_share_the_flow(project, proposal):
    calls = []

    def respond(req):
        calls.append(req)
        return response(proposal)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(configured(), client).analyze(project)
    assert len(calls) == 1 and len(result.knowledge_points) == len(proposal["knowledge_points"])
    assert [p.name for p in result.knowledge_points] == [p["name"] for p in proposal["knowledge_points"]]


@pytest.mark.asyncio
async def test_legacy_large_settings_cannot_extend_the_total_deadline(monkeypatch):
    clock, calls = fake_clock(monkeypatch), []

    async def complete(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.now += 61
        return flat_analysis_fixture()

    monkeypatch.setattr(module, "complete_json", complete)
    settings = configured(project_analysis_timeout_seconds=180, project_analysis_total_timeout_seconds=600)
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(settings).analyze(request())
    assert exc.value.code == "timeout" and len(calls) == 1
    assert 0 < calls[0] <= 60


@pytest.mark.asyncio
async def test_single_generation_receives_only_the_shared_remaining_budget(monkeypatch):
    clock, calls = fake_clock(monkeypatch), []
    deadline = clock.now + 60
    clock.now += 41  # Represents queue/admission time already spent.

    async def complete(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.now += 1
        return flat_analysis_fixture()

    monkeypatch.setattr(module, "complete_json", complete)
    result = await ProjectAnalyzer(configured(project_analysis_timeout_seconds=180,
        project_analysis_total_timeout_seconds=600)).analyze(request(), deadline=deadline)
    assert result.knowledge_points and len(calls) == 1
    assert 0 < calls[0] <= 19


@pytest.mark.asyncio
async def test_late_invalid_schema_does_not_start_a_second_request(monkeypatch):
    clock, calls = fake_clock(monkeypatch), []

    async def complete(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.now += 56
        return {}

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(AnalysisError):
        await ProjectAnalyzer(configured()).analyze(request())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_external_deadline_includes_time_already_spent_before_analyzer(monkeypatch):
    clock, calls = fake_clock(monkeypatch), []

    async def complete(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.now += 11
        return flat_analysis_fixture()

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(configured()).analyze(request(), deadline=clock.now + 10)
    assert exc.value.code == "timeout" and len(calls) == 1 and calls[0] <= 10


@pytest.mark.asyncio
async def test_expired_deadline_never_calls_the_provider(monkeypatch):
    clock = fake_clock(monkeypatch)

    async def complete(*args, **kwargs):
        pytest.fail("expired request must not call a model")

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(configured()).analyze(request(), deadline=clock.now)
    assert exc.value.code == "timeout"


@pytest.mark.asyncio
async def test_wall_clock_timeout_cancels_an_unfinished_request(monkeypatch):
    state = SimpleNamespace(calls=0, cancelled=False)
    monkeypatch.setattr(module, "ANALYSIS_TIMEOUT_SECONDS", 0.01)

    async def complete(*args, **kwargs):
        state.calls += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state.cancelled = True
            raise

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(configured()).analyze(request())
    assert exc.value.code == "timeout" and state.calls == 1 and state.cancelled


@pytest.mark.asyncio
async def test_callback_time_cannot_result_in_a_late_success(monkeypatch):
    clock = fake_clock(monkeypatch)
    audit = []

    async def complete(*args, **kwargs):
        return flat_analysis_fixture()

    def record(entry):
        audit.append(entry)
        clock.now += 61

    monkeypatch.setattr(module, "complete_json", complete)
    with pytest.raises(AnalysisError) as exc:
        await ProjectAnalyzer(configured()).analyze(request(), on_analysis_attempt=record)
    assert exc.value.code == "timeout"
    assert len(audit) == 1
    assert audit[0]["validation_scope"] == "schema_safety_limits"


@pytest.mark.asyncio
async def test_effective_policy_and_usage_are_audited_without_mutating_search_settings():
    settings = configured(project_analysis_model="deepseek-v4-pro", project_analysis_reasoning_effort="low",
                          llm_max_output_tokens=2048, project_analysis_max_output_tokens=6000)
    calls, audit = [], []

    def respond(req):
        calls.append(json.loads(req.content))
        body = flat_analysis_fixture() if len(calls) == 1 else {"ok": True}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(body)}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await ProjectAnalyzer(settings, client).analyze(request(), on_analysis_attempt=audit.append)
        assert await complete_json(settings, "Offline shared-search probe", {}, client) == {"ok": True}
    assert [call["model"] for call in calls] == ["deepseek-v4-pro", "deepseek-flash"]
    assert calls[0]["thinking"] == {"type": "enabled"} and calls[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in calls[1]
    assert settings.llm_model == "deepseek-flash" and settings.llm_max_output_tokens == 2048
    assert len(audit) == 1
    row = audit[0]
    assert row["model"] == "deepseek-v4-pro" and row["reasoning_effort"] == "low"
    assert row["max_output_tokens"] == 6000 and row["prompt_version"].startswith("project-analysis-v9")
    assert row["elapsed_seconds"] >= row["model_elapsed_seconds"] >= 0
    assert row["completion"]["usage"]["total_tokens"] == 150
    assert row["completion"]["status"] == "completed" and row["outcome"] == "accepted"
