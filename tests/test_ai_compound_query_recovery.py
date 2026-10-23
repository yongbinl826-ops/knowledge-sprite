"""An independent English discovery lead still matches only the unchanged unit."""
import httpx
import pytest

from backend.app.ai_video_service import visible_point_ids
from backend.app.models import SearchRequest
from test_ai_grounded_recovery import URL, SourcePages, recovery_service


@pytest.mark.parametrize("teaching", [False, True])
@pytest.mark.parametrize("source_topic,covered", [
    ("Rust 数组排序", False),
    ("Rust 借用检查与生命周期推断", True),
])
async def test_complete_original_remains_the_only_matching_target(teaching, source_topic, covered, recovery_service):
    point = "借用检查与生命周期推断"
    hint = "Rust array sorting"  # Deliberately unrelated, not a trusted translation.
    original = "Rust " + point
    supplemented = hint

    def respond(query, _count):
        return httpx.Response(200, json={"organic": [] if not query.endswith(supplemented) else [
            {"title": original, "snippet": original, "link": URL}]})

    service, searches, _ = recovery_service(plan={point: {"urls": [], "queries": [hint]}},
        respond=respond, teaching_match_enabled=teaching)
    service.fetcher = SourcePages({URL: source_topic})
    identifier = service.create(SearchRequest(knowledge_points=[point], preferred_platforms=["bilibili"],
        topic_technologies={point: "Rust"}))["job_id"]
    await service.run(identifier)
    job = service.store.get_job(identifier)
    assert searches == ["site:bilibili.com " + original, "site:bilibili.com " + supplemented]
    assert len(service.fetcher.calls) == 1
    assert bool(visible_point_ids(service, job)) is covered
    assert job["ai_video_fallback"]["remaining_points"] == (0 if covered else 1)
    assert job["knowledge_points"][0]["text"] == point
    resource = next(iter(service.store.resources(identifier).values()))
    assert resource["fetch_status"] == "fetched" and resource["video_evidence_status"] == "page_verified"
    assert hint not in resource["title"] and hint not in resource["description"]
