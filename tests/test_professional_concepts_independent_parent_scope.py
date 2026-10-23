"""Verified current parent ownership may scope its own canonical chapter title."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import pytest

SOURCE = Path(os.environ.get("PROFESSIONAL_CONCEPT_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(SOURCE))
CASES = [("pygame", "碰撞检测", "JavaScript"), ("JavaScript", "事件", "pygame"),
    ("微信小程序", "事件", "支付宝小程序"), ("micro:bit", "数字输入", "Arduino")]


def own_course(owner, concept):
    from backend.app.extractor import MetadataExtractor
    url = "https://www.bilibili.com/video/BV1AAAAAAAAA/"
    state = {"videoData": {"bvid": "BV1AAAAAAAAA", "title": owner + " 入门课程",
        "desc": "本课程使用 " + owner + "，面向入门学习者。", "owner": {"name": "Synthetic instructor"},
        "pages": [{"page": 1, "part": concept, "duration": 120, "cid": 123}]}}
    parsed = MetadataExtractor().extract("<script>window.__INITIAL_STATE__="
        + json.dumps(state, ensure_ascii=False) + ";</script>", url, datetime.now(timezone.utc).isoformat())
    evidence = parsed.pop("evidence")
    return {**parsed, "resource_id": "own-course", "url": url, "canonical_url": url,
        "resolved_url": url, "platform": "bilibili"}, evidence


@pytest.mark.parametrize("owner,concept,foreign", CASES)
def test_verified_current_parent_and_own_chapter_preserve_existing_support(owner, concept, foreign):
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource
    resource, evidence = own_course(owner, concept)
    canonical_point = {"knowledge_point_id": "k1", "text": concept}
    original = deepcopy(canonical_point)
    empty = SearchRequest(knowledge_points=[concept])
    mapped = SearchRequest(knowledge_points=[concept], topic_technologies={concept: owner})
    canonical = rank_resource(canonical_point, resource, evidence, empty)
    assert canonical and canonical["topic_evidence_status"] == "supported"
    prefixed = owner + " " + concept
    legacy = rank_resource({"knowledge_point_id": "k1", "text": prefixed}, resource, evidence,
        SearchRequest(knowledge_points=[prefixed]))
    explicit = rank_resource(canonical_point, resource, evidence, mapped)
    # Only the two existing Latin-prefix parent-inheritance positives are a
    # regression gate. The other two are recorded conservative old limitations.
    if owner in {"pygame", "JavaScript"}:
        assert legacy and legacy["topic_evidence_status"] == "supported"
        assert explicit and explicit["topic_evidence_status"] == "supported"
    assert canonical_point == original and mapped.knowledge_points == [concept]


@pytest.mark.parametrize("owner,concept,foreign", CASES)
def test_other_verified_parent_stack_does_not_scope_canonical_chapter(owner, concept, foreign):
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource
    resource, evidence = own_course(foreign, concept)
    result = rank_resource({"knowledge_point_id": "k1", "text": concept}, resource, evidence,
        SearchRequest(knowledge_points=[concept], topic_technologies={concept: owner}))
    assert result is None or result["topic_evidence_status"] == "needs_review"
