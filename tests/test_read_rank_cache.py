from copy import deepcopy

import pytest
from backend.app.models import SearchRequest
from backend.app.read_rank_cache import ReadRankCache




def arguments():
    return {"point": {"knowledge_point_id": "p", "text": "pandas CSV", "learning_targets": ["read_csv"]},
        "resource": {"resource_id": "r", "url": "https://example.org/a", "field_provenance": {"title": {"evidence_id": "e"}}},
        "observed": [{"evidence_id": "e", "text": "pandas read_csv"}],
        "eligibility_evidence": [{"evidence_id": "identity", "text": "video"}],
        "request": SearchRequest(knowledge_points=["pandas CSV"]), "require_type": True}


@pytest.mark.parametrize("field", ["point_text", "target", "point_id", "resource_url", "resource_id", "provenance", "observed", "eligibility", "request", "require_type"])
def test_every_semantic_or_provenance_input_changes_key(field):
    calls = []
    cache = ReadRankCache(ranker=lambda *a, **k: calls.append(1) or {"value": [len(calls)]})
    args = arguments(); cache.rank(**args); cache.rank(**args)
    changed = deepcopy(args)
    if field == "point_text": changed["point"]["text"] += " other"
    elif field == "target": changed["point"]["learning_targets"].append("to_csv")
    elif field == "point_id": changed["point"]["knowledge_point_id"] = "q"
    elif field == "resource_url": changed["resource"]["url"] += "/chapter"
    elif field == "resource_id": changed["resource"]["resource_id"] = "s"
    elif field == "provenance": changed["resource"]["field_provenance"]["title"]["evidence_id"] = "different"
    elif field == "observed": changed["observed"][0]["text"] += " not taught"
    elif field == "eligibility": changed["eligibility_evidence"][0]["text"] = "text only"
    elif field == "request": changed["request"] = changed["request"].model_copy(update={"language": "en"})
    else: changed["require_type"] = False
    cache.rank(**changed)
    assert len(calls) == 2 and cache.hits == 1
    assert all(isinstance(k, str) and len(k) == 64 for k in cache.entries)


def test_none_is_cached_and_exceptions_are_not_cached():
    calls = []
    cache = ReadRankCache(ranker=lambda *a, **k: calls.append(1))
    assert cache.rank(**arguments()) is None and cache.rank(**arguments()) is None
    assert len(calls) == 1 and cache.hits == 1
    def fail(*a, **k): calls.append(1); raise RuntimeError("synthetic")
    failing = ReadRankCache(ranker=fail)
    for _ in range(2):
        with pytest.raises(RuntimeError): failing.rank(**arguments())
    assert not failing.entries


def test_deepcopy_at_insert_and_hit_prevents_mutation_poisoning():
    original = {"subtopic_coverage": [{"status": "unknown"}]}
    cache = ReadRankCache(ranker=lambda *a, **k: original)
    first = cache.rank(**arguments()); first["subtopic_coverage"][0]["status"] = "forged"
    second = cache.rank(**arguments()); assert second["subtopic_coverage"][0]["status"] == "unknown"
    second["subtopic_coverage"].clear()
    assert cache.rank(**arguments())["subtopic_coverage"] == [{"status": "unknown"}]


def test_lru_entry_limit_and_output_byte_limit():
    cache = ReadRankCache(ranker=lambda *a, **k: {"value": "x" * 30}, max_entries=2, max_output_bytes=100)
    first = arguments(); second = arguments(); second["point"]["text"] = "two"
    third = arguments(); third["point"]["text"] = "three"
    cache.rank(**first); cache.rank(**second); cache.rank(**first); cache.rank(**third)
    assert len(cache.entries) == 2 and cache.output_bytes <= 100 and cache.evictions == 1
    previous_misses = cache.misses; cache.rank(**second)
    assert cache.misses == previous_misses + 1
    big = ReadRankCache(ranker=lambda *a, **k: {"value": "x" * 101}, max_output_bytes=100)
    big.rank(**first); assert not big.entries and big.output_bytes == 0


def test_oversized_unserializable_inputs_bypass_without_changing_ranker_behavior():
    calls = []
    cache = ReadRankCache(ranker=lambda *a, **k: calls.append(1) or {"ok": True}, max_input_bytes=100)
    for _ in range(2): assert cache.rank(**arguments()) == {"ok": True}
    assert len(calls) == 2 and not cache.entries and cache.bypasses == 2
    cache = ReadRankCache(ranker=lambda *a, **k: calls.append(1) or None)
    args = arguments(); args["resource"]["non_json"] = object()
    cache.rank(**args); cache.rank(**args)
    assert not cache.entries and cache.bypasses == 2
