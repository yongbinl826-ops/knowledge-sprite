"""Rule-only recall policy; no requests, courses or teaching claims."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from backend.app import queries as qm
from backend.app.models import SearchRequest
from backend.app.mooc_queries import mooc_query_plan
from backend.app.platform_search import platform_query


CAPTURED = json.loads((Path(__file__).parent / "fixtures/complementary_queries/requests.json").read_text(encoding="utf-8"))


def test_actual_js_request_keeps_exact_whole_name_then_two_different_components():
    request = SearchRequest.model_validate(CAPTURED[0]["request"])
    original = deepcopy(request.model_dump())
    text = request.knowledge_points[0]
    point = {"knowledge_point_id": "same-original-point", "text": text}
    plan = [platform_query(point, "bilibili", request, round_index=i) for i in range(3)]
    assert plan[0].query == f"site:bilibili.com/video JavaScript {text} 视频教程"
    assert plan[1].query == "site:bilibili.com/video JavaScript localStorage 读写 视频教程 示例"
    assert plan[2].query == "site:bilibili.com/video JavaScript JSON 序列化 教学 实战"
    assert all(query.domain_filters == ["bilibili.com"] and query.knowledge_point_id == point["knowledge_point_id"] for query in plan)
    assert "localStorage" not in plan[2].query and "HTML" not in plan[1].query and "CSS" not in plan[2].query
    assert request.model_dump() == original


def test_actual_arduino_request_adds_only_declared_board_to_original_whole_name():
    request = SearchRequest.model_validate(CAPTURED[1]["request"])
    text = request.knowledge_points[0]
    before = deepcopy(request.model_dump())
    query = platform_query({"knowledge_point_id": "original", "text": text}, "bilibili", request)
    assert query.query == f"site:bilibili.com/video Arduino Uno {text} 视频教程"
    assert all(token not in query.query for token in ("ESP32", "A0", "PWM", "100", "delay"))
    assert qm.complementary_search_phrase(text, request, 1) is None
    assert request.model_dump() == before


@pytest.mark.parametrize("text,stack,expected", [
    ("Python 文件读取及JSON序列化", "使用 Python。", ["Python 文件读取", "Python JSON 序列化"]),
    ("pandas 数据清洗以及分组聚合", "使用 Python 和 pandas。", ["pandas 数据清洗", "pandas 分组聚合"]),
    ("QuillFlow 读取以及错误恢复", "", ["QuillFlow 读取", "QuillFlow 错误恢复"]),
    ("读取JSON以及写入JSON", "Use Rust.", ["Rust 读取JSON", "Rust 写入JSON"]),
])
def test_explicit_conjunctions_and_declared_context_generalize_without_aliases(text, stack, expected):
    req = SearchRequest(knowledge_points=[text], project_context=stack)
    assert [qm.complementary_search_phrase(text, req, i) for i in (1, 2)] == expected


@pytest.mark.parametrize("text", ["Python 及格率统计", "Python 涉及数组访问", "Rust 普及编程", "输入及时响应", "Arduino 按键消抖"])
def test_unsplittable_or_lexical_ji_words_do_not_invent_components(text):
    req = SearchRequest(knowledge_points=[text])
    assert qm.complementary_search_phrase(text, req, 1) is None


@pytest.mark.parametrize("context", [
    "不使用 React。", "不采用 Vue，只学习 DOM。", "比较 React 和 Vue。", "Instead of React use JavaScript.",
    "已会使用 Python，尚未学习 JSON。", "例如使用 Ruby。", "使用 Python 或 JavaScript。",
    "使用 https://example.org。", "使用 site:example.org。", "使用 secret-key token。",
])
def test_negative_comparison_options_examples_or_instructions_supply_no_stack(context):
    text = "数据读取与序列化"
    req = SearchRequest(knowledge_points=[text], project_context=context)
    assert qm.declared_query_stack(req, text) == []
    assert qm.contextual_search_phrase(text, req) == text


def test_positive_new_clause_does_not_borrow_explicitly_excluded_framework():
    req = SearchRequest(knowledge_points=["localStorage读写与JSON序列化"],
        project_context="不使用 React；只用原生 JavaScript。")
    phrase = qm.complementary_search_phrase(req.knowledge_points[0], req, 2)
    assert phrase == "JavaScript JSON 序列化" and "React" not in phrase


def test_hidden_legacy_targets_do_not_drive_professional_query_components():
    text = "按钮消抖状态检测"
    req = SearchRequest(knowledge_points=[text], project_context="使用 Arduino Uno。",
                        learning_targets={text: ["Python socket"]})
    assert qm.contextual_search_phrase(text, req) == text
    assert qm.complementary_search_phrase(text, req, 1) is None


@pytest.mark.parametrize("rounds", [2, 3, 10])
def test_mooc_prefixes_have_same_point_scope_and_no_extra_slots(rounds):
    req = SearchRequest.model_validate(CAPTURED[0]["request"])
    point = {"knowledge_point_id": "original", "text": req.knowledge_points[0]}
    plan = mooc_query_plan(point, req, rounds=rounds)
    assert len(plan) == rounds
    assert plan == mooc_query_plan(point, req, rounds=10)[:rounds]
    assert req.knowledge_points[0] in plan[0].query and "JavaScript" in plan[0].query
    assert all(query.knowledge_point_id == "original" and query.domain_filters == ["icourse163.org"] for query in plan)
    assert "localStorage 读写" in plan[1].query
    if rounds >= 3:
        assert "JSON 序列化" in plan[2].query and "localStorage" not in plan[2].query


def test_long_name_never_truncated_for_background_context():
    text = "目标" * 75
    req = SearchRequest(knowledge_points=[text], project_context="使用 VeryLongTechnologyName LongerVersionName ExtraName。")
    result = qm.contextual_search_phrase(text, req)
    assert text in result and result == text


def test_versions_and_two_platform_limits_remain_in_original_contract():
    text = "QuillFlow 读取与恢复"
    req = SearchRequest(knowledge_points=[text], technical_version="2.4", preferred_platforms=["bilibili", "icourse163"])
    for i in range(3):
        query = platform_query({"knowledge_point_id": "original", "text": text}, "bilibili", req, round_index=i)
        assert "2.4" in query.query
    generated = qm.generate_queries("original", text, req)
    assert len(generated) <= 6 and all(row.knowledge_point_id == "original" for row in generated)


@pytest.mark.parametrize("text,expected", [
    ("Python 图像饱和度调节与亮度调节", ["Python 图像饱和度调节", "Python 亮度调节"]),
    ("Python 电路信号中和处理与滤波处理", ["Python 电路信号中和处理", "Python 滤波处理"]),
    ("Python 图像饱和度调节以及亮度调节", ["Python 图像饱和度调节", "Python 亮度调节"]),
    ("Python 图像饱和度调节、亮度调节", ["Python 图像饱和度调节", "Python 亮度调节"]),
])
def test_explicit_conjunction_does_not_split_internal_he_word(text, expected):
    req = SearchRequest(knowledge_points=[text], project_context="使用 Python。")
    assert [qm.complementary_search_phrase(text, req, index) for index in (1, 2)] == expected
    point = {"knowledge_point_id": "original", "text": text}
    plan = [platform_query(point, "bilibili", req, round_index=index) for index in range(3)]
    assert text in plan[0].query and len(plan) == 3
    assert expected[0] in plan[1].query and expected[1] in plan[2].query
    assert req.knowledge_points == [text]


@pytest.mark.parametrize("text", ["Python 图像饱和度调节", "Python 电路信号中和处理", "Python 列表和字典"])
def test_ambiguous_he_without_explicit_boundary_does_not_create_component(text):
    req = SearchRequest(knowledge_points=[text], project_context="使用 Python。")
    assert qm.complementary_search_phrase(text, req, 1) is None
    assert qm.complementary_search_phrase(text, req, 2) is None
