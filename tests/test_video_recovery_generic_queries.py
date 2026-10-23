"""Unknown concepts remain bounded discovery leads, never inferred source facts."""
from copy import deepcopy

import pytest

from backend.app.ai_video_fallback import normalize_empty_api_calls, video_search_phrase
from backend.app.models import SearchRequest
from backend.app.queries import video_recovery_search_phrases


@pytest.mark.parametrize("point,technology,hint", [
    ("借用检查", "Rust", "Rust borrow checker"),
    ("窗口帧", "SQL", "SQL window frames"),
    ("指针事件处理", "JavaScript", "JavaScript pointer event handling"),
    ("按钮消抖", "Arduino", "Arduino button debouncing"),
])
def test_unfamiliar_single_concept_can_use_model_english_without_new_dictionary(point, technology, hint):
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: technology})
    before = deepcopy(request.model_dump())
    assert video_recovery_search_phrases(point, request, [hint]) == [f"{technology} {point}", hint]
    assert video_recovery_search_phrases(point, request) == [f"{technology} {point}"]
    assert request.model_dump() == before


@pytest.mark.parametrize("hint", [
    "Python pointer event handling", "JavaScript introduction tutorial", "JavaScript programming basics",
    "JavaScript", "JavaScript pointer events version 2", "JavaScript site:example.org pointer",
    "JavaScript https://example.org/pointer", "JavaScript pointer\nevents", "JavaScript pointer | execute",
    "JavaScript pointer/touch events", "JavaScript $(secret)", "JavaScript -paid pointer events",
])
def test_unknown_concept_does_not_disable_technology_version_syntax_or_generic_checks(hint):
    request = SearchRequest(knowledge_points=["指针事件处理"], topic_technologies={"指针事件处理": "JavaScript"})
    assert video_recovery_search_phrases("指针事件处理", request, [hint]) == ["JavaScript 指针事件处理"]


def test_unknown_english_lead_keeps_explicit_api_and_version_and_remains_three_slots():
    point = "PointerEvent 指针事件处理"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "JavaScript"}, technical_version="ES2022")
    result = video_recovery_search_phrases(point, request, [
        "JavaScript PointerEvent pointer handling", "JavaScript PointerEvent pointer input", "JavaScript PointerEvent ignored"])
    assert len(result) == 3
    assert all("JavaScript" in phrase and "PointerEvent" in phrase and "ES2022" in phrase for phrase in result)
    assert not any("ignored" in phrase for phrase in result)
    assert video_recovery_search_phrases(point, request, ["JavaScript pointer event handling"]) == [result[0]]
    assert video_recovery_search_phrases(point, request, ["JavaScript PointerEvent ES2023 pointer events"]) == [result[0]]


def test_empty_api_model_query_reaches_both_normalizers_without_changing_its_identifier():
    point = "getContext() 上下文获取"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "HTML Canvas"})
    hint = video_search_phrase("HTML Canvas getContext() rendering context")
    assert hint == "HTML Canvas getContext rendering context"
    assert video_recovery_search_phrases(point, request, [hint]) == [
        "HTML Canvas getContext 上下文获取", hint]


@pytest.mark.parametrize("point,hint", [
    ("文件下载", "Streamlit upload files"),
    ("文件下载与权限核对", "Streamlit download button"),
    ("窗口创建", "Streamlit windows update"),
])
def test_known_or_compound_operation_cannot_use_atomic_translation_exception(point, hint):
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Streamlit"})
    assert hint not in video_recovery_search_phrases(point, request, [hint])


@pytest.mark.parametrize("raw,expected", [
    ("HTML Canvas getContext()", "HTML Canvas getContext"),
    ("JavaScript ctx.drawImage( ) 图像绘制", "JavaScript ctx.drawImage 图像绘制"),
    ("SQL COUNT()", "SQL COUNT"),
])
def test_only_empty_api_call_notation_is_normalized_in_query_copy(raw, expected):
    assert video_search_phrase(raw) == expected
    request = SearchRequest(knowledge_points=[raw])
    before = deepcopy(request.model_dump())
    assert video_recovery_search_phrases(raw, request)[0] == expected
    assert normalize_empty_api_calls(expected) == expected
    assert request.model_dump() == before


@pytest.mark.parametrize("raw", [
    "HTML getContext('2d')", "JavaScript f(argument)", "JavaScript f()()", "JavaScript f()( )",
    "JavaScript (f())", "JavaScript f(())", "JavaScript f();secret", "JavaScript f() site:example.org",
    "JavaScript f(\n)", "JavaScript f(\t)", "JavaScript f()suffix",
])
def test_arguments_nested_notation_and_controls_are_not_silently_rewritten(raw):
    assert video_search_phrase(raw) is None
    request = SearchRequest(knowledge_points=[raw])
    assert video_recovery_search_phrases(raw, request) == []


def test_confirmed_chinese_slash_preserves_all_operations_but_model_slash_is_rejected():
    point = "操作历史栈与撤销/重做游标"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "JavaScript"})
    assert video_recovery_search_phrases(point, request, ["JavaScript undo/redo", "JavaScript undo"]) == [
        "JavaScript 操作历史栈与撤销 and 重做游标"]
    assert request.knowledge_points == [point]
    assert video_search_phrase("JavaScript undo/redo") is None


@pytest.mark.parametrize("point", ["撤销/../../etc", "撤销/http://example.org", "指针/API调用"])
def test_only_directly_adjacent_chinese_slash_is_normalized(point):
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "JavaScript"})
    assert video_recovery_search_phrases(point, request) == []
