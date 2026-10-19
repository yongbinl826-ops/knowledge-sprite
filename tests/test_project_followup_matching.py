"""Offline regressions: observed skills must not prove their missing qualifiers."""
from copy import deepcopy

import pytest

from backend.app.models import Resource, SearchRequest
from backend.app.ranking import assess_topic_evidence, rank_resource, search_instructional_text, topic_observations


def lesson(title, *, description="", chapters=()):
    """Synthetic evidence, never used as a live acceptance result."""
    url = "https://courses.example.org/lesson/qualification-tests"
    evidence = [{"evidence_id": "type", "kind": "search", "source": "fixture", "url": url,
                 "resource_type_hint": "video", "type_source": "search_template"}]
    # Synthetic videos have an independent own-page media declaration. Search
    # engine media templates alone are deliberately not page video identity.
    evidence.append({"evidence_id": "own-media-type", "kind": "page", "field": "resource_type",
        "source": "meta.og:type", "url": url, "text": "video"})
    provenance = {}
    for field, text in (("title", title), ("description", description)):
        evidence.append({"evidence_id": field, "kind": "page", "field": field,
                         "source": "html." + field, "url": url, "text": text})
        provenance[field] = {"evidence_id": field, "source": "html." + field, "url": url}
    catalog = []
    for index, text in enumerate(chapters):
        evidence_id = f"chapter-{index}"
        catalog.append({"title": text, "evidence_id": evidence_id})
        evidence.append({"evidence_id": evidence_id, "kind": "catalog", "field": f"chapters.{index}",
                         "source": "html.catalog", "url": url, "text": text})
    resource = Resource(resource_id="r", url=url, canonical_url=url, title=title, description=description,
                        discovered_at="2026-10-18T00:00:00+00:00", resource_type="video", fetch_status="fetched",
                        metadata_evidence_level="catalog", video_evidence_status="search_discovered", chapters=catalog,
                        field_provenance={**provenance, "resource_type": {"source": "meta.og:type", "evidence_id": "own-media-type", "url": url},
                                          "video_evidence_status": {"source": "search_template", "evidence_id": "type"}}).model_dump()
    return resource, evidence


def evaluate(topic, title, *, description="", chapters=()):
    resource, evidence = lesson(title, description=description, chapters=chapters)
    original = deepcopy((resource, evidence))
    result = rank_resource({"knowledge_point_id": "point", "text": topic}, resource, evidence,
                           SearchRequest(knowledge_points=[topic]))
    assert (resource, evidence) == original
    return result


def coverage(result):
    return {row["text"]: row for row in result["subtopic_coverage"]}


def test_basic_grammar_is_partial_core_without_script_or_runtime_claim_or_wrong_chapter():
    result = evaluate("Python 脚本基础语法与运行", "Python 入门课程",
                      description="Python 课程包含基础语法和自动化办公。",
                      chapters=["【爬虫篇】http与https的区别创建与运行"])
    assert result["topic_evidence_status"] == "partial"
    rows = coverage(result)
    assert rows["脚本基础语法"]["status"] == rows["运行"]["status"] == "unknown"
    assert rows["Python 基础语法"]["status"] == "supported"
    assert rows["Python 基础语法"]["evidence_ids"] == ["description"]
    assert result["supporting_evidence_ids"] == ["description"]
    assert "qualified_skill_core_partial" in result["topic_match_rules"]


def test_actual_core_chapter_keeps_its_own_and_parent_ids_without_sibling_action():
    result = evaluate("Python 脚本基础语法与运行", "Python 入门课程", chapters=["基础语法", "创建与运行"])
    rows = coverage(result)
    assert rows["运行"]["status"] == "unknown"
    assert set(rows["Python 基础语法"]["evidence_ids"]) == {"chapter-0", "title"}
    assert "chapter-1" not in result["supporting_evidence_ids"]


@pytest.mark.parametrize("title", ["Python 基础教程", "Python 程序运行教程", "Python 脚本创建教程"])
def test_general_basics_and_bare_actions_do_not_prove_grammar_core(title):
    assert evaluate("Python 脚本基础语法与运行", title) is None


@pytest.mark.parametrize("title", [
    "Python 课程；Java 基础语法教程", "Python 与 Java 基础语法教程",
    "Python 不讲基础语法", "Python 不进行基础语法教学", "Python 无需基础语法",
    "Python 先修要求：基础语法", "Python 课程；相关课程：基础语法",
])
def test_qualified_core_rejects_prerequisite_negation_and_competing_context(title):
    result = evaluate("Python 脚本基础语法与运行", title)
    assert result is None or not any(row["status"] == "supported" for row in result["subtopic_coverage"])


@pytest.mark.parametrize("title", [
    "pandas DataFrame 选择列教程", "pandas DataFrame 选择指定的列教程", "pandas DataFrame 选择行与列",
])
def test_same_chinese_selection_object_supports_reversed_word_order(title):
    result = evaluate("pandas DataFrame 列选择与列名处理", title)
    assert result["topic_evidence_status"] == "partial"
    rows = coverage(result)
    assert rows["列选择"]["status"] == "supported"
    assert rows["列名处理"]["status"] == "unknown"


def test_variable_name_does_not_prove_dataframe_type_but_literal_column_skill_is_visible():
    result = evaluate("pandas DataFrame 列选择与列名处理", "Pandas 教程 df 与 Series 基础：选择行与列")
    rows = coverage(result)
    assert result["topic_evidence_status"] == "partial"
    assert rows["列选择"]["status"] == rows["列名处理"]["status"] == "unknown"
    assert rows["pandas 列选择（DataFrame 类型未确认）"]["status"] == "supported"


@pytest.mark.parametrize("title", [
    "pandas DataFrame 选择行", "pandas DataFrame 选择列车", "pandas DataFrame 选择列名",
    "pandas DataFrame 选择列车和行", "pandas DataFrame 不要选择列", "pandas DataFrame 禁止选择列",
    "pandas DataFrame 无法选择列", "pandas DataFrame 修改列名", "pandas DataFrame 重命名行索引",
])
def test_selection_does_not_borrow_other_object_action_or_negative_instruction(title):
    assert evaluate("pandas DataFrame 列选择与列名处理", title) is None


def test_type_conversion_core_does_not_prove_numeric_or_missing_value_check():
    result = evaluate("pandas 数值类型转换与缺失值检查", "Pandas 数据清洗-类型转换与处理缺失值",
                      chapters=["Pandas 数据清洗-类型转换与处理缺失值"])
    rows = coverage(result)
    assert result["topic_evidence_status"] == "partial"
    assert rows["数值类型转换"]["status"] == rows["缺失值检查"]["status"] == "unknown"
    assert rows["pandas 类型转换"]["status"] == "supported"
    assert "chapter-0" in rows["pandas 类型转换"]["evidence_ids"]


@pytest.mark.parametrize("operation", ["to_numeric()", "astype(int)", "astype('float64')", 'astype("uint32")'])
def test_explicit_documented_numeric_conversion_supports_only_that_child(operation):
    result = evaluate("pandas 数值类型转换与缺失值检查", "pandas " + operation + " 教程")
    rows = coverage(result)
    assert result["topic_evidence_status"] == "partial"
    assert rows["数值类型转换"]["status"] == "supported"
    assert rows["缺失值检查"]["status"] == "unknown"
    assert "documented_operation_partial" in result["topic_match_rules"]


@pytest.mark.parametrize("operation", ["astype()", "astype('category')", "astype(str)", "astype('string')"])
def test_unspecified_or_nonnumeric_astype_never_claims_numeric_conversion(operation):
    result = evaluate("pandas 数值类型转换与缺失值检查", "pandas " + operation + " 教程")
    rows = coverage(result)
    assert rows["数值类型转换"]["status"] == "unknown"
    assert rows["pandas 类型转换"]["status"] == "supported"


@pytest.mark.parametrize("operation", ["isna()", "检测缺失值", "检测与处理缺失值"])
def test_explicit_missing_value_detection_supports_check_not_numeric_conversion(operation):
    result = evaluate("pandas 数值类型转换与缺失值检查", "pandas " + operation + " 教程")
    rows = coverage(result)
    assert result["topic_evidence_status"] == "partial"
    assert rows["缺失值检查"]["status"] == "supported"
    assert rows["数值类型转换"]["status"] == "unknown"


@pytest.mark.parametrize("title", [
    "pandas 处理缺失值", "pandas fillna() 教程", "pandas dropna() 教程",
    "pandas not_to_numeric()", "pandas isna_custom()", "pandas numpy to_numeric()",
    "pandas 教程；numpy astype(int)", "pandas 教程；to_numeric()",
    "pandas 无法 to_numeric()", "pandas 不讲 to_numeric()", "pandas never use to_numeric()",
])
def test_apis_cannot_be_inferred_from_processing_near_names_other_ownership_or_negation(title):
    result = evaluate("pandas 数值类型转换与缺失值检查", title)
    assert result is None or not any(row["status"] == "supported" for row in result["subtopic_coverage"])


@pytest.mark.parametrize("operation,core", [("mean()", "平均值计算"), ("mean函数", "平均值计算"), ("max()", "最大值计算")])
def test_aggregation_api_is_only_core_not_subject_score_or_pass_rate(operation, core):
    result = evaluate("pandas 分科平均分、最高分与及格率统计", "pandas " + operation + " 教程")
    rows = coverage(result)
    assert result["topic_evidence_status"] == "partial"
    assert all(rows[term]["status"] == "unknown" for term in ["分科平均分", "最高分", "及格率统计"])
    assert rows["pandas " + core]["status"] == "supported"


@pytest.mark.parametrize("title", ["pandas 入门完整教程", "pandas idxmax() 教程", "pandas maximum() 教程", "pandas 统计教程"])
def test_general_statistics_and_other_apis_cannot_fill_missing_score_operations(title):
    assert evaluate("pandas 分科平均分、最高分与及格率统计", title) is None


def test_column_rename_requires_explicit_columns_argument_and_keeps_broad_handling_unknown():
    topic = "pandas DataFrame 列选择与列名处理"
    result = evaluate(topic, "pandas DataFrame rename(columns={'old':'new'}) 教程")
    assert coverage(result)["列名处理"]["status"] == "unknown"
    assert coverage(result)["pandas 列重命名"]["status"] == "supported"
    assert evaluate(topic, "pandas DataFrame rename(index={'old':'new'}) 教程") is None
    assert evaluate(topic, "pandas DataFrame rename() 教程") is None


def test_partial_core_respects_verified_observation_and_video_type_gates():
    topic = {"knowledge_point_id": "point", "text": "Python 脚本基础语法与运行"}
    resource, evidence = lesson("Python 基础语法教程")
    assert assess_topic_evidence(topic, resource, []) is None
    resource["resource_type"] = "unknown"
    assert rank_resource(topic, resource, evidence, SearchRequest(knowledge_points=[topic["text"]])) is None


def test_live_announcement_cannot_use_new_partial_path_to_become_teaching_evidence():
    result = evaluate("Python 脚本基础语法与运行", "预约今晚直播 Python 基础语法")
    assert result is None or result["topic_evidence_status"] == "needs_review"


def test_explicit_whole_requirement_preserves_normal_supported_path():
    topic = "pandas 数值类型转换与缺失值检查"
    result = evaluate(topic, topic + "教程")
    assert result["topic_evidence_status"] == "supported"
    assert all(row["status"] == "supported" for row in result["subtopic_coverage"])
    assert "qualified_skill_core_partial" not in result["topic_match_rules"]


@pytest.mark.parametrize("topic,title", [
    ("Python 脚本基础语法与运行", "Python 课程介绍 SQL 基础语法"),
    ("Python 脚本基础语法与运行", "Python 课程中 HTML 基础语法"),
    ("Python 脚本基础语法与运行", "Python 与 PHP 基础语法教程"),
    ("Python 脚本基础语法与运行", "Python 与 Lua 基础语法教程"),
    ("Python 脚本基础语法与运行", "Python 不包括基础语法教程"),
    ("pandas DataFrame 列选择与列名处理", "pandas DataFrame 与 polars 选择列教程"),
    ("pandas 数值类型转换与缺失值检查", "pandas 读取 CSV 教程（相关 API 列表：to_numeric、isna）"),
    ("pandas 数值类型转换与缺失值检查", "pandas 读取 CSV 教程，顺便提及 to_numeric、isna"),
    ("pandas 数值类型转换与缺失值检查", "pandas 自定义 helper.to_numeric() 教程"),
    ("pandas 数值类型转换与缺失值检查", "pandas helper.isna() 教程"),
    ("pandas 数值类型转换与缺失值检查", "pandas helper.astype(int) 教程"),
    ("pandas 分科平均分、最高分与及格率统计", "pandas 读取 CSV 教程，另见 statistics.mean() 文档"),
    ("pandas 分科平均分、最高分与及格率统计", "pandas statistics.mean() 教程"),
    ("pandas 分科平均分、最高分与及格率统计", "pandas max() 不是最大值计算教程"),
    ("pandas 分科平均分、最高分与及格率统计", "pandas custom.max() 教程"),
    ("pandas 数值类型转换与缺失值检查", "pandas 已弃用 to_numeric() 接口，不建议使用"),
    ("pandas DataFrame 列选择与列名处理", "pandas DataFrame 选择列教程（本视频不涵盖）"),
])
def test_independent_review_counterexamples_do_not_create_core_support(topic, title):
    result = evaluate(topic, title)
    assert result is None or not any(row["status"] == "supported" for row in result["subtopic_coverage"])


@pytest.mark.parametrize("api,part", [("pandas.to_numeric()", "数值类型转换"), ("pd.to_numeric()", "数值类型转换"),
                                      ("pandas.isna()", "缺失值检查"), ("DataFrame.isna()", "缺失值检查"),
                                      ("pandas.Series.astype(int)", "数值类型转换")])
def test_explicit_standard_receiver_keeps_the_documented_operation(api, part):
    result = evaluate("pandas 数值类型转换与缺失值检查", "pandas " + api + " 教程")
    assert coverage(result)[part]["status"] == "supported"


def test_changed_page_text_cannot_piggyback_another_page_fields_id_for_new_core():
    topic = {"knowledge_point_id": "point", "text": "Python 脚本基础语法与运行"}
    resource, evidence = lesson("Python 入门课程", description="普通课程简介")
    resource["description"] = "Python 基础语法教程"
    result = assess_topic_evidence(topic, resource, evidence)
    assert result is None


def search_lesson(title, snippet):
    resource, _ = lesson(title, description=snippet)
    resource.update(metadata_evidence_level="search", fetch_status="not_fetched", chapters=[])
    for field in ("title", "description"):
        resource["field_provenance"][field] = {"evidence_id": "search", "source": "search", "url": resource["url"]}
    evidence = [{"evidence_id": "search", "kind": "search", "source": "fixture", "url": resource["url"],
                 "knowledge_point_id": "point", "title": title, "snippet": snippet,
                 "resource_type_hint": "video", "type_source": "search_template"}]
    resource["field_provenance"]["resource_type"]["source"] = "search_template"
    resource["field_provenance"]["resource_type"]["evidence_id"] = "search"
    resource["field_provenance"]["video_evidence_status"]["evidence_id"] = "search"
    return resource, evidence


@pytest.mark.parametrize("title,snippet", [
    ("sigmaplot柱状图制作教程", "用bar绘制柱状图 #matplotlib #python教学 #学习使我快乐 #绘图指导 #教程来了"),
    ("柱状图绘制教程 #matplotlib", "学习柱状图绘制"),
    ("柱状图绘制教程", "#matplotlib 柱状图绘制"),
    ("柱状图绘制教程", "#matplotlib# 柱状图绘制"),
])
def test_search_hashtag_alone_does_not_supply_requested_technology(title, snippet):
    point = {"knowledge_point_id": "point", "text": "matplotlib 柱状图绘制"}
    resource, evidence = search_lesson(title, snippet)
    # Match the real failure shape: JS-required still has only search fields.
    resource.update(fetch_status="javascript_required", metadata_evidence_level="page")
    original = deepcopy((resource, evidence))
    assert assess_topic_evidence(point, resource, evidence) is None
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])) is None
    assert (resource, evidence) == original
    assert topic_observations(point, resource, evidence)[0]["raw"] == title + " " + snippet


@pytest.mark.parametrize("title,snippet", [
    ("Matplotlib 柱状图绘制教程", "绘图教学 #python #matplotlib"),
    ("柱状图绘制教程", "使用 matplotlib 绘制柱状图 #教程"),
])
def test_real_title_or_nonhashtag_prose_keeps_its_own_support(title, snippet):
    point = {"knowledge_point_id": "point", "text": "matplotlib 柱状图绘制"}
    resource, evidence = search_lesson(title, snippet)
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("page_or_catalog", ["page", "catalog"])
def test_independent_page_or_catalog_can_support_after_search_hashtags_removed(page_or_catalog):
    point = {"knowledge_point_id": "point", "text": "matplotlib 柱状图绘制"}
    resource, evidence = lesson("Matplotlib 柱状图绘制教程" if page_or_catalog == "page" else "Matplotlib 入门课程",
                                chapters=["Matplotlib 柱状图绘制"] if page_or_catalog == "catalog" else [])
    evidence[0].update(title="另一软件柱状图教程", snippet="用bar绘制柱状图 #matplotlib", knowledge_point_id="point")
    result = rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result["topic_evidence_status"] == "supported"
    assert "type" not in result["supporting_evidence_ids"]
    assert ("title" if page_or_catalog == "page" else "chapter-0") in result["supporting_evidence_ids"]


@pytest.mark.parametrize("code", ["C# 集合教程", "color='#ff0000'", "print('#python')", "x#python",
                                  "`#define VALUE 1`", "```c\n#include <stdio.h>\n```", "#include <stdio.h>"])
def test_hashtag_filter_preserves_language_and_code_hash_syntax(code):
    assert search_instructional_text(code + "\n#matplotlib") == code + "\n "


def test_csharp_search_lesson_still_has_the_language_identity():
    point = {"knowledge_point_id": "point", "text": "C# 集合与泛型"}
    resource, evidence = search_lesson("C# 集合与泛型教程", "集合教学 #教程")
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("database", ["MySQL", "PostgreSQL"])
def test_existing_sql_row_number_equivalence_does_not_depend_on_social_sql_tag(database):
    point = {"knowledge_point_id": "point", "text": "SQL window functions ROW_NUMBER"}
    resource, evidence = search_lesson(database + " 去重教程", "DISTINCT/GROUP BY/ROW_NUMBER 全覆盖，实战与性能优化 #SQL #数据清洗")
    result = rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result["topic_evidence_status"] == "supported"
    assert result["supporting_evidence_ids"] == ["search"]
    assert "sql_row_number_is_window_function" in result["topic_match_rules"]
    evidence[0]["snippet"] = "DISTINCT/GROUP BY/ROW_NUMBER 全覆盖，实战与性能优化"
    result_without_tags = rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert result_without_tags["ranking_score"] == result["ranking_score"]


@pytest.mark.parametrize("title,snippet,topic", [
    ("Python 排名教程", "ROW_NUMBER 函数 #SQL", "SQL window functions ROW_NUMBER"),
    ("排名教程", "ROW_NUMBER 函数 #SQL", "SQL window functions ROW_NUMBER"),
    ("NoSQL 排名教程", "ROW_NUMBER 函数", "SQL window functions ROW_NUMBER"),
    ("MySQL 去重教程", "ROW_NUMBER 函数", "SQL window functions RANK"),
])
def test_sql_score_protection_requires_existing_exact_concept_and_nonhashtag_context(title, snippet, topic):
    point = {"knowledge_point_id": "point", "text": topic}
    resource, evidence = search_lesson(title, snippet)
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[topic])) is None


def test_sql_score_protection_cannot_combine_different_search_observations():
    point = {"knowledge_point_id": "point", "text": "SQL window functions ROW_NUMBER"}
    resource, evidence = search_lesson("MySQL 去重教程", "GROUP BY 教学")
    evidence.append({**evidence[0], "evidence_id": "other-search", "title": "Python 排名教程", "snippet": "ROW_NUMBER 函数 #SQL"})
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])) is None
