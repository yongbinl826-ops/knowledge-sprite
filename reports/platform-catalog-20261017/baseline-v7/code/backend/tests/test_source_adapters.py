"""Isolated static fixtures. These are regression tests, not live-site acceptance."""
import html
import json

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.source_adapters import ADAPTERS
from backend.app.source_adapters.archive import duration_seconds


MIT = "https://ocw.mit.edu/courses/isolated-example/"
ARCHIVE = "https://archive.org/details/isolated-example"


def extract(markup, url):
    return MetadataExtractor().extract(markup, url, "2026-10-13T00:00:00+00:00")


def test_registry_is_explicit_and_does_not_match_lookalike_hosts():
    assert {adapter.name for adapter in ADAPTERS} == {"mit_ocw", "archive_details", "microsoft_ai_curriculum"}
    for url in ("https://ocw.mit.edu.evil.org/courses/example/", "https://archive.org.evil.org/details/example"):
        assert not any(adapter.matches(url) for adapter in ADAPTERS)


@pytest.mark.parametrize(("value", "expected"), [(30, 30), (30.25, 30.25), ("30.25", 30.25), (" 30 ", 30)])
def test_archive_duration_preserves_seconds(value, expected):
    assert duration_seconds(value) == expected


@pytest.mark.parametrize("value", [None, True, False, 0, -1, "0", "-1", "1:30", "NaN", "Infinity", "1e1000", float("nan"), float("inf"), {}, [], 10 ** 1000])
def test_archive_invalid_duration_remains_unknown(value):
    assert duration_seconds(value) is None


def test_archive_duration_is_per_item_evidence_not_offset_total_or_generated_url():
    args = html.escape(json.dumps({"audio": False, "identifier": "isolated-example"}), quote=True)
    items = [
        {"title": title, "duration": duration, "sources": [{"type": "mp4", "file": f"/download/isolated-example/{index}.mp4"}]}
        for index, (title, duration) in enumerate([("One", "30.25"), ("Two", 50), ("Unknown", "bad")])
    ]
    playlist = html.escape(json.dumps(items), quote=True)
    result = extract(f'<title>Fixture</title><play-av args="{args}" playlist="{playlist}"></play-av>', ARCHIVE)
    assert [chapter["duration_seconds"] for chapter in result["chapters"]] == [30.25, 50, None]
    assert "duration_seconds" not in result
    evidence = {entry["evidence_id"]: entry for entry in result["evidence"]}
    for index, chapter in enumerate(result["chapters"]):
        assert chapter["url"] is None and chapter["start_seconds"] is None and chapter["end_seconds"] is None
        assert chapter["source_url"] == ARCHIVE
        entry = evidence[chapter["evidence_id"]]
        assert entry["field"] == f"chapters.{index}"
        assert json.loads(entry["text"])["duration_seconds"] == chapter["duration_seconds"]


def test_archive_visible_metadata_keeps_creator_role_and_full_description():
    result = extract('''<meta property="og:title" content="Resource | Site suffix">
      <meta property="og:description" content="Truncated...">
      <h1><span itemprop="name">Specific resource</span></h1>
      <span itemprop="creator">Fixture institution</span>
      <div id="descript" itemprop="description">Full resource description and actual topics.</div>''', ARCHIVE)
    assert result["title"] == "Specific resource"
    assert result["description"] == "Full resource description and actual topics."
    assert result["author"] == "Fixture institution"
    assert result["author_role"] == "credited_creator"
    assert result["field_provenance"]["author"]["source"] == "html.archive.creator"


@pytest.mark.parametrize("suffix", ["", "video_galleries/lectures/"])
def test_mit_course_and_gallery_deduplicate_course_instructors(suffix):
    result = extract('''<title>Course | MIT site</title><div id="course-banner"><h1>Fixture course</h1></div>
      <a class="course-info-instructor">Course instructor A</a>
      <a class="course-info-instructor">Course instructor B</a>
      <a class="course-info-instructor">Course instructor A</a>''', MIT + suffix)
    assert result["author"] == "Course instructor A, Course instructor B"
    assert result["author_role"] == "course_instructors"
    assert result["field_provenance"]["author"]["source"] == "html.mit_ocw.course_instructors"


def test_mit_chapter_uses_its_own_description_and_instructors_not_course_staff():
    result = extract('''<title>Lecture example</title><meta property="og:description" content="Generic site text">
      <a class="course-info-instructor">Other year's course instructor</a>
      <div class="video-page"><div class="description">
      <p><strong>Topics covered</strong>: Recursion and evaluation</p>
      <p><strong>Instructors:</strong> Lecture instructor A and Lecture instructor B</p>
      </div><div class="video-player-wrapper"><video></video></div></div>''', MIT + "resources/lecture-a/")
    assert result["author"] == "Lecture instructor A and Lecture instructor B"
    assert result["author_role"] == "video_instructors"
    role_id = result["field_provenance"]["author_role"]["evidence_id"]
    role_evidence = next(item for item in result["evidence"] if item["evidence_id"] == role_id)
    assert role_evidence["field"] == "author_role" and "Instructors:" in role_evidence["text"]
    assert result["field_provenance"]["author"]["source"] == "html.mit_ocw.video_instructors"
    assert "Recursion and evaluation" in result["description"] and "Generic site text" not in result["description"]
    assert result["field_provenance"]["description"]["source"] == "html.mit_ocw.video_description"
    assert result["video_evidence_status"] == "page_verified"


def test_mit_chapter_without_instructor_label_does_not_copy_course_staff():
    result = extract('''<title>Lecture example</title><a class="course-info-instructor">Course staff</a>
      <div class="video-page"><div class="description"><p>Topics covered: Recursion</p>
      <p><strong>Subtitles:</strong> Subtitle contributor</p></div></div>''', MIT + "resources/lecture-a/")
    assert "author" not in result
    assert "author_role" not in result
    assert result["video_evidence_status"] == "none"


def test_dom_author_role_is_not_assigned_to_a_different_jsonld_author():
    result = extract('''<script type="application/ld+json">
      {"@type":"Course","name":"Course fixture","author":{"name":"Explicit author"}}
      </script><a class="course-info-instructor">Different course staff</a>''', MIT)
    assert result["author"] == "Explicit author"
    assert "author_role" not in result


def test_gallery_specific_description_and_actual_links_preserve_catalog_evidence():
    result = extract('''<title>Video Lectures</title><meta property="og:description" content="Generic site text">
      <main id="course-content-section"><p>Actual collection description.</p>
      <div class="video-gallery-card"><a class="video-link" href="/courses/isolated-example/resources/one/">
      <h5 class="video-title">Lecture One</h5></a></div></main>''', MIT + "video_galleries/lectures/")
    assert result["description"] == "Actual collection description."
    assert result["chapters"][0]["url"] == MIT + "resources/one/"
    assert "duration_seconds" not in result["chapters"][0]
    assert result["field_provenance"]["chapters"]["source"] == "html.mit_ocw.video_gallery"


def test_hidden_source_metadata_does_not_override_generic_fallback():
    result = extract('''<title>Visible title</title><meta property="og:description" content="Visible fallback">
      <div class="video-page"><div class="description" hidden>
      <p><strong>Instructors:</strong> Hidden false instructor</p></div></div>''', MIT + "resources/lecture-a/")
    assert result["description"] == "Visible fallback"
    assert "author" not in result
