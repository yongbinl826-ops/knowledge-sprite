"""Offline regressions for failures found by the unseen-project acceptance set."""
import httpx
import pytest

from backend.app.project_analysis import AnalysisError, ProjectAnalyzer, learning_quality_issues, _raw_edge_as_debounce
from backend.app.project_models import AnalysisDocument, ProjectInput
from tests import test_project_analysis as offline


@pytest.mark.parametrize("text", [
    "假设按钮去抖既可用 millis 时间窗也可用状态比较，二选一即可。",
    "按钮去抖用时间戳或状态比较，记录按下瞬间而非持续电平。",
    "用时间窗或状态比较过滤抖动，只在下降沿记录一次按下。",
    "去抖只需比较当前和前次电平。",
    "时间窗或边沿检测二选一即可去抖。",
    "状态变化立即触发便能消除抖动。",
])
def test_raw_edges_do_not_replace_mechanical_button_debounce(text):
    assert _raw_edge_as_debounce(text)


@pytest.mark.parametrize("text", [
    "仅比较当前和前次电平不能独立去抖。",
    "边沿检测不足以去抖。",
    "比较原始电平变化时重置时间戳，稳定20ms后提交新稳定状态，再检测按下沿。",
    "状态机要求输入持续稳定一个时间窗后转移，再做边沿检测实现去抖。",
    "连续多次稳定采样后确认，再作边沿检测完成去抖。",
    "已有明确硬件去抖后检测边沿。",
    "使用Bounce2去抖库后再做边沿检测。",
])
def test_real_debounce_strategies_and_negative_explanations_remain_valid(text):
    assert not _raw_edge_as_debounce(text)


def test_observed_wrong_assumption_is_checked_even_if_unit_mentions_a_time_window():
    body = offline.analysis_fixture()
    body["assumptions"] = ["按钮去抖用时间戳或状态比较，二选一即可。"]
    body["knowledge_points"][0]["concepts"] = ["去抖时间窗", "下降沿检测"]
    project = ProjectInput(name="Arduino 按钮小游戏", requirements="按钮需要去抖，避免机械按键重复触发。")
    codes = {issue["code"] for issue in learning_quality_issues(project, AnalysisDocument.model_validate(body))}
    assert "raw_edge_is_not_debounce" in codes


def test_generated_tool_annotation_is_feedback_but_saved_analysis_still_reads():
    body = offline.analysis_fixture()
    body["knowledge_points"][0]["technology"] = "Arduino C++ (millis, random)"
    document = AnalysisDocument.model_validate(body)
    assert document.knowledge_points[0].technology == "Arduino C++ (millis, random)"
    assert "explanatory_technology" in {i["code"] for i in learning_quality_issues(offline.request(), document)}


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_error", [httpx.ConnectTimeout, httpx.ConnectError])
async def test_only_presend_connection_failure_can_use_second_analysis_attempt(connection_error):
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise connection_error("offline connection failure", request=request)
        return offline.response(offline.flat_analysis_fixture())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ProjectAnalyzer(offline.settings(), client).analyze(offline.request())
    assert result.knowledge_points and len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout])
async def test_uncertain_timeouts_never_retry_and_connection_retries_are_bounded(error):
    calls = []
    def respond(request):
        calls.append(request)
        raise error("offline transport failure", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError) as raised:
            await ProjectAnalyzer(offline.settings(), client).analyze(offline.request())
    assert len(calls) == (2 if error is httpx.ConnectTimeout else 1)
    assert raised.value.code == ("unavailable" if error is httpx.ConnectTimeout else "timeout")


@pytest.mark.asyncio
async def test_connection_retry_does_not_create_a_third_schema_repair_attempt():
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("offline connection failure", request=request)
        return offline.response("{incomplete")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AnalysisError):
            await ProjectAnalyzer(offline.settings(), client).analyze(offline.request())
    assert len(calls) == 2
