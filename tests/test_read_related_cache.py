"""Independent cache safety tests; retained source replay asserts policy parity."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.models import SearchRequest
from backend.app.read_related_cache import ReadRelatedCache
from backend.app.related_recommendations import related_recommendation, related_recommendations


def arguments():
    url = "https://www.bilibili.com/video/BV1Ct4y127He/"
    return {"point": {"knowledge_point_id": "p", "text": "矩形碰撞检测", "technology": "pygame"},
        "resource": {"resource_id": "r", "url": url, "canonical_url": url, "platform": "bilibili",
            "resource_type": "video", "fetch_status": "search_only", "metadata_evidence_level": "search",
            "field_provenance": {"resource_type": {"evidence_id": "e", "source": "search_template"}}},
        "evidence": [{"evidence_id": "e", "kind": "search", "source": "offline-test",
            "knowledge_point_id": "p", "resource_type_hint": "video", "type_source": "search_template",
            "url": url, "title": "Pygame 矩形碰撞检测教程", "snippet": ""},
            {"evidence_id": "e2", "kind": "search", "source": "offline-test",
             "knowledge_point_id": "p", "url": url, "title": "Pygame 矩形碰撞检测教程"}],
        "request": SearchRequest(knowledge_points=["矩形碰撞检测"], topic_technologies={"矩形碰撞检测": "pygame"}),
        "qualified_outline": {"status": "outline_unavailable", "evidence_ids": []}}


@pytest.mark.parametrize("field", ["point_id", "point_text", "point_technology", "resource_id", "resource_url",
    "payment", "freshness", "fetch_status", "provenance", "evidence", "evidence_order", "evidence_owner",
    "evidence_source", "evidence_freshness", "request_technology", "request_version", "outline"])
def test_exact_input_changes_invalidate(field):
    calls = []
    cache = ReadRelatedCache(projector=lambda *a, **k: calls.append(1) or {"nested": [len(calls)]})
    original = arguments()
    cache.project(**original)
    cache.project(**original)
    args = deepcopy(original)
    if field == "point_id": args["point"]["knowledge_point_id"] = "q"
    elif field == "point_text": args["point"]["text"] += " other"
    elif field == "point_technology": args["point"]["technology"] = "Unity"
    elif field == "resource_id": args["resource"]["resource_id"] = "s"
    elif field == "resource_url": args["resource"]["resolved_url"] = "https://example.org/another"
    elif field == "payment": args["resource"]["requires_payment"] = True
    elif field == "freshness": args["resource"]["cache"] = {"stale": True}
    elif field == "fetch_status": args["resource"]["fetch_status"] = "not_found"
    elif field == "provenance": args["resource"]["field_provenance"]["resource_type"]["evidence_id"] = "different"
    elif field == "evidence": args["evidence"][0]["title"] = "Unity教程"
    elif field == "evidence_order": args["evidence"].reverse()
    elif field == "evidence_owner": args["evidence"][0]["knowledge_point_id"] = "q"
    elif field == "evidence_source": args["evidence"][0]["source"] = "another"
    elif field == "evidence_freshness": args["evidence"][0]["cache"] = {"stale": True}
    elif field == "request_technology": args["request"] = args["request"].model_copy(update={"topic_technologies": {"矩形碰撞检测": "Unity"}})
    elif field == "request_version": args["request"] = args["request"].model_copy(update={"technical_version": "v2"})
    elif field == "outline": args["qualified_outline"]["status"] = "outline_supported"
    cache.project(**args)
    assert len(calls) == 2 and cache.hits == 1
    assert all(type(key) is str and len(key) == 64 for key in cache.entries)


def test_payment_flag_and_removed_evidence_override_cached_reference():
    args = arguments()
    cache = ReadRelatedCache()
    assert cache.project(**args)
    args["resource"]["requires_payment"] = True
    paid = cache.project(**args)
    assert paid and paid["resource"]["requires_payment"] is True
    assert cache.misses == 2
    args["resource"]["requires_payment"] = False
    args["evidence"] = []
    assert cache.project(**args) is None


def test_returned_and_source_objects_do_not_poison_cached_output():
    args = arguments()
    cache = ReadRelatedCache()
    first = cache.project(**args)
    expected = deepcopy(first)
    first["reference"]["basis"].append("forged")
    first["evidence"][0]["title"] = "caller mutation"
    # The projector's cold return can alias source evidence; a detached call
    # with the original inputs still gets the sealed, unmodified stored value.
    second = cache.project(**arguments())
    assert second == expected
    second["reference"]["evidence_ids"].clear()
    assert cache.project(**arguments()) == expected


def test_none_and_exception_behavior():
    calls = []
    cache = ReadRelatedCache(projector=lambda *a, **k: calls.append(1))
    assert cache.project(**arguments()) is None and cache.project(**arguments()) is None
    assert calls == [1]
    def fail(*a, **k):
        raise RuntimeError("synthetic failure")
    failing = ReadRelatedCache(projector=fail)
    for _ in range(2):
        with pytest.raises(RuntimeError): failing.project(**arguments())
    assert not failing.entries


def test_lru_capacity_bytes_oversize_and_non_json_bypass():
    cache = ReadRelatedCache(projector=lambda *a, **k: {"v": "x" * 20}, max_entries=2, max_output_bytes=70)
    args = [arguments() for _ in range(3)]
    for i, row in enumerate(args): row["point"]["knowledge_point_id"] = str(i)
    cache.project(**args[0]); cache.project(**args[1]); cache.project(**args[0]); cache.project(**args[2])
    assert len(cache.entries) == 2 and cache.output_bytes <= 70 and cache.evictions == 1
    cache.project(**args[1]); assert cache.misses == 4
    for options in ({"max_input_bytes": 1}, {"max_output_bytes": 1}):
        small = ReadRelatedCache(projector=lambda *a, **k: {"big": "output"}, **options)
        small.project(**arguments()); assert not small.entries and small.bypasses == 1
    odd = arguments(); odd["resource"]["non_json"] = object()
    cache.project(**odd); assert cache.bypasses == 1


@pytest.mark.parametrize("label,name,technology", [("pygame", "矩形碰撞检测", "pygame"), ("dashboard", "分组聚合", "pandas")])
def test_retained_sources_same_rows_order_limits_and_platforms(label, name, technology):
    source = json.loads((Path(__file__).parent / "fixtures/related-policy-20261020" / (label + "-sources.json")).read_text("utf-8"))
    point = {"knowledge_point_id": "replay", "text": name, "technology": technology}
    request = SearchRequest(knowledge_points=[name], topic_technologies={name: technology})
    cache = ReadRelatedCache()
    for limit in (1, 5, 2):
        args = (point, source["resources"], source["evidence"], request, limit)
        expected = related_recommendations(*args)
        assert cache.recommendations(*args) == expected
        assert cache.recommendations(*args) == expected
    assert cache.hits > 0
    source["resources"].pop(next(iter(source["resources"])))
    args = (point, source["resources"], source["evidence"], request, 5)
    assert cache.recommendations(*args) == related_recommendations(*args)


def test_service_reuses_pairs_but_updates_payment_notice():
    from backend.app.service import JobService
    args = arguments()
    service = object.__new__(JobService)
    service.settings = SimpleNamespace(max_results_per_point=5)
    def run():
        group = deepcopy(args["point"])
        service._add_related_recommendations([group], {"r": args["resource"]}, {"r": args["evidence"]}, args["request"])
        return group
    first = run(); second = run()
    assert first == second and service._read_related_cache.hits == 1
    args["resource"]["requires_payment"] = True
    updated = run()["related_recommendations"]
    assert updated and updated[0]["resource"]["requires_payment"] is True
    assert service._read_related_cache.misses == 2


def test_default_cache_holds_actual_batch_sized_working_set():
    calls = []
    cache = ReadRelatedCache(projector=lambda *a, **k: calls.append(1))
    rows = [arguments() for _ in range(1600)]
    for i, row in enumerate(rows): row["resource"]["resource_id"] = str(i)
    for row in rows: cache.project(**row)
    for row in rows: cache.project(**row)
    assert len(calls) == 1600 and cache.hits == 1600 and cache.evictions == 0


def test_new_unrelated_resource_and_display_sections_reuse_existing_pairs():
    from backend.app.service import JobService
    args = arguments()
    service = object.__new__(JobService)
    service.settings = SimpleNamespace(max_results_per_point=5)
    resources, evidence = {"r": args["resource"]}, {"r": args["evidence"]}
    for index in range(4):
        group = {**args["point"], "items": [{"resource": {"resource_id": str(index)}}],
                 "partial_items": [str(index)], "review_items": [str(index)],
                 "collection_coverage": {"changing": index}}
        expected = related_recommendations(group, resources, evidence, args["request"], 5)
        before = service._read_related_cache.stats() if index else {"hits": 0, "misses": 0}
        service._add_related_recommendations([group], resources, evidence, args["request"])
        assert (group["related_recommendations"], group["related_platform_recommendations"]) == expected
        after = service._read_related_cache.stats()
        if index:
            assert after["hits"] - before["hits"] == index
            assert after["misses"] - before["misses"] == 1
        added = deepcopy(args["resource"])
        added.update(resource_id="new-" + str(index), url="https://example.org/unrelated/" + str(index),
                     canonical_url="https://example.org/unrelated/" + str(index))
        resources[added["resource_id"]] = added
        evidence[added["resource_id"]] = []
