"""Generic evidence-status and complementary coverage fixtures; no network."""
from copy import deepcopy

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Resource, SearchRequest
from backend.app.ranking import decompose_topic, rank_resource, summarize_collection_coverage, tokens
from backend.app.service import JobService


STAMP = "2026-10-14T00:00:00+00:00"
COMPOUND = "JavaScript Promise 并发与错误处理"


def searched(title, snippet="", *, rid="r", point_id="p", platform="other"):
    url = f"https://example.org/lessons/{rid}"
    evidence = {"evidence_id": "search-" + rid, "kind": "search", "source": "fixture",
        "knowledge_point_id": point_id, "url": url, "title": title, "snippet": snippet,
        "resource_type_hint": "video", "type_source": "search_template"}
    provenance = {"source": "search_template", "evidence_id": evidence["evidence_id"]}
    resource = Resource(resource_id=rid, title=title, url=url, canonical_url=url, discovered_at=STAMP,
        resource_type="video", platform=platform, video_evidence_status="search_discovered",
        field_provenance={"title": {"source": "search", "evidence_id": evidence["evidence_id"]},
            "description": {"source": "search", "evidence_id": evidence["evidence_id"]},
            "resource_type": provenance, "video_evidence_status": provenance}).model_dump()
    return resource, [evidence]


def assess(topic, title, snippet="", **kwargs):
    resource, evidence = searched(title, snippet, **kwargs)
    before = deepcopy((resource, evidence))
    match = rank_resource({"knowledge_point_id": "p", "text": topic}, resource, evidence,
                          SearchRequest(knowledge_points=[topic]))
    assert (resource, evidence) == before
    return match


@pytest.mark.parametrize("topic,title,snippet,code", [
    ("CSS Flexbox 对齐", "CSS子网格：完美对齐", "我们将对比传统Flexbox和嵌套Grid方案，手把手教你使用子网格实现完美对齐。", "comparison_mention_only"),
    ("JavaScript closures", "JavaScript 匿名函数求和", "匿名函数也称闭包函数(closures)，允许创建没有名称的函数。", "definition_alias_unconfirmed"),
    ("GIS 坐标系", "预约今晚直播 GIS 坐标系讲解", "GIS坐标系专题直播，快来预约。", "scheduled_teaching_unconfirmed"),
    ("quaternion rotations", "3D数学 quaternion课程", "matrix to quaternion: https://math.example.org/rotations/conversions", "external_link_terms_only"),
])
def test_weak_support_is_retained_with_specific_reason(topic, title, snippet, code):
    match = assess(topic, title, snippet)
    assert match and match["topic_evidence_status"] == "needs_review"
    assert code in {row["code"] for row in match["topic_evidence_reasons"]}
    assert all(row["evidence_ids"] == ["search-r"] for row in match["topic_evidence_reasons"])
    assert match["supporting_evidence_ids"] == []


@pytest.mark.parametrize("topic,title,snippet", [
    ("CSS Flexbox 对齐", "CSS Flexbox 与 Grid 对齐比较教学", "对比两种方案并演示对齐代码。"),
    ("CSS Flexbox 对齐", "CSS Flexbox 对齐实战", "使用Flexbox实现对齐，对比其他Grid方案。"),
    ("CSS Flexbox 对齐", "CSS布局方案比较教学", "演示并比较 CSS Flexbox 对齐和 Grid 对齐的代码实现。"),
    ("JavaScript closures", "JavaScript 闭包 closures 教程", "匿名函数只是写法；演示变量捕获与词法作用域。"),
    ("JavaScript closures", "JavaScript 匿名函数使用", "也称闭包函数(closures)，本课实际演示捕获外部变量和词法作用域。"),
    ("GIS 坐标系", "GIS 坐标系直播回放", "原预约直播现已提供完整回放。"),
    ("GIS 坐标系", "GIS 坐标系直播教学", "讲解坐标系统与投影。"),
    ("quaternion rotations", "Quaternion rotations explained", "References: https://math.example.org/rotations"),
    ("quaternion rotations", "Cinema 4D Quaternion rotations", "A practical animation example."),
])
def test_comparison_replay_and_applications_remain_supported(topic, title, snippet):
    match = assess(topic, title, snippet)
    assert match and match["topic_evidence_status"] == "supported"
    assert match["supporting_evidence_ids"] == ["search-r"]


@pytest.mark.parametrize("status", ["not_fetched", "site_policy_blocked", "timeout", "robots_unavailable"])
def test_page_or_playback_unknown_is_not_topic_uncertainty(status):
    resource, evidence = searched("Python lists tutorial")
    resource.update(fetch_status=status, playback_verified=False)
    match = rank_resource({"knowledge_point_id": "p", "text": "Python lists"}, resource, evidence, SearchRequest(knowledge_points=["Python lists"]))
    assert match["topic_evidence_status"] == "supported"


def test_independent_direct_observation_can_resolve_weak_search_but_not_other_point():
    resource, evidence = searched("JavaScript 匿名函数案例", "匿名函数也称闭包函数(closures)。")
    strong = dict(evidence[0], evidence_id="direct", title="JavaScript closures tutorial", snippet="Lexical scope and variable capture.")
    point = {"knowledge_point_id": "p", "text": "JavaScript closures"}
    request = SearchRequest(knowledge_points=[point["text"]])
    match = rank_resource(point, resource, [*evidence, strong], request)
    assert match["topic_evidence_status"] == "supported" and match["supporting_evidence_ids"] == ["direct"]
    match = rank_resource(point, resource, [*evidence, dict(strong, knowledge_point_id="other")], request)
    assert match["topic_evidence_status"] == "needs_review"


def test_explicit_compound_plan_does_not_invent_ambiguous_topics():
    plan = decompose_topic(COMPOUND)
    assert plan["shared_context"] == ["JavaScript", "Promise"]
    assert [part["text"] for part in plan["subtopics"]] == ["并发", "错误处理"]
    assert decompose_topic("Python lists and dictionaries")["decomposition_status"] == "applied"
    assert decompose_topic("trees and forests")["decomposition_status"] == "unknown"
    assert decompose_topic("与门电路")["subtopics"] == []


@pytest.mark.parametrize("title,status,coverage", [
    ("JavaScript Promise 并发与异常处理教程", "supported", ["supported", "supported"]),
    ("Node.js Promise.all方法执行并发操作", "partial", ["supported", "unknown"]),
    ("Promise.all异常处理教程", "partial", ["unknown", "supported"]),
    ("JavaScript Promise error handling tutorial", "partial", ["unknown", "supported"]),
    ("Promise.all教程", None, None),
    ("JavaScript Promise基础教程", None, None),
    ("JavaScript错误处理教程", None, None),
    ("Java Promise 并发与错误处理教程", None, None),
    ("Python Promise 并发与错误处理教程", None, None),
    ("Java Promise.all 并发与错误处理教程", None, None),
    ("Python Promise.all 并发与错误处理教程", None, None),
    ("Promise.allFake 并发与错误处理教程", None, None),
    ("普通课程，相关视频：JavaScript Promise 并发与错误处理", None, None),
])
def test_each_part_requires_its_own_context_and_explicit_instruction(title, status, coverage):
    match = assess(COMPOUND, title)
    if status is None:
        assert match is None
    else:
        assert match["topic_evidence_status"] == status
        assert [row["status"] for row in match["subtopic_coverage"]] == coverage


def test_error_word_does_not_mean_error_handling_and_prerequisite_does_not_support():
    assert assess(COMPOUND, "JavaScript Promise教程", "你正在以错误的方式使用 Promise。") is None
    assert assess(COMPOUND, "JavaScript Promise课程", "先修要求：JavaScript Promise 并发与错误处理。") is None
    assert "java" not in tokens("JavaScript") and "sql" not in tokens("NoSQL")
    assert tokens("D3.js C++ C#") == {"d3.js", "c++", "c#"}


def item(topic, title, *, rid, platform="other"):
    resource, evidence = searched(title, rid=rid, platform=platform)
    match = rank_resource({"knowledge_point_id": "p", "text": topic}, resource, evidence, SearchRequest(knowledge_points=[topic]))
    return {"resource": resource, "match": match, "evidence": evidence}


def test_collection_is_deduplicated_attributed_and_never_a_single_full_resource():
    concurrent = item(COMPOUND, "Promise.all 并发教程", rid="concurrent")
    errors = item(COMPOUND, "JavaScript Promise 异常处理教程", rid="errors")
    summary = summarize_collection_coverage(COMPOUND, [concurrent, concurrent, errors])
    assert summary["status"] == "all_subtopics_supported"
    assert not summary["single_resource_full_coverage"]
    assert summary["subtopics"][0]["resource_ids"] == ["concurrent"]
    assert summary["subtopics"][1]["resource_ids"] == ["errors"]
    assert summarize_collection_coverage(COMPOUND, [concurrent])["status"] == "some_subtopics_supported"
    tampered = deepcopy(errors)
    tampered["match"]["subtopic_coverage"][1]["evidence_ids"] = ["missing"]
    assert summarize_collection_coverage(COMPOUND, [concurrent, tampered])["status"] == "some_subtopics_supported"
    tampered["match"]["topic_evidence_status"] = "supported"
    assert not summarize_collection_coverage(COMPOUND, [concurrent, tampered])["single_resource_full_coverage"]


def test_subtopics_cannot_borrow_context_between_observations():
    resource, evidence = searched("JavaScript Promise 并发教程")
    evidence.append(dict(evidence[0], evidence_id="other", title="JavaScript 错误处理教程", snippet=""))
    match = rank_resource({"knowledge_point_id": "p", "text": COMPOUND}, resource, evidence, SearchRequest(knowledge_points=[COMPOUND]))
    assert match["topic_evidence_status"] == "partial"
    assert [row["status"] for row in match["subtopic_coverage"]] == ["supported", "unknown"]
    assert match["supporting_evidence_ids"] == ["search-r"]


def test_full_resource_coverage_and_alias_rules_are_explicit():
    whole = item(COMPOUND, "Promise.all 并发与异常处理教程", rid="whole")
    assert whole["match"]["topic_evidence_status"] == "supported"
    assert set(whole["match"]["topic_match_rules"]) >= {"standard_javascript_promise_api_context", "error_exception_handling_terms"}
    assert summarize_collection_coverage(COMPOUND, [whole])["single_resource_full_coverage"]


def test_separate_observations_of_one_resource_are_not_one_complete_observation():
    resource, evidence = searched("JavaScript Promise 并发教程")
    evidence.append(dict(evidence[0], evidence_id="errors", title="JavaScript Promise 异常处理教程"))
    match = rank_resource({"knowledge_point_id": "p", "text": COMPOUND}, resource, evidence, SearchRequest(knowledge_points=[COMPOUND]))
    assert match["topic_evidence_status"] == "partial"
    assert match["topic_evidence_reasons"][0]["code"] == "fragmented_compound_evidence"
    summary = summarize_collection_coverage(COMPOUND, [{"resource": resource, "match": match, "evidence": evidence}])
    assert summary["status"] == "all_subtopics_supported" and not summary["single_resource_full_coverage"]


def stored_service(topic, *, limit=3):
    store = Store(":memory:")
    service = JobService(Settings(max_results_per_point=limit), store)
    job = {"job_id": "job", "status": "completed", "request": SearchRequest(knowledge_points=[topic]).model_dump(),
           "knowledge_points": [{"knowledge_point_id": "p", "text": topic}], "warnings": []}
    store.create_job(job)
    return service


def save_item(service, entry):
    service.store.save_resource("job", entry["resource"])
    for evidence in entry["evidence"]:
        service.store.add_evidence("job", entry["resource"]["resource_id"], "p", evidence)
    if entry.get("match"):
        service.store.save_match("job", entry["match"])


def test_results_recompute_status_consistently_without_mutating_legacy_data():
    service = stored_service("GIS 坐标系")
    entry = item("GIS 坐标系", "预约今晚直播 GIS 坐标系讲解", rid="scheduled", platform="bilibili")
    legacy = deepcopy(entry); legacy["match"].pop("topic_evidence_status")
    save_item(service, legacy)
    before = list(service.store.connection.iterdump())
    group = service.results("job")["groups"][0]
    assert group["items"] == [] and group["platform_items"] == {}
    assert group["review_items"][0]["match"]["topic_evidence_status"] == "needs_review"
    assert group["review_platform_items"]["bilibili"] == group["review_items"]
    assert before == list(service.store.connection.iterdump())
    service.store.close()


def test_results_recover_old_partial_candidates_and_count_only_displayed_collection():
    service = stored_service(COMPOUND, limit=1)
    first = item(COMPOUND, "JavaScript Promise 并发教程", rid="aaa", platform="bilibili")
    second = item(COMPOUND, "JavaScript Promise 异常处理教程", rid="bbb", platform="other")
    # Previous versions rejected both compounds, so no persisted match exists.
    for entry in (first, second):
        entry["match"] = None
        save_item(service, entry)
    group = service.results("job")["groups"][0]
    assert group["items"] == [] and len(group["partial_items"]) == 1
    assert group["section_limit"] == 1 and group["total_partial_matches"] == 2
    assert group["collection_coverage"]["status"] == "some_subtopics_supported"
    assert all(summary["status"] == "some_subtopics_supported" for summary in group["platform_collection_coverage"].values())
    assert set(group["partial_platform_items"]) == {"bilibili", "other"}
    service.store.close()


@pytest.mark.parametrize("prerequisite", ["先修要求：错误处理。", "需要预先掌握异常处理。", "Prerequisites: error handling.", "No prerequisites: error handling."])
def test_compound_subtopic_prerequisite_never_becomes_instruction(prerequisite):
    match = assess(COMPOUND, "JavaScript Promise 并发教程", prerequisite)
    assert match["topic_evidence_status"] == "partial"
    assert [part["status"] for part in match["subtopic_coverage"]] == ["supported", "unknown"]
    assert "先修" in match["subtopic_coverage"][1]["reason"]


def test_compound_cannot_borrow_technical_context_from_prerequisite():
    assert assess(COMPOUND, "并发与错误处理教程", "先修要求：JavaScript Promise。") is None


@pytest.mark.parametrize("title,snippet", [
    ("JavaScript Promise 并发与错误处理教程", "无需先修要求。"),
    ("JavaScript Promise 教程", "本课程讲解并发与异常处理，先修要求：基础算术。"),
    ("JavaScript Promise 教程", "We teach concurrency and error handling, no prerequisites."),
])
def test_explicit_teaching_of_both_subtopics_survives_prerequisite_notes(title, snippet):
    match = assess(COMPOUND, title, snippet)
    assert match["topic_evidence_status"] == "supported"
    assert all(part["status"] == "supported" for part in match["subtopic_coverage"])


def test_full_chinese_subtopic_does_not_require_artificial_cross_word_bigram():
    topic = "Python 文件读写与异常处理"
    match = assess(topic, "Python 文件管理与异常处理", "内容包括：文件的读写、定位与编码处理；异常处理的基本机制。")
    assert match["topic_evidence_status"] == "supported"
    partial = assess(topic, "Python 文件读取与异常处理", "只演示文件读取。")
    assert partial["topic_evidence_status"] == "partial"
    assert partial["subtopic_coverage"][0]["status"] == "unknown"


@pytest.mark.parametrize("title", ["Normalization - 1NF 2NF 3NF and 4NF", "Normalisation and BCNF tutorial"])
def test_standard_normal_forms_establish_database_context_without_reference_url(title):
    for snippet in ("", "https://reference.example.org/database-normalization"):
        match = assess("database normalization" if "Normalization" in title else "database normalisation", title, snippet)
        assert match["topic_evidence_status"] == "supported"
        assert "database_standard_normal_forms_context" in match["topic_match_rules"]
        assert match["supporting_evidence_ids"] == ["search-r"]
    assert assess("database normalization", "Normalization tutorial") is None
    assert assess("database normalization", "UE5 Motion Matching Pose Database Normalization set") is None
