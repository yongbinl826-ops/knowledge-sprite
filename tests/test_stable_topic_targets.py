"""Coverage targets remain stable without erasing original project constraints."""
from backend.app.ranking import rank_resource, summarize_collection_coverage
from backend.app.models import SearchRequest
from tests.test_video_readiness import record


def test_unparsed_atomic_topic_has_one_explicit_target_only_when_actually_supported():
    text = "pandas 读取CSV"
    resource, evidence = record("pandas 读取CSV文件视频教程")
    match = rank_resource({"knowledge_point_id": "p", "text": text}, resource, evidence, SearchRequest(knowledge_points=[text]))
    assert match and match["topic_evidence_status"] == "supported"
    assert match["subtopic_coverage"][0]["id"] == "whole_topic"
    collection = summarize_collection_coverage(text, [{"resource": resource, "evidence": evidence, "match": match}])
    assert collection["status"] == "all_subtopics_supported"
    assert collection["subtopics"][0]["text"] == text


def test_qualified_core_does_not_erase_original_conjunction_or_claim_invalid_rows_are_handled():
    text = "pandas 时间列解析与无效行分离"
    resource, evidence = record("pandas to_datetime('2026-01-01')日期时间转换教程")
    match = rank_resource({"knowledge_point_id": "p", "text": text}, resource, evidence, SearchRequest(knowledge_points=[text]))
    assert match and match["topic_evidence_status"] == "partial"
    collection = summarize_collection_coverage(text, [{"resource": resource, "evidence": evidence, "match": match}])
    assert collection["status"] == "some_subtopics_supported"
    assert {(p["id"], p["text"]) for p in collection["subtopics"]} == {(p["id"], p["text"]) for p in match["subtopic_coverage"]}
    assert [p["id"] for p in match["subtopic_coverage"] if p["status"] == "supported"] == ["operation_core"]
    assert any(p["text"] == "无效行分离" and p["status"] == "unknown" for p in collection["subtopics"])
    assert next(p for p in collection["subtopics"] if p["id"] == "operation_qualification")["status"] == "unknown"
