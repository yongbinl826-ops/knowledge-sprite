"""Narrow, source-bound teaching aliases; all selected parts remain required."""
import pytest

from backend.app.mooc_relevance import assess_mooc_relevance
from test_mooc_relevance import case


def assessment(point, chapters, title="Web前端设计", snippet="", *, fetched=True):
    selected = {"knowledge_point_id": "p", "text": point}
    resource, evidence = case(chapters, title, point=selected, snippet=snippet)
    if not fetched:
        resource.update(fetch_status="not_fetched", metadata_evidence_level="search", chapters=[])
    return assess_mooc_relevance(selected, resource, evidence)


@pytest.mark.parametrize("version", ["HTML5", "HTML 5", "html5", "HTML"])
def test_html_version_and_structure_element_chapters_cover_both_requested_parts(version):
    result = assessment("HTML 表单与网页结构", (f"第三章 {version}多媒体与表单", "2-5 HTML结构元素"))
    assert result["status"] == "outline_supported" and result["display_eligible"]
    assert len(result["matched_chapters"]) == 2
    assert all(not row["context_evidence_ids"] for row in result["matched_chapters"])


@pytest.mark.parametrize("structure", ["HTML结构元素", "HTML 文档结构", "HTML5基本结构", "HTML 5 文档结构"])
def test_only_explicit_html_structure_teaching_aliases_support_structure(structure):
    result = assessment("HTML 表单与网页结构", ("HTML5表单", structure))
    assert result["display_eligible"]


@pytest.mark.parametrize("other", ["HTML50表单", "XHTML表单", "HTML5Template表单", "CSS表单样式",
                                  "表单的应用", "先修知识：HTML5表单", "本章不包括HTML5表单"])
def test_html_alias_does_not_widen_owner_or_borrow_a_neighbor(other):
    result = assessment("HTML 表单与网页结构", ("HTML5简介", other, "HTML结构元素"))
    assert result["status"] == "outline_partial" and not result["display_eligible"]


@pytest.mark.parametrize("structure", ["CSS网页布局", "网页视觉风格", "HTML结构力学", "DOM介绍",
                                       "HTML标签概述", "先修知识：HTML文档结构", "HTML文档结构拓展阅读"])
def test_structure_is_not_inferred_from_layout_generic_intro_or_non_teaching(structure):
    result = assessment("HTML 表单与网页结构", ("HTML5表单", structure))
    assert result["status"] == "outline_partial" and not result["display_eligible"]


@pytest.mark.parametrize("join", ["SQL两个表连接", "SQL多表联接", "SQL内连接", "SQL外连接",
                                  "SQL INNER JOIN", "SQL LEFT JOIN", "SQL RIGHT JOIN", "SQL FULL JOIN"])
def test_explicit_sql_join_operations_and_group_by_keep_both_obligations(join):
    result = assessment("SQL 多表连接与分组查询", (join, "SQL GROUP BY"), title="数据库原理与应用")
    assert result["status"] == "outline_supported" and result["display_eligible"]
    assert len(result["matched_chapters"]) == 2


@pytest.mark.parametrize("join", ["SQL JOIN", "SQL连接数据库", "SQL连接池", "SQL单表查询",
                                  "NoSQL INNER JOIN", "Python字符串join", "不讲SQL内连接"])
def test_join_keyword_or_foreign_owner_alone_does_not_prove_multiple_table_join(join):
    result = assessment("SQL 多表连接与分组查询", (join, "SQL GROUP BY"), title="数据库原理与应用")
    assert result["status"] == "outline_partial" and not result["display_eligible"]


@pytest.mark.parametrize("group", ["SQL GROUP BY", "SQL grouping queries", "SQL分组统计查询"])
def test_group_query_aliases_are_current_outline_evidence(group):
    assert assessment("SQL 多表连接与分组查询", ("SQL两表连接", group), title="数据库原理")["display_eligible"]


@pytest.mark.parametrize("group", ["pandas groupby", "分组查询", "SQL聚合函数", "SQL ORDER BY", "预备知识：SQL GROUP BY"])
def test_grouping_needs_own_technical_context_and_query_evidence(group):
    result = assessment("SQL 多表连接与分组查询", ("SQL两表连接", group), title="数据库原理")
    assert result["status"] == "outline_partial" and not result["display_eligible"]


def test_unambiguous_own_sql_course_title_can_still_supply_its_existing_context():
    result = assessment("SQL 多表连接与分组查询", ("INNER JOIN", "GROUP BY"), title="SQL查询语言")
    assert result["display_eligible"]
    assert all(row["context_evidence_ids"] for row in result["matched_chapters"])


@pytest.mark.parametrize("point,title,body", [
    ("pandas 数据分组与聚合", "Python数据处理", "项目5 使用pandas进行数据分组与聚合"),
    ("SQL 多表连接与分组查询", "数据库原理与应用", "使用SQL实现多关系查询、分组查询与连接查询"),
])
def test_public_overview_before_prerequisite_section_admits_only_a_probe(point, title, body):
    result = assessment(point, (), title=title, fetched=False,
        snippet=f"【课程目标】\n\n{body}\n\n预备知识\n\nPython语言基础。\n\n证书要求\n完成考核。")
    assert result["status"] == "search_candidate" and result["probe_eligible"]
    assert not result["display_eligible"] and not result["matched_chapters"]


@pytest.mark.parametrize("snippet", [
    "预备知识\n\npandas数据分组与聚合\n\n需要先掌握。",
    "先修知识：pandas数据分组与聚合\n\n后续要求熟练。",
    "预备知识\n\npandas\n\n课程内容\n\n数据分组与聚合。",
    "拓展阅读\n\npandas数据分组与聚合",
    "课程概述\n\n本课程不讲pandas数据分组与聚合。\n\n预备知识\n\n数学基础。",
    "课程概述\n\n推荐其他课程：\n\n相关推荐：pandas数据分组与聚合",
])
def test_prerequisite_non_teaching_and_related_sections_cannot_donate_probe_ownership(snippet):
    result = assessment("pandas 数据分组与聚合", (), title="Python数据处理", fetched=False, snippet=snippet)
    assert not result["probe_eligible"] and not result["display_eligible"]


def test_explicit_new_teaching_section_can_resume_after_prerequisites():
    result = assessment("pandas 数据分组与聚合", (), title="Python数据处理", fetched=False,
        snippet="预备知识\n\nPython语言基础\n\n课程内容\n\n本课程讲授pandas数据分组与聚合。")
    assert result["probe_eligible"] and not result["display_eligible"]
