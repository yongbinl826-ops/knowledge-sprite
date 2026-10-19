"""Replay real publicly fetched announcement HTML; no network or video media."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource, SearchRequest
from backend.app.ranking import rank_resource, topic_observations
from backend.app.source_adapters.freecodecamp import FreeCodeCampCourseAdapter, bound_video_topic_summary


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ("article-0.html", "https://www.freecodecamp.org/news/learn-python-interactively/", "a067cda6ce4f322e7942a6ce370aaa47e464e93565bc2d5256adfc9d0f56ad03", "kLZgQWjnUz0"),
    ("article-1-retry.html", "https://www.freecodecamp.org/news/master-modern-react-routing-tanstack-router-crash-course/", "2a1ce70e07e41aeadf5386276d86b9f43bf095f479aa9f086082a79584d4bb80", "P-UIf7V7gV0"),
)


def html_fixture(index=0):
    name, url, expected_sha, _ = FIXTURES[index]
    raw = (ROOT / "tests/fixtures/freecodecamp" / name).read_bytes()
    manifest = json.loads((ROOT / "tests/fixtures/freecodecamp/public-source-manifest.json").read_text(encoding="utf-8"))
    source = next(row for row in manifest if row["fixture"] == name)
    assert source["source_sha256"] == expected_sha
    assert sha256(raw).hexdigest() == source["fixture_sha256"]
    return raw.decode("utf-8"), url


def resource_from(html, url):
    result = MetadataExtractor().extract(html, url, "2026-10-18T00:00:00Z")
    result.update(resource_id="r", url=url, canonical_url=url)
    return result


@pytest.mark.parametrize("index", [0, 1])
def test_real_announcement_binds_single_visible_video_without_inventing_chapters(index):
    html, url = html_fixture(index)
    resource = resource_from(html, url)
    assert resource["resource_type"] == "video" and resource["video_evidence_status"] == "page_verified"
    assert resource["chapters"] == []
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert summary and len(summary) <= 1800
    assert "Recommended courses from our partners" not in summary
    assert "40,000 people get jobs" not in summary
    assert "I'm a teacher and developer" not in summary
    proof = next(row for row in resource["evidence"] if row.get("field") == "video_evidence_status")
    assert json.loads(proof["text"])["video_id"] == FIXTURES[index][3]
    assert "no player/media request" in proof["text"]


@pytest.mark.parametrize("damage", ["no_declaration", "no_iframe", "no_watch_link", "different_watch", "different_embed_host", "hidden_iframe", "outside_article", "outside_content", "two_videos", "no_heading", "wrong_domain"])
def test_article_embed_or_unbound_links_do_not_promote_video(damage):
    html, url = html_fixture()
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("article.post-full section.post-content")
    frame = body.select_one("iframe")
    anchor = body.select_one('a[href*="youtube.com/watch"]')
    if damage == "no_declaration":
        for p in body.find_all("p", recursive=False):
            if "We just published" in p.get_text():
                p.decompose()
    elif damage == "no_iframe":
        frame.decompose()
    elif damage == "no_watch_link":
        anchor.decompose()
    elif damage == "different_watch":
        anchor["href"] = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    elif damage == "different_embed_host":
        frame["src"] = "https://www.youtube.com.attacker.example/embed/kLZgQWjnUz0"
    elif damage == "hidden_iframe":
        frame.parent["hidden"] = ""
    elif damage == "outside_article":
        soup.body.append(frame.extract())
    elif damage == "outside_content":
        soup.select_one("article.post-full").append(frame.extract())
    elif damage == "two_videos":
        second = BeautifulSoup('<iframe src="https://www.youtube.com/embed/aaaaaaaaaaa"></iframe>', "html.parser").iframe
        body.append(second)
    elif damage == "no_heading":
        soup.select_one("h1.post-full-title").decompose()
    elif damage == "wrong_domain":
        url = url.replace("www.freecodecamp.org", "www.freecodecamp.org.attacker.example")
    result = resource_from(str(soup), url)
    assert result.get("video_evidence_status") != "page_verified"
    assert result.get("resource_type") != "video"
    assert not result.get("video_topic_summary")


def test_non_course_article_and_generic_embeds_remain_text():
    url = "https://www.freecodecamp.org/news/plain-python-article/"
    html = ('<article class="post-full"><h1 class="post-full-title">Python article</h1><section class="post-content">'
            '<p>This article explains Python variables and shows a reference video.</p>'
            '<a href="https://www.youtube.com/watch?v=kLZgQWjnUz0">freeCodeCamp.org YouTube channel</a>'
            '<iframe src="https://www.youtube.com/embed/kLZgQWjnUz0"></iframe></section></article>')
    assert not FreeCodeCampCourseAdapter().extract(BeautifulSoup(html, "html.parser"), url).fields


def test_declared_course_topics_are_separate_from_article_meta_search_footer_and_navigation():
    html, url = html_fixture()
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.post-full")
    article.append(BeautifulSoup('<aside><p>Python quantum mechanics</p></aside><nav class="chapter-list"><a href="/news/another-lesson/">Python quantum mechanics</a></nav>', "html.parser"))
    for script in soup.select('script[type="application/ld+json"]'):
        data = json.loads(script.get_text())
        data["description"] = "Python quantum mechanics is explained in this article."
        script.string = json.dumps(data)
    resource = resource_from(str(soup), url)
    assert resource["chapters"] == []
    evidence = resource["evidence"] + [{"evidence_id": "s", "kind": "search", "knowledge_point_id": "p", "url": url,
                                       "source": "synthetic-adversarial-excerpt", "title": resource["title"], "snippet": "Python quantum mechanics"}]
    before = deepcopy((resource, evidence))
    point = {"knowledge_point_id": "p", "text": "Python quantum mechanics"}
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])) is None
    assert all("quantum mechanics" not in row["raw"] for row in topic_observations(point, resource, evidence))
    assert (resource, evidence) == before
    learning = {"knowledge_point_id": "p", "text": "Python variables and user input"}
    match = rank_resource(learning, resource, evidence, SearchRequest(knowledge_points=[learning["text"]]))
    assert match and match["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("damage", ["missing_summary_evidence", "wrong_summary_url", "wrong_summary_provenance", "changed_summary", "different_video_binding", "changed_course_title", "unverified_page"])
def test_retained_binding_must_be_recheckable_before_any_topic_coverage(damage):
    html, url = html_fixture()
    resource = resource_from(html, url)
    evidence = deepcopy(resource["evidence"])
    if damage == "missing_summary_evidence":
        evidence = [row for row in evidence if row.get("field") != "video_topic_summary"]
    elif damage == "wrong_summary_url":
        next(row for row in evidence if row.get("field") == "video_topic_summary")["url"] = "https://www.freecodecamp.org/news/other-course/"
    elif damage == "wrong_summary_provenance":
        resource["field_provenance"]["video_topic_summary"]["source"] = "meta.description"
    elif damage == "changed_summary":
        resource["video_topic_summary"] += " Python quantum mechanics"
    elif damage == "different_video_binding":
        row = next(row for row in evidence if row.get("field") == "video_evidence_status")
        payload = json.loads(row["text"]); payload["watch_url"] = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
        row["text"] = json.dumps(payload)
    elif damage == "changed_course_title":
        resource["title"] = "Other course"
    elif damage == "unverified_page":
        resource["fetch_status"] = "search_only_policy"
    assert bound_video_topic_summary(resource, evidence) is None
    point = {"knowledge_point_id": "p", "text": "Python variables and user input"}
    evidence.append({"evidence_id": "s", "kind": "search", "knowledge_point_id": "p", "url": url,
                     "title": point["text"], "snippet": point["text"], "source": "synthetic-adversarial-excerpt"})
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])) is None


@pytest.mark.asyncio
async def test_observed_html_fetch_persistence_model_and_final_source_bound_coverage():
    from backend.app.fetcher import Fetcher, HTTPResult
    html, url = html_fixture()
    class OfflineObservedResponse(Fetcher):
        async def fetch(self, requested):
            assert requested == url
            return HTTPResult(200, {"content-type": "text/html; charset=utf-8"}, html.encode(), url)
    enriched = await OfflineObservedResponse().enrich({"url": url, "title": "Learn Python Interactively", "source": "public_catalog"})
    resource = Resource.model_validate(dict(enriched, resource_id="r")).model_dump(mode="json")
    assert resource["video_topic_summary"] == enriched["video_topic_summary"]
    point = {"knowledge_point_id": "p", "text": "Python variables and user input"}
    match = rank_resource(point, resource, enriched["evidence"], SearchRequest(knowledge_points=[point["text"]]))
    assert match and match["topic_evidence_status"] == "supported"
    assert resource["chapters"] == []
