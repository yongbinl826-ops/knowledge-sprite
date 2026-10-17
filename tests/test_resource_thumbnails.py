"""Observed cover metadata and cache provenance; all inputs are isolated fixtures."""
import json

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, Resource, SearchRequest
from backend.app.providers import parse_candidates
from backend.app.service import JobService
from backend.app.url_utils import safe_thumbnail_url


URL = "https://www.icourse163.org/course/PKU-1003479006"
IMAGE = "https://images.example.org/python.jpg?imageView&thumbnail=510y288&quality=100"
AT = "2026-10-17T05:00:00+00:00"


@pytest.mark.parametrize("reference", [
    "data:image/png;base64,AAAA", "javascript:alert(1)", "file:///C:/secret.png",
    "http://localhost/image.jpg", "http://127.0.0.1/image.jpg", "http://127.1/image.jpg",
    "http://0177.0.0.1/image.jpg", "http://0x7f.0.0.1/image.jpg", "http://192.168.1.1/image.jpg",
    "http://[::1]/image.jpg", "https://user:password@example.org/image.jpg",
    "https://example.org:8080/image.jpg", "https://example.org/\nimage.jpg", "//localhost/img.jpg",
    "https://image.internal/image.jpg", "https://image.local/image.jpg", "", None, {"url": IMAGE},
])
def test_invalid_cover_references_stay_unknown(reference):
    assert safe_thumbnail_url(reference, URL) is None
    assert Candidate(id="x", title="Course", url=URL, source="test", query="Python",
                     thumbnail_url=reference).thumbnail_url is None


def test_image_reference_preserves_cdn_query_and_resolves_observed_relative_path():
    assert safe_thumbnail_url(IMAGE + "#unused", URL) == IMAGE
    assert safe_thumbnail_url("//images.example.org/cover.jpg", URL) == "https://images.example.org/cover.jpg"
    assert safe_thumbnail_url("/covers/course.jpg", URL) == "https://www.icourse163.org/covers/course.jpg"


@pytest.mark.parametrize("field,value", [
    ("thumbnailUrl", IMAGE),
    ("thumbnailUrl", ["javascript:alert(1)", IMAGE]),
    ("image", {"@type": "ImageObject", "contentUrl": IMAGE}),
    ("image", [{"url": IMAGE}]),
])
def test_jsonld_cover_has_linked_page_evidence(field, value):
    node = {"@type": "Course", "name": "Python", field: value}
    html = '<script type="application/ld+json">' + json.dumps(node) + "</script>"
    result = MetadataExtractor().extract(html, URL, AT)
    assert result["thumbnail_url"] == IMAGE
    provenance = result["field_provenance"]["thumbnail_url"]
    assert provenance["source"] == "jsonld." + field and provenance["url"] == URL
    record = next(row for row in result["evidence"] if row["evidence_id"] == provenance["evidence_id"])
    assert record["kind"] == "page" and record["field"] == "thumbnail_url"
    assert record["text"] == IMAGE and record["fetched_at"] == AT


def test_og_cover_falls_back_from_invalid_primary_image_but_never_uses_arbitrary_img():
    html = ('<html><title>Python course</title><meta property="og:image" content="http://127.0.0.1/img">'
            '<meta property="og:image:secure_url" content="' + IMAGE + '"><img src="https://images.example.org/ad.jpg"></html>')
    result = MetadataExtractor().extract(html, URL, AT)
    assert result["thumbnail_url"] == IMAGE
    assert result["field_provenance"]["thumbnail_url"]["source"] == "meta.og:image:secure_url"
    missing = MetadataExtractor().extract('<h1>Python course</h1><img src="' + IMAGE + '">', URL, AT)
    assert "thumbnail_url" not in missing
    assert Resource(resource_id="r", title="Python", url=URL, canonical_url=URL, discovered_at=AT).thumbnail_url is None


def mooc_page(image=IMAGE):
    return ('<html><title>Python课程</title><div id="j-course-heading-intro">'
            '<div class="course-heading-intro_intro">Python 列表入门课程介绍</div></div>'
            '<div id="j-courseImg"><img class="img" src="' + image + '"></div>'
            '<div id="j-course-outline"><div class="f-richEditorText"><p>Python 列表基础</p></div></div></html>')


def test_mooc_cover_is_tied_to_course_structure_and_has_independent_evidence():
    result = MetadataExtractor().extract(mooc_page(), URL, AT)
    assert result["thumbnail_url"] == IMAGE
    assert result["field_provenance"]["thumbnail_url"]["source"] == "html.icourse163.course_cover"
    assert result["chapters"][0]["title"] == "Python 列表基础"
    assert result["chapters"][0]["evidence_id"] != result["field_provenance"]["thumbnail_url"]["evidence_id"]
    assert "thumbnail_url" not in MetadataExtractor().extract(mooc_page(), "https://example.org/page", AT)
    assert "thumbnail_url" not in MetadataExtractor().extract(mooc_page("data:image/png;base64,AAAA"), URL, AT)


def test_blocked_page_does_not_promote_cover_metadata():
    result = MetadataExtractor().extract('<title>Access denied</title><meta property="og:image" content="' + IMAGE + '">', URL, AT)
    assert result["fetch_status"] == "access_denied" and "thumbnail_url" not in result


def test_search_only_preserves_supplied_searx_thumbnail_without_generating_one():
    item = {"title": "Python 列表视频", "url": "https://www.bilibili.com/video/BV1234567890", "thumbnail": IMAGE}
    candidate = parse_candidates([item], "searxng", "Python 列表", 1, [])[0]
    assert candidate.thumbnail_url == IMAGE and candidate.thumbnail_source == "search.thumbnail"
    for field in ({}, {"thumbnail": "data:image/png;base64,AAAA"}, {"image": IMAGE}):
        row = dict(item)
        row.pop("thumbnail")
        row.update(field)
        assert parse_candidates([row], "searxng", "Python 列表", 1, [])[0].thumbnail_url is None


class ThumbnailSearch:
    name = "isolated-cover-test"

    async def search(self, query, language, limit, domains):
        return [Candidate(id="cover", title="Python 列表课程", url=URL, snippet="Python 列表教学",
            source=self.name, query=query, thumbnail_url="https://images.example.org/search.jpg",
            thumbnail_source="search.thumbnail")]


class ThumbnailFetcher:
    def __init__(self, page=True):
        self.page = page
        self.calls = 0

    async def enrich(self, candidate):
        self.calls += 1
        return MetadataExtractor().extract(mooc_page(), URL, AT) if self.page else {
            "fetch_status": "site_policy_blocked", "evidence": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [True, False])
async def test_service_keeps_correct_cover_provenance_through_cache_and_api_model(page):
    store = Store(":memory:")
    fetcher = ThumbnailFetcher(page)
    service = JobService(Settings(max_search_requests=1, max_detail_pages=1, official_sitemap_fallback=False),
                         store, provider=ThumbnailSearch(), fetcher=fetcher)
    try:
        for _ in range(2):
            job = service.create(SearchRequest(knowledge_points=["Python 列表"], preferred_platforms=[]))["job_id"]
            await service.run(job)
            resource = next(iter(store.resources(job).values()))
            assert resource["thumbnail_url"] == (IMAGE if page else "https://images.example.org/search.jpg")
            assert Resource.model_validate(resource).thumbnail_url == resource["thumbnail_url"]
            basis = resource["field_provenance"]["thumbnail_url"]
            record = next(row for row in store.evidence(job, resource["resource_id"]) if row["evidence_id"] == basis["evidence_id"])
            assert basis["source"] == ("html.icourse163.course_cover" if page else "search.thumbnail")
            assert record["kind"] == ("page" if page else "search")
            if not page:
                assert record["thumbnail_url"] == resource["thumbnail_url"]
        assert fetcher.calls == 1
    finally:
        store.close()
