"""Synthetic actual-extractor controls; no HTTP, models or persistent DB."""
from copy import deepcopy
import json

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import SearchRequest, now
from backend.app.ranking import rank_resource


URL = "https://www.bilibili.com/video/BV1AAAAAAAAA/"


def course(owner, concept, *, title=None, description=None, parts=None):
    state = {"videoData": {"bvid": "BV1AAAAAAAAA", "title": title or owner + " 入门课程",
        "desc": description if description is not None else "本课程使用 " + owner + "，面向入门学习者。",
        "owner": {"name": "Synthetic instructor"},
        "pages": [{"page": i, "part": part, "duration": 120, "cid": 122 + i}
                  for i, part in enumerate(parts or [concept], 1)]}}
    html = "<script>window.__INITIAL_STATE__=" + json.dumps(state, ensure_ascii=False) + ";</script>"
    resource = MetadataExtractor().extract(html, URL, now())
    evidence = resource.pop("evidence")
    resource.update(resource_id="course", url=URL, canonical_url=URL, resolved_url=URL, platform="bilibili")
    return resource, evidence


def mapped(owner, concept, resource, evidence):
    point = {"knowledge_point_id": "p1", "text": concept}
    request = SearchRequest(knowledge_points=[concept], topic_technologies={concept: owner})
    before = deepcopy((point, request.model_dump(), resource, evidence))
    result = rank_resource(point, resource, evidence, request)
    assert (point, request.model_dump(), resource, evidence) == before
    return result


@pytest.mark.parametrize("owner,concept", [("pygame", "碰撞检测"), ("JavaScript", "事件")])
def test_mapped_concept_keeps_verified_parent_context_of_its_current_chapter(owner, concept):
    resource, evidence = course(owner, concept)
    prefixed = owner + " " + concept
    legacy = rank_resource({"knowledge_point_id": "p1", "text": prefixed}, resource, evidence,
                           SearchRequest(knowledge_points=[prefixed]))
    assert legacy and legacy["topic_evidence_status"] == "supported"
    result = mapped(owner, concept, resource, evidence)
    assert result and result["topic_evidence_status"] == "supported"
    assert "chapter_inherits_evidenced_parent_technical_context" in result["topic_match_rules"]
    own_ids = {row["evidence_id"] for row in evidence if row["kind"] in {"page", "catalog"}}
    assert set(result["supporting_evidence_ids"]) <= own_ids
    assert any(row["kind"] == "catalog" and row["evidence_id"] in result["supporting_evidence_ids"] for row in evidence)


@pytest.mark.parametrize("mutation", ["foreign_parent", "future_parent", "prerequisite_parent", "negative_parent",
    "search_parent", "sibling_owner", "foreign_chapter", "future_chapter", "prerequisite_chapter",
    "parent_wrong_url", "catalog_wrong_url", "broken_catalog_id"])
def test_parent_scope_does_not_borrow_unverified_or_noncurrent_context(mutation):
    owner, concept = "pygame", "碰撞检测"
    title, description, parts = None, None, None
    if mutation == "foreign_parent":
        title, description = "JavaScript 入门课程", "本课程讲解 JavaScript。"
    elif mutation == "future_parent":
        title, description = "通用入门课程", "下节课讲解 pygame。"
    elif mutation == "prerequisite_parent":
        title, description = "通用入门课程", "先修要求：pygame。"
    elif mutation == "negative_parent":
        title, description = "通用入门课程", "本课不讲 pygame。"
    elif mutation == "sibling_owner":
        title, description, parts = "通用入门课程", "公开教学目录。", [concept, "pygame 其他主题"]
    elif mutation == "foreign_chapter":
        parts = ["JavaScript " + concept]
    elif mutation == "future_chapter":
        parts = ["下节课讲解 " + concept]
    elif mutation == "prerequisite_chapter":
        parts = ["先修要求：" + concept]
    resource, evidence = course(owner, concept, title=title, description=description, parts=parts)
    if mutation in {"search_parent", "parent_wrong_url"}:
        for field in ("title", "description"):
            proof = resource["field_provenance"][field]
            row = next(row for row in evidence if row["evidence_id"] == proof["evidence_id"])
            if mutation == "search_parent":
                row["kind"] = "search"
                row["source"] = proof["source"] = "search"
            else:
                row["url"] = proof["url"] = "https://www.bilibili.com/video/BV1BBBBBBBBB/"
    elif mutation == "catalog_wrong_url":
        for row in evidence:
            if row["kind"] == "catalog":
                row["url"] = "https://www.bilibili.com/video/BV1BBBBBBBBB/"
    elif mutation == "broken_catalog_id":
        for row in resource["chapters"]:
            row["evidence_id"] = "not-an-own-record"
    result = mapped(owner, concept, resource, evidence)
    assert result is None or result["topic_evidence_status"] == "needs_review"
