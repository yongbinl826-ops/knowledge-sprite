"""Offline source-binding and scope tests; live recall is a separate acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.mooc_relevance import assess_mooc_relevance, is_mooc_resource

URL = "https://www.icourse163.org/course/OWN-123"
POINT = {"knowledge_point_id": "p", "text": "Python 列表与字典"}


def case(titles=("列表", "字典"), title="Python 程序设计", *, point=None, snippet="Python 列表与字典课程"):
    point = point or POINT
    term = {"id": "456", "outLineDto": {"outLine": "", "outLineStructureDtos": [
        {"name": text, "goals": "", "plan": ""} for text in titles]}}
    markup = ('<div id="j-course-heading-intro"><div class="course-heading-intro_intro">'
              '本课程依据公开的课程介绍和课程目录开展教学。本页提供课程的独立章节列表，供学生核对课程范围。'
              '学生可在课程页面查看各单元的学习安排和课程内容说明。'
              '</div></div>'
              '<div id="j-course-outline"></div><script>window.termDto = ' + json.dumps(term)
              + '; window.courseDto = ' + json.dumps({"id": "123", "name": title}) + ';</script>')
    resource = MetadataExtractor().extract(markup, URL, "offline")
    resource.update(url=URL, canonical_url=URL, resource_id="r", platform="icourse163")
    evidence = resource.pop("evidence")
    evidence.append({"evidence_id": "search", "kind": "search", "url": URL, "knowledge_point_id": point["knowledge_point_id"],
                     "title": title, "snippet": snippet})
    return resource, evidence


def assess(resource, evidence, point=None):
    return assess_mooc_relevance(point or POINT, resource, evidence)


def test_whole_course_scope_can_cover_selected_parts_in_separate_own_chapters():
    resource, evidence = case()
    before = deepcopy((resource, evidence))
    result = assess(resource, evidence)
    assert result["status"] == "outline_supported" and result["display_eligible"]
    assert len(result["matched_chapters"]) == 2 and not result["probe_eligible"]
    assert [row["status"] for row in result["subtopics"]] == ["supported", "supported"]
    assert (resource, evidence) == before
    for chapter in result["matched_chapters"]:
        raw = next(row["text"] for row in evidence if row["evidence_id"] == chapter["evidence_id"])
        assert chapter["source_text_sha256"] == hashlib.sha256(raw.encode()).hexdigest()


def test_partial_and_no_match_are_diagnostics_not_main_recommendations():
    resource, evidence = case(("列表", "函数"))
    result = assess(resource, evidence)
    assert result["status"] == "outline_partial" and not result["display_eligible"]
    assert result["subtopics"][1]["status"] == "not_observed"
    resource, evidence = case(("函数", "网络请求"))
    result = assess(resource, evidence)
    assert result["status"] == "outline_no_match" and not result["probe_eligible"]


@pytest.mark.parametrize("heading", ["函数列表", "参数列表", "课程列表", "API参考列表"])
def test_reference_lists_and_terminology_dictionary_do_not_declare_data_structures(heading):
    resource, evidence = case((heading, "术语字典"))
    result = assess(resource, evidence)
    assert result["status"] == "outline_no_match" and not result["display_eligible"]
    assert all(row["status"] == "not_observed" for row in result["subtopics"])


def test_independent_datatype_mention_survives_reference_list_text():
    resource, evidence = case(("Python列表及其常用函数列表", "Python字典操作与术语字典"))
    assert assess(resource, evidence)["status"] == "outline_supported"


@pytest.mark.parametrize("damage", ["foreign_url", "wrong_index", "foreign_source", "changed_title", "changed_json",
    "invalid_json", "wrong_hash", "wrong_digest", "duplicate_id", "chapter_id_missing", "aggregate_kind",
    "aggregate_url", "aggregate_provenance", "source_url", "stale_resource", "stale_chapter", "stale_aggregate",
    "catalog_limit", "wrong_kind", "unfetched", "resolved_foreign"])
def test_any_catalog_tampering_or_incomplete_acquisition_cannot_claim_scope(damage):
    resource, evidence = case()
    chapter = resource["chapters"][0]
    row = next(row for row in evidence if row["evidence_id"] == chapter["evidence_id"])
    aggregate = next(row for row in evidence if row.get("field") == "chapters")
    if damage == "foreign_url": row["url"] = URL.replace("123", "999")
    elif damage == "wrong_index": row["field"] = "chapters.1"
    elif damage == "foreign_source": row["source"] = "html.other_outline"
    elif damage == "changed_title": chapter["title"] = "列表和字典"
    elif damage == "changed_json": row["text"] = row["text"].replace("列表", "列表和字典")
    elif damage == "invalid_json": row["text"] = "{} invalid"
    elif damage == "wrong_hash": row["id"] = "ev_wrong"
    elif damage == "wrong_digest": row["evidence_sha256"] = "0" * 64
    elif damage == "duplicate_id": evidence.append(dict(row))
    elif damage == "chapter_id_missing": chapter["evidence_id"] = "missing"
    elif damage == "aggregate_kind": aggregate["kind"] = "search"
    elif damage == "aggregate_url": aggregate["url"] = URL.replace("123", "999")
    elif damage == "aggregate_provenance": resource["field_provenance"]["chapters"]["source"] = "other"
    elif damage == "source_url": chapter["source_url"] = URL.replace("123", "999")
    elif damage == "stale_resource": resource["cache"] = {"stale": True}
    elif damage == "stale_chapter": row["cache"] = {"stale": True}
    elif damage == "stale_aggregate": aggregate["cache"] = {"stale": True}
    elif damage == "catalog_limit": resource["catalog_fetch_status"] = "catalog_limit_exceeded"
    elif damage == "wrong_kind": resource["catalog_kind"] = "video_playlist"
    elif damage == "unfetched": resource["fetch_status"] = "blocked"
    elif damage == "resolved_foreign": resource["resolved_url"] = URL.replace("123", "999")
    result = assess(resource, evidence)
    assert not result["display_eligible"] and not result["matched_chapters"]
    assert all(row["status"] == "unknown" for row in result["subtopics"])


@pytest.mark.parametrize("title", ["先修知识：Python 列表与字典", "不讲 Python 列表与字典", "未来课程 Python 列表与字典", "Python 列表与字典 拓展阅读"])
def test_prerequisites_negation_future_and_reading_are_not_teaching(title):
    resource, evidence = case((title,))
    assert assess(resource, evidence)["status"] == "outline_no_match"


@pytest.mark.parametrize("title", ["本章不包括Python列表与字典", "本章不含Python列表与字典", "本章不涵盖Python列表与字典",
    "Python excluding lists and dictionaries"])
def test_explicit_exclusion_is_not_positive_outline_coverage(title):
    resource, evidence = case((title,))
    assert assess(resource, evidence)["status"] == "outline_no_match"


def test_exception_handling_heading_is_a_positive_skill_not_an_exclusion():
    p = {"knowledge_point_id": "p", "text": "Python 异常处理"}
    resource, evidence = case(("Python异常处理",), point=p)
    assert assess(resource, evidence, p)["status"] == "outline_supported"


@pytest.mark.parametrize("point,title,chapter", [("Java 列表", "JavaScript 程序设计", "列表"),
    ("SQL JOIN", "NoSQL 数据库", "JOIN"), ("pandas 数据分组", "Python 数据处理", "数据分组"),
    ("Python 列表", "Python 和 Java 程序设计", "列表"),
    ("C 指针", "C++ 程序设计", "指针"),
    ("SQL JOIN", "SQLAlchemy 程序设计", "JOIN")])
def test_foreign_or_ambiguous_technology_cannot_donate_context(point, title, chapter):
    p = {"knowledge_point_id": "p", "text": point}
    resource, evidence = case((chapter,), title, point=p)
    assert assess(resource, evidence, p)["status"] == "outline_no_match"


def test_sibling_pandas_heading_does_not_donate_context_to_later_unowned_action():
    p = {"knowledge_point_id": "p", "text": "pandas 数据分组与聚合"}
    resource, evidence = case(("pandas 介绍", "NumPy数组", "数据分组与聚合"), "Python 数据处理", point=p)
    assert assess(resource, evidence, p)["status"] == "outline_no_match"
    resource, evidence = case(("pandas 数据分组与聚合",), "Python 数据处理", point=p)
    assert assess(resource, evidence, p)["status"] == "outline_supported"


def test_parent_search_title_or_tampered_page_title_cannot_supply_context():
    resource, evidence = case()
    origin = resource["field_provenance"]["title"]
    origin["source"] = "search"
    assert assess(resource, evidence)["status"] == "outline_no_match"


def test_tampering_both_parent_title_and_evidence_fails_original_hash():
    resource, evidence = case(title="Java程序设计")
    origin = resource["field_provenance"]["title"]
    row = next(row for row in evidence if row["evidence_id"] == origin["evidence_id"])
    resource["title"] = row["text"] = "Python程序设计"
    assert assess(resource, evidence)["status"] == "outline_no_match"


def test_search_only_admits_probe_never_coverage():
    resource, evidence = case()
    resource.update(fetch_status="not_fetched", metadata_evidence_level="search", chapters=[])
    result = assess(resource, evidence)
    assert result["status"] == "search_candidate" and result["probe_eligible"]
    assert not result["display_eligible"] and not result["evidence_ids"]


def test_a_broad_course_title_can_be_probed_from_own_specific_snippet():
    p = {"knowledge_point_id": "p", "text": "Flask Web开发"}
    resource, evidence = case(title="Python程序设计", snippet="本课程讲授 Flask Web开发。", point=p)
    resource.update(fetch_status="not_fetched", chapters=[])
    assert assess(resource, evidence, p)["probe_eligible"]


@pytest.mark.parametrize("status", ["fetched", "success"])
def test_explicit_successful_catalog_status_is_accepted(status):
    resource, evidence = case()
    resource["catalog_fetch_status"] = status
    assert assess(resource, evidence)["status"] == "outline_supported"


def test_uuid_remapping_keeps_verified_original_catalog_hash():
    resource, evidence = case()
    mapping = {row["evidence_id"]: f"uuid-{i}" for i, row in enumerate(evidence)}
    for row in evidence:
        row["evidence_id"] = mapping[row["evidence_id"]]
    for chapter in resource["chapters"]:
        chapter["evidence_id"] = mapping[chapter["evidence_id"]]
    for origin in resource["field_provenance"].values():
        origin["evidence_id"] = mapping[origin["evidence_id"]]
    assert assess(resource, evidence)["display_eligible"]


@pytest.mark.parametrize("point,title,snippet", [
    ("SQL JOIN 查询", "高等数学", "数学课程"), ("HTML CSS", "结构力学", "建筑工程"),
    ("ESP32 MQTT", "物联网技术", "物联网通信基础"),
    ("Python 列表与字典", "Python数据分析与展示", "先修知识：Python列表、字典，需要预先掌握"),
    ("Python 列表与字典", "Python 程序设计", "本课程不讲 Python 列表与字典"),
    ("Python 列表与字典", "MOOC进校园", "Python列表与字典"),
    ("Java 列表", "JavaScript 课程", "JavaScript 列表"),
    ("SQL JOIN", "NoSQL 课程", "NoSQL JOIN"),
    ("Python 列表与字典", "结构力学", "相关推荐：Python列表与字典"),
    ("数据", "数据科学", "数据课程"),
])
def test_irrelevant_promotional_prior_only_and_generic_search_leads_are_filtered(point, title, snippet):
    p = {"knowledge_point_id": "p", "text": point}
    resource, evidence = case(title=title, snippet=snippet, point=p)
    resource.update(fetch_status="not_fetched", chapters=[])
    result = assess(resource, evidence, p)
    assert result["status"] == "rejected" and not result["probe_eligible"]


@pytest.mark.parametrize("url", [URL.replace("/course/", "/learn/"), URL + "?unknown=x", URL + "#learn",
    URL.replace("www.icourse163.org", "other.example.org"), URL.replace("https:", "http:")])
def test_unsupported_routes_are_not_rewritten_or_probed(url):
    resource, evidence = case()
    resource.update(url=url, canonical_url=url, fetch_status="not_fetched", chapters=[])
    evidence[-1]["url"] = url
    result = assess(resource, evidence)
    assert result["status"] == "rejected" and not result["probe_eligible"]


@pytest.mark.parametrize("url", [URL + "?outVendor=search", URL.replace("OWN-", "OTHER-"),
    "https://www.icourse163.org/course/detail.htm?cid=123"])
def test_native_alias_admits_own_probe_but_never_borrows_base_url_outline(url):
    resource, evidence = case()
    resource.update(url=url, canonical_url=url)
    evidence[-1]["url"] = url
    # The base URL's valid catalog is not the alias URL's observed catalog.
    result = assess(resource, evidence)
    assert not result["display_eligible"] and not result["matched_chapters"]
    resource.update(fetch_status="not_fetched", chapters=[], metadata_evidence_level="search")
    result = assess(resource, evidence)
    assert result["probe_eligible"] and result["status"] == "search_candidate"
    assert not result["display_eligible"]
    assert resource["url"] == resource["canonical_url"] == url


def test_query_or_foreign_point_cannot_create_search_relevance():
    resource, evidence = case(title="高等数学", snippet="数学")
    resource.update(fetch_status="not_fetched", chapters=[])
    evidence[-1]["query"] = "Python 列表与字典"
    assert assess(resource, evidence)["status"] == "rejected"
    resource, evidence = case()
    evidence[-1]["knowledge_point_id"] = "another"
    assert assess(resource, evidence)["status"] == "rejected"


def test_host_classification_is_independent_of_platform_label():
    assert is_mooc_resource({"url": URL, "platform": "bilibili"})
    assert not is_mooc_resource({"url": "https://www.bilibili.com/video/BV1", "platform": "icourse163"})
    assert not is_mooc_resource({"url": "https://www.icourse163.org.attacker.example/course/OWN-123"})
    assert not is_mooc_resource({"url": "https://evilicourse163.org/course/OWN-123"})


def test_mooc_subdomain_enters_strict_gate_but_cannot_be_probed():
    resource, evidence = case()
    url = "https://kaoyan.icourse163.org/course/terms/123.htm?courseId=456"
    resource.update(url=url, canonical_url=url, platform="icourse163")
    assert is_mooc_resource(resource)
    assert assess(resource, evidence)["status"] == "rejected"


def test_real_retained_outline_requires_selected_topics_not_course_title_overlap():
    fixtures = Path(__file__).parent / "fixtures/mooc_structure"
    expected = json.loads((fixtures / "03-expected.json").read_text("utf-8"))
    resource = MetadataExtractor().extract((fixtures / "03-own-outline.html").read_text("utf-8"), expected["url"], "offline")
    resource.update(url=expected["url"], canonical_url=expected["url"], platform="icourse163")
    evidence = resource.pop("evidence")
    evidence.append({"evidence_id": "search", "kind": "search", "url": expected["url"], "knowledge_point_id": "p", "title": "Python数据处理"})
    assert len(resource["chapters"]) == 43
    p = {"knowledge_point_id": "p", "text": "pandas 数据分组与聚合"}
    result = assess(resource, evidence, p)
    assert result["status"] == "outline_supported"
    assert any(row["title"] == "项目6 使用pandas进行数据分组与聚合" for row in result["matched_chapters"])
    assert assess(resource, evidence)["status"] == "outline_no_match"
    p["text"] = "pandas 分组聚合与图表绘制"
    assert assess(resource, evidence, p)["status"] == "outline_partial"


def test_confirmed_selected_target_is_additional_obligation():
    resource, evidence = case()
    result = assess(resource, evidence, {**POINT, "learning_targets": ["集合"]})
    assert result["status"] == "outline_partial" and not result["display_eligible"]
    assert result["subtopics"][-1]["text"] == "集合"
