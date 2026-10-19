"""Real public lesson replay; no network, player, media or private API."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource, SearchRequest
from backend.app.ranking import rank_resource, topic_observations
import backend.app.source_adapters as adapter_registry
from backend.app.source_adapters.techwithtim import (
    SUMMARY_SOURCE, VIDEO_SOURCE, TechWithTimLessonAdapter, bound_video_topic_summary,
    lesson_page_url,
)


FIXTURES = Path(__file__).parent / "fixtures/techwithtim"
URL = "https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars"


def real_fixture():
    raw = (FIXTURES / "scoring-health-bars.html").read_bytes()
    manifest = json.loads((FIXTURES / "public-source-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == "552c5bb41113823ad3ba64b0acd9e6f6c26e984791c871babd2108765900cc53"
    assert sha256(raw).hexdigest() == manifest["fixture_sha256"]
    return raw.decode()


def extract_resource(monkeypatch, html=None, url=URL):
    monkeypatch.setattr(adapter_registry, "ADAPTERS", (TechWithTimLessonAdapter(),))
    result = MetadataExtractor().extract(html or real_fixture(), url, "2026-10-18T00:00:00Z")
    result.update(resource_id="twt-real", url=url, canonical_url=url, discovered_at="2026-10-18T00:00:00Z")
    return result


def test_real_lesson_binds_own_video_and_excludes_cumulative_code(monkeypatch):
    resource = extract_resource(monkeypatch)
    assert resource["title"] == "Scoring & Health Bars"
    assert resource["resource_type"] == "video" and resource["video_evidence_status"] == "page_verified"
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert summary and len(summary) <= 1800
    assert "increasing the score each time a bullet hits" in summary
    assert "display this score to the screen" in summary
    assert "pygame.font.SysFont" in summary and "font.render" in summary and "win.blit" in summary
    assert "pygame.init" not in summary and "pygame.key.get_pressed" not in summary and "K_SPACE" not in summary
    assert "Character Animation & Sprites" not in summary and "Sound Effects & Music" not in summary
    assert "Full Code" not in summary and "class enemy" not in summary
    proof = next(row for row in resource["evidence"] if row.get("field") == "video_evidence_status")
    binding = json.loads(proof["text"])
    assert binding["video_id"] == "JLUqOmE9veI"
    assert binding["embed_title"] == binding["lesson_title"] == resource["title"]
    assert "no player/media request" in binding["basis"]
    assert TechWithTimLessonAdapter().extract(BeautifulSoup(real_fixture(), "html.parser"), URL).chapters == []
    validated = Resource.model_validate(resource).model_dump()
    assert validated["video_topic_summary"] == summary
    assert bound_video_topic_summary(validated, resource["evidence"]) == summary


@pytest.mark.parametrize("damage", ["wrong_domain", "non_https", "series_route", "no_frame", "wrong_embed_host",
                                   "wrong_embed_title", "two_frames", "hidden_frame", "hidden_content", "hidden_heading",
                                   "frame_in_sidebar", "markdown_in_sidebar", "negated_binding",
                                   "two_content_roots", "no_teaching_prose"])
def test_unbound_text_series_sidebar_or_hidden_video_is_not_promoted(damage):
    soup = BeautifulSoup(real_fixture(), "html.parser")
    content = soup.select_one('div[class*="tutoriallayout__Content-"]')
    body = content.select_one('div[class*="markdown__Container-"]')
    frame = content.iframe
    sidebar = soup.select_one('div[class*="tutoriallayout__Lessons-"]')
    binding = next(p for p in body.find_all("p", recursive=False) if "video above offers" in p.get_text())
    url = URL
    if damage == "wrong_domain":
        url = URL.replace("www.techwithtim.net", "www.techwithtim.net.attacker.example")
    elif damage == "non_https":
        url = URL.replace("https:", "http:")
    elif damage == "series_route":
        url = URL.rsplit("/", 1)[0]
    elif damage == "no_frame":
        frame.decompose()
    elif damage == "wrong_embed_host":
        frame["src"] = "https://www.youtube.com.attacker.example/embed/JLUqOmE9veI"
    elif damage == "wrong_embed_title":
        frame["title"] = "A different lesson"
    elif damage == "two_frames":
        frame.parent.append(deepcopy(frame))
    elif damage == "hidden_frame":
        frame.parent["style"] = "display: none"
    elif damage == "hidden_content":
        content["aria-hidden"] = "true"
    elif damage == "hidden_heading":
        content.h1["hidden"] = ""
    elif damage == "frame_in_sidebar":
        sidebar.append(frame.extract())
    elif damage == "markdown_in_sidebar":
        sidebar.append(body.extract())
    elif damage == "no_binding":
        binding.decompose()
    elif damage == "negated_binding":
        binding.string = "The video above offers more in depth explanations, but does not teach this lesson."
    elif damage == "binding_in_sidebar":
        sidebar.append(binding.extract())
    elif damage == "hidden_binding":
        binding["hidden"] = ""
    elif damage == "two_content_roots":
        content.parent.append(deepcopy(content))
    elif damage == "no_teaching_prose":
        for p in list(body.find_all("p", recursive=False)):
            if p != binding:
                p.decompose()
    assert not TechWithTimLessonAdapter().extract(soup, url).fields


@pytest.mark.parametrize("pollution", ["sidebar", "full_code", "hidden_child", "footer", "article_meta"])
def test_unrelated_page_content_is_not_lesson_teaching_evidence(monkeypatch, pollution):
    soup = BeautifulSoup(real_fixture(), "html.parser")
    body = soup.select_one('div[class*="markdown__Container-"]')
    contaminant = "pygame quantum teleportation"
    if pollution == "sidebar":
        soup.select_one('div[class*="tutoriallayout__Lessons-"]').append(BeautifulSoup(f"<p>{contaminant}</p>", "html.parser"))
    elif pollution == "full_code":
        body.append(BeautifulSoup(f"<p>We will teach {contaminant}.</p><pre>quantum_teleportation = True</pre>", "html.parser"))
    elif pollution == "hidden_child":
        body.find("p").append(BeautifulSoup(f'<span style="display:none">{contaminant}</span>', "html.parser"))
    elif pollution == "footer":
        soup.body.append(BeautifulSoup(f"<footer><p>{contaminant}</p></footer>", "html.parser"))
    elif pollution == "article_meta":
        soup.select_one('meta[property="og:description"]')["content"] = contaminant
    resource = extract_resource(monkeypatch, str(soup))
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert summary and contaminant not in summary
    assert contaminant not in resource["description"]


@pytest.mark.parametrize("damage", ["missing_proof", "summary_url", "summary_source", "summary_changed",
                                   "title_changed", "embed_changed", "embed_title", "lesson_url", "summary_hash",
                                   "binding_negated", "proof_kind", "unverified_resource", "cross_page_title",
                                   "resource_url_changed", "summary_without_title_valid_hash", "summary_trimmed_old_proof",
                                   "previous_code_injected_old_proof"])
def test_retained_topic_proof_requires_same_lesson_and_exact_summary(monkeypatch, damage):
    resource = extract_resource(monkeypatch)
    evidence = deepcopy(resource["evidence"])
    proof = next(row for row in evidence if row.get("field") == "video_evidence_status")
    summary_row = next(row for row in evidence if row.get("field") == "video_topic_summary")
    binding = json.loads(proof["text"])
    if damage == "missing_proof":
        evidence.remove(proof)
    elif damage == "summary_url":
        summary_row["url"] = URL.replace("scoring-health-bars", "unrelated-lesson")
    elif damage == "summary_source":
        summary_row["source"] = "meta.description"
    elif damage == "summary_changed":
        resource["video_topic_summary"] += "\npygame teleportation"
        summary_row["text"] = resource["video_topic_summary"]
    elif damage == "title_changed":
        resource["title"] = "Different lesson"
    elif damage == "embed_changed":
        binding["embed_url"] = "https://www.youtube.com/embed/aaaaaaaaaaa"
    elif damage == "embed_title":
        binding["embed_title"] = "Different lesson"
    elif damage == "lesson_url":
        binding["lesson_url"] = URL.replace("scoring-health-bars", "unrelated-lesson")
    elif damage == "summary_hash":
        binding["summary_sha256"] = "0" * 64
    elif damage == "binding_negated":
        binding["teaching_binding"] += " The video does not teach this lesson."
    elif damage == "proof_kind":
        proof["kind"] = "search"
    elif damage == "unverified_resource":
        resource["fetch_status"] = "not_fetched"
    elif damage == "cross_page_title":
        title = next(row for row in evidence if row.get("field") == "title")
        title["url"] = URL.replace("scoring-health-bars", "unrelated-lesson")
    elif damage == "resource_url_changed":
        resource["url"] = URL.replace("scoring-health-bars", "unrelated-lesson")
    elif damage == "summary_without_title_valid_hash":
        resource["video_topic_summary"] = resource["video_topic_summary"].split("\n", 1)[1]
        summary_row["text"] = resource["video_topic_summary"]
        binding["summary_sha256"] = sha256(resource["video_topic_summary"].encode()).hexdigest()
    elif damage == "summary_trimmed_old_proof":
        resource["video_topic_summary"] = resource["video_topic_summary"].split("\n", 1)[0] + "\nScore"
        summary_row["text"] = resource["video_topic_summary"]
    elif damage == "previous_code_injected_old_proof":
        resource["video_topic_summary"] += "\nkeys = pygame.key.get_pressed(); if keys[pygame.K_SPACE]: restart()"
        summary_row["text"] = resource["video_topic_summary"]
    proof["text"] = json.dumps(binding)
    before = deepcopy((resource, evidence))
    assert bound_video_topic_summary(resource, evidence) is None
    assert (resource, evidence) == before


@pytest.mark.parametrize("url", ["https://www.techwithtim.net/tutorials", "https://www.techwithtim.net/tutorials/game-development-with-python",
                                "https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial",
                                URL + "?redirect=https://attacker.example", URL + "#other-lesson",
                                URL.replace("www.techwithtim.net", "www.techwithtim.net:80"),
                                URL.replace("www.techwithtim.net", "www.techwithtim.net:444"),
                                URL.replace("https://", "https://user:pass@"),
                                URL.replace("www.techwithtim.net", "127.0.0.1"), URL.replace("www.techwithtim.net", "www.techwithtim.net.attacker.example")])
def test_directory_or_untrusted_urls_cannot_be_lesson_proof(url):
    assert lesson_page_url(url) is None


def test_real_lesson_field_sources_are_distinct_from_article_metadata():
    facts = TechWithTimLessonAdapter().extract(BeautifulSoup(real_fixture(), "html.parser"), URL)
    fields = {fact.field: fact for fact in facts.fields}
    assert fields["video_topic_summary"].source == SUMMARY_SOURCE
    assert fields["video_evidence_status"].source == VIDEO_SOURCE
    assert fields["description"].value == fields["video_topic_summary"].value


@pytest.mark.parametrize("field", ["title", "video_evidence_status", "video_topic_summary"])
@pytest.mark.parametrize("variant", ["identical", "different_text", "different_url"])
def test_ambiguous_duplicate_evidence_identifiers_are_rejected(monkeypatch, field, variant):
    resource = extract_resource(monkeypatch)
    evidence = deepcopy(resource["evidence"])
    duplicate = deepcopy(next(row for row in evidence if row.get("field") == field))
    if variant == "different_text":
        duplicate["text"] = "different evidence sharing this identifier"
    elif variant == "different_url":
        duplicate["url"] = URL.replace("scoring-health-bars", "another-lesson")
    evidence.append(duplicate)
    assert bound_video_topic_summary(resource, evidence) is None
    assert bound_video_topic_summary(resource, list(reversed(evidence))) is None


@pytest.mark.parametrize("embed", ["https://www.youtube.com:80/embed/JLUqOmE9veI", "https://www.youtube.com/embed/JLUqOmE9veI#another",
                                  "https://www.youtube.com/embed/JLUqOmE9veI?next=https://attacker.example"])
def test_nonstandard_embed_scope_does_not_bind_lesson(embed):
    soup = BeautifulSoup(real_fixture(), "html.parser")
    soup.iframe["src"] = embed
    assert not TechWithTimLessonAdapter().extract(soup, URL).fields


def test_registered_extractor_retains_real_lesson_summary_without_sidebar_chapters():
    resource = MetadataExtractor().extract(real_fixture(), URL, "2026-10-18T00:00:00Z")
    resource.update(url=URL, canonical_url=URL, resource_id="registered", discovered_at=resource["fetched_at"])
    assert resource["chapters"] == []
    assert bound_video_topic_summary(resource, resource["evidence"])


def test_scoped_ranking_cannot_borrow_search_sidebar_or_cumulative_full_code(monkeypatch):
    resource = extract_resource(monkeypatch)
    point = {"knowledge_point_id": "p", "text": "pygame 初始化与键盘长按移动"}
    resource["chapters"] = [{"title": "pygame 初始化与键盘长按移动", "start_seconds": 1}]
    evidence = resource["evidence"] + [{"evidence_id": "s", "kind": "search", "source": "public_catalog",
                                       "url": URL, "knowledge_point_id": "p", "title": point["text"],
                                       "snippet": "pygame.init() and pygame.key.get_pressed() keyboard movement tutorial"}]
    observations = topic_observations(point, resource, evidence)
    assert observations
    assert all("pygame.key.get_pressed" not in row["raw"] and "pygame.init" not in row["raw"] for row in observations)
    assert all("s" not in row["evidence_ids"] for row in observations)
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])) is None


def test_damaged_bound_summary_has_no_generic_article_or_search_fallback(monkeypatch):
    resource = extract_resource(monkeypatch)
    resource["video_topic_summary"] += "\npygame quantum teleportation"
    resource["description"] = "pygame quantum teleportation tutorial"
    point = {"knowledge_point_id": "p", "text": "pygame quantum teleportation"}
    evidence = resource["evidence"] + [{"evidence_id": "s", "kind": "search", "url": URL,
                                       "knowledge_point_id": "p", "title": point["text"], "snippet": point["text"]}]
    assert topic_observations(point, resource, evidence) == []
    assert rank_resource(point, resource, evidence, SearchRequest(knowledge_points=[point["text"]])) is None
