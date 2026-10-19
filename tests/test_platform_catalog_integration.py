"""Offline integration of saved browser catalogs with resource eligibility.

These fixtures are rendered DOM captures, not fresh HTTP responses. Mutations
below deliberately damage evidence bindings; no test fetches or plays a video.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource, SearchRequest
from backend.app.ranking import (
    has_course_page,
    has_learning_evidence,
    has_video_evidence,
    rank_resource,
    topic_observations,
)
from backend.app.resource_identity import derive_course_identity, summarize_course_identities


CAPTURES = Path(__file__).resolve().parents[1] / "reports/platform-catalog-20261017/browser"
MOOC = "https://www.icourse163.org/course/PKU-1003479006"
BILIBILI = "https://www.bilibili.com/video/BV1VZ4y1G7YB/"
# Fixed replay clock, not a claim that these unit tests made a live request.
REPLAY_AT = "2026-10-17T03:58:05.372Z"
POINT = {"knowledge_point_id": "catalog-point", "text": "列表和元组"}
REQUEST = SearchRequest(knowledge_points=[POINT["text"]])


def resource_from_capture(name: str, url: str, *, with_closed_term: bool = False):
    markup = (CAPTURES / name).read_text(encoding="utf-8")
    if with_closed_term:
        # Explicitly compose two real fragments saved from the same page. Neither
        # original fragment is changed or represented as a complete HTTP body.
        soup = BeautifulSoup(markup, "html.parser")
        soup.body.append(BeautifulSoup((CAPTURES / "mooc-term-dom.html").read_text(encoding="utf-8"), "html.parser"))
        markup = str(soup)
    extracted = MetadataExtractor().extract(markup, url, REPLAY_AT)
    evidence = extracted.pop("evidence")
    resource = Resource.model_validate({
        **extracted,
        "resource_id": "capture-mooc" if url == MOOC else "capture-bilibili",
        "url": url,
        "canonical_url": url,
        "discovered_at": REPLAY_AT,
    }).model_dump()
    return resource, evidence


def test_real_mooc_catalog_survives_schema_and_ranking_as_a_nonvideo_course():
    resource, evidence = resource_from_capture("mooc-dom.html", MOOC)

    assert resource["resource_type"] == "course"
    assert resource["catalog_kind"] == "course_outline"
    assert len(resource["chapters"]) == 84
    assert has_course_page(resource, evidence)
    assert has_learning_evidence(resource, evidence)
    assert not has_video_evidence(resource, evidence)
    assert resource["video_evidence_status"] == "none"
    assert resource["playback_verified"] is False

    match = rank_resource(POINT, resource, evidence, REQUEST)
    assert match is not None
    assert match["topic_evidence_status"] == "supported"
    assert "catalog" in match["coverage_basis"]
    assert set(match["supporting_evidence_ids"]) <= {row["evidence_id"] for row in evidence}

    resource["course_identity"] = derive_course_identity(resource, evidence)
    identity = resource["course_identity"]
    assert identity["role"] == "course" and identity["family_url"] == MOOC
    assert identity["offering_id"] is None and identity["lesson_id"] is None
    summary = summarize_course_identities([resource])
    assert summary["identified_course_families"] == 1
    assert summary["identified_lessons"] == 0  # 84 outline rows do not become courses or lessons.


@pytest.mark.parametrize("damage", [
    "missing_provenance",
    "missing_evidence",
    "bound_to_title",
    "wrong_field",
    "wrong_source",
    "different_course_url",
])
def test_mooc_catalog_cannot_bypass_missing_or_misbound_course_type_evidence(damage):
    resource, evidence = resource_from_capture("mooc-dom.html", MOOC)
    provenance = resource["field_provenance"]["resource_type"]
    type_row = next(row for row in evidence if row["evidence_id"] == provenance["evidence_id"])
    if damage == "missing_provenance":
        del resource["field_provenance"]["resource_type"]
    elif damage == "missing_evidence":
        evidence.remove(type_row)
    elif damage == "bound_to_title":
        provenance["evidence_id"] = resource["field_provenance"]["title"]["evidence_id"]
    elif damage == "wrong_field":
        type_row["field"] = "description"
    elif damage == "wrong_source":
        type_row["source"] = "html.unrelated.course_claim"
    elif damage == "different_course_url":
        type_row["url"] = "https://www.icourse163.org/course/OTHER-1000000000"

    # Keep the genuine catalog intact: catalog presence cannot repair the
    # deliberately broken independent resource-type observation.
    assert len(resource["chapters"]) == 84
    assert not has_course_page(resource, evidence)
    assert not has_learning_evidence(resource, evidence)
    assert rank_resource(POINT, resource, evidence, REQUEST) is None


def test_real_bilibili_video_parts_survive_schema_without_asserting_playback_or_courses():
    resource, evidence = resource_from_capture("bilibili-dom.html", BILIBILI)

    assert resource["resource_type"] == "video"
    assert resource["catalog_kind"] == "video_parts"
    assert len(resource["chapters"]) == 15
    assert has_video_evidence(resource, evidence)
    assert has_learning_evidence(resource, evidence)
    assert not has_course_page(resource, evidence)
    assert resource["video_evidence_status"] == "page_verified"
    assert resource["playback_verified"] is False
    assert all(row["url"] is None and row["start_seconds"] is None and row["end_seconds"] is None
               for row in resource["chapters"])
    assert rank_resource(POINT, resource, evidence, REQUEST) is not None

    resource["course_identity"] = derive_course_identity(resource, evidence)
    assert resource["course_identity"]["family_id"] is None
    summary = summarize_course_identities([resource])
    assert summary["resource_records"] == 1
    assert summary["identified_course_families"] == 0
    assert summary["identified_lessons"] == 0


@pytest.mark.parametrize("damage", ["missing_video_evidence", "bound_to_catalog"])
def test_video_parts_kind_alone_does_not_replace_the_video_status_evidence(damage):
    resource, evidence = resource_from_capture("bilibili-dom.html", BILIBILI)
    provenance = resource["field_provenance"]["video_evidence_status"]
    if damage == "missing_video_evidence":
        evidence = [row for row in evidence if row["evidence_id"] != provenance["evidence_id"]]
    else:
        provenance["evidence_id"] = resource["chapters"][0]["evidence_id"]

    assert resource["catalog_kind"] == "video_parts" and len(resource["chapters"]) == 15
    assert not has_video_evidence(resource, evidence)
    assert not has_learning_evidence(resource, evidence)
    assert rank_resource(POINT, resource, evidence, REQUEST) is None


def test_closed_mooc_offering_keeps_public_catalog_and_its_independent_access_notice():
    resource, evidence = resource_from_capture("mooc-dom.html", MOOC, with_closed_term=True)

    assert resource["access_notice"] == "老师已关闭该学期，无法查看"
    assert resource["fetch_status"] == "fetched"
    assert resource["resource_type"] == "course" and resource["catalog_kind"] == "course_outline"
    assert len(resource["chapters"]) == 84
    notice = resource["field_provenance"]["access_notice"]
    observed = next(row for row in evidence if row["evidence_id"] == notice["evidence_id"])
    assert observed["kind"] == "page" and observed["field"] == "access_notice"
    assert observed["url"] == MOOC and observed["text"] == resource["access_notice"]
    assert has_course_page(resource, evidence)
    assert rank_resource(POINT, resource, evidence, REQUEST) is not None
    assert not has_video_evidence(resource, evidence)
    assert resource["playback_verified"] is False
    assert all(resource[field] is None for field in ("requires_login", "requires_payment", "requires_enrollment"))


def test_mooc_lessons_inherit_evidenced_course_context_but_do_not_merge_teaching():
    resource, evidence = resource_from_capture("mooc-dom.html", MOOC, with_closed_term=True)
    point = {"knowledge_point_id": "compound-catalog-point", "text": "Python 列表与字典"}
    assert has_course_page(resource, evidence) and has_learning_evidence(resource, evidence)
    observations = topic_observations(point, resource, evidence)
    lesson_rows = [row for row in observations if row["title"].startswith(("课程16 ", "课程17 "))]
    # The course's own evidenced Python title supplies only the language. Each
    # actual lesson still has to prove its topic, and they cannot become a single
    # observation claiming complete teaching of both requested concepts.
    assert len(lesson_rows) == 2
    assert all("Python" not in row["title"] and row["evidence_ids"] for row in lesson_rows)
    assert not any("列表" in row["title"] and "字典" in row["title"] for row in lesson_rows)
    assert all(row["body"] == "Python" for row in lesson_rows)
    parent_id = resource["field_provenance"]["title"]["evidence_id"]
    assert all(parent_id in row["evidence_ids"] and len(row["evidence_ids"]) == 2 for row in lesson_rows)
    match = rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]]))
    assert match["topic_evidence_status"] == "partial"
    assert match["topic_evidence_reasons"][0]["code"] == "fragmented_compound_evidence"
    assert "chapter_inherits_evidenced_parent_technical_context" in match["topic_match_rules"]
