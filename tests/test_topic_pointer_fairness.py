"""Read-only pointer allocation: source hints never become teaching claims."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch, AsyncMock
import json

import pytest

from backend.app import teaching_match, teaching_review
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.service import JobService, _topic_pointer_reservoir, _reserve_topic_pointer, _display_topic_pointers

FIXTURE = Path(__file__).parent / "fixtures/phase3_pointer_fairness/retained_actual_pools.json"
ACTUAL = json.loads(FIXTURE.read_text(encoding="utf-8"))


def actual_service(case):
    store = Store(":memory:")
    service = JobService(Settings(llm_provider="none"), store)
    job = deepcopy(case["job_data"])
    store.save_job(job)
    for resource in case["resources"]:
        store.save_resource(job["job_id"], resource)
    for row in case["evidence"]:
        store.add_evidence(job["job_id"], row["resource_id"], row.get("knowledge_point_id"), row)
    return service, job


def test_actual_late_analogwrite_part_receives_original_first_skill_slot_without_coverage():
    case = ACTUAL[0]; before = deepcopy(case)
    service, job = actual_service(case)
    model = AsyncMock(side_effect=AssertionError("Read must not call model"))
    changes = service.store.connection.total_changes
    with patch.object(teaching_match, "judge_batch", model), patch.object(teaching_review, "review_batch", model):
        result = service.results(job["job_id"])
        assert service.results(job["job_id"]) == result
    group = next(g for g in result["groups"] if g["knowledge_point_id"] == case["point_id"])
    pointers = group["related_topic_pointers"]
    assert any(e["pointer"]["skill_id"] == "skill_1" and e["pointer"]["quote"] == "1-25 模拟输出1 - analogWrite"
               and e["pointer"]["target_url"].endswith("?p=26") for e in pointers)
    assert pointers[0]["pointer"]["skill_id"] == "skill_1"
    source = next(r for r in case["resources"] if r["resource_id"] == "res_fb0aa4e15e8b69c8cfa56b36")
    assert not any(e.get("kind") == "search" and e.get("knowledge_point_id") == case["point_id"]
                   and e["resource_id"] == source["resource_id"] for e in case["evidence"])
    pointer = next(e["pointer"] for e in pointers if e["pointer"]["quote"] == "1-25 模拟输出1 - analogWrite")
    raw = next(e for e in case["evidence"] if e["evidence_id"] == pointer["evidence_id"])
    assert pointer["quote"] in raw["text"]
    assert pointer["source_text_sha256"] == teaching_match._hash(raw["text"])
    assert len(pointers) <= 4
    assert service.store.connection.total_changes == changes
    model.assert_not_called()
    assert case == before
    assert all(e["pointer"]["scope"] == "topic_declared" for e in pointers)


@pytest.mark.parametrize("damage", ["sentinel", "unreviewed", "old-seal", "fingerprint", "source", "point-skills", "student-stage", "other-job-only"])
def test_cross_point_pointer_only_link_requires_current_rebound_existing_seal(damage):
    case = deepcopy(ACTUAL[0]); rid = "res_fb0aa4e15e8b69c8cfa56b36"; pid = case["point_id"]
    decisions = case["job_data"]["teaching_decisions"][pid]
    if damage == "sentinel": decisions[rid] = {}
    elif damage == "unreviewed": decisions.pop(rid)
    elif damage == "old-seal": decisions[rid]["_review_version"] = "old-review-version"
    elif damage == "fingerprint": decisions[rid] = teaching_review.sealed_decision({"fingerprint": "0" * 64, "supports": []})
    elif damage == "source":
        resource = next(r for r in case["resources"] if r["resource_id"] == rid)
        resource["title"] += " changed source"
        for row in case["evidence"]:
            if row["resource_id"] == rid and row.get("kind") == "page" and row.get("field") == "title":
                row["text"] = resource["title"]
    elif damage == "point-skills":
        point = next(p for p in case["job_data"]["knowledge_points"] if p["knowledge_point_id"] == pid)
        point["learning_skills"][0] += " new requirement"
    elif damage == "student-stage": case["job_data"]["request"]["student_level"] = "advanced"
    else: case["resources"] = [r for r in case["resources"] if r["resource_id"] != rid]
    service, job = actual_service(case)
    group = next(g for g in service.results(job["job_id"])["groups"] if g["knowledge_point_id"] == pid)
    assert all(e["resource"]["resource_id"] != rid for e in group["related_topic_pointers"])


def test_valid_empty_cross_point_link_never_enters_primary_rank_or_match_collection():
    case = deepcopy(ACTUAL[0]); rid = "res_fb0aa4e15e8b69c8cfa56b36"; pid = case["point_id"]
    service, job = actual_service(case)
    from backend.app import service as service_module
    real_rank = service_module.rank_resource
    def checked_rank(point, resource, *args, **kwargs):
        assert not (point["knowledge_point_id"] == pid and resource["resource_id"] == rid)
        return real_rank(point, resource, *args, **kwargs)
    with patch("backend.app.service.rank_resource", checked_rank):
        result = service.results(job["job_id"])
    group = next(g for g in result["groups"] if g["knowledge_point_id"] == pid)
    assert any(e["resource"]["resource_id"] == rid for e in group["related_topic_pointers"])
    assert all(e["resource"]["resource_id"] != rid for key in ("items", "partial_items", "review_items") for e in group[key])
    assert all(rid not in row["content_resource_ids"] and rid not in row["title_resource_ids"]
               for row in group["learning_coverage"]["skills"])


def test_actual_web_dom_only_chapters_do_not_borrow_selector_query_skill():
    case = ACTUAL[1]
    service, job = actual_service(case)
    group = next(g for g in service.results(job["job_id"])["groups"] if g["knowledge_point_id"] == case["point_id"])
    original = {(e["pointer"]["evidence_id"], e["pointer"]["skill_id"]) for e in case["original_shown_pointers"]}
    assert len(original) == 4
    assert not any((e["pointer"]["evidence_id"], e["pointer"]["skill_id"]) in original
                   for e in group["related_topic_pointers"])


def point(skills=2):
    return {"knowledge_point_id": "point-own", "learning_skills": [f"Skill {i}" for i in range(1, skills+1)]}


def entry(p, index, *, skill=1, missing=2, target=None):
    rid = f"res-{index}"
    pointer = {"knowledge_point_id": p["knowledge_point_id"], "resource_id": rid,
               "skill_id": f"skill_{skill}", "skill": p["learning_skills"][skill-1],
               "scope": "topic_declared", "basis": "catalog", "evidence_id": f"ev-{index}",
               "quote": f"observed heading {index}", "target_url": target or f"https://lessons.example/{index}",
               "missing_components": [f"unknown-{i}" for i in range(missing)]}
    return {"resource": {"resource_id": rid}, "evidence": [], "pointer": pointer}


def reserve(pools, p, item):
    _reserve_topic_pointer(pools, p, item["resource"], item["evidence"], item["pointer"])


def test_late_specific_source_replaces_early_generic_in_small_per_skill_reservoir():
    p = point(); pools = _topic_pointer_reservoir(p)
    for i in range(20):
        reserve(pools, p, entry(p, i, skill=2, missing=3))
        assert sum(len(pool["items"]) for pool in pools.values()) <= 8
    reserve(pools, p, entry(p, "late-1", skill=1, missing=1))
    reserve(pools, p, entry(p, "late-2", skill=2, missing=0))
    shown = _display_topic_pointers(pools)
    assert [e["pointer"]["skill_id"] for e in shown] == ["skill_1", "skill_2", "skill_2", "skill_2"]
    assert shown[0]["resource"]["resource_id"] == "res-late-1"
    assert shown[1]["resource"]["resource_id"] == "res-late-2"


def test_stable_url_dedup_prefers_specific_candidate_and_preserves_another_skill():
    p = point(); items = [entry(p, "generic", missing=3, target="https://lessons.example/shared"),
        entry(p, "specific", missing=0, target="https://lessons.example/shared"),
        entry(p, "skill2-shared", skill=2, target="https://lessons.example/shared"),
        entry(p, "skill2-unique", skill=2)]
    results = []
    for ordered in (items, list(reversed(items))):
        pools = _topic_pointer_reservoir(p)
        for item in ordered: reserve(pools, p, item)
        results.append(_display_topic_pointers(pools))
    assert results[0] == results[1]
    assert [e["resource"]["resource_id"] for e in results[0]] == ["res-specific", "res-skill2-unique"]


@pytest.mark.parametrize("damage", ["unknown-skill", "wrong-skill", "wrong-point", "wrong-resource", "unsafe-url", "not-catalog"])
def test_unknown_or_mismatched_pointer_cannot_enter_known_skill_pool(damage):
    p = point(); pools = _topic_pointer_reservoir(p); item = entry(p, 1)
    field, value = {"unknown-skill": ("skill_id", "skill_7"), "wrong-skill": ("skill", "foreign skill"),
        "wrong-point": ("knowledge_point_id", "other"), "wrong-resource": ("resource_id", "foreign"),
        "unsafe-url": ("target_url", "http://127.1/private"), "not-catalog": ("basis", "title")}[damage]
    item["pointer"][field] = value
    reserve(pools, p, item)
    assert _display_topic_pointers(pools) == []


def test_six_skill_bound_original_order_and_inputs_unchanged():
    p = point(6); pools = _topic_pointer_reservoir(p); original = deepcopy(p)
    for skill in reversed(range(1, 7)):
        for i in reversed(range(8)):
            item = entry(p, f"{skill}-{i}", skill=skill, missing=i)
            before = deepcopy(item); reserve(pools, p, item); assert item == before
            assert sum(len(pool["items"]) for pool in pools.values()) <= 24
    assert [e["pointer"]["skill_id"] for e in _display_topic_pointers(pools)] == ["skill_1", "skill_2", "skill_3", "skill_4"]
    assert p == original


def test_get_scans_full_known_pool_but_takes_at_most_six_pointers_per_resource():
    from test_learning_support_service import setup
    from test_related_topic_pointer_service import link, pointer, reject_rank
    service, job, resources, _ = setup(resources_count=6)
    p = job["knowledge_points"][0]
    for resource in resources.values(): link(service, job, resource, p)
    inspected = []
    def produce(pair):
        inspected.append(pair["_binding"]["resource_id"])
        base = pointer(pair)
        return [{**base, "target_url": base["target_url"] + f"?lesson={i}",
                 "missing_components": ["unproved"] * (6-i)} for i in range(7)]
    changes = service.store.connection.total_changes
    with patch.object(teaching_match, "topic_pointers", side_effect=produce), patch("backend.app.service.rank_resource", reject_rank):
        group = service.results(job["job_id"])["groups"][0]
    assert set(inspected) == set(resources) and len(inspected) == 6
    assert len(group["related_topic_pointers"]) == 4
    assert all(not e["pointer"]["target_url"].endswith("lesson=6") for e in group["related_topic_pointers"])
    assert service.store.connection.total_changes == changes
