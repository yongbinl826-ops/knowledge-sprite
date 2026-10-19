"""A retained real namespace target; no new source/teaching equivalence."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import SearchRequest
from backend.app.ranking import pygame_text_display_match, rank_resource
from backend.app.source_adapters.techwithtim import bound_video_topic_summary


FIXTURES = Path(__file__).parent / "fixtures"
TARGET = "pygame.font 渲染文字"
FLOW = 'face = pygame.font.SysFont("sans", 24)\nlabel = face.render("Ready", True, color)\nscreen.blit(label, (10,20))'


def retained():
    data = json.loads((FIXTURES / "pygame_font_namespace/scoring-runtime-r8.json").read_text(encoding="utf-8"))
    assert sha256(data["resource"]["video_topic_summary"].encode()).hexdigest() == data["provenance"]["summary_sha256"]
    return data


def observed_html(body=None, *, sidebar=""):
    data = retained()
    soup = BeautifulSoup((FIXTURES / "techwithtim/scoring-health-bars.html").read_text(encoding="utf-8"), "html.parser")
    if body is not None:
        own = soup.select_one('div[class*="markdown__Container-"]')
        own.clear()
        own.append(BeautifulSoup(body, "html.parser"))
    if sidebar:
        soup.append(BeautifulSoup(sidebar, "html.parser"))
    url = data["resource"]["url"]
    resource = MetadataExtractor().extract(str(soup), url, "2026-10-18T00:00:00Z")
    resource.update(resource_id="retained-scoring", url=url, canonical_url=url,
                    discovered_at="2026-10-18T00:00:00Z", fetch_status="fetched", metadata_evidence_level="page")
    return resource


def target_status(resource, evidence=None, owner="pygame"):
    point = {"knowledge_point_id": "namespace-target", "text": owner + " 游戏状态机与胜利判定",
             "learning_targets": [TARGET]}
    match = rank_resource(point, resource, evidence if evidence is not None else resource["evidence"],
                          SearchRequest(knowledge_points=[point["text"]]))
    rows = {r["text"]: r for r in match["subtopic_coverage"]} if match else {}
    return rows.get(TARGET, {"status": "unknown"})["status"]


def test_actual_runtime_own_source_supports_only_rendering_target_and_keeps_project_unknown():
    data = retained()
    before = deepcopy(data)
    assert bound_video_topic_summary(data["resource"], data["evidence"])
    match = rank_resource(data["point"], data["resource"], data["evidence"], SearchRequest.model_validate(data["request"]))
    assert match and match["topic_evidence_status"] == "partial"
    rows = {r["text"]: r for r in match["subtopic_coverage"]}
    assert rows[TARGET]["status"] == "supported"
    assert rows[TARGET]["evidence_ids"]
    assert all(r["status"] == "unknown" for r in match["subtopic_coverage"] if r["text"] != TARGET)
    assert data == before


def test_actual_public_html_extraction_binding_then_rank_retains_no_full_code_coverage():
    resource = observed_html()
    summary = bound_video_topic_summary(resource, resource["evidence"])
    assert summary and "font = pygame.font.SysFont" in summary and "text = font.render" in summary and "win.blit(text" in summary
    assert "pygame.init()" not in summary and "pygame.key.get_pressed" not in summary
    assert target_status(resource) == "supported"
    point = {"knowledge_point_id": "prior-code", "text": "pygame 初始化与按键", "learning_targets": ["pygame.init", "pygame.key.get_pressed"]}
    match = rank_resource(point, resource, resource["evidence"], SearchRequest(knowledge_points=[point["text"]]))
    assert match is None or all(row["status"] == "unknown" for row in match["subtopic_coverage"] if row["id"].startswith("learning_target_"))


@pytest.mark.parametrize("target", [TARGET, "pygame.font   渲染文字", "PYGAME.FONT 渲染文字"])
def test_only_exact_namespace_rendering_target_spelling_is_added(target):
    assert pygame_text_display_match(target, FLOW)


@pytest.mark.parametrize("target", [
    "pandas.font 渲染文字", "foo.pygame.font 渲染文字", "pygame.fontTools 渲染文字",
    "pygame.font 渲染文字与胜利判定", "pygame.font 构造", "pygame.font.SysFont 渲染文字",
    "pygame.font 渲染文字并设置状态", "pygame.font 下载字体", "pygame.font render text",
])
def test_new_target_grammar_does_not_expand_owner_api_or_extra_intent(target):
    assert pygame_text_display_match(target, FLOW) is None


@pytest.mark.parametrize("flow", [
    'pygame.font.SysFont("sans", 24)',
    FLOW.replace("pygame.font", "helper.pygame.font"),
    FLOW.replace("pygame.font", "pandas.font"),
    FLOW.replace("face.render", "other_face.render"),
    FLOW.replace("screen.blit(label", "screen.blit(other_label"),
    FLOW.replace("label = face.render", "face = Qt.Font(); label = face.render"),
    FLOW.replace("screen.blit(label", "label = other_image; screen.blit(label"),
    "API list: " + FLOW.replace("\n", "; "),
    "Prerequisite: " + FLOW.replace("\n", "; "),
    FLOW.replace("label = face.render", "not teach rendering: label = face.render"),
])
def test_namespace_target_keeps_existing_own_render_flow_guards(flow):
    assert not pygame_text_display_match(TARGET, flow)


PROSE = ("<p>This own lesson explains how to install fonts for a pygame project.</p>"
         "<p>We only create the font object here and inspect its font configuration.</p>"
         '<pre>face = pygame.font.SysFont("sans", 24)</pre>')


@pytest.mark.parametrize("heading", ["Full Code", "Complete Program", "Previous Lesson", "Next Lesson", "Prerequisites"])
def test_later_previous_future_or_cumulative_sections_cannot_donate_render_flow(heading):
    body = PROSE + f"<h2>{heading}</h2><p>This other section contains a rendered label example.</p><pre>{FLOW}</pre>"
    resource = observed_html(body)
    assert bound_video_topic_summary(resource, resource["evidence"])
    assert "face.render" not in resource["video_topic_summary"]
    assert target_status(resource) == "unknown"


def test_other_lesson_sidebar_flow_cannot_donate_teaching():
    resource = observed_html(PROSE, sidebar=f"<aside><h2>Another video</h2><p>Rendered label in a different lesson.</p><pre>{FLOW}</pre></aside>")
    assert target_status(resource) == "unknown"


def test_valid_own_flow_still_cannot_borrow_a_foreign_project_owner():
    assert target_status(observed_html(), owner="pandas") == "unknown"


@pytest.mark.parametrize("damage", ["other_lesson_url", "duplicate_proof", "summary_changed"])
def test_real_page_proof_damage_cannot_fall_back_to_search_or_article_prose(damage):
    data = retained()
    resource, evidence = data["resource"], data["evidence"]
    if damage == "other_lesson_url":
        next(e for e in evidence if e.get("field") == "video_topic_summary")["url"] = resource["url"] + "-other"
    elif damage == "duplicate_proof":
        evidence.append(deepcopy(next(e for e in evidence if e.get("field") == "video_evidence_status")))
    else:
        resource["video_topic_summary"] += "\nAnother lesson teaches READY/PLAYING/WIN."
    assert bound_video_topic_summary(resource, evidence) is None
    assert target_status(resource, evidence) == "unknown"


@pytest.mark.parametrize("observation", [
    "pygame游戏开发教程009：显示文字",
    "pygame游戏开发教程009：显示文字。本次内容中提到的相关字体下载地址：https://github.com/example/pygame_demo.git",
    "pygame显示文字。Another lesson teaches pygame.font rendering.",
])
def test_namespace_target_does_not_infer_the_module_from_generic_display_title(observation):
    assert pygame_text_display_match(TARGET, observation) is False


@pytest.mark.parametrize("observation", [
    "pygame 教程：使用 pygame.font 渲染文字",
    "pygame 字体教学：pygame.font 模块显示文字",
])
def test_explicit_own_module_prose_may_support_namespace_rendering(observation):
    assert pygame_text_display_match(TARGET, observation) is True


def test_generic_display_target_keeps_its_less_specific_teaching_meaning():
    assert pygame_text_display_match("pygame 文字显示", "pygame游戏开发教程009：显示文字") is True
