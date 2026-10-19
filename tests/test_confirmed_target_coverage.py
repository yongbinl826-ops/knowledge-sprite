"""Confirmed learning skills survive search without becoming source evidence."""
from copy import deepcopy

from backend.app.models import SearchRequest
from backend.app.ranking import assess_topic_evidence, coverage_targets, summarize_collection_coverage
from tests.test_video_readiness import record


def page_record(title, description):
    resource, evidence = record(title)
    resource.update(description=description, metadata_evidence_level="page", fetch_status="fetched")
    for field, value in (("title", title), ("description", description)):
        identifier = "page-" + field
        resource["field_provenance"][field] = {"source": "html." + field, "url": resource["url"], "evidence_id": identifier}
        evidence.append({"evidence_id": identifier, "kind": "page", "field": field, "text": value,
            "source": "html." + field, "url": resource["url"]})
    return resource, evidence


def test_matching_title_cannot_complete_unobserved_confirmed_skill():
    point = {"knowledge_point_id": "p", "text": "pandas CSV reading", "learning_targets": ["read_csv", "drop_duplicates"]}
    resource, evidence = page_record("pandas CSV reading tutorial", "Use pandas read_csv to read a CSV file.")
    original = deepcopy((point, resource, evidence))
    result = assess_topic_evidence(point, resource, evidence)
    assert result and result["topic_evidence_status"] == "partial"
    targets = {row["text"]: row for row in result["subtopic_coverage"]}
    assert targets["read_csv"]["status"] == "supported"
    assert targets["drop_duplicates"]["status"] == "unknown"
    collection = summarize_collection_coverage(point["text"], [{"resource": resource, "evidence": evidence, "match": result}], point["learning_targets"])
    assert collection["status"] == "some_subtopics_supported"
    assert len(collection["subtopics"]) == 3
    assert (point, resource, evidence) == original


def test_search_excerpt_alone_never_attests_confirmed_skills():
    point = {"knowledge_point_id": "p", "text": "pandas CSV reading", "learning_targets": ["drop_duplicates"]}
    resource, evidence = record("pandas CSV reading tutorial", "pandas drop_duplicates tutorial")
    result = assess_topic_evidence(point, resource, evidence)
    assert result and result["topic_evidence_status"] == "partial"
    assert result["subtopic_coverage"][-1]["status"] == "unknown"


def test_partial_source_for_one_confirmed_skill_retains_unmatched_project_requirement():
    point = {"knowledge_point_id": "p", "text": "pandas clean bicycle trip records", "learning_targets": ["drop_duplicates", "to_datetime"]}
    resource, evidence = page_record("pandas drop_duplicates tutorial", "Learn pandas drop_duplicates to remove duplicate rows.")
    result = assess_topic_evidence(point, resource, evidence)
    assert result and result["topic_evidence_status"] == "partial"
    assert result["subtopic_coverage"][0]["status"] == "unknown"
    assert result["subtopic_coverage"][1]["status"] == "supported"
    assert result["subtopic_coverage"][2]["status"] == "unknown"


def test_no_learning_target_is_invented_for_historic_or_manual_request():
    text = "pandas CSV reading"
    assert SearchRequest(knowledge_points=[text]).learning_targets == {}
    assert all(not row["id"].startswith("learning_target_") for row in coverage_targets(text)["subtopics"])


def test_prerequisite_skill_and_other_tool_do_not_become_target_support():
    point = {"knowledge_point_id": "p", "text": "pandas CSV reading", "learning_targets": ["drop_duplicates"]}
    for description in ("Prerequisites: pandas drop_duplicates.", "NumPy drop_duplicates tutorial."):
        resource, evidence = page_record("pandas CSV reading tutorial", description)
        result = assess_topic_evidence(point, resource, evidence)
        assert result and result["subtopic_coverage"][-1]["status"] == "unknown"
