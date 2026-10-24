"""Offline MOOC cover facts; synthetic markup never asserts live coverage."""
import json

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.helpful_video_chapters import observed_cover


URL = "https://www.icourse163.org/course/detail.htm?cid=123&tid=456"
IMAGE = "https://mooc-image.nosdn.127.net/observed-course-cover.jpg"
OTHER_IMAGE = "https://images.example.org/related-course.jpg"
STAMP = "2026-10-23T14:00:00+00:00"


def course_page(*, course_id="123", term_id="456", outline=None, cover=IMAGE,
                script=True, jsonld_image=None):
    term = {"id": term_id}
    if outline is not None:
        term["outLineDto"] = {"outLine": outline}
    payload = ("window.termDto = " + json.dumps(term) + "; window.courseDto = "
               + json.dumps({"id": course_id, "name": "Python课程"}) + ";")
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@type": "Course", "name": "Related course", "image": jsonld_image}) + "</script>"
              if jsonld_image is not None else "")
    return ('<html><head><title>Python课程</title>' + jsonld + '</head><body>'
            '<div id="j-course-heading-intro"><div class="course-heading-intro_intro">课程介绍</div></div>'
            '<div id="j-courseImg"><img class="img" src="' + cover + '"></div>'
            '<div id="j-course-outline"></div>'
            + ("<script>" + payload + "</script>" if script else "") + "</body></html>")


@pytest.mark.parametrize("outline", [None, "", "<p></p>"])
def test_same_course_legacy_cover_does_not_require_available_curriculum(outline):
    metadata = MetadataExtractor().extract(course_page(outline=outline), URL, STAMP)
    assert metadata["chapters"] == []
    assert metadata["thumbnail_url"] == IMAGE
    assert metadata["field_provenance"]["thumbnail_url"]["source"] == "html.icourse163.course_cover"
    cover = observed_cover({"url": URL}, {"url": URL, **metadata})
    assert cover["thumbnail_url"] == IMAGE and cover["source_url"] == URL
    evidence = next(row for row in metadata["evidence"] if row["field"] == "thumbnail_url")
    assert evidence["text"] == IMAGE and evidence["url"] == URL
    assert not metadata.get("playback_verified")


@pytest.mark.parametrize("changes", [
    {"course_id": "999"}, {"term_id": "999"}, {"course_id": True}, {"term_id": True},
    {"script": False}, {"cover": "https://127.0.0.1/private.png"},
])
def test_legacy_cover_requires_safe_image_and_literal_course_term_binding(changes):
    metadata = MetadataExtractor().extract(course_page(**changes), URL, STAMP)
    assert "thumbnail_url" not in metadata
    assert observed_cover({"url": URL}, {"url": URL, **metadata}) is None


@pytest.mark.parametrize("url", [URL, "https://www.icourse163.org/course/OWN-123"])
@pytest.mark.parametrize("jsonld_image", [IMAGE, OTHER_IMAGE])
def test_native_cover_wins_over_generic_jsonld_and_retains_independent_evidence(url, jsonld_image):
    metadata = MetadataExtractor().extract(course_page(jsonld_image=jsonld_image), url, STAMP)
    assert metadata["thumbnail_url"] == IMAGE
    receipt = metadata["field_provenance"]["thumbnail_url"]
    assert receipt["source"] == "html.icourse163.course_cover"
    old = next(row for row in metadata["evidence"] if row["source"] == "jsonld.image")
    current = next(row for row in metadata["evidence"] if row["evidence_id"] == receipt["evidence_id"])
    assert old["text"] == jsonld_image and current["text"] == IMAGE
    assert current["kind"] == "page" and current["url"] == url
    assert observed_cover({"url": url}, {"url": url, **metadata})


def test_generic_jsonld_alone_is_not_promoted_into_a_native_cover_fact():
    metadata = MetadataExtractor().extract(course_page(script=False, jsonld_image=OTHER_IMAGE), URL, STAMP)
    assert metadata["thumbnail_url"] == OTHER_IMAGE
    assert metadata["field_provenance"]["thumbnail_url"]["source"] == "jsonld.image"
    assert observed_cover({"url": URL}, {"url": URL, **metadata}) is None
