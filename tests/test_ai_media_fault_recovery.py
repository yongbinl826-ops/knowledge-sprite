"""A source-declared current audio defect must not stop later gap recovery."""
import json

import httpx
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from test_ai_grounded_recovery import POINT, URL, DEAD_URL, SourcePages, organic, recovery_service, run, visible


@pytest.mark.parametrize("teaching", [False, True])
async def test_audio_fault_is_retained_but_following_english_query_recovers(teaching, recovery_service):
    def respond(query, _count):
        target = DEAD_URL if "event loop" in query else URL
        return httpx.Response(200, json={"organic": [organic(url=target)]})

    service, searches, _ = recovery_service(plan={POINT: {"urls": [], "queries": []}},
        respond=respond, teaching_match_enabled=teaching)

    class Pages(SourcePages):
        async def enrich(self, candidate):
            if candidate["url"] != URL:
                return await super().enrich(candidate)
            self.calls.append(candidate)
            video = {"@context": "https://schema.org", "@type": "VideoObject", "name": POINT,
                "description": "音频坏了 不想录了 就这样吧 后面应该会有完整版",
                "contentUrl": "https://media.example.org/audio-broken.mp4"}
            return MetadataExtractor().extract('<script type="application/ld+json">'
                + json.dumps(video, ensure_ascii=False) + '</script>', candidate["url"], now())

    service.fetcher = Pages({DEAD_URL: POINT})
    identifier, result = await run(service)
    raw = service.store.resources(identifier)
    faulty = next(row for row in raw.values() if row["url"] == URL)
    assert faulty["description"].startswith("音频坏了")
    assert faulty["video_evidence_status"] == "page_verified"
    assert len(searches) == 2 and searches[-1].endswith("Pygame event loop")
    group = result["groups"][0]
    assert visible(group) and all(row["resource"]["url"] == DEAD_URL for row in visible(group))
    assert all(row["resource"]["url"] != URL for row in group.get("discovery_items", []))
    assert service.store.get_job(identifier)["ai_video_fallback"]["remaining_points"] == 0
