"""Isolated fixtures for source identity and point-scoped ranking; no network."""
from copy import deepcopy
import json

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import CourseIdentity, Resource, SearchRequest
from backend.app.ranking import has_course_page, has_learning_evidence, rank_resource
from backend.app.resource_identity import derive_course_identity, diversify, summarize_course_identities
from backend.app.url_utils import normalize_url


STAMP = "2026-10-13T00:00:00+00:00"  # Fixed offline fixture clock.


def extracted(url, node, rid="r"):
    data = MetadataExtractor().extract('<script type="application/ld+json">' + json.dumps(node) + '</script>', url, STAMP)
    evidence = data.pop("evidence")
    resource = Resource(resource_id=rid, url=url, canonical_url=normalize_url(url), discovered_at=STAMP,
                        title=data.pop("title", "Synthetic lesson"), **data).model_dump()
    return resource, evidence


def searched(url, rid="r", point_id="p", title="Python lists course", hint="video", source="search_template"):
    record = {"evidence_id": "search-" + rid, "kind": "search", "knowledge_point_id": point_id, "url": url,
              "title": title, "snippet": "", "type_source": source, "resource_type_hint": hint}
    provenance = {"source": source, "evidence_id": record["evidence_id"]}
    resource = Resource(resource_id=rid, title=title, url=url, canonical_url=normalize_url(url), discovered_at=STAMP,
        resource_type=hint, video_evidence_status="search_discovered" if hint == "video" else "none",
        field_provenance={"title": {"source": "search", "evidence_id": record["evidence_id"]},
            "resource_type": provenance, **({"video_evidence_status": provenance} if hint == "video" else {})}).model_dump()
    return resource, [record]


def identified(resource, evidence):
    return dict(resource, course_identity=derive_course_identity(resource, evidence))


def test_reliable_course_page_is_recommended_without_claiming_video():
    resource, evidence = extracted("https://academy.example.org/courses/python-lists", {
        "@type": "Course", "name": "Python lists course", "description": "Learn Python lists with worked examples."})
    before = deepcopy(resource)
    assert has_course_page(resource, evidence)
    assert has_learning_evidence(resource, evidence)
    match = rank_resource({"knowledge_point_id": "p", "text": "Python lists"}, resource, evidence,
                          SearchRequest(knowledge_points=["Python lists"]))
    assert match and match["coverage_basis"] == ["title", "description"]
    assert resource == before and resource["video_evidence_status"] == "none" and not resource["playback_verified"]
    identity = derive_course_identity(resource, evidence)
    assert identity["basis"] == "page_course" and identity["role"] == "course"
    assert identity["family_id"] and identity["offering_id"] is None


@pytest.mark.parametrize("mutation", ["missing_id", "wrong_url", "wrong_source", "wrong_type", "not_fetched"])
def test_course_page_rejects_unbound_or_wrong_structure_evidence(mutation):
    resource, evidence = extracted("https://academy.example.org/courses/x", {"@type": "Course", "name": "Python lists course"})
    record = next(entry for entry in evidence if entry["field"] == "resource_type")
    if mutation == "missing_id":
        resource["field_provenance"]["resource_type"]["evidence_id"] = "absent"
    elif mutation == "wrong_url":
        record["url"] = "https://unrelated.example.org/course"
    elif mutation == "wrong_source":
        record["source"] = "search_template"
    elif mutation == "wrong_type":
        record["text"] = "VideoObject"
    else:
        resource["fetch_status"] = "timeout"
    assert not has_course_page(resource, evidence)
    assert not has_learning_evidence(resource, evidence)


def test_course_page_relevance_and_prerequisite_rejections_remain():
    resource, evidence = extracted("https://academy.example.org/course/x", {"@type": "Course", "name": "Web design course",
        "description": "Prerequisites: Python lists. This course teaches visual layout."})
    request = SearchRequest(knowledge_points=["Python lists"])
    assert has_learning_evidence(resource, evidence)
    assert rank_resource({"knowledge_point_id": "p", "text": "Python lists"}, resource, evidence, request) is None


@pytest.mark.parametrize("selector", ["course-outline", "curriculum", "chapter-list"])
def test_course_notes_with_css_outline_do_not_become_course_or_catalog(selector):
    html = f'<title>Python课程笔记</title><main><p>这是个人阅读笔记，包含Python列表与字典使用说明。</p><div class="{selector}"><a href="/notes/lists">列表笔记</a></div></main>'
    result = MetadataExtractor().extract(html, "https://notes.example.org/python", STAMP)
    assert "resource_type" not in result
    assert result["chapters"] == [] and result["video_evidence_status"] == "none"
    assert not has_learning_evidence(result, result["evidence"])


def test_mit_parent_path_groups_course_gallery_and_lessons_without_merging_terms():
    root = "https://ocw.mit.edu/courses/0-123-synthetic-course-spring-2005/"
    resources = []
    for index, tail in enumerate(["", "video_galleries/video-lectures/", "resources/lecture-a/", "resources/lecture-b/"]):
        url = root + tail
        resource, evidence = (extracted(url, {"@type": "VideoObject", "name": "Synthetic lesson"}, str(index))
                              if "resources" in tail else searched(url, str(index)))
        resources.append(identified(resource, evidence))
    assert {r["course_identity"]["role"] for r in resources} == {"course", "catalog", "lesson"}
    assert len({r["course_identity"]["family_id"] for r in resources}) == 1
    assert len({r["course_identity"]["offering_id"] for r in resources}) == 1
    assert len({r["url"] for r in resources}) == 4
    summary = summarize_course_identities(resources + [resources[0]])
    assert summary["resource_records"] == 4 and summary["identified_course_families"] == 1
    assert summary["identified_course_offerings"] == 1 and summary["identified_lessons"] == 2
    other, records = searched(root.replace("2005", "2006"), "other")
    assert derive_course_identity(other, records)["family_id"] != resources[0]["course_identity"]["family_id"]


def test_bilibili_parts_remain_resources_without_invented_courses():
    resources = []
    for part in [2, 3]:
        url = f"https://www.bilibili.com/video/BV1ab411c7de?p={part}&uid={part}"
        resource, evidence = searched(url, str(part), source="url_pattern")
        before = deepcopy((resource, evidence))
        identity = derive_course_identity(resource, evidence)
        assert identity["status"] == "partial" and identity["role"] == "video"
        assert identity["family_id"] is identity["lesson_id"] is None
        assert (resource, evidence) == before
        resources.append(dict(resource, course_identity=identity))
    assert resources[0]["canonical_url"] != resources[1]["canonical_url"]
    summary = summarize_course_identities(resources)
    assert summary["resource_records"] == summary["unknown_course_family_resources"] == 2
    assert summary["identified_course_families"] == summary["identified_lessons"] == 0


def test_mooc_and_xuetang_recognized_entry_forms_keep_unknown_offering():
    identities = []
    for path in ["course/ABC-123456", "learn/ABC-123456"]:
        resource, evidence = searched("https://www.icourse163.org/" + path + "?tid=2026", hint="course", source="url_pattern")
        identity = derive_course_identity(resource, evidence)
        assert identity["family_id"] and identity["offering_id"] is None
        assert identity["basis"] == "recognized_url"
        identities.append(identity)
    assert identities[0]["family_id"] == identities[1]["family_id"]
    resource, evidence = searched("https://www.xuetangx.com/course/THU02041000368", hint="course", source="url_pattern")
    identity = derive_course_identity(resource, evidence)
    assert identity["family_id"] and identity["offering_id"] is None
    assert derive_course_identity(resource, []) == CourseIdentity().model_dump()


def test_same_origin_typed_parent_is_extracted_and_bound_without_following():
    url = "https://academy.example.org/lessons/lists"
    resource, evidence = extracted(url, {"@type": "VideoObject", "name": "Python lists lesson",
        "isPartOf": {"@type": "Course", "url": "/courses/python"}})
    assert resource["parent_course_url"] == "https://academy.example.org/courses/python"
    assert "_catalog_followup" not in resource
    identity = derive_course_identity(resource, evidence)
    assert identity["basis"] == "page_is_part_of" and identity["role"] == "lesson"
    assert identity["family_url"] == resource["parent_course_url"] and identity["lesson_id"]
    record = next(entry for entry in evidence if entry["field"] == "parent_course_url")
    assert identity["evidence_ids"] == [record["evidence_id"]]
    assert json.loads(record["text"])["url"] == identity["family_url"]
    record["text"] = json.dumps({"@type": "Course", "url": "/forged"})
    assert derive_course_identity(resource, evidence)["family_id"] is None


@pytest.mark.parametrize("parent", [
    {"@type": "Course", "url": "https://elsewhere.example.org/course/x"},
    {"@type": "WebPage", "url": "/course/x"},
    {"@type": "Course", "name": "Title is not identity"},
    [{"@type": "Course", "url": "/course/a"}, {"@type": "Course", "url": "/course/b"}],
])
def test_ambiguous_or_untyped_or_cross_origin_parent_remains_unknown(parent):
    resource, evidence = extracted("https://academy.example.org/lesson/x", {"@type": "VideoObject", "name": "Synthetic", "isPartOf": parent})
    assert resource["parent_course_url"] is None
    assert derive_course_identity(resource, evidence)["family_id"] is None


def test_observed_redirect_destination_supports_page_identity_without_rewriting_original_url():
    resolved = "https://academy.example.org/course/python"
    resource, evidence = extracted(resolved, {"@type": "Course", "name": "Python course"})
    original = "https://academy.example.org/old-entry"
    resource.update(url=original, canonical_url=original, resolved_url=resolved)
    assert has_course_page(resource, evidence)
    identity = derive_course_identity(resource, evidence)
    assert identity["source_url"] == identity["family_url"] == resolved
    assert resource["url"] == resource["canonical_url"] == original
    resource["resolved_url"] = "https://unrelated.example.org/course/x"
    assert not has_course_page(resource, evidence)


def test_safe_http_https_response_destination_not_html_canonical_drives_course_evidence():
    original, resolved = "http://academy.example.org/course/x", "https://academy.example.org/course/x"
    html = '<link rel="canonical" href="https://elsewhere.example.org/fake-course"><script type="application/ld+json">{"@type":"Course","name":"Python lists course"}</script>'
    metadata = MetadataExtractor().extract(html, resolved, STAMP)
    evidence = metadata.pop("evidence")
    resource = Resource(resource_id="redirected", url=original, canonical_url=original, resolved_url=resolved,
                        discovered_at=STAMP, **metadata).model_dump()
    assert has_course_page(resource, evidence)
    assert derive_course_identity(resource, evidence)["family_url"] == resolved
    resource.pop("resolved_url")
    assert not has_course_page(resource, evidence)


def test_same_title_and_archive_mirror_are_not_automatic_cross_source_course_identity():
    resources = []
    for index, url in enumerate(["https://archive.org/details/synthetic-sicp", "https://other.example.org/video/sicp"]):
        resource, evidence = extracted(url, {"@type": "VideoObject", "name": "Structure and Interpretation of Computer Programs"}, str(index))
        resource["catalog_kind"] = "video_playlist"
        resources.append(identified(resource, evidence))
    assert all(r["course_identity"]["family_id"] is None for r in resources)
    assert summarize_course_identities(resources)["identified_course_families"] == 0


def test_diversification_prefers_distinct_known_courses_and_keeps_unknown_resources_separate():
    def item(rid, family=None):
        return {"resource": {"resource_id": rid, "course_identity": {"family_id": family}}}
    items = [item("home-a", "a"), item("lesson-a", "a"), item("home-b", "b"), item("unknown-a"), item("unknown-b")]
    before = deepcopy(items)
    assert [item["resource"]["resource_id"] for item in diversify(items, 4)] == ["home-a", "home-b", "unknown-a", "unknown-b"]
    assert diversify(items, 5)[-1]["resource"]["resource_id"] == "lesson-a"
    assert items == before and diversify(items, 0) == []


def test_per_point_search_titles_are_order_invariant_and_do_not_borrow_other_point_text():
    url = "https://example.org/public-course"
    resource, first = searched(url, title="Python lists course", point_id="p1")
    second = dict(first[0], evidence_id="second", knowledge_point_id="p2", title="SQL joins course")
    request = SearchRequest(knowledge_points=["Python lists", "SQL joins"], language="any")
    observed_scores = []
    for global_title in [first[0]["title"], second["title"]]:
        resource["title"] = global_title
        before = deepcopy(resource)
        matches = []
        for pid, text, own in [("p1", "Python lists", first), ("p2", "SQL joins", [second])]:
            match = rank_resource({"knowledge_point_id": pid, "text": text}, resource, own, request,
                                  eligibility_evidence=first + [second])
            assert match and match["matched_evidence_ids"] == [own[0]["evidence_id"]]
            matches.append(match["ranking_score"])
        assert resource == before
        observed_scores.append(matches)
    assert observed_scores[0] == observed_scores[1]
    assert rank_resource({"knowledge_point_id": "p1", "text": "SQL joins"}, resource, first + [second], request) is None


def test_second_query_title_for_same_point_is_used_without_mutating_global_title():
    resource, evidence = searched("https://example.org/video/x", title="Programming course", point_id="p")
    evidence.append(dict(evidence[0], evidence_id="later", title="Python lists course"))
    match = rank_resource({"knowledge_point_id": "p", "text": "Python lists"}, resource, evidence,
                          SearchRequest(knowledge_points=["Python lists"]))
    assert match and match["matched_evidence_ids"] == ["later"]
    assert resource["title"] == "Programming course"
