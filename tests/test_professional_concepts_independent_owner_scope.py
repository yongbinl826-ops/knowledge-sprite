"""Mapped context is literal, complete, and taught in this own-page scope."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import pytest

SOURCE = Path(os.environ.get("PROFESSIONAL_CONCEPT_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(SOURCE))

CASES = [
    ("micro:bit", "pygame"),
    ("微信小程序", "支付宝小程序"),
    ("Web Audio API", "Web Storage"),
]


def own_video(owner, description):
    from backend.app.extractor import MetadataExtractor
    url = "https://www.bilibili.com/video/BV1AAAAAAAAA/"
    state = {"videoData": {"bvid": "BV1AAAAAAAAA", "title": owner + " 事件",
        "desc": description, "owner": {"name": "Synthetic instructor"},
        "pages": [{"page": 1, "part": owner + " 事件", "duration": 120, "cid": 123}]}}
    parsed = MetadataExtractor().extract("<script>window.__INITIAL_STATE__="
        + json.dumps(state, ensure_ascii=False) + ";</script>", url, datetime.now(timezone.utc).isoformat())
    evidence = parsed.pop("evidence")
    return {**parsed, "resource_id": "source1", "url": url, "canonical_url": url,
        "resolved_url": url, "platform": "bilibili"}, evidence


@pytest.mark.parametrize("technology,foreign", CASES)
def test_complete_context_literal_is_accepted(technology, foreign):
    from backend.app.professional_concepts import clean_topic_technology, contextual_concept_name
    assert clean_topic_technology(technology) == technology
    assert contextual_concept_name("事件", technology) == technology + " 事件"


@pytest.mark.parametrize("technology,foreign", CASES)
def test_own_current_context_can_support_canonical_concept(technology, foreign):
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource
    point = {"knowledge_point_id": "point1", "text": "事件"}
    original = deepcopy(point)
    request = SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": technology})
    resource, evidence = own_video(technology, f"本课讲解 {technology} 事件，通过本课示例演示事件机制。")
    result = rank_resource(point, resource, evidence, request)
    assert result and result["topic_evidence_status"] == "supported"
    assert point == original and request.knowledge_points == ["事件"]


@pytest.mark.parametrize("technology,foreign", CASES)
@pytest.mark.parametrize("role", ["wrong_stack", "next_lesson", "prerequisite", "reference"])
def test_other_stack_cannot_borrow_context_from_noncurrent_role(technology, foreign, role):
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource
    description = f"本课讲解 {foreign} 事件。"
    if role == "next_lesson":
        description += f"下节课讲解 {technology} 事件。"
    elif role == "prerequisite":
        description += f"先修要求：{technology} 事件。"
    elif role == "reference":
        description += f"{technology} 仅作背景对比，不教授其事件机制。"
    resource, evidence = own_video(foreign, description)
    request = SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": technology})
    result = rank_resource({"knowledge_point_id": "point1", "text": "事件"}, resource, evidence, request)
    assert result is None or result["topic_evidence_status"] == "needs_review", (
        technology, role, result and result["topic_evidence_status"], description)
