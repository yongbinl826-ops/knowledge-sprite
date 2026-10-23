"""Pending details and current own topics must survive link-only projection."""
import pytest
from backend.app.ai_video_service import visible_point_ids
from backend.app.related_recommendations import related_recommendation
from test_reference_link_contract import search_case, service_for


@pytest.mark.parametrize("status,covered", [("queued", False), ("running", False), ("completed", True), ("partial", True), ("cancelled", True)])
def test_pending_details_do_not_close_active_gap_but_terminal_real_link_survives(status, covered):
    point, resource, evidence, request = search_case()
    resource["fetch_status"] = "not_fetched"
    item = related_recommendation(point, resource, evidence, request)
    assert item["reference"]["link_eligible"] is True
    service, job = service_for(point, resource, evidence, item)
    job["status"] = status
    assert bool(visible_point_ids(service, job)) is covered
