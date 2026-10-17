"""Offline audit-helper checks; synthetic evidence is never used by live cases."""
import json

import pytest

from backend.app.extractor import MetadataExtractor
from scripts.live_acceptance_revision import audit_resource_evidence


def extracted_item(kind="VideoObject"):
    html = '''<script type="application/ld+json">{
      "@type": "%s", "name": "Synthetic lesson", "hasPart": [
        {"@type": "Clip", "name": "Synthetic chapter", "url": "https://example.org/lesson#chapter", "startOffset": 65}
      ]
    }</script>''' % kind
    metadata = MetadataExtractor().extract(html, "https://example.org/lesson", "2026-10-13T00:00:00Z")
    evidence = metadata.pop("evidence")
    return {"resource": {"resource_id": "fixture-only", "url": "https://example.org/lesson", **metadata}, "evidence": evidence}


def test_plain_course_and_directory_do_not_verify_video():
    audit = audit_resource_evidence(extracted_item("Course"))
    assert audit["has_type_provenance"]
    assert not audit["page_verified"] and not audit["video_catalog"]


def test_actual_video_structure_and_per_chapter_evidence_are_required():
    item = extracted_item()
    audit = audit_resource_evidence(item)
    assert audit["page_verified"] and audit["video_catalog"]
    assert audit["verified_chapter_count"] == 1
    assert not audit["playback_verified"]
    item["resource"]["chapters"][0]["start_seconds"] = 999
    assert not audit_resource_evidence(item)["video_catalog"]


def test_catalog_duration_must_match_record_and_is_not_a_start_offset():
    item = extracted_item()
    chapter = item["resource"]["chapters"][0]
    chapter["duration_seconds"] = 2743
    assert not audit_resource_evidence(item)["video_catalog"]
    record = next(r for r in item["evidence"] if r.get("field") == "chapters.0")
    values = json.loads(record["text"])
    values["duration_seconds"] = 2743
    record["text"] = json.dumps(values)
    assert audit_resource_evidence(item)["video_catalog"]
    assert chapter["start_seconds"] == 65


def chapter_and_record(item):
    chapter = item["resource"]["chapters"][0]
    record = next(r for r in item["evidence"] if r.get("evidence_id") == chapter["evidence_id"])
    return chapter, record


def write_chapter_record(chapter, record):
    record["text"] = json.dumps({key: chapter.get(key) for key in (
        "title", "url", "start_seconds", "end_seconds", "duration_seconds")})


@pytest.mark.parametrize("duration", [True, False, "12", -1, 0, float("inf"), float("-inf"), float("nan"), 10**1000])
def test_invalid_duration_is_rejected_even_if_recorded(duration):
    item = extracted_item()
    chapter, record = chapter_and_record(item)
    chapter["duration_seconds"] = duration
    write_chapter_record(chapter, record)
    audit = audit_resource_evidence(item)
    assert audit["verified_chapter_count"] == 0 and not audit["video_catalog"]


@pytest.mark.parametrize("field", ["start_seconds", "end_seconds", "duration_seconds"])
def test_boolean_in_record_cannot_match_numeric_seconds(field):
    item = extracted_item()
    chapter, record = chapter_and_record(item)
    chapter.update(start_seconds=0, end_seconds=1, duration_seconds=1)
    write_chapter_record(chapter, record)
    fields = json.loads(record["text"])
    fields[field] = bool(chapter[field])
    record["text"] = json.dumps(fields)
    assert audit_resource_evidence(item)["verified_chapter_count"] == 0


@pytest.mark.parametrize("field", ["start_seconds", "end_seconds"])
@pytest.mark.parametrize("seconds", [True, False, "1", -1, float("inf"), float("nan")])
def test_invalid_offsets_are_rejected_even_if_recorded(field, seconds):
    item = extracted_item()
    chapter, record = chapter_and_record(item)
    chapter[field] = seconds
    write_chapter_record(chapter, record)
    assert audit_resource_evidence(item)["verified_chapter_count"] == 0


def test_zero_offsets_unknown_values_and_positive_duration_are_valid():
    item = extracted_item()
    chapter, record = chapter_and_record(item)
    chapter.update(start_seconds=0, end_seconds=0, duration_seconds=0.5)
    write_chapter_record(chapter, record)
    assert audit_resource_evidence(item)["video_catalog"]
    chapter.update(url=None, start_seconds=None, end_seconds=None, duration_seconds=None)
    record["text"] = json.dumps({"title": chapter["title"]})
    assert audit_resource_evidence(item)["video_catalog"]
    for key in ("url", "start_seconds", "end_seconds", "duration_seconds"):
        chapter.pop(key)
    record["text"] = json.dumps({"title": chapter["title"], "url": None, "start_seconds": None,
                                 "end_seconds": None, "duration_seconds": None})
    assert audit_resource_evidence(item)["video_catalog"]


def test_end_before_start_is_not_verified():
    item = extracted_item()
    chapter, record = chapter_and_record(item)
    chapter.update(start_seconds=2, end_seconds=1)
    write_chapter_record(chapter, record)
    assert not audit_resource_evidence(item)["video_catalog"]


@pytest.mark.parametrize("key,value", [
    ("title", "A different chapter"), ("url", "https://example.org/other"),
    ("start_seconds", 66), ("end_seconds", 120), ("duration_seconds", 120),
])
def test_each_chapter_field_must_match_its_own_record(key, value):
    item = extracted_item()
    chapter, _ = chapter_and_record(item)
    chapter[key] = value
    assert audit_resource_evidence(item)["verified_chapter_count"] == 0


def test_other_chapter_id_and_aggregate_only_are_not_row_evidence():
    item = extracted_item()
    chapter, record = chapter_and_record(item)
    # Identical facts do not make the next row's evidence belong to this index.
    record["field"] = "chapters.1"
    assert audit_resource_evidence(item)["verified_chapter_count"] == 0
    record["field"] = "chapters"
    item["resource"]["field_provenance"]["chapters"] = {"evidence_id": record["evidence_id"]}
    chapter.pop("evidence_id")
    assert audit_resource_evidence(item)["verified_chapter_count"] == 0


@pytest.mark.parametrize("text", [None, "", "not JSON", "[]"])
def test_missing_or_non_object_chapter_record_is_not_verified(text):
    item = extracted_item()
    _, record = chapter_and_record(item)
    record["text"] = text
    assert audit_resource_evidence(item)["verified_chapter_count"] == 0


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://user:secret@example.org/lesson",
                                "https://example.org/lesson\n", "https://example.org\\lesson",
                                "https://example.org:invalid/lesson"])
@pytest.mark.parametrize("location", ["source", "chapter"])
def test_unsafe_source_or_chapter_url_is_not_verified(url, location):
    item = extracted_item()
    chapter, record = chapter_and_record(item)
    if location == "source":
        record["url"] = url
    else:
        chapter["url"] = url
        write_chapter_record(chapter, record)
    assert audit_resource_evidence(item)["verified_chapter_count"] == 0


def test_page_flag_and_type_provenance_cannot_replace_video_evidence():
    item = extracted_item()
    item["resource"]["field_provenance"].pop("video_evidence_status")
    assert not audit_resource_evidence(item)["page_verified"]
    item["resource"]["field_provenance"]["video_evidence_status"] = item["resource"]["field_provenance"]["resource_type"]
    assert not audit_resource_evidence(item)["page_verified"]


def test_search_video_discovery_does_not_verify_page_or_playback():
    item = {"resource": {"resource_type": "video", "url": "https://example.org/video", "video_evidence_status": "search_discovered",
        "metadata_evidence_level": "page", "fetch_status": "fetched", "chapters": [],
        "field_provenance": {"video_evidence_status": {"evidence_id": "search-fixture", "source": "search_template"}, "resource_type": {"evidence_id": "search-fixture"}}},
        "evidence": [{"evidence_id": "search-fixture", "kind": "search", "type_source": "search_template", "resource_type_hint": "video", "url": "https://example.org/video"}]}
    audit = audit_resource_evidence(item)
    assert audit["search_discovered"] and not audit["page_verified"] and not audit["video_catalog"]
    item["resource"]["playback_verified"] = True
    audit = audit_resource_evidence(item)
    assert audit["playback_claimed"] and not audit["playback_verified"]
    item["evidence"][0]["resource_type_hint"] = "unknown"
    assert not audit_resource_evidence(item)["search_discovered"]


def test_course_search_entry_is_valid_discovery_but_not_video_verification():
    url = "https://www.icourse163.org/course/TEST-123456"
    item = {"resource": {"resource_type": "course", "url": url, "video_evidence_status": "none",
        "metadata_evidence_level": "search", "fetch_status": "not_fetched", "chapters": [],
        "field_provenance": {"resource_type": {"evidence_id": "search-course", "source": "url_pattern", "url": url}}},
        "evidence": [{"evidence_id": "search-course", "kind": "search", "url": url}]}
    audit = audit_resource_evidence(item)
    assert audit["course_search_candidate"] and audit["has_type_provenance"]
    assert not any(audit[field] for field in ("search_discovered", "page_verified", "video_catalog", "playback_verified"))
    item["resource"]["field_provenance"]["resource_type"] = {"source": "jsonld.@type", "evidence_id": "page-course"}
    item["evidence"].append({"evidence_id": "page-course", "kind": "page", "field": "resource_type", "url": url})
    assert audit_resource_evidence(item)["course_search_candidate"]
    assert not audit_resource_evidence(extracted_item("Course"))["course_search_candidate"]
