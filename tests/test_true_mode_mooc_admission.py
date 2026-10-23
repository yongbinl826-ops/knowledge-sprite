"""Offline retained-source replay, not a new live/content acceptance."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.models import Resource, SearchRequest
from backend.app.ranking import rank_resource, type_from_discovered_url
from backend.app.service import JobService


RETAINED = json.loads((Path(__file__).parent / "fixtures/true_mode_mooc/retained.json").read_text(encoding="utf-8"))["cases"]


def search_snapshot(case):
    resources, evidence = {}, {}
    for rid, original in case["resources"].items():
        searches = [deepcopy(e) for e in case["evidence"][rid] if e.get("kind") == "search"]
        if not searches:
            continue
        first = searches[0]
        eid, url = first["evidence_id"], first["url"]
        kind = type_from_discovered_url(url)
        provenance = {key: {"evidence_id": eid, "source": "search", "url": url}
                      for key in ("title", "description", "url")}
        if kind != "unknown":
            provenance["resource_type"] = {"evidence_id": eid, "source": "url_pattern", "url": url}
        resources[rid] = Resource(resource_id=rid, title=first["title"], url=url, canonical_url=url,
            description=first.get("snippet"), platform=original["platform"], resource_type=kind,
            field_provenance=provenance, discovered_at=first.get("observed_at") or original["discovered_at"]).model_dump()
        evidence[rid] = searches
    return resources, evidence


class ReadOnlyStore:
    def __init__(self, evidence):
        self.rows = evidence

    def evidence(self, job_id, rid, pid=None):
        return deepcopy([e for e in self.rows[rid] if e.get("kind") != "search" or pid is None
                         or e.get("knowledge_point_id") in {None, pid}])


def queues(case, *, teaching=True):
    resources, evidence = search_snapshot(case)
    job = case["job"]
    point = job["knowledge_points"][0]
    service = JobService.__new__(JobService)
    service.settings = SimpleNamespace(teaching_match_enabled=teaching)
    service.store = ReadOnlyStore(evidence)
    state = {"points": [point], "candidate_groups": {point["knowledge_point_id"]: list(resources)},
             "resources": resources, "started": set(), "request": SearchRequest.model_validate(job["request"])}
    before = deepcopy((job, resources, evidence))
    result = service._detail_queues(job, state)[point["knowledge_point_id"]]
    assert (job, resources, evidence) == before
    return result


@pytest.mark.parametrize("case,rid", [
    ("browser_flashcards_intermediate", "res_11bdfb0f9afa5ba060d2ee5a"),
    ("arduino_pot_button_beginner", "res_be0a7b52603aa45ccf730a24"),
    ("pygame_catch_beginner", "res_26e161efe69f4cd72824e49f"),
])
def test_true_mode_admits_existing_own_technical_course_probe(case, rid):
    assert rid in queues(RETAINED[case])


def test_true_mode_does_not_probe_compatibility_only_or_foreign_course():
    assert "res_6bbbbd7026b868c85fd9f67f" not in queues(RETAINED["arduino_pot_button_beginner"])
    case = RETAINED["pygame_catch_beginner"]
    queue = queues(case)
    assert not any("Unity" in case["resources"][rid]["title"] for rid in queue)


@pytest.mark.parametrize("mutation", ["point", "url", "learn", "related", "prerequisite", "negative", "lookalike"])
def test_probe_guard_is_source_scoped_and_does_not_use_reference_owner(mutation):
    case = deepcopy(RETAINED["arduino_pot_button_beginner"])
    rid = "res_be0a7b52603aa45ccf730a24"
    searches = [e for e in case["evidence"][rid] if e.get("kind") == "search"]
    for e in searches:
        e["title"] = "智能系统导论"
        e["snippet"] = "本课程讲解 Arduino 开发。"
        if mutation == "point": e["knowledge_point_id"] = "other-point"
        if mutation == "url": e["url"] = "https://www.icourse163.org/course/OTHER-987"
        if mutation == "learn": e["url"] = "https://www.icourse163.org/learn/OWN-987"
        if mutation == "related": e["snippet"] = "本课程讲解其他内容。相关视频：本课程讲解 Arduino 开发。"
        if mutation == "prerequisite": e["snippet"] = "预备知识\nArduino 开发。"
        if mutation == "negative": e["snippet"] = "本课程不讲 Arduino 开发。"
        if mutation == "lookalike": e["snippet"] = "本课程讲解 ArduinoWrapper 开发。"
    # Preserve resource URL independently of a forged search URL.
    from backend.app.mooc_relevance import teaching_probe_eligible
    resources, evidence = search_snapshot(case)
    resources[rid]["url"] = resources[rid]["canonical_url"] = RETAINED["arduino_pot_button_beginner"]["resources"][rid]["url"]
    assert not teaching_probe_eligible(case["job"]["knowledge_points"][0], resources[rid], evidence[rid])


def test_detail_probe_does_not_create_topic_support():
    case = RETAINED["browser_flashcards_intermediate"]
    resources, evidence = search_snapshot(case)
    rid = "res_11bdfb0f9afa5ba060d2ee5a"
    point = case["job"]["knowledge_points"][0]
    assert rid in queues(case)
    assert rank_resource(point, resources[rid], evidence[rid], SearchRequest.model_validate(case["job"]["request"])) is None


@pytest.mark.parametrize("name", ["事件冒泡", "矩形碰撞检测", "HTTP缓存"])
def test_existing_exact_topic_course_without_parseable_owner_keeps_detail_admission(name):
    case = deepcopy(RETAINED["browser_flashcards_intermediate"])
    job = case["job"]
    job["knowledge_points"][0]["text"] = name
    job["request"]["knowledge_points"] = [name]
    for rows in case["evidence"].values():
        for e in rows:
            e["title"] = name + "课程"
            e["snippet"] = "本课程讲解" + name
    rid = "res_11bdfb0f9afa5ba060d2ee5a"
    assert rid in queues(case)


def test_bound_outline_sorts_before_search_only_without_score_or_claim_changes():
    case = RETAINED["cycling_dashboard_advanced_python"]
    point = case["job"]["knowledge_points"][0]
    request = SearchRequest.model_validate(case["job"]["request"])
    matches = [match for rid, resource in case["resources"].items()
               if (match := rank_resource(point, resource, case["evidence"][rid], request))]
    rid = "res_43a1858bed5a099566be4a28"
    own = next(m for m in matches if m["resource_id"] == rid)
    assert own["ranking_score"] == 65.75
    assert max(m["ranking_score"] for m in matches) == 80
    before = deepcopy(matches)
    assert sorted(matches, key=lambda m: -m["ranking_score"]).index(own) == 3
    ordered = sorted(matches, key=lambda m: JobService._evidence_sort_key(m, case["resources"][m["resource_id"]], case["evidence"][m["resource_id"]]))
    assert ordered.index(own) == 0
    assert matches == before
    assert own["topic_evidence_status"] == "supported"


@pytest.mark.parametrize("mutation", ["url", "id", "text", "stale", "source"])
def test_foreign_or_unbound_catalog_does_not_gain_priority(mutation):
    case = deepcopy(RETAINED["cycling_dashboard_advanced_python"])
    rid = "res_43a1858bed5a099566be4a28"
    resource, evidence = case["resources"][rid], case["evidence"][rid]
    match = rank_resource(case["job"]["knowledge_points"][0], resource, evidence, SearchRequest.model_validate(case["job"]["request"]))
    assert JobService._evidence_sort_key(match, resource, evidence)[0] == -1
    for e in evidence:
        if e.get("kind") in {"page", "catalog"}:
            if mutation == "url": e["url"] = "https://www.icourse163.org/course/OTHER-999"
            if mutation == "id": e["evidence_id"] = "foreign-id"
            if mutation == "text": e["text"] = "unbound data"
            if mutation == "stale": e["cache"] = {"stale": True}
            if mutation == "source": e["source"] = "search"
    assert JobService._evidence_sort_key(match, resource, evidence)[0] == 0


def test_arbitrary_chapters_or_page_title_do_not_gain_body_priority():
    m = {"resource_id": "r", "ranking_score": 80, "supporting_evidence_ids": ["e"]}
    r = {"url": "https://www.bilibili.com/video/BV1xx411c7mD/", "chapters": [{"title": "Python 列表", "evidence_id": "e"}]}
    assert JobService._evidence_sort_key(m, r, [{"evidence_id": "e", "kind": "search"}])[0] == 0
    r["title"] = "Python 列表"
    r["field_provenance"] = {"title": {"evidence_id": "e", "url": r["url"], "source": "meta.title"}}
    assert JobService._evidence_sort_key(m, r, [{"evidence_id": "e", "kind": "page", "field": "title", "text": r["title"], "url": r["url"], "source": "meta.title"}])[0] == 0


def test_bound_body_on_another_platform_is_equally_preferred():
    m = {"resource_id": "r", "ranking_score": 50, "supporting_evidence_ids": ["e"]}
    url = "https://www.bilibili.com/video/BV1xx411c7mD/"
    r = {"url": url, "description": "本课讲解 Python 列表索引", "field_provenance": {
        "description": {"evidence_id": "e", "source": "videoData.desc", "url": url}}}
    e = {"evidence_id": "e", "kind": "page", "field": "description", "text": r["description"], "url": url, "source": "videoData.desc"}
    assert JobService._evidence_sort_key(m, r, [e])[0] == -1
    m["supporting_evidence_ids"] = ["other"]
    assert JobService._evidence_sort_key(m, r, [e])[0] == 0


@pytest.mark.parametrize("bad", [None, [], "invalid", 1])
def test_malformed_page_provenance_never_crashes_or_gains_priority(bad):
    m = {"resource_id": "r", "ranking_score": 50, "supporting_evidence_ids": ["e"]}
    url = "https://www.bilibili.com/video/BV1xx411c7mD/"
    r = {"url": url, "description": "Python 列表索引", "field_provenance": bad}
    e = {"evidence_id": "e", "kind": "page", "field": "description", "text": r["description"], "url": url, "source": "videoData.desc"}
    assert JobService._evidence_sort_key(m, r, [e])[0] == 0
    r["field_provenance"] = {"description": bad}
    assert JobService._evidence_sort_key(m, r, [e])[0] == 0


def test_stale_resource_without_evidence_cache_never_gains_priority():
    case = deepcopy(RETAINED["cycling_dashboard_advanced_python"])
    rid = "res_43a1858bed5a099566be4a28"
    resource, evidence = case["resources"][rid], case["evidence"][rid]
    match = rank_resource(case["job"]["knowledge_points"][0], resource, evidence, SearchRequest.model_validate(case["job"]["request"]))
    assert JobService._evidence_sort_key(match, resource, evidence)[0] == -1
    resource["cache"] = {"stale": True}
    for e in evidence: e.pop("cache", None)
    assert JobService._evidence_sort_key(match, resource, evidence)[0] == 0
