"""Offline orchestration and read-safety checks, not live quality evidence."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.queries import generate_queries
from backend.app.ranking import rank_resource
from backend.app.service import JobService
from backend.app import teaching_match
from backend.app import teaching_review
from backend.app.fetcher import FETCH_DEADLINE_AT
from backend.app.learning_support import summarize_learning_support
from test_teaching_match import lesson, support


@pytest.fixture(autouse=True)
def offline_claim_review(monkeypatch):
    async def accept(settings, claims):
        return {claim["claim_id"]: True for claim in claims}
    monkeypatch.setattr(teaching_review, "review_batch", accept)


def setup(count=1, resources_count=1, configured=True):
    settings = Settings(llm_provider="openai_compatible" if configured else "none", llm_model="offline-model",
        llm_api_key="offline-private-not-a-real-key", llm_base_url="https://model.example/v1")
    store = Store(":memory:")
    service = JobService(settings, store)
    names = [f"QuillFlow 项目阶段 {index}" for index in range(count)]
    skills = {name: ["QuillFlow bounded queues"] for name in names}
    request = SearchRequest(knowledge_points=names, learning_skills=skills, preferred_platforms=[])
    result = service.create(request)
    job = store.get_job(result["job_id"])
    resources = {}
    for index in range(resources_count):
        resource, evidence = lesson(url=f"https://lessons.example/queue-{index}")
        rid = f"res-own-{index}"
        resource.update(resource_id=rid, platform="other", language="en")
        for row in evidence:
            row["evidence_id"] += f"-{index}"
        for field, provenance in resource["field_provenance"].items():
            provenance["evidence_id"] += f"-{index}"
        resources[rid] = resource
        store.save_resource(job["job_id"], resource)
        for row in evidence:
            store.add_evidence(job["job_id"], rid, None, row)
    return service, job, resources, request


async def accept_batch(settings, pairs):
    return {pair["pair_id"]: {"fingerprint": pair["fingerprint"], "supports": [support(pair)]} for pair in pairs}


def test_two_call_and_twenty_pair_cap_with_fair_four_per_point():
    service, job, resources, request = setup(5, 8)
    calls = []
    async def judge(settings, pairs):
        calls.append(deepcopy(pairs))
        return await accept_batch(settings, pairs)
    with patch.object(teaching_match, "judge_batch", judge):
        asyncio.run(service._match_learning_skills(job, resources))
    assert len(calls) == 2
    assert sum(map(len, calls)) == 20
    assert all(len(batch) <= 10 for batch in calls)
    assert all(len(json.dumps([p["payload"] for p in batch], ensure_ascii=False)) < 40_000 for batch in calls)
    ids = [pair["_binding"]["point_id"] for batch in calls for pair in batch]
    assert {pid: ids.count(pid) for pid in ids} == {p["knowledge_point_id"]: 4 for p in job["knowledge_points"]}
    assert ids[:5] == [p["knowledge_point_id"] for p in job["knowledge_points"]]
    assert job["progress"]["teaching_match_calls"] == 2
    assert job["progress"]["teaching_pairs_evaluated"] == 20
    assert len(service.store.matches(job["job_id"])) == 20


def test_cached_decisions_are_rebound_and_result_reads_do_not_write_or_call():
    service, job, resources, request = setup()
    judge = AsyncMock(side_effect=accept_batch)
    with patch.object(teaching_match, "judge_batch", judge):
        asyncio.run(service._match_learning_skills(job, resources))
        assert judge.await_count == 1
        asyncio.run(service._match_learning_skills(job, resources))
        assert judge.await_count == 1
        assert job["progress"]["teaching_cache_hits"] == 1
        before = service.store.connection.total_changes
        first = service.results(job["job_id"])
        assert service.results(job["job_id"]) == first
        assert service.store.connection.total_changes == before
        assert judge.await_count == 1
    group = first["groups"][0]
    assert len(group["partial_items"]) == 1
    assert group["learning_coverage"]["skills"][0]["content_resource_ids"] == ["res-own-0"]
    assert "_teaching_decision" not in json.dumps(first)


def test_valid_empty_decision_cannot_resurrect_literal_match_on_get():
    service, job, resources, request = setup()
    point = job["knowledge_points"][0]
    resource = next(iter(resources.values()))
    row = {"evidence_id": "search-own", "kind": "search", "knowledge_point_id": point["knowledge_point_id"],
           "title": resource["title"], "snippet": resource["description"], "url": resource["url"], "source": "offline", "query": point["text"]}
    service.store.add_evidence(job["job_id"], resource["resource_id"], point["knowledge_point_id"], row)
    assert service.results(job["job_id"])["groups"][0]["partial_items"]
    async def reject(settings, pairs):
        return {p["pair_id"]: {"fingerprint": p["fingerprint"], "supports": []} for p in pairs}
    with patch.object(teaching_match, "judge_batch", reject):
        asyncio.run(service._match_learning_skills(job, resources))
    assert not service.results(job["job_id"])["groups"][0]["partial_items"]


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("private transport details")])
def test_judge_failure_keeps_job_and_sources_with_no_cached_fake_negative(error):
    service, job, resources, _ = setup()
    with patch.object(teaching_match, "judge_batch", AsyncMock(side_effect=error)) as judge:
        asyncio.run(service._match_learning_skills(job, resources))
    assert judge.await_count == 1
    assert service.store.resources(job["job_id"]) == resources
    assert service.store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
    assert "private transport" not in json.dumps(job)
    assert any("未返回可核对结论" in warning for warning in job["warnings"])


def test_cancel_propagates_without_cache_or_saved_positive():
    service, job, resources, _ = setup()
    with patch.object(teaching_match, "judge_batch", AsyncMock(side_effect=asyncio.CancelledError())):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(service._match_learning_skills(job, resources))
    assert not service.store.matches(job["job_id"])
    assert service.store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0


def test_unconfigured_or_zero_call_budget_never_sends_model_request():
    for configured, cap in [(False, 2), (True, 0)]:
        service, job, resources, _ = setup(configured=configured)
        service.settings = replace(service.settings, teaching_match_max_calls_per_job=cap)
        with patch.object(teaching_match, "judge_batch", AsyncMock()) as judge:
            asyncio.run(service._match_learning_skills(job, resources))
        assert not judge.called
        assert job["progress"]["teaching_match_calls"] == 0


def test_source_timeout_cancels_network_work_and_preserves_time_for_teaching(monkeypatch):
    service, job, _, _ = setup()
    service.llm = object()
    events = []
    async def source(*args):
        try:
            await asyncio.Event().wait()
        finally:
            events.append("source_cancelled")
    async def teaching(*args):
        events.append("teaching")
        assert asyncio.get_running_loop().time() < FETCH_DEADLINE_AT.get()
    service._search_queries = source
    service._run_details = source
    service._match_learning_skills = teaching
    service._rerank = AsyncMock()
    monkeypatch.setattr(teaching_match, "DEADLINE_SECONDS", .05)
    monkeypatch.setattr(teaching_review, "DEADLINE_SECONDS", .05)
    async def run():
        token = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + .2)
        try:
            await service._execute(job)
        finally:
            FETCH_DEADLINE_AT.reset(token)
    asyncio.run(run())
    assert events == ["source_cancelled", "source_cancelled", "teaching"]
    assert job["budget_limited"] is True
    assert any("预留时限" in warning for warning in job["warnings"])


def test_title_support_is_separate_and_never_project_completion():
    service, job, resources, request = setup(configured=False)
    point = job["knowledge_points"][0]
    resource = next(iter(resources.values()))
    resource["title"] = "QuillFlow bounded queues"
    resource["description"] = "An introductory lesson."
    evidence = service.store.evidence(job["job_id"], resource["resource_id"])
    for row in evidence:
        if row["field"] in {"title", "description"}:
            row["text"] = resource[row["field"]]
    match = rank_resource(point, resource, evidence, request)
    assert match and match["topic_evidence_status"] == "partial"
    assert match["teaching_support"][0]["basis"] == "title"
    summary = summarize_learning_support(point, [{"resource": resource, "match": match, "evidence": evidence}])
    assert summary["skills"][0]["title_resource_ids"] == [resource["resource_id"]]
    assert not summary["skills"][0]["content_resource_ids"]
    assert "标题" in match["recommendation_reason"]


def link_search(service, job, resource):
    point = job["knowledge_points"][0]
    service.store.add_evidence(job["job_id"], resource["resource_id"], point["knowledge_point_id"],
        {"evidence_id": "linked-search", "kind": "search", "knowledge_point_id": point["knowledge_point_id"],
         "title": resource["title"], "snippet": resource["description"], "url": resource["url"], "source": "offline"})


def test_review_rejection_blocks_literal_resurrection_and_caches_valid_unknown():
    service, job, resources, _ = setup()
    link_search(service, job, next(iter(resources.values())))
    async def reject(settings, claims):
        return {claim["claim_id"]: False for claim in claims}
    with patch.object(teaching_match, "judge_batch", AsyncMock(side_effect=accept_batch)), patch.object(teaching_review, "review_batch", AsyncMock(side_effect=reject)) as reviewer:
        asyncio.run(service._match_learning_skills(job, resources))
        asyncio.run(service._match_learning_skills(job, resources))
    assert reviewer.await_count == 1
    assert job["progress"]["teaching_review_calls"] == 1
    assert job["progress"]["teaching_cache_hits"] == 1
    before = service.store.connection.total_changes
    assert not service.results(job["job_id"])["groups"][0]["partial_items"]
    assert service.store.connection.total_changes == before


def test_failed_review_stays_unknown_is_not_cached_and_cannot_exceed_job_call_cap():
    service, job, resources, _ = setup()
    link_search(service, job, next(iter(resources.values())))
    with patch.object(teaching_match, "judge_batch", AsyncMock(side_effect=accept_batch)) as judge, patch.object(teaching_review, "review_batch", AsyncMock(return_value=None)) as reviewer:
        for _ in range(3):
            asyncio.run(service._match_learning_skills(job, resources))
    assert judge.await_count == 2 and reviewer.await_count == 1
    assert job["upstream_partial"] is True
    assert service.store.connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0
    assert not service.results(job["job_id"])["groups"][0]["partial_items"]


def test_old_unreviewed_persisted_claim_cannot_bypass_read_gate():
    service, job, resources, request = setup()
    resource = next(iter(resources.values()))
    point = job["knowledge_points"][0]
    link_search(service, job, resource)
    evidence = service.store.evidence(job["job_id"], resource["resource_id"], point["knowledge_point_id"])
    pair = teaching_match.prepare_pair(point, resource, evidence)
    old = {"fingerprint": pair["fingerprint"], "supports": [support(pair)]}
    job["teaching_decisions"] = {point["knowledge_point_id"]: {resource["resource_id"]: old}}
    service.store.save_job(job)
    assert not service.results(job["job_id"])["groups"][0]["partial_items"]


def test_malformed_saved_empty_dict_cannot_be_dropped_into_literal_fallback():
    service, job, resources, _ = setup()
    resource = next(iter(resources.values())); point = job["knowledge_points"][0]
    link_search(service, job, resource)
    assert service.results(job["job_id"])["groups"][0]["partial_items"]
    job["teaching_decisions"] = {point["knowledge_point_id"]: {resource["resource_id"]: {}}}
    service.store.save_job(job)
    before = service.store.connection.total_changes
    assert not service.results(job["job_id"])["groups"][0]["partial_items"]
    assert service.store.connection.total_changes == before


def test_seal_tamper_or_source_change_invalidates_get_without_model_or_write():
    service, job, resources, _ = setup()
    with patch.object(teaching_match, "judge_batch", AsyncMock(side_effect=accept_batch)):
        asyncio.run(service._match_learning_skills(job, resources))
    assert service.results(job["job_id"])["groups"][0]["partial_items"]
    point = job["knowledge_points"][0]; rid = next(iter(resources))
    job["teaching_decisions"][point["knowledge_point_id"]][rid]["_review_hash"] = "0" * 64
    service.store.save_job(job)
    before = service.store.connection.total_changes
    with patch.object(teaching_review, "review_batch", AsyncMock()) as reviewer, patch.object(teaching_match, "judge_batch", AsyncMock()) as judge:
        assert not service.results(job["job_id"])["groups"][0]["partial_items"]
        assert not judge.called and not reviewer.called
    assert service.store.connection.total_changes == before


def test_queries_preserve_all_six_reviewed_skills_and_project_constants_are_absent():
    name = "QuillFlow 项目参数12345"
    skills = [f"QuillFlow operation_{index} 教程目标" for index in range(6)]
    request = SearchRequest(knowledge_points=[name], learning_skills={name: skills},
        learning_targets={name: ["同款项目 dataset_12345、2000-5000 常量"]}, preferred_platforms=["bilibili", "icourse163", "xuetangx"])
    before = request.model_dump()
    rows = generate_queries("kp", name, request, ["无关扩展"])
    assert len(rows) == 6
    assert all(any(f"operation_{index}" in row.query for row in rows) for index in range(6))
    assert all("12345" not in row.query and "5000" not in row.query and "无关扩展" not in row.query for row in rows)
    assert request.model_dump() == before


@pytest.mark.parametrize("skill", ["https://example.com/secret", "site:example.com Python", "a\n\u0001b", ""])
def test_new_skill_map_rejects_url_operators_controls_and_empty(skill):
    with pytest.raises(ValueError):
        SearchRequest(knowledge_points=["QuillFlow 任务"], learning_skills={"QuillFlow 任务": [skill]})
