"""A documented rendering data flow, not arbitrary API-name similarity."""
from pathlib import Path

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource, SearchRequest
from backend.app.ranking import pygame_text_display_match, rank_resource


FLOW = 'lesson: face = pygame.font.SysFont("sans", 24)\nlabel = face.render("Ready", True, color)\nscreen.blit(label, (10,20))'


def test_rendered_surface_is_locally_bound_to_a_font_then_displayed():
    assert pygame_text_display_match("pygame 字体渲染", FLOW)
    assert pygame_text_display_match("pygame 文本显示", FLOW)
    assert pygame_text_display_match("pygame 分数统计", FLOW) is None


@pytest.mark.parametrize("text", [
    'pygame.font.SysFont("sans",24)',
    'API list: face = pygame.font.SysFont("sans",24); label=face.render("x",1,c);screen.blit(label,(0,0))',
    FLOW.replace('label = face.render', 'face = Qt.Font(); label = face.render'),
    FLOW.replace('screen.blit(label', 'label = other_image; screen.blit(label'),
    FLOW.replace('screen.blit(label', 'screen.blit(other_label'),
    FLOW.replace('face.render', 'other_font.render'),
    FLOW.replace('pygame.font', 'helper.pygame.font'),
    FLOW.replace('label = face.render', 'not teach rendering: label = face.render'),
])
def test_unbound_or_noninstructional_spelling_is_not_a_rendering_lesson(text):
    assert not pygame_text_display_match("pygame 字体渲染", text)


def test_real_lesson_supports_its_rendering_flow_without_borrowing_prior_collision_code():
    url = "https://www.techwithtim.net/tutorials/game-development-with-python/pygame-tutorial/scoring-health-bars"
    fixture = Path(__file__).parent / "fixtures/techwithtim/scoring-health-bars.html"
    data = MetadataExtractor().extract(fixture.read_text(encoding="utf-8"), url, "2026-10-18T00:00:00Z")
    evidence = data.pop("evidence")
    data.update(resource_id="observed-lesson", url=url, canonical_url=url,
                discovered_at="2026-10-18T00:00:00Z", fetch_status="fetched", metadata_evidence_level="page")
    resource = Resource.model_validate(data).model_dump()
    point = {"knowledge_point_id": "lesson", "text": "pygame 字体渲染与矩形碰撞检测"}
    request = SearchRequest(knowledge_points=[point["text"]])
    result = rank_resource(point, resource, evidence, request)
    assert result and result["topic_evidence_status"] == "partial"
    assert [part["status"] for part in result["subtopic_coverage"]] == ["supported", "unknown"]
    assert not resource["chapters"]
