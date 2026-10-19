"""Synthetic cache working-set regression; live source replay is separate evidence."""
import json

from backend.app.models import SearchRequest
from backend.app.read_rank_cache import ReadRankCache


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def test_default_cache_retains_305_mixed_positive_and_none_inputs_without_reranking():
    # Actual r7 replay found 292 None outputs and 13 positive outputs in a 305
    # input working set. This synthetic test covers only cache behavior, never
    # source identity or learning evidence correctness.
    calls = []
    def rank(point, resource, observed, request, **kwargs):
        calls.append(point["knowledge_point_id"])
        if point["ordinal"] < 292:
            return None
        return {"resource_id": resource["resource_id"], "subtopic_coverage": [
            {"status": "unknown", "evidence_ids": [observed[0]["evidence_id"]]}]}
    cache = ReadRankCache(ranker=rank)
    request = SearchRequest(knowledge_points=["independent cache fixture"])
    inputs = [{"point": {"knowledge_point_id": f"point-{i}", "text": "independent cache fixture", "ordinal": i},
        "resource": {"resource_id": f"resource-{i}", "url": f"https://example.org/lessons/{i}"},
        "observed": [{"evidence_id": f"observation-{i}", "text": "Unchanged own observation"}],
        "eligibility_evidence": [{"evidence_id": f"identity-{i}", "text": "Unchanged identity"}],
        "request": request} for i in range(305)]
    first = [cache.rank(**item) for item in inputs]
    original_bytes = encoded(first)
    assert sum(item is None for item in first) == 292
    assert len(calls) == 305 and cache.misses == 305
    # Returned cold objects must not be able to poison the stored positive.
    first[-1]["subtopic_coverage"][0]["status"] = "forged"
    second = [cache.rank(**item) for item in inputs]
    assert encoded(second) == original_bytes
    assert len(calls) == 305 and cache.hits == 305 and cache.evictions == 0
    second[-1]["subtopic_coverage"].clear()
    third = [cache.rank(**item) for item in inputs]
    assert encoded(third) == original_bytes
    assert len(calls) == 305 and cache.hits == 610 and cache.evictions == 0
    assert cache.stats()["output_bytes"] <= 8 * 1024 * 1024
