"""Actual two public lesson shapes, proof trust boundaries and honest scope."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource
from backend.app.ranking import has_learning_evidence, topic_observations
from backend.app.source_adapters.techwithtim import (
    DOM_TEACHING_BINDING, SUMMARY_LIMIT, TechWithTimLessonAdapter, bound_video_topic_summary,
)

FIXTURES = Path(__file__).parent / "fixtures/techwithtim"
MANIFEST = json.loads((FIXTURES / "public-dom-v2-source-manifest.json").read_text(encoding="utf-8"))


def fixture(index=0):
    entry = MANIFEST["pages"][index]
    raw = (FIXTURES / entry["fixture"]).read_bytes()
    assert sha256(raw).hexdigest() == entry["fixture_sha256"]
    return raw.decode(), entry["source_url"]


def resource(index=0, html=None):
    raw, url = fixture(index)
    result = MetadataExtractor().extract(raw if html is None else html, url, "2026-10-18T18:04:00Z")
    result.update(resource_id="twt-dom-v2", url=url, canonical_url=url, discovered_at=result["fetched_at"])
    return result


@pytest.mark.parametrize("index,video,title", [(0, "i6xMBig-pP4", "Basic Movement & Key Presses"), (1, "5tvER0MT14s", "Tutorial #1")])
def test_actual_owned_lesson_has_new_structural_proof_not_invented_phrase(index, video, title):
    result = resource(index)
    assert result["title"] == title
    assert result["resource_type"] == "video" and result["video_evidence_status"] == "page_verified"
    summary = bound_video_topic_summary(result, result["evidence"])
    assert summary and summary.startswith(title + "\n") and len(summary) <= SUMMARY_LIMIT == 6000
    proof = json.loads(next(e["text"] for e in result["evidence"] if e.get("field") == "video_evidence_status"))
    assert proof["binding_version"] == 2 and proof["binding_kind"] == "same_lesson_dom_v2"
    assert proof["video_id"] == video and proof["embed_title"] == title
    assert proof["teaching_binding"] == DOM_TEACHING_BINDING
    assert "video above offers" not in proof["teaching_binding"]
    assert proof["dom_witness"]["notes_sha256"] == sha256(summary.encode()).hexdigest()
    assert proof["dom_witness"]["notes_characters"] == len(summary)
    assert proof["dom_witness"]["teaching_prose_count"] >= 2
    assert result["chapters"] == []
    assert has_learning_evidence(result, result["evidence"])
    validated = Resource.model_validate(result).model_dump()
    assert bound_video_topic_summary(validated, result["evidence"]) == summary


def test_actual_movement_summary_reaches_own_movement_notes_without_cumulative_program():
    result = resource()
    summary = result["video_topic_summary"]
    assert len(summary) > 1800
    assert "Inside the if statements we will change" in summary
    assert "Now we can start checking for events" in summary
    assert "And now we can move our character around!" in summary
    assert "import pygame pygame.init()" not in summary  # repeated whole-program snippets excluded
    assert "pygame.key.get_pressed" in summary  # actual own incremental teaching block
    assert "KEYDOWN" not in summary  # continuous state does not prove discrete key events
    assert "K_r" not in summary and "READY/PLAYING/WIN" not in summary


def test_actual_snake_notes_prove_grid_lines_not_two_dimensional_maze_or_bounds():
    result = resource(1)
    summary = result["video_topic_summary"]
    assert "Drawing the Grid" in summary and "20x20 grid" in summary
    assert "Creating our Game Loop" in summary
    assert "class snake" not in summary and "import tkinter" not in summary
    assert "```python\ndef main():" in summary and "clock.tick(10)" in summary
    assert "8x8" not in summary and "0..7" not in summary and "wall" not in summary.lower()


@pytest.mark.parametrize("damage", ["no_frame", "no_title", "generic_mismatch", "two_frames", "second_iframe_elsewhere",
    "two_h1", "two_bodies", "two_content", "hidden_frame", "hidden_h1", "hidden_notes", "wrong_embed_host",
    "missing_embed_title", "no_notes", "sidebar_notes", "sidebar_frame", "code_only_notes", "one_teaching_paragraph"])
def test_structural_binding_requires_unique_visible_owned_video_and_notes(damage):
    raw, url = fixture()
    soup = BeautifulSoup(raw, "html.parser")
    content = soup.select_one('div[class*="tutoriallayout__Content-"]')
    body = content.select_one('div[class*="markdown__Container-"]')
    frame = content.iframe
    if damage == "no_frame": frame.decompose()
    elif damage == "no_title": content.h1.decompose()
    elif damage == "generic_mismatch": frame["title"] = "Tutorial #1"
    elif damage == "two_frames": frame.parent.append(deepcopy(frame))
    elif damage == "second_iframe_elsewhere": body.append(deepcopy(frame))
    elif damage == "two_h1": content.append(BeautifulSoup("<h1>Unrelated title</h1>", "html.parser"))
    elif damage == "two_bodies": content.append(deepcopy(body))
    elif damage == "two_content": content.parent.append(deepcopy(content))
    elif damage == "hidden_frame": frame["hidden"] = ""
    elif damage == "hidden_h1": content.h1["aria-hidden"] = "true"
    elif damage == "hidden_notes": body["style"] = "display:none"
    elif damage == "wrong_embed_host": frame["src"] = "https://youtube.example/embed/i6xMBig-pP4"
    elif damage == "missing_embed_title": del frame["title"]
    elif damage == "no_notes": body.decompose()
    elif damage == "sidebar_notes": content.parent.append(body.extract())
    elif damage == "sidebar_frame": content.parent.append(frame.parent.extract())
    elif damage in {"code_only_notes", "one_teaching_paragraph"}:
        body.clear()
        body.append(BeautifulSoup("<p>In this lesson we teach pygame movement and event handling.</p>" if damage == "one_teaching_paragraph" else "<pre>keys = pygame.key.get_pressed()</pre>", "html.parser"))
    assert not TechWithTimLessonAdapter().extract(soup, url).fields


@pytest.mark.parametrize("damage", ["version", "boolean_version", "unknown_kind", "missing_witness", "legacy_downgrade",
    "phrase_downgrade", "title", "iframe_title", "notes_hash", "notes_length", "prose_count", "float_count",
    "bool_count", "visible", "content_count", "heading_count", "markdown_count", "embedded_iframe_count", "all_content_iframe_count"])
def test_dom_proof_is_rechecked_and_cannot_fall_back_to_legacy(damage):
    result = resource()
    evidence = deepcopy(result["evidence"])
    row = next(e for e in evidence if e.get("field") == "video_evidence_status")
    proof = json.loads(row["text"])
    witness = proof["dom_witness"]
    if damage == "version": proof["binding_version"] = 3
    elif damage == "boolean_version": proof["binding_version"] = True
    elif damage == "unknown_kind": proof["binding_kind"] = "same_page"
    elif damage == "missing_witness": del proof["dom_witness"]
    elif damage == "legacy_downgrade": del proof["binding_version"]
    elif damage == "phrase_downgrade": proof["teaching_binding"] = "The video above offers more in-depth explanations."
    elif damage == "title": witness["heading_text"] = "Other lesson"
    elif damage == "iframe_title": witness["iframe_title"] = "Other lesson"
    elif damage == "notes_hash": witness["notes_sha256"] = "0" * 64
    elif damage == "notes_length": witness["notes_characters"] += 1
    elif damage == "prose_count": witness["teaching_prose_count"] = 1
    elif damage == "float_count": witness["teaching_prose_count"] = 2.5
    elif damage == "bool_count": witness["content_count"] = True
    elif damage == "visible": witness["visible"] = "true"
    else: witness[damage] = 2
    row["text"] = json.dumps(proof)
    assert bound_video_topic_summary(result, evidence) is None


def test_summary_is_bounded_at_complete_block_and_does_not_append_later_fragment():
    raw, url = fixture()
    soup = BeautifulSoup(raw, "html.parser")
    body = soup.select_one('div[class*="markdown__Container-"]')
    body.clear()
    for index in range(15):
        body.append(BeautifulSoup(f"<p>Teaching block {index}: " + "pygame movement is explained. " * 18 + "END.</p>", "html.parser"))
    facts = TechWithTimLessonAdapter().extract(soup, url)
    summary = next(f.value for f in facts.fields if f.field == "video_topic_summary")
    assert 1800 < len(summary) <= 6000 and summary.endswith("END.")
    assert "Teaching block 14" not in summary


def test_retained_summary_over_6000_is_rejected_even_with_matching_hashes():
    result = resource()
    evidence = deepcopy(result["evidence"])
    summary = result["title"] + "\n" + "x" * (6001 - len(result["title"]) - 1)
    result["video_topic_summary"] = summary
    row = next(e for e in evidence if e.get("field") == "video_topic_summary")
    row["text"] = summary
    proof_row = next(e for e in evidence if e.get("field") == "video_evidence_status")
    proof = json.loads(proof_row["text"])
    proof["summary_sha256"] = proof["dom_witness"]["notes_sha256"] = sha256(summary.encode()).hexdigest()
    proof["dom_witness"]["notes_characters"] = len(summary)
    proof_row["text"] = json.dumps(proof)
    assert bound_video_topic_summary(result, evidence) is None


@pytest.mark.parametrize("variant", ["no_binding", "binding_in_sidebar", "hidden_binding"])
def test_legacy_phrase_absence_can_use_new_honest_dom_proof(variant):
    old = (FIXTURES / "scoring-health-bars.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(old, "html.parser")
    body = soup.select_one('div[class*="markdown__Container-"]')
    binding = next(p for p in body.find_all("p", recursive=False) if "video above offers" in p.get_text())
    if variant == "no_binding": binding.decompose()
    elif variant == "binding_in_sidebar": soup.select_one('div[class*="tutoriallayout__Lessons-"]').append(binding.extract())
    else: binding["hidden"] = ""
    url = "https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars"
    fields = {f.field: f for f in TechWithTimLessonAdapter().extract(soup, url).fields}
    assert json.loads(fields["video_evidence_status"].excerpt)["binding_kind"] == "same_lesson_dom_v2"


def test_owned_lesson_observations_exclude_catalog_search_and_unrelated_course_text():
    result = resource()
    point = {"knowledge_point_id": "p", "text": "pygame keyboard input"}
    evidence = result["evidence"] + [{"evidence_id": "s", "kind": "search", "source": "techwithtim_catalog",
        "url": result["url"], "knowledge_point_id": "p", "title": "READY PLAYING WIN", "snippet": "K_r resets everything"}]
    observed = topic_observations(point, result, evidence)
    assert observed and all("s" not in r["evidence_ids"] for r in observed)
    assert all("K_r" not in r["raw"] and "READY PLAYING WIN" not in r["raw"] for r in observed)
