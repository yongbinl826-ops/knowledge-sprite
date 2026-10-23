"""MOOC phrase strategies are recall hints, never candidate or outline evidence."""
from copy import deepcopy

import httpx
import pytest

from backend.app.config import Settings
from backend.app.models import SearchRequest
from backend.app.mooc_queries import MOOC_QUERY_POLICY, mooc_platform_query, mooc_query_plan, mooc_query_label
from backend.app.platform_search import platform_query
from backend.app.providers import SearXNGProvider


def plan(text, language="zh", **kwargs):
    point = {"knowledge_point_id": "point", "text": text}
    request = SearchRequest(knowledge_points=[text], language=language,
                            preferred_platforms=["bilibili", "icourse163"], **kwargs)
    return mooc_query_plan(point, request)


@pytest.mark.parametrize("language", ["zh", "en", "any"])
@pytest.mark.parametrize("text", ["Python 列表与字典", "pandas 数据分组与聚合", "SQL 多表连接与分组查询",
    "HTML 表单与网页结构", "SQL JOIN and GROUP BY", "OpenCV video frame reading", "控制变量与条件实验"])
def test_six_distinct_bounded_course_only_queries_keep_point_and_domain(language, text):
    queries = plan(text, language)
    assert len(queries) == len({row.query.casefold() for row in queries}) == 6
    assert all(row.knowledge_point_id == "point" and row.domain_filters == ["icourse163.org"] for row in queries)
    assert all(row.query.startswith("site:icourse163.org/course ") for row in queries)
    assert all(len(row.query) < 360 for row in queries)
    assert all("video tutorial" not in row.query and "视频教程" not in row.query for row in queries)
    if text[0].isascii():
        assert all(text.split()[0] in row.query for row in queries)


@pytest.mark.parametrize("text,broad,third,fourth,translated", [
    ("Python 列表与字典", "Python 程序设计", "Python 列表", "Python 字典", "Python list dictionary"),
    ("SQL 多表连接与分组查询", "SQL 数据库", "SQL 多表连接", "SQL 分组查询", "SQL JOIN GROUP BY"),
    ("HTML 表单与网页结构", "HTML 网页设计", "HTML 表单", "HTML 网页结构", "HTML form document structure"),
    ("pandas 数据分组与聚合", "pandas 数据分析", "pandas 数据分组", "pandas 聚合", "pandas groupby aggregation"),
])
def test_broad_and_explicit_parts_are_generic_and_original_point_remains(text, broad, third, fourth, translated):
    queries = plan(text)
    assert text in queries[0].query
    assert broad + " 课程" in queries[1].query
    assert third + " 课程" in queries[2].query and fourth + " 课程" in queries[3].query
    assert translated in queries[4].query


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("text,owner,parts,family,translated", [
    ("pandas 数据分组与聚合", "pandas", ["数据分组", "聚合"], ("数据分析", "data analysis"), "groupby aggregation"),
    ("SQL 多表连接与分组查询", "SQL", ["多表连接", "分组查询"], ("数据库", "databases"), "JOIN GROUP BY"),
    ("HTML 表单与网页结构", "HTML", ["表单", "网页结构"], ("网页设计", "web design"), "form document structure"),
])
def test_sixth_slot_quotes_each_original_part_without_changing_first_five_or_point(
        language, text, owner, parts, family, translated):
    point = {"knowledge_point_id": "original-point", "text": text}
    request = SearchRequest(knowledge_points=[text], language=language,
        preferred_platforms=["bilibili", "icourse163"], project_context="Private project context must not enter queries")
    before = deepcopy((point, request.model_dump()))
    queries = mooc_query_plan(point, request)
    suffixes = ["course", "course content", "course chapters", "course lessons", "course outline"] if language == "en" else [
        "课程", "课程 内容", "课程 章节", "课程 教学", "课程 目录"]
    labels = [text, owner + " " + family[int(language == "en")],
              owner + " " + parts[0], owner + " " + parts[1], owner + " " + translated]
    assert [query.query for query in queries[:5]] == [
        f"site:icourse163.org/course {label} {suffix}" for label, suffix in zip(labels, suffixes)]
    exact = owner + " " + " ".join('"' + part + '"' for part in parts)
    assert mooc_query_label(point, request, 5) == (exact, "")
    assert queries[5].query == mooc_platform_query(point, request, round_index=5).query == "site:icourse163.org/course " + exact
    assert all(query.query == query.query.strip() and query.knowledge_point_id == "original-point" for query in queries)
    assert (point, request.model_dump()) == before
    assert MOOC_QUERY_POLICY == "course-discovery-phrases-v4"


@pytest.mark.parametrize("text", ["UnknownTool 数据分组与聚合", "控制变量与条件实验", "pandas 分组聚合", "Python 列表"])
@pytest.mark.parametrize("language,suffix", [("zh", "课程 大纲"), ("en", "course syllabus")])
def test_unknown_owner_or_unsplittable_topic_keeps_original_sixth_slot(text, language, suffix):
    assert plan(text, language)[5].query == f"site:icourse163.org/course {text} {suffix}"


def test_exact_selected_targets_are_all_preserved_including_more_than_four_parts():
    text = "Python 数据处理"
    targets = ["列表", "字典", "元组", "集合", "循环"]
    queries = plan(text, learning_targets={text: targets})
    assert queries[5].query == 'site:icourse163.org/course Python "列表" "字典" "元组" "集合" "循环"'
    assert len(queries) == 6


def test_overlong_selected_phrase_query_falls_back_without_truncating_targets():
    text = "Python 数据处理"
    targets = ["数据管理" * 20, "统计处理" * 20, "可视表达" * 20]
    assert plan(text, learning_targets={text: targets})[5].query == f"site:icourse163.org/course {text} 课程 大纲"


@pytest.mark.parametrize("unsafe", ["site:example.org attack", "https://example.org/course/123", "filetype:pdf", "Java 集合"])
def test_unsafe_or_foreign_selected_part_cannot_be_hidden_by_exact_quoting(unsafe):
    text = "Python 列表与字典"
    queries = plan(text, learning_targets={text: ["列表", unsafe]})
    assert queries[5].query == f"site:icourse163.org/course {text} 课程 大纲"
    assert "example.org" not in " ".join(row.query for row in queries)
    assert "filetype:" not in " ".join(row.query for row in queries)
    assert "Java" not in " ".join(row.query for row in queries)


def test_exact_slot_keeps_explicit_version_and_english_phrases_without_translation():
    queries = plan("SQL JOIN and GROUP BY", "en", technical_version="2016")
    assert queries[5].query == 'site:icourse163.org/course SQL "JOIN" "GROUP BY" 2016'
    assert all("2016" in row.query for row in queries)


def test_bilibili_first_whole_then_distinct_components_keep_six_unquoted_video_queries():
    text = "Python 列表与字典"
    point = {"knowledge_point_id": "original-point", "text": text}
    request = SearchRequest(knowledge_points=[text], preferred_platforms=["bilibili", "icourse163"])
    expected = [f"{text} 视频教程", "Python 列表 视频教程 示例", "Python 字典 教学 实战",
                "Python 字典 教程 讲解", "Python 列表 实例 操作", f"{text} 课程 完整"]
    assert [platform_query(point, "bilibili", request, round_index=index).query for index in range(6)] == [
        "site:bilibili.com/video " + label for label in expected]


def test_confirmed_api_targets_preserve_legacy_third_fourth_contract_without_search_operators():
    text = "pandas 表格数据处理"
    queries = plan(text, learning_targets={text: ["DataFrame.groupby()", "agg() 聚合"]})
    assert "pandas DataFrame.groupby" in queries[2].query
    assert "pandas agg 聚合" in queries[3].query
    assert all("(" not in query.query and ")" not in query.query for query in queries)


def test_operator_targets_are_rejected_before_punctuation_cleanup_and_other_owner_is_not_donated():
    text = "Python 列表与字典"
    queries = plan(text, learning_targets={text: ["site:example.org attack", "https://example.org/course/123", "Java 集合", "列表"]})
    combined = " ".join(row.query for row in queries)
    assert "example.org" not in combined and "attack" not in combined and "Java" not in combined
    assert combined.count("site:") == 6


@pytest.mark.parametrize("text", ["函数列表", "PythonWrapper 列表与字典", "NoSQL 多表连接与分组查询", "Machine learning"])
def test_unknown_owner_or_non_type_phrase_does_not_acquire_known_family_or_api_alias(text):
    queries = plan(text)
    # Exact name stays first; unknown compound parts may now be prioritized.
    assert text in queries[0].query
    assert "程序设计" not in queries[1].query and "数据库" not in queries[1].query
    assert " JOIN " not in queries[4].query and " dictionary " not in queries[4].query
    if text[0].isascii():
        assert all(text.split()[0] in row.query for row in queries)


def test_list_and_dictionary_aliases_require_exact_parts_not_mention_lists():
    queries = plan("Python 函数列表与术语字典")
    assert "Python list dictionary" not in queries[4].query
    assert "Python 函数列表与术语字典" in queries[4].query


@pytest.mark.parametrize("text,version", [("Python 列表与字典", "3.12"), ("Python 3.12 列表与字典", "")])
def test_explicit_version_survives_every_round(text, version):
    assert all("3.12" in row.query for row in plan(text, technical_version=version))


def test_stable_label_interface_includes_version_once_and_never_duplicates_owner_in_version():
    point = {"knowledge_point_id": "point", "text": "Python 列表与字典"}
    request = SearchRequest(knowledge_points=[point["text"]], technical_version="Python 3.12")
    label, suffix = mooc_query_label(point, request, 1)
    assert label == "Python 程序设计 3.12" and suffix == "课程 内容"
    assert mooc_platform_query(point, request, round_index=1).query == "site:icourse163.org/course " + label + " " + suffix


def test_explicit_namespace_is_preserved_without_inventing_a_different_owner():
    queries = plan("pandas.DataFrame.groupby 数据分组")
    assert "pandas.DataFrame.groupby" in queries[2].query
    assert "pandas .DataFrame" not in " ".join(row.query for row in queries)


@pytest.mark.parametrize("index", [-1, 10, True, "1", 1.5])
def test_invalid_round_is_rejected(index):
    request = SearchRequest(knowledge_points=["Python 列表"])
    with pytest.raises(ValueError):
        mooc_platform_query({"knowledge_point_id": "point", "text": "Python 列表"}, request, round_index=index)


def test_query_building_does_not_modify_original_topics_goals_or_project_context():
    text = "Python 列表与字典"
    point = {"knowledge_point_id": "point", "text": text}
    request = SearchRequest(knowledge_points=[text], learning_targets={text: ["列表", "字典"]},
                            project_context="unrelated MongoDB deployment and paid account")
    before = deepcopy((point, request.model_dump()))
    queries = mooc_query_plan(point, request)
    assert (point, request.model_dump()) == before
    assert all("MongoDB" not in row.query and "paid" not in row.query for row in queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("language,topic", [("zh", "OpenCV 视频帧读取"), ("en", "OpenCV video frame reading")])
async def test_every_new_mooc_phrase_stays_on_general_course_engine_even_with_video_words(language, topic):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"results": []})

    settings = Settings(searxng_url="https://offline-search.example", searxng_engines=("web",),
        searxng_video_engines=("video",), searxng_fallback_engines=(), search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings, client)
        for query in plan(topic, language):
            await provider.search(query.query, language, 6, query.domain_filters)
    assert len(calls) == 6 and all(request.url.params["engines"] == "web" for request in calls)
