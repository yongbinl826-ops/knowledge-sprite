"""A playable paid preview cannot close a free recommendation gap."""
import json

import httpx
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import now
from backend.app.related_recommendations import related_recommendation
from test_ai_grounded_recovery import POINT, URL, SourcePages, organic, recovery_service, run, visible
from test_related_input_document_aliases import bound_page


FREE_URL = "https://www.bilibili.com/video/BV1xx411c7Dh"


@pytest.mark.asyncio
@pytest.mark.parametrize("teaching", [False, True])
async def test_paid_model_link_is_retained_but_bilingual_recovery_finds_free_page(recovery_service, teaching):
    hints = ["Pygame 事件循环示例", "Pygame 事件循环完整课程"]
    def respond(_query, count):
        return httpx.Response(200, json={"organic": [organic(url=FREE_URL if count == 3 else URL)]})
    service, searches, _ = recovery_service(plan={POINT: {"urls": [URL], "queries": hints}},
        respond=respond, teaching_match_enabled=teaching)

    class Pages(SourcePages):
        async def enrich(self, candidate):
            if candidate["url"] != URL:
                return await super().enrich(candidate)
            self.calls.append(candidate)
            node = {"@context": "https://schema.org", "@type": "VideoObject", "name": POINT,
                    "description": POINT + "完整课程", "offers": {"@type": "Offer", "price": "18"},
                    "contentUrl": "https://media.example.org/paid.mp4"}
            return MetadataExtractor().extract('<script type="application/ld+json">'
                + json.dumps(node, ensure_ascii=False) + '</script>', candidate["url"], now())

    service.fetcher = Pages({FREE_URL: POINT})
    identifier, result = await run(service)
    resources = service.store.resources(identifier)
    paid = next(row for row in resources.values() if row["url"] == URL)
    assert paid["requires_payment"] is True and paid["video_evidence_status"] == "page_verified"
    assert len(searches) == 3
    assert searches[0].endswith(POINT)
    assert searches[1].endswith("Pygame event loop")
    assert any(searches[2].endswith(hint) for hint in hints)
    rows = visible(result["groups"][0])
    assert rows and all(row["resource"]["url"] == FREE_URL for row in rows)
    assert not any(row["resource"]["url"] == URL for row in result["groups"][0].get("discovery_items", []))
    assert service.store.get_job(identifier)["ai_video_fallback"]["remaining_points"] == 0


@pytest.mark.parametrize("paid", [True, False, None])
def test_related_links_preserve_payment_requirement_without_claiming_unknown_is_free(paid):
    args = bound_page("文件下载", "Streamlit", "Streamlit 下载按钮")
    args[1]["requires_payment"] = paid
    result = related_recommendation(*args)
    assert result
    assert result["resource"]["requires_payment"] is paid
    assert result["reference"]["exact_teaching_verified"] is False
