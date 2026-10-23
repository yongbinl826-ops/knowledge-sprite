"""Unverified bilingual discovery keeps the original target and source gates."""
from copy import deepcopy

import pytest

from backend.app.models import SearchRequest
from backend.app.queries import video_recovery_search_phrases


@pytest.mark.parametrize("point,technology,hint", [
    ("逻辑尺寸、设备像素比与坐标换算", "HTML5 Canvas", "HTML5 Canvas pixel ratio coordinate conversion"),
    ("Pointer 事件统一鼠标与触摸输入", "JavaScript", "JavaScript Pointer mouse touch events"),
    ("操作历史栈与撤销/重做游标", "JavaScript", "JavaScript undo redo history cursor"),
    ("借用检查与生命周期推断", "Rust", "Rust borrow checker lifetime inference"),
    ("窗口帧与同序记录", "SQL", "SQL window frames peer rows"),
])
def test_unfamiliar_compound_can_add_english_without_dropping_original(point, technology, hint):
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: technology})
    before = deepcopy(request.model_dump())
    phrases = video_recovery_search_phrases(point, request, [hint])
    assert len(phrases) == 2
    assert phrases[1] == hint
    assert phrases[0].startswith(technology + " ")
    assert request.model_dump() == before


@pytest.mark.parametrize("hint", [
    "Python Pointer mouse touch events", "JavaScript mouse touch events", "JavaScript Pointer tutorial",
    "JavaScript Pointer mouse touch ES2023", "JavaScript Pointer site:example.org",
    "JavaScript Pointer mouse/touch", "JavaScript Pointer mouse\ntouch", "JavaScript Pointer $(secret)",
])
def test_compound_hints_keep_syntax_technology_api_and_version_guards(hint):
    point = "Pointer 鼠标与触摸输入"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "JavaScript"}, technical_version="ES2022")
    phrases = video_recovery_search_phrases(point, request, [hint])
    assert phrases == ["JavaScript Pointer 鼠标与触摸输入 ES2022"]


def test_no_model_translation_is_assumed_to_cover_an_unknown_operation():
    point = "借用检查与生命周期推断"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Rust"})
    phrases = video_recovery_search_phrases(point, request, ["Rust borrow checker"])
    assert phrases == ["Rust " + point, "Rust borrow checker"]
    assert request.knowledge_points == [point]  # A search lead never changes matching scope.


def test_known_compound_actions_cannot_be_replaced_by_partial_or_wrong_hints():
    point = "表单输入与文件下载"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Streamlit"})
    assert video_recovery_search_phrases(point, request, ["Streamlit form input", "Streamlit upload files"]) == [
        "Streamlit 表单输入与文件下载", "Streamlit form input and file download", "Streamlit form input and download button"]


def test_bounded_supplements_do_not_truncate_or_consume_more_than_three_slots():
    point = "借用检查与生命周期推断"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Rust"})
    hints = ["Rust borrow checker lifetime inference", "Rust borrowing lifetime elision", "Rust ignored words"]
    phrases = video_recovery_search_phrases(point, request, hints)
    assert len(phrases) == 3 and not any("ignored" in phrase for phrase in phrases)
    assert phrases == ["Rust " + point, *hints[:2]]
    long_point = "范围限定" * 32 + point
    long_request = SearchRequest(knowledge_points=[long_point], topic_technologies={long_point: "Rust"})
    long_phrases = video_recovery_search_phrases(long_point, long_request, hints)
    assert long_phrases[0] == "Rust " + long_point
    assert long_phrases == ["Rust " + long_point, *hints[:2]]
    assert len(long_phrases[0]) <= 320 and all(len(value) <= 80 for value in long_phrases[1:])
