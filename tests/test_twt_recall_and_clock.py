"""Offline actual-directory replay and finite own-code/Clock boundaries."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.models import SearchRequest
from backend.app import source_adapters as registry
from tests.test_techwithtim_catalog import make as transport_fixture


from backend.app import techwithtim_catalog as catalog, pygame_frame_limit as clock, ranking
from backend.app.source_adapters import techwithtim as adapter

FIXTURES = Path(__file__).parent / "fixtures"
ENTRY = catalog.ORIGIN + "/tutorials/game-development-with-python"


def real_directories():
    value = json.loads((FIXTURES / "twt_recall/twt_observed_directories.json").read_text(encoding="utf-8"))
    return value["category"], value["series"]


class NoNetwork:
    async def fetch(self, *args, **kwargs):
        raise AssertionError("No external request in retained directory replay")


def cached_provider():
    category, series = real_directories()
    provider = catalog.TechWithTimCatalogProvider(Settings(), fetcher=NoNetwork())
    provider._put(ENTRY, category)
    provider._put(series["source_url"], series)
    # A zero-heading query may now inspect one additional observed series.
    # Reuse the real retained directory fixture, never permit a network call.
    observed = json.loads((FIXTURES / "twt_multiseries/actual-directories.json").read_text(encoding="utf-8"))
    for document in observed["documents"]:
        if document["source_url"].endswith("/snake-pygame"):
            provider._put(document["source_url"], document)
    return provider, series


@pytest.mark.asyncio
async def test_actual_seventh_heading_is_recalled_from_confirmed_font_target_without_video_claim():
    provider, series = cached_provider()
    before = deepcopy(provider.memory_cache)
    query = "pygame 游戏状态机与胜利判定 state"
    plain = await provider.search(query, "zh", 6, [], original_point="pygame 游戏状态机与胜利判定")
    assert len(series["lessons"]) == 10 and series["lessons"][6]["title"] == "Scoring & Health Bars"
    assert series["lessons"][6]["url"] not in {row.url for row in plain}
    rows = await provider.search(query, "zh", 6, [], original_point="pygame 游戏状态机与胜利判定",
                                 learning_targets=["pygame.font 渲染文字", "胜利判定", "状态切换"])
    assert len(rows) == 6 and rows[0].url == series["lessons"][6]["url"]
    assert all(row.resource_type_hint == "unknown" and row.type_source is None for row in rows)
    assert rows[0].discovery_evidence["confidence"] == "low" and rows[0].discovery_evidence["independent_detail_required"]
    assert rows[0].discovery_evidence["recall_rules"] == ["pygame_font_text_display_to_score_health_heading"]
    assert all(row.url in {lesson["url"] for lesson in series["lessons"]} for row in rows)
    assert provider.memory_cache == before and provider.last_requests == []
    assert len(provider.last_discovery["indexes"]) == 2


@pytest.mark.parametrize("target", ["pygame.font 渲染文字", "pygame.font.SysFont 字体", "显示文字", "font rendering", "text display"])
def test_font_heading_association_is_only_an_explained_recall_hint(target):
    _, series = real_directories()
    plan = catalog.lesson_recall_plan("pygame 游戏状态 state", "pygame 游戏状态", [target])
    ordered = catalog.order_observed_lessons(series["lessons"], plan)
    assert ordered[0][1] == series["lessons"][6]
    assert plan["confirmed_target_count"] == 1 and plan["rules"]
    assert "evidence_ids" not in plan and "supported" not in plan


@pytest.mark.parametrize("point,target", [("Python 字体", "font rendering"), ("PygameWrapper 字体", "pygame.font"),
    ("pygame 游戏状态", "foo.pygame.font"), ("pygame 游戏状态", "matplotlib.font"),
    ("pygame 游戏状态", "matplotlib 字体"), ("pygame 游戏状态", "text input"), ("pygame 游戏状态", "collision boxes")])
def test_foreign_or_unrelated_intent_does_not_create_font_heading_hint(point, target):
    assert not catalog.lesson_recall_plan(point, point, [target])["rules"]


@pytest.mark.asyncio
async def test_unrelated_collision_query_does_not_promote_scoring_and_foreign_owner_does_not_fetch():
    provider, series = cached_provider()
    rows = await provider.search("pygame collision tutorial", "en", 6, [], original_point="pygame collision")
    assert rows[0].title == "Collision & Hit Boxes"
    assert series["lessons"][6]["url"] not in {row.url for row in rows}
    for point in ("JavaScript font", "PygameWrapper font", "foo.pygame font"):
        assert await provider.search(point, "en", 6, [], original_point=point, learning_targets=["pygame.font"]) == []
        assert provider.last_requests == []


@pytest.mark.asyncio
async def test_confirmed_literal_heading_is_generic_and_cache_does_not_pin_previous_target():
    provider, series = cached_provider()
    first = await provider.search("pygame状态", "zh", 1, [], original_point="pygame 状态", learning_targets=["pygame.font"])
    second = await provider.search("pygame状态", "zh", 1, [], original_point="pygame 状态", learning_targets=["sound effects music"])
    assert first[0].title == "Scoring & Health Bars" and second[0].title == "Sound Effects & Music"
    assert first[0].discovery_evidence["confirmed_targets_sha256"] != second[0].discovery_evidence["confirmed_targets_sha256"]
    assert second[0].discovery_evidence["recall_rules"] == [] and provider.last_requests == []


@pytest.mark.asyncio
async def test_existing_fetcher_budget_and_six_candidate_limits_are_unchanged():
    old, transport = transport_fixture()
    provider = catalog.TechWithTimCatalogProvider(old.settings, fetcher=old.fetcher)
    rows = await provider.search("pygame collision", "en", 99, [], original_point="pygame collision", learning_targets=["pygame.font"])
    assert len(rows) == 6
    assert len(transport.calls) == 3 and transport.calls[0].endswith("/robots.txt")
    assert len(provider.last_discovery["indexes"]) == 2


def fenced(code, prose="This own lesson explains the frame loop."):
    return prose + "\n```python\n" + code + "\n```"


GOOD = "def main():\n    clock = pygame.time.Clock()\n    flag = True\n    while flag:\n        clock.tick(10)\n"


@pytest.mark.parametrize("code", [GOOD,
    GOOD.replace("clock.tick(10)", "clock.tick(framerate=30)"),
    GOOD.replace("clock =", "fps = 24\n    clock =").replace("clock.tick(10)", "clock.tick(fps)"),
    GOOD.replace("flag = True\n    while flag:", "for frame in range(3):"),
])
def test_only_positive_explicit_pygame_clock_tick_in_loop_proves_requested_frame_limit(code):
    assert clock.is_pygame_clock_frame_limit("clock.tick 限帧", fenced(code))


@pytest.mark.parametrize("code", [GOOD.replace("tick(10)", "tick()"), GOOD.replace("tick(10)", "tick(0)"),
    GOOD.replace("tick(10)", "tick(-10)"), GOOD.replace("tick(10)", "tick(True)"), GOOD.replace("tick(10)", "tick(" + "9" * 400 + ")"),
    GOOD.replace("pygame.time.Clock()", "foreign.time.Clock()"), GOOD.replace("clock.tick", "other.tick"),
    GOOD.replace("flag = True", "clock = helper\n    flag = True"),
    GOOD.replace("flag = True", "clock.tick = helper\n    flag = True"),
    GOOD.replace("flag = True", "flag = False"), GOOD.replace("while flag:", "while False:"),
    GOOD.replace("        clock.tick(10)", "        if False:\n            clock.tick(10)"),
    GOOD.replace("def main():", "def main(pygame):"),
    GOOD.replace("clock =", "pygame = helper\n    clock ="),
    GOOD.replace("flag = True", "fps = 30\n    fps = 0\n    flag = True").replace("tick(10)", "tick(fps)"),
    GOOD.replace("flag = True\n    while flag:", "for frame in range(0):"),
    GOOD + "\ndef other():\n    pass",
])
def test_clock_wrong_owner_reassignment_nonpositive_dead_or_unbound_call_is_rejected(code):
    assert not clock.is_pygame_clock_frame_limit("clock.tick 限帧", fenced(code))


@pytest.mark.parametrize("prose", ["Prerequisites: Clock.tick frame limiting.", "TODO: frame limiting.",
    "We do not teach calling clock.tick.", "Next lesson will cover clock.tick.", "本课不教限帧。",
    "We cannot limit the frame rate in this main() function.", "We can't control frame rate here.",
    "Frame limiting cannot be taught in this main() function."])
def test_full_context_negation_prerequisite_and_future_scope_cannot_be_cropped(prose):
    assert not clock.is_pygame_clock_frame_limit("clock.tick 限帧", fenced(GOOD, prose))


@pytest.mark.parametrize("target", ["pygame.get_ticks 真实计时", "clock.tick 限帧与胜利冻结", "clock.tick 限帧和重置",
                                   "游戏窗口与主循环", "clock.tick(0) 限帧"])
def test_clock_helper_never_supports_whole_unit_timing_or_unrequested_qualifier(target):
    assert not clock.is_pygame_clock_frame_limit(target, fenced(GOOD))


def snake_html():
    return (FIXTURES / "twt_recall/snake-tutorial-1.html").read_text(encoding="utf-8")


def extract(monkeypatch, html):
    monkeypatch.setattr(registry, "ADAPTERS", (adapter.TechWithTimLessonAdapter(),))
    manifest = json.loads((FIXTURES / "twt_recall/snake-source.json").read_text(encoding="utf-8"))
    url = manifest["source_url"]
    result = MetadataExtractor().extract(html, url, "2026-10-18T00:00:00Z")
    result.update(resource_id="retained-own-demo", url=url, canonical_url=url, discovered_at=result["fetched_at"])
    return result


def test_actual_own_function_survives_extractor_evidence_and_binding_with_exact_indentation(monkeypatch):
    resource = extract(monkeypatch, snake_html())
    summary = resource["video_topic_summary"]
    assert "```python\ndef main():" in summary and "\n    while flag:\n" in summary
    assert "clock = pygame.time.Clock()" in summary and "clock.tick(10)" in summary
    assert "class snake" not in summary and "import tkinter" not in summary and "Full Code" not in summary
    assert resource["video_evidence_status"] == "page_verified"
    assert adapter.bound_video_topic_summary(resource, resource["evidence"]) == summary
    source = next(row for row in resource["evidence"] if row.get("field") == "video_topic_summary")
    assert source["text"] == summary
    assert clock.is_pygame_clock_frame_limit("clock.tick 限帧", summary)
    assert not clock.is_pygame_clock_frame_limit("pygame.get_ticks 计时", summary)


def test_actual_confirmed_clock_skill_is_partial_with_all_timing_and_whole_unit_requirements_unknown(monkeypatch):
    resource = extract(monkeypatch, snake_html())
    point = {"knowledge_point_id": "time-unit", "text": "pygame 真实时间计时与限帧", "learning_targets": [
        "pygame.time.get_ticks 毫秒", "结束时间减开始时间", "clock.tick 限帧", "重置时更新时间基准"]}
    request = SearchRequest(knowledge_points=[point["text"]], student_level="intermediate")
    before = deepcopy((resource, resource["evidence"]))
    match = ranking.rank_resource(point, resource, resource["evidence"], request)
    assert match and match["topic_evidence_status"] == "partial"
    rows = {row["text"]: row for row in match["subtopic_coverage"]}
    assert rows["clock.tick 限帧"]["status"] == "supported"
    assert all(rows[text]["status"] == "unknown" for text in point["learning_targets"] if text != "clock.tick 限帧")
    assert all(row["status"] == "unknown" for row in match["subtopic_coverage"] if not row["id"].startswith("learning_target_"))
    assert (resource, resource["evidence"]) == before
    point.pop("learning_targets")
    assert ranking.rank_resource(point, resource, resource["evidence"], request) is None


@pytest.mark.parametrize("owner", ["Arduino", "pandas", "foo.pygame", "PygameWrapper", "pygame.time"])
def test_confirmed_clock_fallback_cannot_borrow_foreign_or_nonroot_unit_owner(monkeypatch, owner):
    resource = extract(monkeypatch, snake_html())
    point = {"knowledge_point_id": "foreign-clock", "text": owner + " 主循环与按键",
             "learning_targets": ["clock.tick 限帧"]}
    request = SearchRequest(knowledge_points=[point["text"]], student_level="intermediate")
    before = deepcopy(resource)
    match = ranking.rank_resource(point, resource, resource["evidence"], request)
    assert match is None or all(
        row["status"] == "unknown" for row in match["subtopic_coverage"]
        if row["id"].startswith("learning_target_")
    )
    assert resource == before


@pytest.mark.parametrize("prose", ["We cannot limit the frame rate in this main() function.",
                                 "We can't cap frame rate in this main() function."])
def test_actual_extraction_keeps_negative_function_scope_from_proving_clock(monkeypatch, prose):
    document = BeautifulSoup(snake_html(), "html.parser")
    block = next(tag for tag in document.find_all("pre") if tag.get_text().lstrip().startswith("def main():"))
    block.find_previous("p").string = prose
    resource = extract(monkeypatch, str(document))
    summary = resource.get("video_topic_summary", "")
    assert "```python\ndef main():" not in summary
    assert not clock.is_pygame_clock_frame_limit("clock.tick 限帧", summary)
    point = {"knowledge_point_id": "negative-clock", "text": "pygame 真实时间计时与限帧",
             "learning_targets": ["clock.tick 限帧"]}
    match = ranking.rank_resource(point, resource, resource["evidence"],
                                 SearchRequest(knowledge_points=[point["text"]], student_level="intermediate"))
    assert match is None or all(row["status"] == "unknown" for row in match["subtopic_coverage"]
                               if row["id"].startswith("learning_target_"))


@pytest.mark.parametrize("prose,code", [("We explain main() function.", GOOD.replace("pygame.time.Clock", "foreign.Clock")),
    ("We explain main() function.", GOOD.replace("pygame.time.Clock", "foreign.Clock").replace("flag = True", "log(pygame)\n    flag = True")),
    ("We explain main() function.", GOOD.replace("clock =", "# TODO: frame limiting\n    clock =")),
    ("The complete program is inside main() function.", GOOD),
    ("Prerequisites: main() function.", GOOD), ("TODO: main() function.", GOOD),
    ("We do not teach main() function.", GOOD), ("We explain unrelated() function.", GOOD),
    ("We cannot limit the frame rate in this main() function.", GOOD),
    ("We can't cap frame rate in this main() function.", GOOD),
    ("We explain main() function.", GOOD + "\nclass Other:\n    pass"),
    ("We explain main() function.", "import pygame\n" + GOOD),
    ("We explain main() function.", GOOD + "\ndef extra():\n    pass"),
    ("We explain main() function.", GOOD.replace("clock.tick(10)", "pass\n" + "        pass\n" * 40)),
])
def test_function_demo_is_finite_owned_and_immediately_explained(prose, code):
    pre = BeautifulSoup("<pre></pre>", "html.parser").pre
    pre.string = code
    assert adapter._function_demonstration(pre, prose) is None


def test_full_code_or_final_program_never_enters_own_function_summary():
    for heading in ("Full Code", "Final Program", "Complete Code"):
        body = BeautifulSoup("<div><p>This lesson explains pygame steps in detail.</p><p>We explain the game here in this own lesson.</p>"
                             + "<h2>" + heading + "</h2><p>We explain main() function.</p><pre></pre></div>", "html.parser").div
        body.pre.string = GOOD
        summary = adapter._teaching_summary(body, "Own lesson")
        assert summary and "def main" not in summary
