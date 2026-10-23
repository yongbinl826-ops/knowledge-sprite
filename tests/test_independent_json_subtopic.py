"""Actual own JS JSON material: partial only, relative portable receipt."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from backend.app import ranking
from backend.app.models import SearchRequest


def data():
    return json.loads((Path(__file__).parent / "fixtures/independent_json_subtopic.json").read_text(encoding="utf-8"))


def rank(d):
    return ranking.rank_resource(d["point"], d["resource"], d["evidence"],
        SearchRequest.model_validate(d["request"]), eligibility_evidence=d["evidence"])


def set_field(d, field, text):
    d["resource"][field] = text
    eid = d["resource"]["field_provenance"][field]["evidence_id"]
    next(row for row in d["evidence"] if row["evidence_id"] == eid)["text"] = text


def test_actual_JS_JSON_is_only_independent_partial_never_IO_or_full():
    d = data(); before = deepcopy(d)
    match = rank(d)
    assert match and match["topic_evidence_status"] == "partial"
    parts = {p["text"]: p for p in match["subtopic_coverage"]}
    assert parts["读写"]["status"] == "unknown"
    assert parts["JSON序列化"]["status"] == "supported"
    assert "JavaScript" in parts["JSON序列化"]["reason"]
    assert all(next(e for e in d["evidence"] if e["evidence_id"] == eid)["kind"] in {"page", "catalog"}
               for eid in match["supporting_evidence_ids"])
    assert "高级" in match["recommendation_reason"]
    assert "与当前学习阶段相符" not in match["recommendation_reason"]
    summary = ranking.summarize_collection_coverage(d["point"]["text"], [
        {"resource": d["resource"], "match": match, "evidence": d["evidence"]}])
    assert summary["status"] == "some_subtopics_supported"
    assert not summary["single_resource_full_coverage"]
    assert d == before


@pytest.mark.parametrize("title", [
    "JavaScript JSON.parse解析", "JavaScript JSON介绍", "JSON序列化", "Python JSON序列化",
    "Java JSON序列化", "JavaScript wrong.JSON序列化", "JavaScript API列表 JSON序列化",
    "JavaScript 函数清单 JSON序列化", "JavaScript 参考资料 JSON序列化",
    "JavaScript JSON序列化 isn't covered", "JavaScript JSON序列化将于明天讲解",
    "其他课程讲解JavaScript JSON序列化", "先修要求：JavaScript JSON序列化",
    "JavaScript JSON序列化是先修要求", "JavaScript JSON序列化，仅作参考",
])
def test_missing_owner_wrong_owner_scope_list_and_nonserialization_do_not_gain_support(title):
    d = data()
    # Isolate the mutated scalar fact. The retained original catalog really
    # teaches JSON serialization and cannot be silently treated as a negative.
    d["resource"]["chapters"] = []
    set_field(d, "title", title)
    set_field(d, "description", "本期课程资料。")
    match = rank(d)
    assert not match or not any(p["text"] == "JSON序列化" and p["status"] == "supported"
                                for p in match["subtopic_coverage"])


@pytest.mark.parametrize("description", [
    "本课不讲JSON序列化。", "JSON序列化 is not covered。", "先修要求：JSON序列化。",
    "JSON序列化将于明天讲解。", "JSON序列化仅供参考资料。",
])
def test_own_scalar_exclusion_cannot_be_rescued_by_title_or_catalog(description):
    d = data(); set_field(d, "description", description)
    match = rank(d)
    assert not match or not any(p["text"] == "JSON序列化" and p["status"] == "supported"
                                for p in match["subtopic_coverage"])


@pytest.mark.parametrize("mutation", ["origin_url", "row_url", "row_text", "row_source", "search_source"])
def test_broken_own_title_binding_cannot_supply_independent_JSON(mutation):
    d = data(); origin = d["resource"]["field_provenance"]["title"]
    row = next(e for e in d["evidence"] if e["evidence_id"] == origin["evidence_id"])
    if mutation == "origin_url": origin["url"] = "https://www.bilibili.com/video/BV1OtherPage/"
    elif mutation == "row_url": row["url"] = "https://www.bilibili.com/video/BV1OtherPage/"
    elif mutation == "row_text": row["text"] = "另一页"
    elif mutation == "row_source": row["source"] = "foreign.source"
    else: origin["source"] = "search"
    assert rank(d) is None


def test_search_JS_owner_does_not_rescue_own_context_free_JSON():
    d = data(); set_field(d, "title", "JSON序列化"); set_field(d, "description", "本期课程资料。")
    d["evidence"].append({"evidence_id": "search-owner", "kind": "search", "source": "search", "url": d["resource"]["url"],
        "title": "JavaScript JSON序列化 localStorage读写", "snippet": "JS JSON.stringify",
        "knowledge_point_id": d["point"]["knowledge_point_id"]})
    assert rank(d) is None


def test_unrelated_negation_does_not_erase_explicit_current_JSON_topic():
    d = data(); set_field(d, "title", "JavaScript JSON序列化，本课不讲CSS")
    set_field(d, "description", "本课JSON主题。")
    assert rank(d)["topic_evidence_status"] == "partial"


@pytest.mark.parametrize("description", [
    "先修：JavaScript JSON序列化。", "下节课讲JavaScript JSON序列化。",
    "JavaScript JSON序列化。",
])
def test_description_role_is_not_assumed_current_teaching(description):
    d = data(); d["resource"]["chapters"] = []
    set_field(d, "title", "JavaScript课程"); set_field(d, "description", description)
    assert rank(d) is None


def test_explicit_own_current_teaching_description_is_partial():
    d = data(); d["resource"]["chapters"] = []
    set_field(d, "title", "JavaScript课程")
    set_field(d, "description", "本节讲解JavaScript JSON序列化。")
    assert rank(d)["topic_evidence_status"] == "partial"


def test_actual_own_JSON_chapters_can_inherit_same_page_current_JS_course_owner():
    d = data(); set_field(d, "title", "JavaScript课程"); set_field(d, "description", "课程资料。")
    match = rank(d)
    assert match and match["topic_evidence_status"] == "partial"
    ids = {c["evidence_id"] for c in d["resource"]["chapters"]}
    assert ids.intersection(match["supporting_evidence_ids"])
    assert d["resource"]["field_provenance"]["title"]["evidence_id"] in match["supporting_evidence_ids"]
    assert next(p for p in match["subtopic_coverage"] if p["text"] == "读写")["status"] == "unknown"
