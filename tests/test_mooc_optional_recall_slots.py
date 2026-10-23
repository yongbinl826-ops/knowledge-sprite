"""Optional search-only recall phrases keep original topics and old cache keys."""
from copy import deepcopy
from dataclasses import replace

import pytest

from backend.app import config
from backend.app.config import Settings
from backend.app.models import SearchRequest
from backend.app.mooc_queries import (MOOC_QUERY_POLICY, mooc_platform_query,
                                      mooc_query_label, mooc_query_plan, mooc_query_site)
from backend.app.platform_search import platform_budget, platform_query


def topic(text, **kwargs):
    return ({"knowledge_point_id": "original", "text": text},
            SearchRequest(knowledge_points=[text], preferred_platforms=["bilibili", "icourse163"], **kwargs))


@pytest.mark.parametrize("language", ["zh", "en", "any"])
@pytest.mark.parametrize("text,extra", [
    ("pandas 数据分组与聚合", ['pandas "分组" "聚合"', "pandas 数据分组 聚合",
                                "pandas groupby aggregation", "pandas 分组 聚合"]),
    ("SQL 多表连接与分组查询", ['SQL "连接" "分组"', "SQL 多表连接 分组查询",
                                "SQL JOIN GROUP BY", "SQL 连接 分组"]),
    ("HTML 表单与网页结构", ['HTML "表单" "网页结构"', "HTML 表单 网页结构",
                            "HTML form document structure", "HTML 表单 网页结构"]),
])
def test_four_optional_slots_have_narrower_scope_and_search_only_aliases(language, text, extra):
    point, request = topic(text, language=language, project_context="Private unrelated project text")
    before = deepcopy((point, request.model_dump()))
    default = mooc_query_plan(point, request)
    expanded = mooc_query_plan(point, request, rounds=10)
    assert len(default) == 6 and expanded[:6] == default
    assert MOOC_QUERY_POLICY == "course-discovery-phrases-v4"
    assert [query.query for query in expanded[6:]] == ["site:www.icourse163.org/course/ " + label for label in extra]
    for index, query in enumerate(expanded):
        assert query == mooc_platform_query(point, request, round_index=index)
        assert query == platform_query(point, "icourse163", request, round_index=index)
        assert query.knowledge_point_id == "original" and query.domain_filters == ["icourse163.org"]
        assert query.query == query.query.strip() and query.query.count("site:") == 1
        if index >= 6:
            assert mooc_query_label(point, request, index) == (extra[index - 6], "")
    assert (point, request.model_dump()) == before
    assert "Private" not in " ".join(query.query for query in expanded)


def test_optional_slots_preserve_every_selected_target_including_unmapped_phrases():
    text = "pandas 数据处理"
    selected = ["数据分组", "聚合", "缺失值", "数据透视表", "自定义转换"]
    point, request = topic(text, learning_targets={text: selected})
    before = deepcopy((point, request.model_dump()))
    expected = ['pandas "分组" "聚合" "缺失值" "数据透视表" "自定义转换"',
                "pandas 数据分组 聚合 缺失值 数据透视表 自定义转换",
                "pandas groupby aggregation missing values 数据透视表 自定义转换",
                "pandas 分组 聚合 缺失值 数据透视表 自定义转换"]
    assert [mooc_query_label(point, request, index)[0] for index in range(6, 10)] == expected
    assert (point, request.model_dump()) == before


@pytest.mark.parametrize("text", ["UnknownTool 数据分组与聚合", "控制变量与条件实验", "pandas 分组聚合", "Python 列表"])
def test_unknown_owner_or_unsplittable_topic_uses_whole_original_fallback(text):
    point, request = topic(text)
    assert [mooc_query_label(point, request, index) for index in range(6, 10)] == [(text, "")] * 4
    assert all(query.query == "site:www.icourse163.org/course/ " + text
               for query in mooc_query_plan(point, request, rounds=10)[6:])


@pytest.mark.parametrize("unsafe", ["site:example.org query", "https://example.org/course/123", "filetype:pdf", "Java 集合"])
def test_unsafe_or_foreign_selected_target_falls_back_without_dropping_an_obligation(unsafe):
    text = "Python 列表与字典"
    point, request = topic(text, learning_targets={text: ["列表", unsafe]})
    assert [mooc_query_label(point, request, index) for index in range(6, 10)] == [(text, "")] * 4


def test_oversized_combined_targets_fall_back_without_partial_alias_search():
    text = "pandas 数据处理"
    point, request = topic(text, learning_targets={text: ["数据管理" * 20, "统计处理" * 20, "可视表达" * 20]})
    assert [mooc_query_label(point, request, index) for index in range(6, 10)] == [(text, "")] * 4


def test_explicit_version_and_original_english_targets_survive_all_ten_slots_once():
    point, request = topic("SQL JOIN and GROUP BY", language="en", technical_version="SQL 2016")
    queries = mooc_query_plan(point, request, rounds=10)
    assert all(row.query.count("2016") == 1 for row in queries)
    assert [row.query for row in queries[6:]] == [
        'site:www.icourse163.org/course/ SQL "JOIN" "GROUP BY" 2016',
        *["site:www.icourse163.org/course/ SQL JOIN GROUP BY 2016"] * 3,
    ]


@pytest.mark.parametrize("value", [0, 11, True, "10", 2.5])
def test_explicit_plan_size_is_bounded_integer(value):
    point, request = topic("SQL 多表连接与分组查询")
    with pytest.raises(ValueError):
        mooc_query_plan(point, request, rounds=value)


@pytest.mark.parametrize("index", [-1, 10, True, "6", 6.5])
def test_optional_site_and_label_helpers_reject_invalid_indices(index):
    point, request = topic("pandas 数据分组与聚合")
    with pytest.raises(ValueError):
        mooc_query_site(index)
    with pytest.raises(ValueError):
        mooc_query_label(point, request, index)


def test_config_allows_ten_mooc_rounds_and_retains_bilibili_six_and_existing_defaults():
    settings = Settings()
    assert (settings.mooc_search_rounds, settings.bilibili_search_rounds) == (2, 2)
    expanded = replace(settings, parallel_platform_search=True, mooc_search_rounds=10,
                       bilibili_search_rounds=6, max_search_requests=80).validate()
    assert platform_budget(expanded, 3, ["bilibili", "icourse163"])["platform_request_limits"] == {
        "bilibili": 18, "icourse163": 30, "open_web": 3}
    for fields in ({"mooc_search_rounds": 11}, {"bilibili_search_rounds": 7}):
        with pytest.raises(ValueError):
            replace(settings, **fields).validate()
    point, request = topic("pandas 数据分组与聚合")
    for index in range(6, 10):
        with pytest.raises(ValueError):
            platform_query(point, "bilibili", request, round_index=index)


def test_environment_accepts_ten_mooc_rounds_without_reading_local_dotenv(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("MOOC_SEARCH_ROUNDS", "10")
    monkeypatch.setenv("BILIBILI_SEARCH_ROUNDS", "6")
    assert (Settings.from_env().mooc_search_rounds, Settings.from_env().bilibili_search_rounds) == (10, 6)
    monkeypatch.setenv("MOOC_SEARCH_ROUNDS", "11")
    with pytest.raises(ValueError, match="MOOC_SEARCH_ROUNDS"):
        Settings.from_env()
