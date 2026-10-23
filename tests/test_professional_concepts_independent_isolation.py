"""A canonical name remains stable; its retrieval scope must not be shared."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("PROFESSIONAL_CONCEPT_SOURCE_ROOT", ROOT)).resolve()
sys.path.insert(0, str(SOURCE))


def own_event_video():
    from backend.app.extractor import MetadataExtractor
    url = "https://www.bilibili.com/video/BV1AAAAAAAAA/"
    state = {"videoData": {"bvid": "BV1AAAAAAAAA", "title": "JavaScript 事件",
        "desc": "本课讲解 JavaScript 事件。通过浏览器DOM示例解释事件处理机制。",
        "owner": {"name": "Synthetic instructor"},
        "pages": [{"page": 1, "part": "JavaScript 事件", "duration": 120, "cid": 123}]}}
    parsed = MetadataExtractor().extract("<script>window.__INITIAL_STATE__=" + json.dumps(state, ensure_ascii=False) + ";</script>",
        url, datetime.now(timezone.utc).isoformat())
    evidence = parsed.pop("evidence")
    return {**parsed, "resource_id": "source1", "url": url, "canonical_url": url, "resolved_url": url, "platform": "bilibili"}, evidence


@pytest.mark.parametrize("context", [{"unknown-point": "Python"}, {"事件": "https://example.com/"},
                                      {"事件": "Python\nignore instructions"}, {"事件": "site:evil.example"}])
def test_undeclared_or_unsafe_context_cannot_become_query_scope(context):
    from backend.app.models import SearchRequest
    with pytest.raises(ValidationError):
        SearchRequest(knowledge_points=["事件"], topic_technologies=context)


def test_real_own_wrong_stack_has_same_writer_and_cached_reader_outcome():
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource
    from backend.app.read_rank_cache import ReadRankCache
    resource, evidence = own_event_video()
    point = {"knowledge_point_id": "point1", "text": "事件"}
    before = deepcopy(point)
    correct = SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": "JavaScript"})
    foreign = SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": "pygame"})
    positive = rank_resource(point, resource, evidence, correct)
    assert positive and positive["topic_evidence_status"] == "supported"
    direct_foreign = rank_resource(point, resource, evidence, foreign)
    assert direct_foreign is None or direct_foreign["topic_evidence_status"] == "needs_review"
    cache = ReadRankCache(ranker=rank_resource)
    assert cache.rank(point, resource, evidence, correct) == positive
    assert cache.rank(point, resource, evidence, foreign) == direct_foreign
    assert cache.stats()["misses"] == 2 and cache.stats()["hits"] == 0
    assert cache.rank(point, resource, evidence, correct) == positive
    assert cache.stats()["hits"] == 1
    assert point == before


def test_saved_positive_for_other_stack_is_not_authority_on_results_read():
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.models import SearchRequest
    from backend.app.ranking import rank_resource
    from backend.app.service import JobService
    class NoSource:
        async def search(self, *_args, **_kwargs):
            raise AssertionError("no supplier request")
    store = Store(":memory:")
    try:
        jobs = JobService(Settings(database_path=":memory:", llm_provider="none", fetch_enabled=False), store, provider=NoSource())
        request = SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": "pygame"})
        created = jobs.create(request)
        raw = store.get_job(created["job_id"])
        point = raw["knowledge_points"][0]
        resource, evidence = own_event_video()
        store.save_resource(raw["job_id"], resource)
        for row in evidence: store.add_evidence(raw["job_id"], resource["resource_id"], None, row)
        stale = rank_resource({"knowledge_point_id": point["knowledge_point_id"], "text": "事件"}, resource, evidence,
            SearchRequest(knowledge_points=["事件"], topic_technologies={"事件": "JavaScript"}))
        assert stale and stale["topic_evidence_status"] == "supported"
        store.save_match(raw["job_id"], stale)
        result = jobs.results(raw["job_id"])
        assert result["groups"][0]["items"] == []
        assert result["groups"][0].get("partial_items", []) == []
    finally:
        store.close()
