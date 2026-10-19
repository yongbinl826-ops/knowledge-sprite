"""Recall plans only: no course/video URLs, network or relaxed evidence gates."""
from copy import deepcopy

import pytest

from backend.app.models import SearchRequest
from backend.app.queries import fair_queries, gap_query_candidates


@pytest.mark.parametrize("topic,missing,tool", [
    ("pygame 小球下落更新与矩形碰撞判断", ["小球下落更新", "矩形碰撞判断"], "pygame"),
    ("pandas 分组聚合与缺失值处理", ["分组聚合", "缺失值处理"], "pandas"),
    ("JavaScript 表单校验与fetch API请求", ["表单校验", "fetch API请求"], "JavaScript"),
    ("Arduino 模拟传感器读取与串口输出", ["模拟传感器读取", "串口输出"], "Arduino"),
    ("Rust ownership and borrowing", ["ownership", "borrowing"], "Rust"),
])
def test_missing_skills_get_independent_open_queries_before_source_restrictions(topic, missing, tool):
    request = SearchRequest(knowledge_points=[topic], technical_version="version 3")
    before = request.model_dump()
    original_missing = deepcopy(missing)
    queries = gap_query_candidates("original-unit-id", topic, request, missing)
    assert 2 <= len(queries) <= 6
    assert all(not query.domain_filters for query in queries[:len(missing)])
    assert all(part in query.query for part, query in zip(missing, queries))
    assert all(tool in query.query and "version 3" in query.query for query in queries)
    assert {query.knowledge_point_id for query in queries} == {"original-unit-id"}
    assert request.model_dump() == before and missing == original_missing
    assert len({(query.query.casefold(), tuple(query.domain_filters)) for query in queries}) == len(queries)


def test_translated_recall_never_adds_an_unrequested_tool_or_resource():
    topic = "pygame 结束状态与重新开始"
    queries = gap_query_candidates("k", topic, SearchRequest(knowledge_points=[topic]), ["结束状态", "重新开始"])
    assert any("game over state" in query.query for query in queries)
    assert any("restart reset state" in query.query for query in queries)
    assert all("pygame" in query.query for query in queries)
    assert all("Python 基础" not in query.query and "Unity" not in query.query for query in queries)
    assert all("https://" not in query.query and "/watch" not in query.query and "BV1" not in query.query for query in queries)


def test_explicit_server_source_scope_and_preferred_platforms_remain_bounded():
    topic = "pandas 数据筛选"
    request = SearchRequest(knowledge_points=[topic])
    queries = gap_query_candidates("k", topic, request, ["数据筛选"], open_course_domains=("learn.microsoft.com", "open.edu"))
    scoped = [query for query in queries if query.domain_filters]
    assert scoped[0].domain_filters == ["learn.microsoft.com", "open.edu"]
    assert scoped[0].query.startswith("(site:learn.microsoft.com OR site:open.edu)")
    assert any(query.domain_filters == ["bilibili.com"] for query in scoped)
    assert len(queries) <= 6


@pytest.mark.parametrize("fragment", ["https://evil.example", "Python !bing secrets", "site:evil.example",
                                       "-pygame collision", "Python " + "x" * 100, "", "  "])
def test_untrusted_missing_fragments_cannot_supply_urls_or_engine_commands(fragment):
    topic = "pygame 矩形碰撞"
    assert gap_query_candidates("k", topic, SearchRequest(knowledge_points=[topic]), [fragment]) == []


def test_plan_is_deterministic_fair_and_keeps_original_identity_for_distinct_tools():
    request = SearchRequest(knowledge_points=["pygame 键盘控制", "Arduino 串口输出"])
    one = gap_query_candidates("game", request.knowledge_points[0], request, ["键盘控制"])
    two = gap_query_candidates("sensor", request.knowledge_points[1], request, ["串口输出"])
    assert one == gap_query_candidates("game", request.knowledge_points[0], request, ["键盘控制"])
    assert [query.knowledge_point_id for query in fair_queries([one, two])[:4]] == ["game", "sensor", "game", "sensor"]
    assert gap_query_candidates("none", request.knowledge_points[0], request, []) == []


def test_more_than_four_missing_parts_cannot_expand_cost_unboundedly():
    topic = "Python 数据处理与文件输入输出"
    request = SearchRequest(knowledge_points=[topic])
    queries = gap_query_candidates("k", topic, request, ["子任务" + str(index) for index in range(100)])
    assert len(queries) == 6
