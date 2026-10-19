"""Offline regressions for the bounded relational normal-form equivalence."""
from copy import deepcopy

import pytest

from backend.app.models import Resource, SearchRequest
from backend.app.ranking import _normal_forms_context, compound_english_match, rank_resource


def ranked(title, snippet="", *, point="database normalization"):
    url = "https://courses.example.org/normal-form-lesson"
    evidence = [{"evidence_id": "search", "kind": "search", "source": "fixture",
                 "knowledge_point_id": "p", "url": url, "title": title, "snippet": snippet,
                 "resource_type_hint": "video", "type_source": "search_template"}]
    provenance = {"source": "search_template", "evidence_id": "search"}
    resource = Resource(resource_id="r", url=url, canonical_url=url, title=title,
                        discovered_at="2026-10-18T00:00:00+00:00", resource_type="video",
                        video_evidence_status="search_discovered",
                        field_provenance={"resource_type": provenance,
                                          "video_evidence_status": provenance}).model_dump()
    original = deepcopy((resource, evidence))
    result = rank_resource({"knowledge_point_id": "p", "text": point}, resource, evidence,
                           SearchRequest(knowledge_points=[point]))
    assert (resource, evidence) == original
    return result


@pytest.mark.parametrize("point,title", [
    ("database normalization", "Normalization - 1NF 2NF 3NF and 4NF"),
    ("database normalisation", "Normalisation and BCNF tutorial"),
    ("database normalization", "We teach normalization using 1NF and 2NF"),
    ("database normalization", "Normalization: 5NF examples"),
])
def test_standard_names_in_same_teaching_clause_keep_bounded_database_sense(point, title):
    result = ranked(title, point=point)
    assert result["topic_evidence_status"] == "supported"
    assert result["supporting_evidence_ids"] == ["search"]
    assert "database_standard_normal_forms_context" in result["topic_match_rules"]


@pytest.mark.parametrize("title,snippet", [
    ("Image normalization tutorial", "Prerequisites: BCNF"),
    ("Normalization tutorial", "We do not teach 1NF or BCNF."),
    ("Normalization tutorial", "We don't cover BCNF."),
    ("Normalization tutorial", "BCNF is not covered."),
    ("Normalization tutorial", "We exclude BCNF."),
    ("Normalization tutorial", "No BCNF content."),
    ("Normalization tutorial", "Students must already know BCNF."),
    ("Normalization tutorial", "Required prior knowledge: 1NF"),
    ("Normalization tutorial", "先修知识：BCNF"),
    ("Normalization tutorial", "本课不讲1NF与BCNF"),
    ("Normalization tutorial", "BCNF merely mentioned in references."),
    ("Normalization tutorial", "Related videos: BCNF tutorial"),
    ("Normalization tutorial", "https://reference.example.org/database/1nf"),
    ("Image normalization tutorial. BCNF", ""),
    ("Image normalization tutorial; BCNF", ""),
    ("Image normalization tutorial | BCNF", ""),
    ("Image normalization tutorial, BCNF", ""),
    ("Image normalization tutorial\nBCNF", ""),
    ("Normalization tutorial", ""),
    ("BCNF tutorial", ""),
])
def test_missing_database_sense_cannot_be_donated_by_non_teaching_or_another_clause(title, snippet):
    result = ranked(title, snippet)
    assert result is None or result["topic_evidence_status"] != "supported"
    assert not _normal_forms_context("database normalization", title + " " + snippet)


def test_context_equivalence_never_fills_an_additional_requested_skill_or_wrong_target():
    text = "Normalization - 1NF and BCNF tutorial"
    assert not compound_english_match("database normalization transactions", [text])
    assert not _normal_forms_context("image normalization", text)
    assert not _normal_forms_context("database replication", text)
    assert not compound_english_match("database normalization", ["Normalization", "1NF"])


def test_an_independent_complete_teaching_clause_survives_other_prerequisite_clause():
    text = "Prerequisites: Python. Normalization and BCNF tutorial"
    assert _normal_forms_context("database normalization", text)
    result = ranked(text)
    assert result["topic_evidence_status"] == "supported"

