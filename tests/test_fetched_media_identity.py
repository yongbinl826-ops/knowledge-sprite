"""Offline retained page replay: teaching facts and media identity are separate."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app import ranking, video_availability as availability, service
from backend.app.config import Settings
from backend.app.models import SearchRequest


def retained():
    return json.loads((Path(__file__).parent / "fixtures/media_identity/retained-css-generic-page.json").read_text(encoding="utf-8"))


def assessment(fixture):
    return ranking.rank_resource(fixture["point"], fixture["resource"], fixture["evidence"],
        SearchRequest(knowledge_points=[fixture["point"]["text"]]))


def test_actual_fetched_css_page_keeps_raw_url_and_teaching_facts_but_enters_review_only():
    fixture = retained(); before = deepcopy(fixture)
    assert ranking.has_learning_evidence(fixture["resource"], fixture["evidence"])
    assert availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])
    match = assessment(fixture)
    assert match and match["topic_evidence_status"] == "needs_review"
    assert match["topic_evidence_reasons"][0]["code"] == "media_identity_unconfirmed"
    assert match["supporting_evidence_ids"] == [] and all(row["status"] == "unknown" for row in match["subtopic_coverage"])
    projected = availability.project_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])
    assert projected["url"] == fixture["resource"]["url"] and "尚无" in projected["access_notice"]
    assert "无效" not in projected["access_notice"] and "文章" not in projected["access_notice"]
    assert fixture == before


def identity(fixture, kind="jsonld"):
    fixture = deepcopy(fixture); resource = fixture["resource"]; url = resource["canonical_url"]
    if kind == "title":
        eid = resource["field_provenance"]["title"]["evidence_id"]
        resource["title"] = "[Video] " + resource["title"]
        next(row for row in fixture["evidence"] if row["evidence_id"] == eid)["text"] = resource["title"]
        return fixture
    field = "video_evidence_status" if kind == "jsonld" else "resource_type"
    source = "jsonld.VideoObject" if kind == "jsonld" else "meta.og:type"
    text = "page_verified" if kind == "jsonld" else "video"
    if kind == "jsonld": resource["video_evidence_status"] = "page_verified"
    resource["field_provenance"][field] = {"evidence_id": "own-media", "source": source, "url": url}
    fixture["evidence"].append({"evidence_id": "own-media", "kind": "page", "field": field, "source": source, "url": url, "text": text})
    return fixture


@pytest.mark.parametrize("kind", ["jsonld", "ogtype", "title"])
def test_bound_own_video_identity_does_not_require_playback(kind):
    fixture = identity(retained(), kind)
    assert not availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])
    assert assessment(fixture)["topic_evidence_status"] == "partial"
    assert fixture["resource"]["playback_verified"] is False


@pytest.mark.parametrize("mutation", ["wrong-url", "wrong-id", "search-kind", "wrong-provenance-url"])
@pytest.mark.parametrize("kind", ["jsonld", "ogtype", "title"])
def test_foreign_or_unbound_media_fact_cannot_lift_unknown_identity(kind, mutation):
    fixture = identity(retained(), kind); resource = fixture["resource"]
    field = "title" if kind == "title" else "video_evidence_status" if kind == "jsonld" else "resource_type"
    origin = resource["field_provenance"][field]
    row = next(row for row in fixture["evidence"] if row["evidence_id"] == origin["evidence_id"])
    if mutation == "wrong-url": row["url"] = "https://example.org/other-video"
    elif mutation == "wrong-id": origin["evidence_id"] = "missing"
    elif mutation == "search-kind": row["kind"] = "search"
    else: origin["url"] = "https://example.org/other-video"
    assert availability.is_unconfirmed_fetched_media(resource, fixture["evidence"])


@pytest.mark.parametrize("kind", ["jsonld", "ogtype"])
@pytest.mark.parametrize("text", ["", "article", "unknown", "VideoObject", "course"])
def test_media_type_or_identity_status_must_have_the_actual_typed_value(kind, text):
    fixture = identity(retained(), kind)
    next(row for row in fixture["evidence"] if row["evidence_id"] == "own-media")["text"] = text
    assert availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])


@pytest.mark.parametrize("provider", ["fcc-python", "fcc-react", "twt-snake"])
def test_actual_publisher_bound_video_identities_are_preserved_without_playback(provider, monkeypatch):
    if provider.startswith("fcc"):
        from tests.test_freecodecamp_course_announcement import html_fixture, resource_from
        html, url = html_fixture(0 if provider == "fcc-python" else 1)
        resource = resource_from(html, url)
    else:
        from tests.test_twt_recall_and_clock import extract, snake_html
        resource = extract(monkeypatch, snake_html())
    assert resource["video_evidence_status"] == "page_verified"
    assert not availability.is_unconfirmed_fetched_media(resource, resource["evidence"])


@pytest.mark.parametrize("field", ["requires_login", "requires_payment", "requires_enrollment"])
def test_access_flags_are_kept_and_do_not_disqualify_bound_video_identity(field):
    fixture = identity(retained(), "ogtype")
    fixture["resource"][field] = True
    fixture["resource"]["access_notice"] = "来源标注需要账号或购买；尚未验证播放。"
    before = deepcopy(fixture["resource"])
    assert availability.project_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"]) == before
    assert assessment(fixture)["topic_evidence_status"] == "partial"


@pytest.mark.parametrize("status", ["not_fetched", "login_required", "access_denied", "rate_limited", "javascript_required"])
def test_access_or_unfetched_state_is_not_called_an_invalid_or_nonvideo_page(status):
    fixture = retained(); fixture["resource"]["fetch_status"] = status
    assert not availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])


@pytest.mark.parametrize("kind", ["course", "playlist"])
def test_generic_search_template_media_type_cannot_bypass_own_identity(kind):
    fixture = retained(); fixture["resource"]["resource_type"] = kind
    assert availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])


def test_known_public_video_entry_proof_keeps_existing_identity_contract():
    fixture = json.loads((Path(__file__).parent / "fixtures/media_identity/namespace_datetime_candidate.json").read_text(encoding="utf-8"))
    resource = fixture["resource"]
    # Controlled state transition of a retained real public video entry, with
    # no added own video fact or new fetch. Its exact public entry format is
    # already recognized by the existing URL identity contract.
    assert ranking.type_from_discovered_url(resource["url"]) == "video"
    resource["fetch_status"] = "fetched"
    resource["metadata_evidence_level"] = "page"
    assert not availability.is_unconfirmed_fetched_media(resource, fixture["evidence"])


def test_actual_bound_bilibili_page_video_identity_stays_partial():
    fixture = json.loads((Path(__file__).parent / "fixtures/media_identity/group_count_related_tail.json").read_text(encoding="utf-8"))
    assert fixture["resource"]["video_evidence_status"] == "page_verified"
    assert not availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])
    assert ranking.rank_resource(fixture["point"], fixture["resource"], fixture["evidence"],
        SearchRequest(knowledge_points=[fixture["point"]["text"]], **fixture["request"]))["topic_evidence_status"] == "partial"


def test_persisted_old_partial_row_moves_only_to_review_in_real_result_projection():
    fixture = retained(); before = deepcopy(fixture)
    point, resource, evidence = fixture["point"], fixture["resource"], fixture["evidence"]
    request = SearchRequest(knowledge_points=[point["text"]]).model_dump()
    class ReadOnlyRows:
        def get_job(self, job_id):
            return {"job_id": job_id, "status": "partial", "request": request, "knowledge_points": [point], "warnings": []}
        def resources(self, job_id): return {resource["resource_id"]: deepcopy(resource)}
        def matches(self, job_id): return [deepcopy(fixture["match"])]
        def evidence(self, job_id, rid, point_id=None): return deepcopy(evidence)
        def attempts(self, job_id): return []
    jobs = service.JobService.__new__(service.JobService); jobs.store = ReadOnlyRows(); jobs.settings = Settings()
    first = jobs.results("retained-job"); second = jobs.results("retained-job")
    assert first == second
    group = first["groups"][0]
    assert group["items"] == group["partial_items"] == []
    assert len(group["review_items"]) == 1 and "尚无" in group["review_items"][0]["resource"]["access_notice"]
    assert group["collection_coverage"]["status"] == "unknown"
    assert fixture == before


def test_identity_projection_does_not_invent_a_relevant_candidate():
    fixture = retained()
    assert availability.unconfirmed_fetched_media_assessment(None, fixture["resource"], fixture["evidence"]) is None


def native_fixture(url, media_type="video"):
    fixture = retained(); resource = fixture["resource"]
    resource.update(url=url, canonical_url=url, resource_type=media_type,
                    video_evidence_status="search_discovered" if media_type == "video" else "none")
    origin = {"source": "url_pattern", "evidence_id": "native-search", "url": url}
    resource["field_provenance"] = {"resource_type": dict(origin), "video_evidence_status": dict(origin)}
    fixture["evidence"] = [{"evidence_id": "native-search", "kind": "search", "source": "searxng:bilibili",
        "url": url, "title": "Observed lesson", "type_source": "search_template", "resource_type_hint": media_type}]
    return fixture


@pytest.mark.parametrize("url,kind", [
    ("https://www.bilibili.com/video/BV1ab411c7de", "video"),
    ("https://www.youtube.com/watch?v=123456789a_", "video"),
    ("https://youtu.be/123456789a_", "video"),
    ("https://www.icourse163.org/course/PKU-1003479006", "course"),
    ("https://www.xuetangx.com/course/observed-course", "course"),
])
def test_native_entry_is_independently_recognized_and_bound_to_search(url, kind):
    fixture = native_fixture(url, kind)
    assert availability.native_media_entry_type(url) == ranking.type_from_discovered_url(url) == kind
    assert not availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])


@pytest.mark.parametrize("url", [
    "https://example.org/article", "https://www.bilibili.com/read/cv1234",
    "https://bilibili.com.evil.org/video/BV1ab411c7de", "https://example.org/video/BV1ab411c7de",
    "https://youtube.com.evil.org/watch?v=123456789a_", "https://youtu.be.evil.org/123456789a_",
    "https://www.youtube.com/watch?v=123456789a_&v=another1234", "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/channel/123456789a_", "https://example.org/course/PKU-1003479006",
])
def test_url_pattern_label_on_generic_or_lookalike_page_never_confirms_identity(url):
    fixture = native_fixture(url)
    assert availability.native_media_entry_type(url) == "unknown"
    assert availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])


@pytest.mark.parametrize("mutation", ["no-source", "wrong-row-url", "wrong-origin-url", "missing-id", "page-kind", "template-origin", "wrong-type"])
def test_native_entry_exemption_still_requires_the_correct_source_binding(mutation):
    fixture = native_fixture("https://www.youtube.com/watch?v=123456789a_")
    resource, row = fixture["resource"], fixture["evidence"][0]
    if mutation == "no-source": row["source"] = ""
    elif mutation == "wrong-row-url": row["url"] = "https://example.org/article"
    elif mutation == "wrong-origin-url":
        for origin in resource["field_provenance"].values(): origin["url"] = "https://example.org/article"
    elif mutation == "missing-id": row["evidence_id"] = "other"
    elif mutation == "page-kind": row["kind"] = "page"
    elif mutation == "template-origin":
        for origin in resource["field_provenance"].values(): origin["source"] = "search_template"
    else: resource["resource_type"] = "course"
    assert availability.is_unconfirmed_fetched_media(resource, fixture["evidence"])


@pytest.mark.parametrize("media_type", ["course", "playlist"])
def test_generic_course_or_playlist_is_review_not_invalid_with_coverage_removed(media_type):
    fixture = retained(); fixture["resource"]["resource_type"] = media_type
    before = deepcopy(fixture)
    match = availability.unconfirmed_fetched_media_assessment(fixture["match"], fixture["resource"], fixture["evidence"])
    assert match["topic_evidence_status"] == "needs_review" and match["supporting_evidence_ids"] == []
    assert all(part["status"] == "unknown" and part["evidence_ids"] == [] for part in match["subtopic_coverage"])
    projected = availability.project_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])
    assert projected["resource_type"] == media_type and "无效" not in projected["access_notice"]
    assert fixture == before


def test_own_jsonld_course_preserves_course_identity_without_video_claim():
    from tests.test_course_identity import extracted
    resource, evidence = extracted("https://academy.example.org/courses/python-lists", {
        "@type": "Course", "name": "Python lists course", "description": "Learn Python lists with worked examples."})
    assert not availability.is_unconfirmed_fetched_media(resource, evidence)
    assert resource["resource_type"] == "course" and resource["video_evidence_status"] == "none"


@pytest.mark.parametrize("mutation", ["wrong-type", "empty-type", "wrong-url", "wrong-source", "wrong-kind", "wrong-id"])
def test_course_own_type_is_not_granted_from_invalid_or_unbound_fact(mutation):
    from tests.test_course_identity import extracted
    resource, evidence = extracted("https://academy.example.org/courses/python-lists", {"@type": "Course", "name": "Python lists course"})
    row = next(row for row in evidence if row["field"] == "resource_type")
    if mutation == "wrong-type": row["text"] = "Article"
    elif mutation == "empty-type": row["text"] = ""
    elif mutation == "wrong-url": row["url"] = "https://other.example.org/course"
    elif mutation == "wrong-source": row["source"] = "search_template"
    elif mutation == "wrong-kind": row["kind"] = "search"
    else: row["evidence_id"] = "other"
    assert availability.is_unconfirmed_fetched_media(resource, evidence)


@pytest.mark.parametrize("capture_name", ["mooc-dom.html", "mooc-term-dom.html"])
def test_actual_icourse_course_structure_is_preserved(capture_name):
    from tests.test_platform_catalog_adapters import capture, extract, MOOC
    markup = capture("mooc-dom.html")
    if capture_name == "mooc-term-dom.html":
        # Explicit same-page composition, matching the retained adapter test.
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(markup, "html.parser")
        soup.body.append(BeautifulSoup(capture(capture_name), "html.parser"))
        markup = str(soup)
    resource = extract(markup, MOOC)
    resource["url"] = resource["canonical_url"] = MOOC
    resource["fetch_status"] = "fetched"
    assert resource["resource_type"] == "course"
    assert not availability.is_unconfirmed_fetched_media(resource, resource["evidence"])


@pytest.mark.parametrize("source,kind,url", [
    ("html.mit_ocw.video_player", "video", "https://ocw.mit.edu/courses/a/resources/lecture/"),
    ("html.mit_ocw.video_gallery", "playlist", "https://ocw.mit.edu/courses/a/video_galleries/lectures/"),
    ("html.archive.play_av.playlist", "playlist", "https://archive.org/details/observed-course"),
])
def test_registered_own_source_media_structure_has_typed_bound_identity(source, kind, url):
    fixture = native_fixture(url, kind); resource = fixture["resource"]
    resource["field_provenance"] = {"resource_type": {"source": source, "evidence_id": "type", "url": url}}
    fixture["evidence"] = [{"evidence_id": "type", "kind": "page", "field": "resource_type", "source": source,
                            "url": url, "text": "Registered parser observed this own media structure; playback not tested"}]
    assert not availability.is_unconfirmed_fetched_media(resource, fixture["evidence"])
    resource["url"] = resource["canonical_url"] = "https://example.org/article"
    resource["field_provenance"]["resource_type"]["url"] = fixture["evidence"][0]["url"] = resource["url"]
    assert availability.is_unconfirmed_fetched_media(resource, fixture["evidence"])


@pytest.mark.parametrize("media_type", ["video", "course", "playlist"])
def test_successful_fetch_without_own_metadata_cannot_launder_search_template(media_type):
    fixture = retained(); fixture["resource"].update(resource_type=media_type, metadata_evidence_level="search")
    assert availability.is_unconfirmed_fetched_media(fixture["resource"], fixture["evidence"])
