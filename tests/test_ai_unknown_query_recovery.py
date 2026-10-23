"""Broader discovery never lets model translations become coverage evidence."""
import httpx
import pytest

from backend.app.ai_video_service import visible_point_ids
from backend.app.models import SearchRequest
from test_ai_grounded_recovery import URL, SourcePages, recovery_service


@pytest.mark.parametrize("teaching", [False, True])
@pytest.mark.parametrize("actual_topic,covered", [("JavaScript 数组排序", False), ("JavaScript 指针事件处理", True)])
async def test_unknown_english_query_requires_independent_original_point_page(teaching, actual_topic, covered, recovery_service):
    point = "指针事件处理"
    # Its owner is valid, but the model's English operation is intentionally wrong.
    hint = "JavaScript array sorting"

    def respond(query, _count):
        return httpx.Response(200, json={"organic": [] if not query.endswith(hint) else [
            {"title": "JavaScript 视频课程", "snippet": "JavaScript 指针事件处理", "link": URL}]})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": [hint]}},
        respond=respond, teaching_match_enabled=teaching)
    service.fetcher = SourcePages({URL: actual_topic})
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "JavaScript"}))["job_id"]
    await service.run(identifier)
    job = service.store.get_job(identifier)
    assert searches == ["site:bilibili.com JavaScript 指针事件处理", "site:bilibili.com " + hint]
    assert len(service.fetcher.calls) == 1
    assert bool(visible_point_ids(service, job)) is covered
    assert job["ai_video_fallback"]["remaining_points"] == (0 if covered else 1)
    resource = next(iter(service.store.resources(identifier).values()))
    assert resource["title"] == actual_topic + "公开教学视频"
    assert resource["fetch_status"] == "fetched" and resource["video_evidence_status"] == "page_verified"
    assert hint not in resource["title"] and hint not in resource["description"]
    assert job["knowledge_points"][0]["text"] == point
