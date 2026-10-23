"""An unknown implementation context must keep real video discovery open.

HTTP/model boundaries are synthetic; extraction, storage, projection and gap
recovery run through the production service. No playback is exercised.
"""
import pytest

from backend.app.ai_video_service import visible_point_ids
from backend.app.models import Candidate, SearchRequest
from scripts.verify_grounded_video_live import coverage
from test_ai_video_service import OfflineModel, OfflinePages, OfflineSearch, make_service


POINT = "会话状态管理"
UNKNOWN = "https://www.bilibili.com/video/BV1xx411c7Df"
MATCHED = "https://www.bilibili.com/video/BV1xx411c7Dg"


@pytest.mark.asyncio
@pytest.mark.parametrize("source_topic", [POINT, "Flask " + POINT])
async def test_source_without_selected_framework_does_not_stop_recovery(make_service, source_topic):
    # The search engine suggests the requested framework, but the actual page
    # either omits it or explicitly implements the same topic in another one.
    candidate = Candidate(id="initial", title="Streamlit " + POINT, url=UNKNOWN,
                          source="offline", query="", resource_type_hint="video",
                          type_source="search_template")
    service = make_service(provider=OfflineSearch([candidate]),
        model=OfflineModel({POINT: [MATCHED]}),
        fetcher=OfflinePages({UNKNOWN: source_topic, MATCHED: "Streamlit " + POINT}))
    identifier = service.create(SearchRequest(knowledge_points=[POINT],
        preferred_platforms=["bilibili"], topic_technologies={POINT: "Streamlit"}))["job_id"]
    await service.run(identifier)
    assert service.llm.calls and service.llm.calls[0]["points"] == [POINT]
    assert MATCHED in [row["url"] for row in service.fetcher.calls]
    result = service.results(identifier)
    assert {r["url"] for r in coverage(result)[0]["verified_videos"]} == {MATCHED}
    assert len(visible_point_ids(service, service.store.get_job(identifier))) == 1
    assert service.store.get_job(identifier)["ai_video_fallback"]["remaining_points"] == 0


@pytest.mark.asyncio
async def test_topic_without_requested_technology_keeps_broad_relevance(make_service):
    candidate = Candidate(id="initial", title=POINT, url=UNKNOWN, source="offline", query="",
                          resource_type_hint="video", type_source="search_template")
    service = make_service(provider=OfflineSearch([candidate]), fetcher=OfflinePages({UNKNOWN: POINT}),
                           model=OfflineModel({POINT: [MATCHED]}))
    identifier = service.create(SearchRequest(knowledge_points=[POINT], preferred_platforms=["bilibili"]))["job_id"]
    await service.run(identifier)
    assert service.llm.calls == []
    assert {r["url"] for r in coverage(service.results(identifier))[0]["verified_videos"]} == {UNKNOWN}


def test_live_acceptance_does_not_count_unknown_technology_as_covered():
    evidence = {"evidence_id": "page", "kind": "page"}
    resource = {"resource_id": "actual-page", "url": UNKNOWN, "fetch_status": "fetched",
                "video_evidence_status": "page_verified"}
    row = {"resource": resource, "evidence": [evidence], "reference": {
        "evidence_ids": ["page"], "basis": ["page"], "technical_context": "unconfirmed"}}
    result = {"groups": [{"text": POINT, "technology": "Streamlit", "related_recommendations": [row]}]}
    assert coverage(result)[0]["verified_videos"] == []
