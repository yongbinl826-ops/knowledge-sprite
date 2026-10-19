"""Real publisher project-course shape and unadapted watch-only counterexample."""
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


FIXTURES = Path(__file__).parent / "fixtures/freecodecamp"
URL = "https://www.freecodecamp.org/news/learn-pandas-for-data-science/"
WATCH_ONLY = "https://www.freecodecamp.org/news/matplotlib-course-learn-python-data-visualization/"


def fixture(name="article-projects.html"):
    manifest = json.loads((FIXTURES / "public-project-source-manifest.json").read_text(encoding="utf-8"))
    row = next(row for row in manifest if row["fixture"] == name)
    raw = (FIXTURES / name).read_bytes()
    assert sha256(raw).hexdigest() == row["fixture_sha256"]
    assert row["source_sha256"] == ("aba768d1213eec291684a2202a9c8af3c9c7f70262450fee5dae0e9328ecbf3b" if name == "article-projects.html"
                                     else "3a0f39ae813aa4786aa8772c314f83400303eaab16759a9e48090cb650dd4c12")
    return raw.decode()


def resource_from(html=None, url=URL):
    resource = MetadataExtractor().extract(html or fixture(), url, "2026-10-18T00:00:00Z")
    resource.update(resource_id="fcc-projects", url=url, canonical_url=url, discovered_at=resource["fetched_at"])
    return resource


def test_real_pandas_project_course_uses_same_id_short_watch_link_and_scoped_teaching():
    resource = resource_from()
    assert resource["resource_type"] == "video" and resource["video_evidence_status"] == "page_verified"
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert summary and len(summary) <= 1800
    assert "null values, duplicate values, outliers" in summary
    assert "grouping operations" in summary and "Joining and Groupby Practice" in summary
    assert "filtering and sorting" in summary
    assert "Santiago is also the creator" not in summary and "Data is the new oil" not in summary
    assert "5-hour watch" not in summary and resource["chapters"] == []
    proof = next(e for e in resource["evidence"] if e.get("field") == "video_evidence_status")
    binding = json.loads(proof["text"])
    assert binding["watch_url"] == "https://youtu.be/gtjxAH8uaP0"
    assert binding["embed_url"] == "https://www.youtube.com/embed/gtjxAH8uaP0"
    assert binding["video_id"] == "gtjxAH8uaP0"
    saved = Resource.model_validate(resource).model_dump()
    assert bound_video_topic_summary(saved, resource["evidence"]) == summary


@pytest.mark.parametrize("watch", ["http://youtu.be/gtjxAH8uaP0", "https://youtu.be.attacker.example/gtjxAH8uaP0",
                                  "https://youtu.be/aaaaaaaaaaa", "https://youtu.be/gtjxAH8uaP0/other",
                                  "https://youtu.be/gtjxAH8uaP0?redirect=https://attacker.example",
                                  "https://youtu.be/gtjxAH8uaP0#different", "https://youtu.be:80/gtjxAH8uaP0",
                                  "https://youtu.be/gtjxAH8uaP", "https://user:pass@youtu.be/gtjxAH8uaP0"])
def test_short_watch_url_must_be_exact_public_same_video_metadata(watch):
    soup = BeautifulSoup(fixture(), "html.parser")
    soup.select_one('section.post-content a[href^="https://youtu.be/"]')["href"] = watch
    assert not FreeCodeCampCourseAdapter().extract(soup, URL).fields


@pytest.mark.parametrize("damage", ["no_marker", "different_section", "outside_content", "after_conclusion",
                                   "no_difficulty", "hidden_project", "project_link_cta", "unannounced_extra_section"])
def test_project_content_requires_the_courses_own_explicit_intro_scope(damage):
    soup = BeautifulSoup(fixture(), "html.parser")
    content = soup.select_one("section.post-content")
    marker = next(p for p in content.find_all("p", recursive=False) if p.get_text() == "Below are the projects you will build.")
    target = next(p for p in content.find_all("p", recursive=False) if p.strong and "Google Playstore" in p.strong.get_text())
    if damage == "no_marker":
        marker.decompose()
    elif damage == "different_section":
        content.find("h2").string = "Unrelated recommended courses"
    elif damage == "outside_content":
        soup.select_one("article.post-full").append(target.extract())
    elif damage == "after_conclusion":
        content.find("h2", string="Conclusion").insert_after(target.extract())
    elif damage == "no_difficulty":
        for heading in content.find_all("h3", recursive=False):
            heading.decompose()
    elif damage == "hidden_project":
        target["hidden"] = ""
    elif damage == "project_link_cta":
        target.append(BeautifulSoup('<a href="https://example.org">Recommended external course</a>', "html.parser"))
    elif damage == "unannounced_extra_section":
        marker.insert_before(BeautifulSoup('<h2>Related content</h2>', "html.parser"))
    resource = resource_from(str(soup))
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert summary and "null values, duplicate values, outliers" not in summary


def test_complete_limitation_sentences_survive_project_excerpt_selection():
    soup = BeautifulSoup(fixture(), "html.parser")
    content = soup.select_one("section.post-content")
    target = next(p for p in content.find_all("p", recursive=False) if p.strong and "Google Playstore" in p.strong.get_text())
    target.append(" However, this course does not teach deleting duplicate rows. You must already know row filtering.")
    resource = resource_from(str(soup))
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert "does not teach deleting duplicate rows" in summary
    assert "must already know row filtering" in summary


def test_hidden_or_related_course_text_and_installation_reference_are_not_coverage():
    soup = BeautifulSoup(fixture(), "html.parser")
    content = soup.select_one("section.post-content")
    target = next(p for p in content.find_all("p", recursive=False) if p.strong and "Google Playstore" in p.strong.get_text())
    target.append(BeautifulSoup('<span style="display:none"> Learn how to implement quantum teleportation.</span>', "html.parser"))
    content.append(BeautifulSoup('<aside><p><strong>Quantum</strong>Learn how to implement quantum teleportation.</p></aside>', "html.parser"))
    resource = resource_from(str(soup))
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert summary and "quantum teleportation" not in summary


def test_real_matplotlib_watch_only_article_stays_unadapted_without_bar_topic_claims():
    html = fixture("article-watch-only.html")
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one('a[href="https://www.youtube.com/watch?v=3Xc3CA655Y4"]')
    assert not soup.select_one("section.post-content iframe")
    assert not FreeCodeCampCourseAdapter().extract(soup, WATCH_ONLY).fields
    resource = resource_from(html, WATCH_ONLY)
    assert resource.get("resource_type") != "video" and not resource.get("video_topic_summary")
    point = {"knowledge_point_id": "p", "text": "Matplotlib 出发站Top10条形图"}
    assert rank_resource(point, resource, resource["evidence"], SearchRequest(knowledge_points=[point["text"]])) is None


def test_project_course_scoped_observations_exclude_search_scenario_and_fake_chapters():
    resource = resource_from()
    point = {"knowledge_point_id": "p", "text": "pandas 骑行分钟时长与复核日志"}
    resource["chapters"] = [{"title": point["text"], "start_seconds": 1}]
    evidence = resource["evidence"] + [{"evidence_id": "s", "kind": "search", "source": "public_catalog",
                                       "knowledge_point_id": "p", "url": URL, "title": point["text"], "snippet": point["text"]}]
    before = deepcopy((resource, evidence))
    observations = topic_observations(point, resource, evidence)
    assert observations and all("s" not in o["evidence_ids"] and "骑行分钟" not in o["raw"] for o in observations)
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])) is None
    assert (resource, evidence) == before
