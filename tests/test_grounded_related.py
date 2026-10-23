"""Source-bound semantic references; all network replies here are fixtures."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from backend.app import grounded_related as gr
from backend.app.ai_video_service import _recover_from_own_metadata, visible_point_ids
from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.fetcher import FETCH_DEADLINE_AT
from backend.app.models import SearchRequest, now
from backend.app.related_recommendations import related_recommendation
from test_ai_grounded_recovery import recovery_service, SourcePages
from test_ai_retained_recovery import CatalogPages

URL = "https://www.bilibili.com/video/BV1xx411c7Df/"
TOPIC = "HTML 表单控件值读取与事件绑定"
TITLE = "HTML form values and onclick events"
DESCRIPTION = "HTML form values are read through input.value in onclick handlers."


def source(title=TITLE, description=DESCRIPTION):
    node = {"@context": "https://schema.org", "@type": "VideoObject", "name": title,
            "description": description, "contentUrl": "https://media.example.org/video.mp4"}
    parsed = MetadataExtractor().extract('<script type="application/ld+json">'
        + json.dumps(node, ensure_ascii=False) + '</script>', URL, now())
    evidence = parsed.pop("evidence")
    return {**parsed, "resource_id": "resource_1", "url": URL, "canonical_url": URL, "platform": "bilibili"}, evidence


def inputs():
    request = SearchRequest(knowledge_points=[TOPIC], topic_technologies={TOPIC: "HTML"}, preferred_platforms=["bilibili"])
    return {"knowledge_point_id": "kp_1", "text": TOPIC, "technology": "HTML"}, request


def settings():
    return replace(Settings(), llm_provider="openai_compatible", llm_api_key="offline-key",
                   llm_model="offline-model", llm_base_url="https://model.example/v1")


def decision(pair, *, basis="description"):
    observed = next(s for s in pair["core"]["sources"] if s["basis"] == basis)
    return {"pair_id": pair["pair_id"], "fingerprint": pair["fingerprint"], "support": {
        "evidence_id": observed["evidence_id"], "source_text_sha256": observed["source_text_sha256"],
        "quote": observed["segments"][0], "basis": basis}}


def reply(body):
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}]})


async def judge(pair, *, accept=True, alter=None, basis="description"):
    calls = []
    def respond(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        calls.append(data)
        if "pairs" in data:
            value = decision(pair, basis=basis)
            if alter:
                alter(value)
            return reply({"decisions": [value]})
        return reply({"decisions": [{"pair_id": pair["pair_id"], "accepted": accept}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await gr.judge_batch(settings(), [pair], client=client)
    return result, calls


async def test_bilingual_own_page_only_becomes_related_after_independent_review():
    point, request = inputs()
    resource, evidence = source()
    assert related_recommendation(point, resource, evidence, request) is None
    pair = gr.prepare_pair(point, resource, evidence, request, hints=["UNTRUSTED MODEL SEARCH"])
    result, calls = await judge(pair)
    assert len(calls) == 2 and "UNTRUSTED MODEL SEARCH" not in json.dumps(calls)
    projected = gr.project_reference(point, resource, evidence, request, result[pair["pair_id"]])
    assert projected["reference"]["exact_teaching_verified"] is False
    assert projected["reference"]["technical_context"] == "observed"
    assert projected["reference"]["source_quote"] == DESCRIPTION
    assert related_recommendation(point, resource, evidence, request,
        grounded_decision=result[pair["pair_id"]]) == projected


async def test_current_reviewed_page_outweighs_search_only_lexical_projection():
    point, request = inputs()
    resource, evidence = source()
    evidence.append({"evidence_id": "search-1", "source": "serper", "kind": "search", "url": URL,
        "knowledge_point_id": point["knowledge_point_id"], "title": TOPIC, "snippet": TOPIC + "完整教程"})
    before = related_recommendation(point, resource, evidence, request)
    assert before is None or before["reference"]["basis"] == ["search"]
    pair = gr.prepare_pair(point, resource, evidence, request)
    result, _ = await judge(pair)
    after = related_recommendation(point, resource, evidence, request, grounded_decision=result[pair["pair_id"]])
    assert after is not None and after["reference"]["basis"] == ["page"]
    assert "source_quote" in after["reference"]


@pytest.mark.parametrize("mutate", [
    lambda d: d["support"].update(quote="HTML imaginary form validation"),
    lambda d: d["support"].update(evidence_id="unknown"),
    lambda d: d["support"].update(source_text_sha256="0" * 64),
    lambda d: d.update(fingerprint="0" * 64),
])
async def test_invalid_quote_or_identity_never_enters_review(mutate):
    point, request = inputs()
    resource, evidence = source()
    pair = gr.prepare_pair(point, resource, evidence, request)
    result, calls = await judge(pair, alter=mutate)
    assert not result and len(calls) == 1


async def test_valid_quote_rejected_by_review_stays_unknown():
    point, request = inputs()
    resource, evidence = source()
    result, calls = await judge(gr.prepare_pair(point, resource, evidence, request), accept=False)
    assert len(calls) == 2 and not result


@pytest.mark.parametrize("change", ["resource_stale", "row_stale", "paid", "changed_title", "foreign_url", "fault"])
async def test_reviewed_decision_rebound_on_every_projection(change):
    point, request = inputs()
    resource, evidence = source()
    pair = gr.prepare_pair(point, resource, evidence, request)
    result, _ = await judge(pair)
    if change == "resource_stale":
        resource["cache"] = {"stale": True}
    elif change == "row_stale":
        next(e for e in evidence if e["field"] == "description")["cache"] = {"stale": True}
    elif change == "paid":
        resource["requires_payment"] = True
    elif change == "changed_title":
        resource["title"] = "Other course"
    elif change == "foreign_url":
        next(e for e in evidence if e["field"] == "description")["url"] = "https://example.org/other"
    else:
        resource["description"] = "音频坏了 不想录了 就这样吧"
        next(e for e in evidence if e["field"] == "description")["text"] = resource["description"]
    assert gr.project_reference(point, resource, evidence, request, result[pair["pair_id"]]) is None


async def test_review_timeout_never_seals_a_positive():
    point, request = inputs()
    resource, evidence = source()
    pair = gr.prepare_pair(point, resource, evidence, request)
    calls = []
    async def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return reply({"decisions": [decision(pair)]})
        await asyncio.sleep(1)
        return reply({"decisions": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TimeoutError):
            await gr.judge_batch(settings(), [pair], client=client, timeout_seconds=.02)
    assert len(calls) == 2


@pytest.mark.parametrize("teaching", [False, True])
async def test_background_reuses_already_fetched_source_and_get_never_calls_model(recovery_service, teaching):
    service, searches, _ = recovery_service(teaching_match_enabled=teaching)
    point, request = inputs()
    job = service.store.get_job(service.create(request)["job_id"])
    resource, evidence = source()
    service.store.save_resource(job["job_id"], resource)
    for row in evidence:
        service.store.add_evidence(job["job_id"], resource["resource_id"], job["knowledge_points"][0]["knowledge_point_id"], row)
    pid = job["knowledge_points"][0]["knowledge_point_id"]
    state = {"request": request, "points": job["knowledge_points"], "resources": {resource["resource_id"]: resource},
             "candidate_groups": {pid: [resource["resource_id"]]}, "reserved": 1}
    calls = []
    def respond(request):
        data = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(data)
        if "pairs" in data:
            pair = gr.prepare_pair(job["knowledge_points"][0], resource,
                service.store.evidence(job["job_id"], resource["resource_id"]), state["request"])
            return reply({"decisions": [decision(pair)]})
        return reply({"decisions": [{"pair_id": data["claims"][0]["pair_id"], "accepted": True}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service.settings = replace(service.settings, llm_provider="openai_compatible", llm_api_key="offline-key",
            llm_model="offline-model", llm_base_url="https://model.example/v1")
        service.llm.client = client
        assert not visible_point_ids(service, job)
        await _recover_from_own_metadata(service, job, state, state["points"])
        assert len(calls) == 2 and visible_point_ids(service, job) == {pid}
        for _ in range(3):
            service.results(job["job_id"])
        await _recover_from_own_metadata(service, job, state, state["points"])
        assert len(calls) == 2 and not searches and not service.fetcher.calls
        assert state["reserved"] == 1
        assert job["grounded_related"]["accepted"] == 1
        assert job["budgets"]["grounded_related_max_model_calls"] == 4


async def test_expired_global_deadline_never_starts_model(recovery_service):
    service, _, _ = recovery_service()
    point, request = inputs()
    job = service.store.get_job(service.create(request)["job_id"])
    resource, evidence = source()
    service.store.save_resource(job["job_id"], resource)
    for row in evidence:
        service.store.add_evidence(job["job_id"], resource["resource_id"], "kp_1", row)
    service.settings = replace(service.settings, llm_provider="openai_compatible", llm_api_key="offline-key", llm_model="offline")
    state = {"request": request, "points": job["knowledge_points"], "resources": {resource["resource_id"]: resource}, "candidate_groups": {}}
    token = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() - 1)
    try:
        await _recover_from_own_metadata(service, job, state, state["points"])
    finally:
        FETCH_DEADLINE_AT.reset(token)
    assert job["grounded_related"]["judgment_calls"] == 0


@pytest.mark.parametrize("accept", [True, False])
async def test_newly_fetched_model_url_gets_own_page_review_at_final_after_search(recovery_service, accept):
    service, searches, _ = recovery_service(plan={TOPIC: {"urls": [URL], "queries": []}},
        respond=lambda *_: httpx.Response(200, json={"organic": []}),
        llm_provider="openai_compatible", llm_api_key="offline-key", llm_model="offline-model",
        llm_base_url="https://model.example/v1")
    service.fetcher = SourcePages({URL: TITLE})
    calls = []
    def respond(request):
        data = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(data)
        if "pairs" in data:
            pair = data["pairs"][0]
            observed = next(s for s in pair["observations"] if s["basis"] == "description")
            return reply({"decisions": [{"pair_id": pair["pair_id"], "fingerprint": pair["fingerprint"],
                "support": {"evidence_id": observed["evidence_id"], "basis": "description",
                    "quote": observed["segments"][0], "source_text_sha256": observed["source_text_sha256"]}}]})
        return reply({"decisions": [{"pair_id": data["claims"][0]["pair_id"], "accepted": accept}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service.llm.client = client
        _, request = inputs()
        identifier = service.create(request)["job_id"]
        await service.run(identifier)
        job = service.store.get_job(identifier)
        assert len(calls) == 2 and bool(visible_point_ids(service, job)) is accept
        assert len(service.fetcher.calls) == 1
        assert job["grounded_related"]["accepted"] == int(accept)
        assert job["ai_video_fallback"]["remaining_points"] == int(not accept)
        assert len(searches) == 1  # final-only audit follows the bounded source stage
        assert not any(row.get("kind") == "page" and "model" in str(row.get("source", ""))
            for rid in service.store.resources(identifier) for row in service.store.evidence(identifier, rid))


async def test_source_title_from_actual_form_case_is_valid_without_project_dictionary():
    point, request = inputs()
    resource, evidence = source(
        "【html中标记的简单应用】-16-javascript取form表单中input表单元素的值-onclick事件",
        "html中标记的简单应用中，form表单的目的就是获取数据，进行交互响应。 所以理解form表单元素时，要连同抓取这些表单元素的值value，一起学习，才能完整。 这里是基础教学，所以用javascirpt进行简单取值以供引出更多知识点")
    assert related_recommendation(point, resource, evidence, request) is None
    pair = gr.prepare_pair(point, resource, evidence, request)
    assert pair is not None
    assert gr.validate_support(pair, decision(pair, basis="title"))


async def test_known_paid_chapter_is_excluded_and_new_payment_invalidates_saved_reference():
    point, request = inputs()
    parsed = await CatalogPages({URL: ("HTML complete course", [TITLE])}).enrich({"url": URL})
    evidence = parsed.pop("evidence")
    resource = {**parsed, "resource_id": "resource_1", "url": URL, "canonical_url": URL, "platform": "bilibili"}
    pair = gr.prepare_pair(point, resource, evidence, request)
    result, _ = await judge(pair, basis="catalog")
    saved = result[pair["pair_id"]]
    assert gr.project_reference(point, resource, evidence, request, saved)
    resource["chapters"][0]["requires_payment"] = True
    after = gr.prepare_pair(point, resource, evidence, request)
    assert not any(s["basis"] == "catalog" for s in (after or {}).get("sources", []))
    assert gr.project_reference(point, resource, evidence, request, saved) is None


async def test_selection_hint_reaches_later_actual_chapter_without_becoming_source_text():
    point, request = inputs()
    chapters = ["Introduction section " + str(i) for i in range(45)] + [TITLE]
    parsed = await CatalogPages({URL: ("HTML complete course", chapters)}).enrich({"url": URL})
    evidence = parsed.pop("evidence")
    resource = {**parsed, "resource_id": "resource_1", "url": URL, "canonical_url": URL, "platform": "bilibili"}
    pair = gr.prepare_pair(point, resource, evidence, request,
        hints=["HTML form values onclick UNOBSERVED_HINT"])
    selected = [s for s in pair["sources"] if s["basis"] == "catalog"]
    assert len(pair["sources"]) <= gr.MAX_SOURCES
    assert any(s["_target"].endswith("?p=46") and s["_projected"] == TITLE for s in selected)
    assert "UNOBSERVED_HINT" not in json.dumps(gr.batch_payload([pair]))
