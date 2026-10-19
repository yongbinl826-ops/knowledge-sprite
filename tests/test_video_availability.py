"""Staged pure-helper tests; no backend/test-tree changes or HTTP."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
from backend.app import video_availability as helper
URL = "https://videos.example.org/lesson/123"


def sample():
    resource = {"resource_id": "r", "url": URL, "canonical_url": URL, "title": "Video platform",
                "fetch_status": "javascript_required", "resource_type": "video",
                "metadata_evidence_level": "page", "video_evidence_status": "search_discovered",
                "access_notice": "Existing source notice.", "requires_login": None, "requires_payment": None,
                "field_provenance": {"title": {"source": "html.title", "evidence_id": "page-title", "url": URL}}}
    evidence = [{"evidence_id": "search", "kind": "search", "source": "search-engine", "url": URL,
                 "title": "Read CSV files using pandas", "type_source": "search_template", "resource_type_hint": "video"},
                {"evidence_id": "page-title", "kind": "page", "field": "title", "source": "html.title", "url": URL, "text": "Video platform"}]
    return resource, evidence


def test_projection_keeps_exact_real_search_title_raw_url_and_original_evidence_without_mutation():
    resource, evidence = sample()
    before = deepcopy((resource, evidence))
    projected = helper.project_unconfirmed_video_shell(resource, evidence)
    assert projected["title"] == evidence[0]["title"]
    assert projected["url"] == resource["url"] and projected["canonical_url"] == resource["canonical_url"]
    assert projected["field_provenance"]["title"]["evidence_id"] == "search"
    assert projected["video_evidence_status"] == "search_discovered"
    assert projected["requires_login"] is None and projected["requires_payment"] is None
    assert "Existing source notice." in projected["access_notice"]
    assert helper.project_unconfirmed_video_shell(projected, evidence) == projected
    assert (resource, evidence) == before


@pytest.mark.parametrize("status", ["fetched", "success", "not_fetched", "login_required", "access_denied", "captcha", "not_found"])
def test_other_access_states_are_not_relabelled_as_a_javascript_shell(status):
    resource, evidence = sample()
    resource["fetch_status"] = status
    assert not helper.is_unconfirmed_video_shell(resource, evidence)
    assert helper.project_unconfirmed_video_shell(resource, evidence) is resource


@pytest.mark.parametrize("source", sorted(helper._PAGE_VIDEO_PROOFS))
def test_same_page_explicit_video_proof_is_preserved_even_when_javascript_is_required(source):
    resource, evidence = sample()
    resource["video_evidence_status"] = "page_verified"
    resource["field_provenance"]["video_evidence_status"] = {"source": source, "evidence_id": "video", "url": URL}
    evidence.append({"evidence_id": "video", "kind": "page", "field": "video_evidence_status", "source": source, "url": URL, "text": "Page identifies its particular video"})
    assert not helper.is_unconfirmed_video_shell(resource, evidence)
    assert helper.project_unconfirmed_video_shell(resource, evidence) is resource


@pytest.mark.parametrize("mutation", ["foreign-page", "foreign-provenance", "wrong-source", "wrong-field", "search", "catalog", "missing-id", "no-proof"])
def test_a_claimed_page_verified_status_cannot_borrow_unbound_or_generic_identity(mutation):
    resource, evidence = sample()
    resource["video_evidence_status"] = "page_verified"
    proof = {"source": "jsonld.VideoObject", "evidence_id": "video", "url": URL}
    row = {"evidence_id": "video", "kind": "page", "field": "video_evidence_status", "source": "jsonld.VideoObject", "url": URL}
    resource["field_provenance"]["video_evidence_status"] = proof
    if mutation == "foreign-page": row["url"] = URL + "/other"
    if mutation == "foreign-provenance": proof["url"] = URL + "/other"
    if mutation == "wrong-source": proof["source"] = row["source"] = "meta.og:type"
    if mutation == "wrong-field": row["field"] = "title"
    if mutation in {"search", "catalog"}: row["kind"] = mutation
    if mutation == "missing-id": proof["evidence_id"] = row["evidence_id"] = None
    if mutation != "no-proof": evidence.append(row)
    assert helper.is_unconfirmed_video_shell(resource, evidence)


@pytest.mark.parametrize("change", [{"url": URL + "/other"}, {"url": "http://127.1/"}, {"title": " "},
                                   {"source": ""}, {"evidence_id": ""}, {"kind": "page"},
                                   {"type_source": "query"}, {"resource_type_hint": "unknown"}])
def test_search_title_restore_requires_exact_resource_url_and_real_media_observation(change):
    resource, evidence = sample()
    evidence[0].update(change)
    projected = helper.project_unconfirmed_video_shell(resource, evidence)
    assert projected["title"] == resource["title"]
    assert helper.PAGE_SHELL_NOTICE in projected["access_notice"]


def test_tracking_parameter_normalization_can_match_but_other_video_paths_cannot():
    resource, evidence = sample()
    evidence[0]["url"] = URL + "?utm_source=index"
    assert helper.project_unconfirmed_video_shell(resource, evidence)["title"] == evidence[0]["title"]
    resource["resolved_url"] = URL + "/other"
    evidence[0]["url"] = resource["resolved_url"]
    assert helper.project_unconfirmed_video_shell(resource, evidence)["title"] == resource["title"]


def test_review_projection_clears_all_teaching_coverage_without_inventing_irrelevant_hits():
    resource, evidence = sample()
    evidence.append({"evidence_id": "other-page", "kind": "page", "field": "title", "url": URL + "/other"})
    assessment = {"topic_evidence_status": "partial", "supporting_evidence_ids": ["search"],
                  "topic_evidence_reasons": [], "subtopic_coverage": [
                      {"id": "core", "text": "CSV reading", "status": "supported", "evidence_ids": ["search"]},
                      {"id": "target", "text": "business boundary", "status": "unknown", "evidence_ids": []}]}
    original = deepcopy(assessment)
    result = helper.unconfirmed_video_shell_assessment(assessment, resource, evidence)
    assert result["topic_evidence_status"] == "needs_review"
    assert result["supporting_evidence_ids"] == []
    assert all(p["status"] == "unknown" and p["evidence_ids"] == [] for p in result["subtopic_coverage"])
    assert result["topic_evidence_reasons"][0]["code"] == "page_shell_unconfirmed"
    assert result["topic_evidence_reasons"][0]["evidence_ids"] == ["page-title"]
    assert assessment == original
    assert helper.unconfirmed_video_shell_assessment(None, resource, evidence) is None


def test_retained_real_shell_observation_replays_without_http_or_database_access():
    retained = HERE / "fixtures/video_shell/observed-shell.json"
    packet = json.loads(retained.read_text(encoding="utf-8"))
    resource = packet["resource"]
    evidence = resource["own_evidence"]
    original = deepcopy(resource)
    projected = helper.project_unconfirmed_video_shell(resource, evidence)
    assert projected["title"] == evidence[0]["title"]
    result = helper.unconfirmed_video_shell_assessment(resource["assessment_current"], resource, evidence)
    assert result["topic_evidence_status"] == "needs_review" and not result["supporting_evidence_ids"]
    assert all(p["status"] == "unknown" for p in result["subtopic_coverage"])
    assert resource == original
