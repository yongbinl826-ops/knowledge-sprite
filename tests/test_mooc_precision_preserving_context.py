"""Offline precision checks using the actual public-course DTO extractor."""
from copy import deepcopy
import hashlib
import json

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.mooc_relevance import assess_mooc_relevance


URL = "https://www.icourse163.org/course/OWN-123"
SOURCE = "html.icourse163.termDto.outLineDto.outLineStructureDtos"
POINT = {"knowledge_point_id": "selected", "text": "pandas 数据分组与聚合"}


def observed(rows, *, point=POINT, title="程序设计基础", outline="", snippet=None):
    term = {"id": "456", "outLineDto": {"outLine": outline, "outLineStructureDtos": rows}}
    markup = ('<div id="j-course-heading-intro"><div class="course-heading-intro_intro">'
              '本课程提供公开的课程章节与教学内容说明，学生可以核对各单元的学习安排。'
              '</div></div><div id="j-course-outline"></div><script>window.termDto = '
              + json.dumps(term).replace("</", "<\\/") + '; window.courseDto = '
              + json.dumps({"id": "123", "name": title}) + ';</script>')
    resource = MetadataExtractor().extract(markup, URL, "offline-context")
    evidence = resource.pop("evidence")
    resource.update(url=URL, canonical_url=URL, resource_id="resource", platform="icourse163")
    evidence.append({"evidence_id": "search", "kind": "search", "url": URL,
                     "knowledge_point_id": point["knowledge_point_id"], "title": title,
                     "snippet": point["text"] + "课程教学" if snippet is None else snippet})
    return resource, evidence


def evaluate(rows, *, point=POINT, **kwargs):
    resource, evidence = observed(rows, point=point, **kwargs)
    return assess_mooc_relevance(point, resource, evidence)


@pytest.mark.parametrize("structure", [
    "HTML文件结构", "HTML文件基本结构", "HTML5文件结构", "HTML5文件的基本结构",
    "HTML5网页文档结构", "网页文档结构", "网页文档基本结构", "文档的基本结构",
])
def test_explicit_document_structure_synonyms_still_require_separate_form_coverage(structure):
    point = {"knowledge_point_id": "html", "text": "HTML 表单与网页结构"}
    result = evaluate([{"name": "HTML5基础", "plan": "表单元素;;;" + structure}], point=point)
    assert result["status"] == "outline_supported" and result["display_eligible"]
    assert [row["index"] for row in result["matched_chapters"]] == [1, 2]
    assert [row["title"] for row in result["matched_chapters"]] == ["表单元素", structure]
    incomplete = evaluate([{"name": "HTML5基础", "plan": structure}], point=point)
    assert incomplete["status"] == "outline_partial" and not incomplete["display_eligible"]
    assert [row["status"] for row in incomplete["subtopics"]] == ["not_observed", "supported"]


@pytest.mark.parametrize("structure", [
    "CSS文件结构", "CSS文件的基本结构", "JavaScript对象结构", "JS对象结构",
    "项目目录结构", "HTML网站布局", "HTML网站目录结构", "HTML文件目录结构",
])
def test_other_structures_never_become_html_document_structure(structure):
    point = {"knowledge_point_id": "html", "text": "HTML 表单与网页结构"}
    result = evaluate([{"name": "HTML5基础", "plan": "表单元素;;;" + structure}], point=point)
    assert result["status"] == "outline_partial" and not result["display_eligible"]
    assert [row["status"] for row in result["subtopics"]] == ["supported", "not_observed"]


@pytest.mark.parametrize("text,parent,children", [
    ("pandas 数据分组与聚合", "Pandas 数据分析", ["数据分组", "聚合"]),
    ("SQL 多表连接与分组查询", "SQL 数据查询", ["两个表连接", "GROUP BY"]),
    ("HTML 表单与网页结构", "HTML5基础", ["表单元素", "文档的基本结构"]),
])
def test_verified_same_dto_parent_can_supply_only_its_technical_owner(text, parent, children):
    point = {"knowledge_point_id": "selected", "text": text}
    resource, evidence = observed([{"name": parent, "plan": ";;;".join(children)}], point=point)
    original = deepcopy((point, resource, evidence))
    assert "outline_parent_index" not in resource["chapters"][0]
    assert [row["outline_parent_index"] for row in resource["chapters"][1:]] == [0, 0]
    result = assess_mooc_relevance(point, resource, evidence)
    assert result["display_eligible"] and result["status"] == "outline_supported"
    assert [row["title"] for row in result["matched_chapters"]] == children
    parent_id = resource["chapters"][0]["evidence_id"]
    for matched in result["matched_chapters"]:
        assert matched["context_evidence_ids"] == [parent_id]
        raw = next(row["text"] for row in evidence if row["evidence_id"] == matched["evidence_id"])
        assert matched["source_text_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert parent_id in result["evidence_ids"]
    assert (point, resource, evidence) == original


@pytest.mark.parametrize("rows,outline", [
    ([{"name": "数据分析", "goals": "使用pandas", "plan": "数据分组;;;聚合"}], ""),
    ([{"name": "pandas介绍"}, {"name": "数据分析", "plan": "数据分组;;;聚合"}], ""),
    ([], "<p>pandas介绍</p><p>数据分组</p><p>聚合</p>"),
    ([{"name": "pandas 与 NumPy", "plan": "数据分组;;;聚合"}], ""),
    ([{"name": "先修知识：pandas", "plan": "数据分组;;;聚合"}], ""),
    ([{"name": "本章不讲pandas", "plan": "数据分组;;;聚合"}], ""),
    ([{"name": "pandas 拓展阅读", "plan": "数据分组;;;聚合"}], ""),
])
def test_goals_neighbors_legacy_paragraphs_and_ambiguous_or_nonteaching_parents_cannot_donate(rows, outline):
    result = evaluate(rows, outline=outline)
    assert result["status"] == "outline_no_match" and not result["display_eligible"]
    assert result["matched_chapters"] == []


def test_parent_donation_does_not_fill_a_missing_selected_child_or_conflicting_child():
    for plan in ("数据分组;;;文件读取", "数据分组;;;NumPy 聚合"):
        result = evaluate([{"name": "pandas", "plan": plan}])
        assert result["status"] == "outline_partial" and not result["display_eligible"]
        assert [row["status"] for row in result["subtopics"]] == ["supported", "not_observed"]


def rebind_chapter(resource, evidence, index):
    """Rehash synthetic facts to test topology independently of text tampering."""
    chapter = resource["chapters"][index]
    row = next(row for row in evidence if row["evidence_id"] == chapter["evidence_id"])
    facts = {key: value for key, value in chapter.items() if key not in {"evidence_id", "source"}}
    row["text"] = json.dumps(facts, ensure_ascii=False)
    row["evidence_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    row["id"] = "ev_" + hashlib.sha256(f"{URL}|chapters.{index}|{row['source']}|{row['text']}".encode()).hexdigest()[:20]
    chapter["evidence_id"] = row["evidence_id"] = row["id"]
    aggregate = next(item for item in evidence if item.get("field") == "chapters")
    aggregate["text"] = str(resource["chapters"])
    aggregate["id"] = "ev_" + hashlib.sha256(f"{URL}|chapters|{aggregate['source']}|{aggregate['text']}".encode()).hexdigest()[:20]
    aggregate["evidence_id"] = aggregate["id"]
    resource["field_provenance"]["chapters"]["evidence_id"] = aggregate["id"]


@pytest.mark.parametrize("damage", [
    "future_parent", "parent_is_child", "wrong_record", "foreign_url", "foreign_source",
    "changed_parent_title", "changed_child_binding", "parent_hash", "aggregate_hash",
])
def test_parent_context_requires_original_same_page_catalog_binding(damage):
    resource, evidence = observed([
        {"name": "pandas", "plan": "数据分组;;;聚合"},
        {"name": "pandas", "plan": "其他内容"},
    ])
    parent = resource["chapters"][0]
    parent_evidence = next(row for row in evidence if row["evidence_id"] == parent["evidence_id"])
    if damage in {"future_parent", "parent_is_child", "wrong_record"}:
        index, target = {"future_parent": (1, 3), "parent_is_child": (2, 1), "wrong_record": (4, 0)}[damage]
        resource["chapters"][index]["outline_parent_index"] = target
        rebind_chapter(resource, evidence, index)
    elif damage == "foreign_url":
        parent_evidence["url"] = URL.replace("123", "999")
    elif damage == "foreign_source":
        parent_evidence["source"] = "html.icourse163.course_outline.text"
    elif damage == "changed_parent_title":
        parent["title"] = "pandas 修改的父章节"
    elif damage == "changed_child_binding":
        resource["chapters"][2]["outline_parent_index"] = 1
    elif damage == "parent_hash":
        parent_evidence["evidence_sha256"] = "0" * 64
    elif damage == "aggregate_hash":
        next(row for row in evidence if row.get("field") == "chapters")["id"] = "ev_changed"
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert not result["display_eligible"] and result["matched_chapters"] == []
    assert all(row["status"] == "unknown" for row in result["subtopics"])


@pytest.mark.parametrize("snippet", [
    "课程概述：系统讲解Pandas数据分析工具。",
    "课程概述：系统讲解数据管理模块pandas. 第五节为数据展示。",
])
def test_explicit_search_teaching_owner_without_children_allows_only_low_priority_probe(snippet):
    resource, evidence = observed([], title="Python程序设计与应用", snippet=snippet)
    resource.update(fetch_status="not_fetched", metadata_evidence_level="search", chapters=[])
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert result["status"] == "search_candidate" and result["probe_eligible"]
    assert 0 < result["probe_priority"] < 20
    assert not result["display_eligible"] and result["matched_chapters"] == []
    assert all(row["status"] == "unknown" for row in result["subtopics"])
    assert "search_only_never_coverage" in result["reason_codes"]


@pytest.mark.parametrize("snippet", [
    "先修知识：掌握pandas数据分析工具。", "本课程不讲解Pandas。",
    "拓展阅读：系统讲解Pandas数据分析工具。", "系统讲解pandas.DataFrame数据结构。",
])
def test_search_probe_extension_rejects_prerequisites_negation_reading_and_identifier_prefix(snippet):
    resource, evidence = observed([], title="程序设计基础", snippet=snippet)
    resource.update(fetch_status="not_fetched", metadata_evidence_level="search", chapters=[])
    result = assess_mooc_relevance(POINT, resource, evidence)
    assert not result["probe_eligible"] and not result["display_eligible"]


def test_search_period_normalization_does_not_change_outline_technical_identifiers():
    result = evaluate([{"name": "pandas.", "plan": "数据分组;;;聚合"}],
                      snippet="系统讲解pandas. 数据分组与聚合课程。")
    assert result["status"] == "outline_no_match" and not result["display_eligible"]
    assert not result["probe_eligible"]
