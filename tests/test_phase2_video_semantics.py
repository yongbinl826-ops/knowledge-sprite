"""Bounded documented API semantics; fixtures are offline public-index shapes."""
from copy import deepcopy

import pytest

from backend.app.models import SearchRequest
from backend.app.ranking import compound_english_match, rank_resource


POINT = "pygame 小球下落与矩形碰撞判定"
REAL_TITLE = "Collision Detection - PyGame Thursdays 8"
REAL_SNIPPET = "... Pygame is super simple with the colliderect() function, and I'll show you everything you need to know in this video. #pygame #codemy ..."
REAL_URL = "https://www.youtube.com/watch?v=UGubCYs25IY"


def assess(title, snippet="", *, point=POINT, url=REAL_URL, video_type=True):
    evidence = [{"evidence_id": "s", "kind": "search", "source": "offline-public-index-shape",
                 "url": url, "title": title, "snippet": snippet, "knowledge_point_id": "p",
                 "type_source": "search_template" if video_type else None, "resource_type_hint": "video" if video_type else "unknown"}]
    identity = {"source": "search_template", "evidence_id": "s", "url": url}
    resource = {"resource_id": "r", "url": url, "canonical_url": url, "title": title, "platform": "youtube",
                "resource_type": "video", "video_evidence_status": "search_discovered", "fetch_status": "search_only_policy",
                "metadata_evidence_level": "search", "chapters": [],
                "field_provenance": {"title": {"source": "search", "evidence_id": "s"}, "resource_type": identity,
                                     "video_evidence_status": identity}}
    before = deepcopy((resource, evidence))
    match = rank_resource({"knowledge_point_id": "p", "text": point}, resource, evidence, SearchRequest(knowledge_points=[point]))
    assert (resource, evidence) == before
    return match


@pytest.mark.parametrize("title,snippet", [
    (REAL_TITLE, REAL_SNIPPET),
    ("Collisions in Pygame - Beginner Tutorial", "In this video I will explain how to check for collisions in Pygame ... colliderect(), point collisions using collidepoint() and line ..."),
    ("pygame.Rect.colliderect tutorial", ""),
    ("Pygame Rect.colliderect 函数讲解", ""),
])
def test_documented_rect_collision_does_not_prove_falling(title, snippet):
    match = assess(title, snippet)
    assert match and match["topic_evidence_status"] == "partial"
    assert {row["text"]: row["status"] for row in match["subtopic_coverage"]} == {"小球下落": "unknown", "矩形碰撞判定": "supported"}
    assert "尚未确认：小球下落" in match["recommendation_reason"]
    assert "pygame_colliderect_tests_rectangle_overlap" in match["topic_match_rules"]


@pytest.mark.parametrize("title,snippet", [
    ("Pygame Sprite 碰撞检测教程", ""),
    ("Pygame 自定义碰撞区域和函数", ""),
    ("Pygame collidepoint() tutorial", ""),
    ("Pygame 教程", "不讲 colliderect()，仅讲窗口创建。"),
    ("Pygame 教程", "仅列出 API 列表：colliderect()。"),
    ("Pygame 教程", "api list: colliderect()"),
    ("Pygame 教程", "Listing methods: colliderect()"),
    ("Pygame 教程", "Reference: colliderect()"),
    ("Pygame 教程", "需先掌握 colliderect()，本节讲窗口创建。"),
    ("Qt colliderect() tutorial", ""),
    ("Pygame 安装教程", "Qt Rect.colliderect() tutorial"),
    ("Pygame 安装教程", "... Qt colliderect() tutorial"),
    ("Pygame 教程", "You need to already know colliderect(), this lesson teaches window setup."),
    ("Pygame helper.colliderect() tutorial", ""),
    ("Pygame pygame.RectWrapper.colliderect() tutorial", ""),
    ("Pygame 窗口创建教程", "课程大纲：课时1 窗口创建；课时2 colliderect() tutorial"),
    ("Pygame window tutorial", "Course outline: lesson1 window setup; lesson2 colliderect() tutorial"),
    ("Pygame 窗口创建教程", "相关视频：Pygame colliderect() tutorial"),
    ("Pygame 窗口创建教程", "参考链接 https://example.org/pygame/colliderect()"),
])
def test_unproved_rectangle_operations_remain_unknown(title, snippet):
    match = assess(title, snippet)
    assert match is None or not any(row["status"] == "supported" for row in match["subtopic_coverage"] if row["text"] == "矩形碰撞判定")


def test_api_equivalence_cannot_discard_extra_qualifications_or_create_video_from_docs():
    assert assess(REAL_TITLE, REAL_SNIPPET, point="pygame 小球下落与像素级矩形碰撞判定") is None
    assert assess(REAL_TITLE, REAL_SNIPPET, url="https://www.pygame.org/docs/ref/rect.html", video_type=False) is None
    assert assess("pygame 矩形碰撞判定教程", point=POINT)
    assert compound_english_match("pygame 矩形碰撞判定", ["pygame.Rect.colliderect tutorial"])


@pytest.mark.asyncio
async def test_real_index_shape_search_admission_to_final_partial_without_page_or_playback(tmp_path):
    import httpx
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.providers import SearXNGProvider
    from backend.app.service import JobService

    def respond(request):
        return httpx.Response(200, json={"results": [{"title": REAL_TITLE, "content": REAL_SNIPPET, "url": REAL_URL, "template": "videos.html"}]})
    class RestrictedPlatformMetadata:
        async def enrich(self, candidate):
            return {"fetch_status": "site_policy_blocked", "metadata_evidence_level": "search", "chapters": [], "evidence": []}
    settings = Settings(database_path=str(tmp_path / "documented-api.sqlite3"), searxng_url="https://search.example",
                        searxng_video_engines=("primary",), max_search_requests=1, max_detail_pages=1, search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = Store(settings.database_path)
        service = JobService(settings, store, provider=SearXNGProvider(settings, client), fetcher=RestrictedPlatformMetadata())
        try:
            jid = service.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=[]))["job_id"]
            await service.run(jid)
            group = service.results(jid)["groups"][0]
            assert not group["items"] and len(group["partial_items"]) == 1
            item = group["partial_items"][0]
            assert item["resource"]["video_evidence_status"] == "search_discovered"
            assert item["resource"]["chapters"] == []
            assert item["match"]["subtopic_coverage"][0]["status"] == "unknown"
            assert item["match"]["subtopic_coverage"][1]["status"] == "supported"
        finally:
            store.close()


@pytest.mark.parametrize("media_type", [None, "Article", "VideoObject", "Course"])
def test_source_language_distinguishes_page_tags_from_media_course_metadata(media_type):
    from backend.app.extractor import MetadataExtractor
    from backend.app.ranking import source_language_notice
    import json
    url = "https://example.org/lesson"
    payload = json.dumps({"@type": media_type, "inLanguage": "en", "name": "Python lesson"}) if media_type else None
    html = '<html lang="en"><head><title>Python 中文标题</title>'
    if payload:
        html += '<script type="application/ld+json">' + payload + '</script>'
    html += '</head><body>' + 'Visible lesson description. ' * 5 + '</body></html>'
    resource = MetadataExtractor().extract(html, url, "2026-10-18T00:00:00Z")
    resource.update(url=url, canonical_url=url)
    notice = source_language_notice(resource, resource["evidence"], "zh")
    assert "英语（en）" in notice and "偏好为中文" in notice
    if media_type in {"VideoObject", "Course"}:
        assert "视频/课程元数据标注语言" in notice and "音轨与字幕" in notice
    else:
        assert "来源页面语言" in notice and "视频/授课语言仍需确认" in notice
    resource["language"] = "zh"
    assert "中文（zh）" not in source_language_notice(resource, resource["evidence"], "zh")


def test_unknown_language_never_guesses_chinese_from_title_or_removes_stage_guidance():
    from backend.app.ranking import source_language_notice
    assert "尚未由来源元数据确认" in source_language_notice({"title": "Python 中文标题"}, [], "zh")
    assert "尚未核实" in source_language_notice({"language": "en"}, [], "zh")
    match = assess(REAL_TITLE, REAL_SNIPPET)
    assert "视频/授课语言尚未由来源元数据确认" in match["recommendation_reason"]
    assert "学习门槛未由来源明确确认" in match["recommendation_reason"]
