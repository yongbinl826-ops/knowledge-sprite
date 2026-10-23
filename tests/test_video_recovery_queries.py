"""Deterministic bounded video recall survives an unavailable model."""
from copy import deepcopy

import pytest

from backend.app.models import SearchRequest
from backend.app.queries import gap_query_candidates, video_recovery_search_phrases


@pytest.mark.parametrize("point,technology,english", [
    ("表单输入", "Streamlit", "form input"),
    ("文件下载", "Streamlit", "file download"),
    ("文本分段", "Python", "text splitting"),
    ("表单录入", "Django", "form input"),
    ("下载文件", "Rust", "file download"),
    ("文本切分", "JavaScript", "text splitting"),
    ("文本分割", "C++", "text splitting"),
])
def test_model_timeout_still_has_original_then_compact_english(point, technology, english):
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: technology})
    before = deepcopy(request.model_dump())
    expected = [technology + " " + point, technology + " " + english]
    if point == "文件下载" and technology == "Streamlit":
        expected.append("Streamlit download button")
    assert video_recovery_search_phrases(point, request) == expected
    assert request.model_dump() == before


def test_english_slot_precedes_model_variants_and_maximum_is_three():
    request = SearchRequest(knowledge_points=["文件下载"], topic_technologies={"文件下载": "Streamlit"})
    hints = ["Streamlit download button", "Streamlit download files"]
    assert video_recovery_search_phrases("文件下载", request, hints) == [
        "Streamlit 文件下载", "Streamlit file download", "Streamlit download button"]
    assert hints == ["Streamlit download button", "Streamlit download files"]


def test_cosmetic_original_repetition_cannot_displace_complementary_button_query():
    request = SearchRequest(knowledge_points=["文件下载"], topic_technologies={"文件下载": "Streamlit"})
    assert video_recovery_search_phrases("文件下载", request, ["Streamlit 文件下载教程", "Streamlit file download tutorial"]) == [
        "Streamlit 文件下载", "Streamlit file download", "Streamlit download button"]


@pytest.mark.parametrize("technology", ["Streamlit", "Flet", "Gradio", "Dash", "HTML", "React", "Vue"])
def test_declared_ui_download_has_button_alternative_when_model_is_unavailable(technology):
    point = "文件下载"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: technology}, technical_version="version 2")
    assert video_recovery_search_phrases(point, request) == [
        technology + " 文件下载 version 2", technology + " file download version 2",
        technology + " download button version 2"]


@pytest.mark.parametrize("technology", ["Python", "Rust", "Java", "requests", "FastAPI"])
def test_backend_or_cli_download_does_not_invent_a_button(technology):
    point = "文件下载"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: technology})
    assert video_recovery_search_phrases(point, request) == [
        technology + " 文件下载", technology + " file download"]


@pytest.mark.parametrize("hints", [None, [], [42], "Streamlit download button", [""]])
def test_missing_or_invalid_model_hints_do_not_remove_deterministic_queries(hints):
    request = SearchRequest(knowledge_points=["文件下载"], topic_technologies={"文件下载": "Streamlit"})
    assert video_recovery_search_phrases("文件下载", request, hints) == [
        "Streamlit 文件下载", "Streamlit file download", "Streamlit download button"]


@pytest.mark.parametrize("hint", [
    "Django download files", "Streamlit introduction tutorial", "Python text splitting",
    "Streamlit upload files", "Streamlit files", "Streamlit download button version 0.1",
    "Streamlit download button binary files export generated documents tutorial",
    "Streamlit https://example.org/download", "Streamlit site:bilibili.com 文件下载",
    "Streamlit 文件下载\nsecret", "Streamlit 文件下载 $(secret)", "Streamlit 文件下载 -paid",
])
def test_model_cannot_change_technology_core_version_or_add_unsafe_or_long_query(hint):
    request = SearchRequest(knowledge_points=["文件下载"], topic_technologies={"文件下载": "Streamlit"})
    assert video_recovery_search_phrases("文件下载", request, [hint]) == [
        "Streamlit 文件下载", "Streamlit file download", "Streamlit download button"]


def test_explicit_versions_and_api_literals_survive_every_phrase():
    point = "Python 3.13 str.split 文本分段"
    request = SearchRequest(knowledge_points=[point], technical_version="Python 3.13")
    result = video_recovery_search_phrases(point, request, [
        "Python 3.13 str.split text splitting basics", "Python 3.12 str.split text splitting"])
    assert len(result) == 3
    assert result[0] == point
    assert result[1] == "Python 3.13 str.split text splitting"
    assert all("Python 3.13" in phrase and "str.split" in phrase for phrase in result)
    assert not any("3.12" in phrase for phrase in result)


def test_request_version_is_added_without_inventing_one_when_absent():
    request = SearchRequest(knowledge_points=["文本分段"], topic_technologies={"文本分段": "Python"},
                            technical_version="Python 3.13")
    result = video_recovery_search_phrases("文本分段", request, ["Python split text"])
    assert len(result) == 3 and all("Python 3.13" in phrase for phrase in result)
    empty_version = request.model_copy(update={"technical_version": ""})
    assert all("3.13" not in phrase for phrase in video_recovery_search_phrases("文本分段", empty_version))


def test_compound_core_is_kept_instead_of_hiding_an_untranslated_operation():
    point = "文件下载与权限核对"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Streamlit"})
    result = video_recovery_search_phrases(point, request, ["Streamlit download button"])
    assert result == ["Streamlit 文件下载与权限核对", "Streamlit file download and 权限核对",
                      "Streamlit download button and 权限核对"]
    assert all("权限核对" in phrase for phrase in result)


def test_legacy_wildcard_translation_cannot_swallow_an_untranslated_core_operation():
    point = "Python CSV转JSON读取与文本分段"
    request = SearchRequest(knowledge_points=[point])
    result = video_recovery_search_phrases(point, request, ["Python JSON read CSV and text splitting"])
    assert result == [point, "Python CSV转JSON读取 and text splitting"]
    assert all("CSV转JSON读取" in phrase for phrase in result)


def test_two_known_operations_remain_together_in_bilingual_and_model_query():
    point = "表单输入与文件下载"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Streamlit"})
    assert video_recovery_search_phrases(point, request, [
        "Streamlit form input", "Streamlit form input and download button"]) == [
            "Streamlit 表单输入与文件下载", "Streamlit form input and file download",
            "Streamlit form input and download button"]


def test_declared_context_preserved_and_project_description_does_not_add_operations():
    request = SearchRequest(knowledge_points=["文本分段"], project_context="使用 Python。还要部署和用户管理。")
    assert video_recovery_search_phrases("文本分段", request) == ["Python 文本分段", "Python text splitting"]
    request = request.model_copy(update={"project_context": "不使用 Python。"})
    assert video_recovery_search_phrases("文本分段", request) == ["文本分段", "text splitting"]


def test_unknown_operations_do_not_receive_an_invented_translation_or_broad_hint():
    point = "QuillFlow 压缩边界追踪"
    request = SearchRequest(knowledge_points=[point])
    assert video_recovery_search_phrases(point, request, ["QuillFlow tutorial"]) == [point]
    assert video_recovery_search_phrases(point, request, [point + "教程"]) == [point]


def test_hints_are_deduplicated_and_only_first_two_are_inspected():
    request = SearchRequest(knowledge_points=["文本分段"], topic_technologies={"文本分段": "Python"})
    assert video_recovery_search_phrases("文本分段", request, [
        "PYTHON text splitting", "Python 文本分段", "Python split text"]) == [
            "Python 文本分段", "Python text splitting"]


def test_long_labels_and_constraints_are_never_silently_truncated():
    point = "精确限定" * 25 + "文本分段"
    request = SearchRequest(knowledge_points=[point], topic_technologies={point: "Python"}, technical_version="version 3")
    result = video_recovery_search_phrases(point, request)
    assert result == ["Python " + point + " version 3"]
    assert len(result[0]) <= 320


@pytest.mark.parametrize("point,version", [
    ("site:example.org 文本分段", ""), ("文本分段", "3.13;secret"),
    ("https://example.org 文本分段", ""), ("文本分段", "http://example.org"),
])
def test_original_input_cannot_supply_query_operators_or_urls(point, version):
    request = SearchRequest(knowledge_points=[point], technical_version=version)
    assert video_recovery_search_phrases(point, request) == []


def test_foreign_point_is_not_translated_into_current_request():
    request = SearchRequest(knowledge_points=["文件下载"])
    assert video_recovery_search_phrases("文本分段", request) == []


@pytest.mark.parametrize("point,english", [("表单输入", "form input"), ("文件下载", "file download"), ("文本分段", "text splitting")])
def test_new_generic_vocabulary_is_shared_with_existing_gap_query_mechanism(point, english):
    topic = "Python " + point
    request = SearchRequest(knowledge_points=[topic])
    rows = gap_query_candidates("unchanged-id", topic, request, [point])
    assert any(english in row.query for row in rows)
    assert all(row.knowledge_point_id == "unchanged-id" and "Python" in row.query for row in rows)
