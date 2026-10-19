"""Offline query-selection regressions; model transport is explicitly mocked."""
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.llm import OpenAICompatibleLLM
from backend.app.models import SearchRequest
from backend.app.queries import compact_search_phrase, fair_queries, generate_queries


def test_complete_literal_operations_win_over_a_half_topic():
    point = "Rust ownership and borrowing"
    variants = ["Rust ownership", "Rust ownership borrowing examples"]
    assert compact_search_phrase(point, variants) == variants[1]


def test_complete_chinese_operations_win_without_joining_variants():
    point = "NumPy 数组索引与形状调整"
    variants = ["NumPy 数组索引", "NumPy 数组索引 形状调整 reshape", "NumPy reshape"]
    assert compact_search_phrase(point, variants) == variants[1]


def test_near_original_can_use_a_short_novel_alternative_preserving_parts():
    point = "SQL 分组与聚合"
    variants = ["SQL 聚合 分组", "SQL GROUP BY 分组 聚合"]
    assert compact_search_phrase(point, variants) == variants[1]


def test_new_api_alone_cannot_displace_proven_complete_operation_words():
    point = "NumPy 数组索引与形状调整"
    variants = ["NumPy 数组索引 形状调整", "NumPy reshape"]
    assert compact_search_phrase(point, variants) == variants[0]


def test_useful_subset_is_not_rejected_for_removing_example_context():
    assert compact_search_phrase("Python 本地文件路径处理", ["Python 文件路径处理"]) == "Python 文件路径处理"


def test_selected_teaching_suffix_does_not_block_a_later_operation_preserving_variant():
    point = "Python 脚本基础语法与运行"
    variants = ["Python 脚本基础语法与运行入门", "Python 脚本基础语法 运行 py"]
    assert compact_search_phrase(point, variants) == variants[1]


@pytest.mark.parametrize("suffix", ["入门", "视频教程", "教学 示例", "tutorial", "beginner examples"])
def test_teaching_suffix_alone_does_not_make_an_alternative_novel(suffix):
    variants = ["SQL 分组 聚合", f"SQL 分组 聚合 {suffix}"]
    assert compact_search_phrase("SQL 分组与聚合", variants) == variants[0]


def test_skipping_self_still_cannot_drop_an_explicit_operation():
    variants = ["Python 脚本基础语法与运行入门", "Python 运行 py"]
    assert compact_search_phrase("Python 脚本基础语法与运行", variants) == variants[0]


def test_project_length_expansion_is_rejected_without_losing_original_or_short_api():
    point = "Python 本地文件路径处理"
    verbose = "Python 3 本地文件路径处理 读取输入 Excel 路径并拼接输出目录保存图片与 Excel"
    concise = "Python pathlib Path 文件路径处理"
    assert compact_search_phrase(point, [verbose, concise]) == concise
    assert compact_search_phrase(point, [verbose]) is None
    queries = generate_queries("original", point, SearchRequest(knowledge_points=[point]), [verbose])
    assert point in queries[0].query and point in queries[1].query
    assert len(queries) <= 6


def test_growth_guard_retains_short_api_variants_for_small_topics():
    assert compact_search_phrase("Python 路径", ["Python pathlib Path 文件路径处理"]) == "Python pathlib Path 文件路径处理"


@pytest.mark.parametrize("domains", [(), ("ocw.mit.edu",)])
def test_rejected_verbose_variant_never_returns_through_legacy_query_paths(domains):
    point = "Python 本地文件路径处理"
    verbose = "Python 3 本地文件路径处理 读取输入 Excel 路径并拼接输出目录保存图片与 Excel"
    queries = generate_queries("point", point, SearchRequest(knowledge_points=[point]), [verbose], open_course_domains=domains)
    assert all(verbose not in query.query and "读取输入" not in query.query for query in queries)
    assert queries[1].query == point + " 课程 教学"
    assert len(queries) <= 6


@pytest.mark.parametrize("domains", [(), ("ocw.mit.edu",)])
def test_unsafe_variant_is_excluded_but_safe_non_ascii_topic_expansion_remains(domains):
    point = "问卷统计分析"
    safe = "描述统计 分组汇总"
    queries = generate_queries("point", point, SearchRequest(knowledge_points=[point]), ["!video site:example.org", safe], open_course_domains=domains)
    assert all("!video" not in query.query and "example.org" not in query.query for query in queries)
    assert any(safe in query.query for query in queries)
    assert all(query.knowledge_point_id == "point" for query in queries)


@pytest.mark.parametrize("variant", ["pandas Series 索引切片", "pandas 索引切片", "pandas DataFrames 索引切片"])
def test_explicit_technical_object_cannot_disappear_or_change(variant):
    assert compact_search_phrase("pandas DataFrame 索引切片", [variant]) is None


@pytest.mark.parametrize("variant", ["Java 本地文件处理", "JavaScript site:example.org 文件处理", "JavaScript !video 文件处理", "JavaScript https://example.org", "JavaScript -文件处理", "JavaScript " + "a" * 81])
def test_candidate_preference_cannot_bypass_existing_safety_or_technology(variant):
    assert compact_search_phrase("JavaScript 本地文件路径处理", [variant]) is None


def test_invalid_or_wrong_object_first_variant_can_use_valid_later_variant():
    variants = ["pandas Series 索引", "pandas DataFrame loc 索引切片"]
    assert compact_search_phrase("pandas DataFrame 索引切片", variants) == variants[1]


def test_versions_and_original_point_remain_in_first_query_and_scoped_queries():
    point = "Rust ownership and borrowing"
    request = SearchRequest(knowledge_points=[point], technical_version="Rust 1.80", preferred_platforms=["bilibili", "icourse163", "xuetangx"])
    variants = ["Rust ownership", "Rust ownership borrowing examples"]
    queries = generate_queries("unchanged", point, request, variants, open_course_domains=("ocw.mit.edu",))
    assert len(queries) == 6
    assert point in queries[0].query
    assert queries[1].query == variants[1] + " Rust 1.80 视频教程"
    assert all(point in query.query for query in queries[2:])
    assert all("Rust 1.80" in query.query for query in queries)
    assert all(query.knowledge_point_id == "unchanged" for query in queries)
    assert request.knowledge_points == [point]
    assert [query.domain_filters for query in queries[2:]] == [["bilibili.com"], ["icourse163.org"], ["xuetangx.com"], ["ocw.mit.edu"]]


def test_rejected_variants_do_not_remove_original_or_change_fair_rounds():
    points = ["pandas DataFrame 索引切片", "Rust ownership and borrowing"]
    request = SearchRequest(knowledge_points=points)
    groups = [generate_queries(str(index), point, request, ["wrong technology"]) for index, point in enumerate(points)]
    assert [query.knowledge_point_id for query in fair_queries(groups)[:4]] == ["0", "1", "0", "1"]
    assert all(point in group[0].query and point in group[1].query for point, group in zip(points, groups))


@pytest.mark.asyncio
async def test_expansion_prompt_keeps_compound_scope_and_data_contract():
    observed = []
    keywords = ["Rust ownership borrowing examples", "Rust borrowing lifetimes"]
    def response(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"keywords": keywords})}}]})
    settings = Settings(llm_api_key="offline-synthetic-key", llm_base_url="https://model.example/v1", llm_model="offline-mock")
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await OpenAICompatibleLLM(settings, client).expand("Rust ownership and borrowing", "业务项目说明")
    assert result == keywords
    assert len(observed) == 1
    prompt = observed[0]["messages"][0]["content"]
    assert "FIRST phrase must express ALL core requested teaching operations" in prompt
    assert "explicit technical objects and versions" in prompt
    assert "not evidence that a course teaches" in prompt
    assert "do not concatenate every synonym or API name" in prompt
    assert json.loads(observed[0]["messages"][1]["content"]) == {"knowledge_point": "Rust ownership and borrowing", "project_context": "业务项目说明"}
    assert observed[0]["response_format"] == {"type": "json_object"}
