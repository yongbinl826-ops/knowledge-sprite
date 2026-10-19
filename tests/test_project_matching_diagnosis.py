"""Offline matching regressions motivated by the frozen project-search audit."""
from copy import deepcopy

import pytest

from backend.app.models import Resource, SearchRequest
from backend.app.ranking import compound_english_match, decompose_topic, rank_resource, tokens, topic_observations


@pytest.mark.parametrize("joiner", ["与", "和", "及", "、"])
def test_conjunction_before_word_initial_conjunction_preserves_complete_term(joiner):
    point = f"pandas 平均分、最高分{joiner}及格率统计"
    assert [row["text"] for row in decompose_topic(point)["subtopics"]] == ["平均分", "最高分", "及格率统计"]
    assert "及格" in tokens(point)
    assert compound_english_match(point, ["pandas 平均分、最高分及格率统计教程"])
    assert not compound_english_match(point, ["pandas 平均分、最高分格率统计教程"])


@pytest.mark.parametrize("term,missing", [("及格率统计", "格率统计"), ("和弦理论", "弦理论"), ("与门电路", "门电路")])
def test_technical_prefix_does_not_strip_a_word_initial_character(term, missing):
    assert term[:2] in tokens("Python " + term)
    assert compound_english_match("Python " + term, ["Python " + term + "课程"])
    assert not compound_english_match("Python " + term, ["Python " + missing + "课程"])


def catalog_fixture(chapters, *, title="Python 入门课程", description=""):
    url = "https://courses.example.org/lesson/1"
    evidence = [{"evidence_id": "type", "kind": "search", "source": "fixture", "url": url,
                 "resource_type_hint": "video", "type_source": "search_template"}]
    # This synthetic lesson has independent own-page video identity; the
    # search engine media template is deliberately not a page identity fact.
    evidence.append({"evidence_id": "own-media-type", "kind": "page", "field": "resource_type",
        "source": "meta.og:type", "url": url, "text": "video"})
    fields = {}
    for field, text in (("title", title), ("description", description)):
        evidence.append({"evidence_id": field, "kind": "page", "field": field, "source": "html." + field, "url": url, "text": text})
        fields[field] = {"evidence_id": field, "source": "html." + field, "url": url}
    parsed = []
    for i, text in enumerate(chapters):
        evidence_id = f"chapter-{i}"
        parsed.append({"title": text, "evidence_id": evidence_id})
        evidence.append({"evidence_id": evidence_id, "kind": "catalog", "field": f"chapters.{i}", "source": "html.catalog", "url": url, "text": text})
    resource = Resource(resource_id="r", url=url, canonical_url=url, title=title, description=description,
        discovered_at="2026-10-18T00:00:00+00:00", resource_type="video", fetch_status="fetched", metadata_evidence_level="catalog",
        video_evidence_status="search_discovered", chapters=parsed,
        field_provenance={**fields, "resource_type": {"source": "meta.og:type", "evidence_id": "own-media-type", "url": url},
                          "video_evidence_status": {"source": "search_template", "evidence_id": "type"}}).model_dump()
    return resource, evidence


def match(topic, resource, evidence):
    before = deepcopy((resource, evidence))
    result = rank_resource({"knowledge_point_id": "p", "text": topic}, resource, evidence, SearchRequest(knowledge_points=[topic]))
    assert (resource, evidence) == before
    return result


def test_chapter_inherits_only_evidenced_page_technical_context_with_joint_provenance():
    resource, evidence = catalog_fixture(["列表与字典操作"])
    result = match("Python 列表与字典", resource, evidence)
    assert result["topic_evidence_status"] == "supported"
    assert set(result["supporting_evidence_ids"]) == {"chapter-0", "title"}
    assert "chapter_inherits_evidenced_parent_technical_context" in result["topic_match_rules"]
    observation = topic_observations({"knowledge_point_id": "p", "text": "Python 列表与字典"}, resource, evidence)[-1]
    assert observation["title"] == observation["raw"] == "列表与字典操作"
    assert observation["body"] == "Python"


def test_separate_chapter_teaching_stays_partial_even_with_shared_parent_context():
    resource, evidence = catalog_fixture(["列表操作", "字典操作"])
    result = match("Python 列表与字典", resource, evidence)
    assert result["topic_evidence_status"] == "partial"
    assert result["topic_evidence_reasons"][0]["code"] == "fragmented_compound_evidence"
    assert [row["status"] for row in result["subtopic_coverage"]] == ["supported", "supported"]
    assert result["subtopic_coverage"][0]["evidence_ids"] == ["chapter-0", "title"]
    assert result["subtopic_coverage"][1]["evidence_ids"] == ["chapter-1", "title"]


def test_parent_actions_are_not_inserted_into_a_different_chapter():
    resource, evidence = catalog_fixture(["字典操作"], title="Python 列表课程")
    result = match("Python 列表与字典", resource, evidence)
    assert result["topic_evidence_status"] == "partial"
    assert result["topic_evidence_reasons"][0]["code"] == "fragmented_compound_evidence"


@pytest.mark.parametrize("damage", ["missing_evidence", "wrong_field", "wrong_source", "foreign_page", "foreign_provenance", "search_only", "modified_text", "foreign_catalog"])
def test_parent_context_requires_current_resource_page_field_evidence(damage):
    resource, evidence = catalog_fixture(["列表与字典操作"])
    parent = next(row for row in evidence if row["evidence_id"] == "title")
    if damage == "missing_evidence":
        evidence.remove(parent)
    elif damage == "wrong_field":
        parent["field"] = "description"
    elif damage == "wrong_source":
        parent["source"] = "unrelated"
    elif damage == "foreign_page":
        parent["url"] = "https://courses.example.org/other"
    elif damage == "foreign_provenance":
        resource["field_provenance"]["title"]["url"] = "https://courses.example.org/other"
    elif damage == "search_only":
        parent["kind"] = "search"
    elif damage == "modified_text":
        parent["text"] = "另一门课程"
    elif damage == "foreign_catalog":
        evidence[-1]["url"] = "https://courses.example.org/other"
    assert match("Python 列表与字典", resource, evidence) is None


@pytest.mark.parametrize("title,description,chapter", [
    ("Python 入门课程", "", "Java 列表与字典操作"),
    ("Python 与 Java 比较课程", "", "列表与字典操作"),
    ("编程入门课程", "先修要求：Python。", "列表与字典操作"),
    ("编程入门课程", "相关课程：Python 入门", "列表与字典操作"),
    ("编程入门课程", "参考 https://example.org/Python", "列表与字典操作"),
    ("Python 入门课程", "", "先修要求：列表与字典操作。"),
])
def test_conflicting_prerequisite_and_external_context_do_not_become_instruction(title, description, chapter):
    resource, evidence = catalog_fixture([chapter], title=title, description=description)
    assert match("Python 列表与字典", resource, evidence) is None


def test_sibling_chapter_cannot_supply_technical_context():
    resource, evidence = catalog_fixture(["Python 环境配置", "列表与字典操作"], title="编程入门课程")
    assert match("Python 列表与字典", resource, evidence) is None


def test_evidenced_description_can_supply_context_without_teaching_actions():
    resource, evidence = catalog_fixture(["列表与字典操作"], title="编程入门课程", description="本课程使用 Python 讲授编程。")
    result = match("Python 列表与字典", resource, evidence)
    assert result["topic_evidence_status"] == "supported"
    assert set(result["supporting_evidence_ids"]) == {"chapter-0", "description"}


def test_parent_does_not_donate_english_instructional_terms_as_technical_context():
    resource, evidence = catalog_fixture(["文件操作"], title="Python file writing 入门课程")
    rows = topic_observations({"knowledge_point_id": "p", "text": "Python file writing 文件操作"}, resource, evidence)
    assert rows[-1]["body"] == "Python"
    assert "writing" not in rows[-1]["body"]


@pytest.mark.parametrize("topic,title,qualification", [
    ("Python 本地文件路径处理", "Python 文件路径处理教程", "本地"),
    ("matplotlib 图表保存为图片", "Matplotlib 保存图片教程", "图表"),
    ("pandas 统计结果导出 Excel", "Pandas 导出数据到EXCEL教程", "统计结果"),
])
def test_operation_core_integrates_as_partial_without_modifying_requested_point(topic, title, qualification):
    resource, evidence = catalog_fixture([], title=title)
    result = match(topic, resource, evidence)
    assert result["topic_evidence_status"] == "partial"
    assert "bounded_operation_partial" in result["topic_match_rules"]
    assert result["subtopic_coverage"][1]["text"] == qualification
    assert result["subtopic_coverage"][1]["status"] == "unknown"
    assert result["subtopic_coverage"][1]["evidence_ids"] == []


@pytest.mark.parametrize("title,description", [
    ("导出Excel教程", "先修要求：pandas。"),
    ("pandas 入门课程", "先修要求：导出Excel；本课程学习列表。"),
    ("普通教程", "相关课程：pandas 导出Excel"),
    ("普通教程", "参考 https://example.org/pandas/export/Excel"),
    ("pandas 数据分析课程", "导出CSV教程"),
])
def test_operation_partial_cannot_borrow_prerequisite_related_or_external_terms(title, description):
    resource, evidence = catalog_fixture([], title=title, description=description)
    result = match("pandas 统计结果导出 Excel", resource, evidence)
    assert result is None or "bounded_operation_partial" not in result["topic_match_rules"]


def test_operation_partial_cannot_bypass_weak_or_type_gate():
    resource, evidence = catalog_fixture([], title="预约今晚直播 pandas 导出Excel")
    result = match("pandas 统计结果导出 Excel", resource, evidence)
    assert result is None or result["topic_evidence_status"] == "needs_review"
    resource, evidence = catalog_fixture([], title="pandas 导出Excel教程")
    resource["resource_type"] = "unknown"
    assert match("pandas 统计结果导出 Excel", resource, evidence) is None


def test_exact_operation_point_keeps_normal_supported_path():
    topic = "pandas 统计结果导出 Excel"
    resource, evidence = catalog_fixture([], title=topic + "教程")
    result = match(topic, resource, evidence)
    assert result["topic_evidence_status"] == "supported"
    assert "bounded_operation_partial" not in result["topic_match_rules"]


@pytest.mark.parametrize("chapter", [
    "【爬虫篇】http与https的区别创建与运行",
    "创建与运行", "Python 创建与运行", "Python 程序运行", "脚本基础语法概览；爬虫服务运行",
])
def test_bare_action_does_not_gain_topic_support_from_parent_language(chapter):
    resource, evidence = catalog_fixture([chapter])
    result = match("Python 脚本基础语法与运行", resource, evidence)
    assert result is None or result["subtopic_coverage"][1]["status"] == "unknown"


@pytest.mark.parametrize("topic,chapter", [
    ("Python 脚本基础语法与运行", "脚本运行教程"),
    ("Python 脚本基础语法与运行", "运行脚本"),
    ("Python 脚本基础语法与运行", "脚本的运行"),
    ("Python 程序编写与执行", "程序执行"),
    ("Python 程序编写与执行", "执行该程序"),
    ("Python 函数定义与调用", "函数调用"),
])
def test_bare_action_retains_explicit_request_object_in_same_chapter(topic, chapter):
    resource, evidence = catalog_fixture([chapter])
    result = match(topic, resource, evidence)
    assert result["topic_evidence_status"] == "partial"
    assert result["subtopic_coverage"][1]["status"] == "supported"
    assert set(result["supporting_evidence_ids"]) == {"chapter-0", "title"}


def test_action_object_cannot_be_supplied_by_a_sibling_or_parent_instruction():
    resource, evidence = catalog_fixture(["脚本基础语法", "爬虫创建与运行"])
    result = match("Python 脚本基础语法与运行", resource, evidence)
    assert result["topic_evidence_status"] == "partial"
    assert [row["status"] for row in result["subtopic_coverage"]] == ["supported", "unknown"]
    assert "chapter-1" not in result["supporting_evidence_ids"]


def test_direct_whole_topic_with_bare_action_remains_supported():
    topic = "Python 脚本基础语法与运行"
    resource, evidence = catalog_fixture([], title=topic + "教程")
    assert match(topic, resource, evidence)["topic_evidence_status"] == "supported"
