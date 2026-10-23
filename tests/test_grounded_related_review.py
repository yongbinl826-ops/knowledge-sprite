"""Independent offline audit: simulated verdicts do not establish model accuracy."""
import asyncio
from copy import deepcopy
import json

import pytest

from backend.app import grounded_related as grounded
from backend.app.config import Settings
from backend.app.models import SearchRequest
from backend.app.read_related_cache import ReadRelatedCache
from test_ai_grounded_recovery import recovery_service


def case(*, topic="表单控件值读取与事件绑定", technology="HTML",
         title="HTML form input values and event handlers", description=None):
    url = "https://lessons.example/own-video"
    point = {"knowledge_point_id": "point-audit", "text": topic, "technology": technology}
    request = SearchRequest(knowledge_points=[topic], topic_technologies={topic: technology})
    resource = {"resource_id": "resource-audit", "title": title,
        "description": description or "HTML: read form input values and bind event handlers.",
        "url": url, "canonical_url": url, "resolved_url": url, "platform": "open_web",
        "resource_type": "video", "video_evidence_status": "page_verified",
        "fetch_status": "fetched", "metadata_evidence_level": "page", "chapters": [],
        "fetched_at": "2026-10-21T00:00:00+00:00", "field_provenance": {}}
    evidence = []
    for field, source in (("title", "html.title"), ("description", "html.description"),
                          ("video_evidence_status", "jsonld.VideoObject"), ("resource_type", "meta.og:type")):
        eid = "own-" + field
        resource["field_provenance"][field] = {"evidence_id": eid, "source": source, "url": url}
        evidence.append({"evidence_id": eid, "source": source, "url": url, "kind": "page",
            "field": field, "text": resource[field], "fetched_at": resource["fetched_at"]})
    return point, resource, evidence, request


def settings():
    return Settings(llm_provider="openai_compatible", llm_model="offline-review",
                    llm_api_key="offline-test-placeholder", llm_base_url="https://model.example/v1")


def decision(pair, *, basis="description", quote=None):
    source = next(s for s in pair["sources"] if s["basis"] == basis)
    return {"pair_id": pair["pair_id"], "fingerprint": pair["fingerprint"], "support": {
        "evidence_id": source["evidence_id"], "source_text_sha256": source["source_text_sha256"],
        "basis": basis, "quote": quote or source["_projected"]}}


def reviewed(monkeypatch, pair, *, accepted=True, quote=None, basis="description"):
    calls = []

    async def answer(config, prompt, payload, client=None, **kwargs):
        calls.append(deepcopy(payload))
        if len(calls) == 1:
            return {"decisions": [decision(pair, quote=quote, basis=basis)]}
        return {"decisions": [{"pair_id": pair["pair_id"], "accepted": accepted}]}

    monkeypatch.setattr(grounded, "complete_json", answer)
    result = asyncio.run(grounded.judge_batch(settings(), [pair]))
    return result.get(pair["pair_id"]), calls


def test_two_stage_review_and_pure_rebind_without_mutation(monkeypatch):
    args = case(); before = deepcopy(args[:3]); pair = grounded.prepare_pair(*args)
    assert pair
    result, calls = reviewed(monkeypatch, pair)
    assert len(calls) == 2 and result
    projected = grounded.project_reference(*args, result)
    assert projected and projected["reference"]["exact_teaching_verified"] is False
    assert projected["reference"]["basis"] == ["page"]
    assert projected["reference"]["source_quote"] == args[1]["description"]
    assert before == args[:3]
    assert "https://" not in json.dumps(calls)
    assert calls[1]["claims"][0]["topic"] == args[0]["text"]


@pytest.mark.parametrize("mutation", ["foreign-id", "bad-hash", "bad-basis", "fabricated-quote", "joined-quote", "bad-fingerprint"])
def test_fabricated_or_misattributed_support_never_reaches_review(monkeypatch, mutation):
    pair = grounded.prepare_pair(*case()); value = decision(pair)
    if mutation == "foreign-id": value["support"]["evidence_id"] = "foreign"
    elif mutation == "bad-hash": value["support"]["source_text_sha256"] = "0" * 64
    elif mutation == "bad-basis": value["support"]["basis"] = "catalog"
    elif mutation == "fabricated-quote": value["support"]["quote"] = "HTML: a fabricated source statement."
    elif mutation == "joined-quote": value["support"]["quote"] = "HTML: read form input values bind event handlers."
    else: value["fingerprint"] = "0" * 64
    assert grounded.validate_support(pair, value) is None
    calls = []

    async def answer(*args, **kwargs):
        calls.append(1)
        return {"decisions": [value]}

    monkeypatch.setattr(grounded, "complete_json", answer)
    assert asyncio.run(grounded.judge_batch(settings(), [pair])) == {}
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["point-id", "point-text", "technology", "technical-version",
    "resource-id", "resource-url", "paid", "resource-stale", "row-stale", "new-fetch", "source-text",
    "source-id", "source-url", "source-kind", "source-provenance", "audio-fault"])
def test_current_input_change_invalidates_reviewed_projection(monkeypatch, mutation):
    p, r, e, request = case(); pair = grounded.prepare_pair(p, r, e, request); sealed, _ = reviewed(monkeypatch, pair)
    if mutation == "point-id": p["knowledge_point_id"] = "another-point"
    elif mutation == "point-text": p["text"] = "HTML 其他操作"
    elif mutation == "technology": request.topic_technologies[p["text"]] = "Python"
    elif mutation == "technical-version": request.technical_version = "v99"
    elif mutation == "resource-id": r["resource_id"] = "another-resource"
    elif mutation == "resource-url": r["url"] = "https://lessons.example/other"
    elif mutation == "paid": r["requires_payment"] = True
    elif mutation == "resource-stale": r["cache"] = {"stale": True}
    elif mutation == "row-stale": e[1]["cache"] = {"stale": True}
    elif mutation == "new-fetch": r["fetched_at"] = "2026-10-21T01:00:00+00:00"
    elif mutation == "source-text": r["description"] = e[1]["text"] = "HTML unrelated topic"
    elif mutation == "source-id": e[1]["evidence_id"] = "replacement-source"
    elif mutation == "source-url": e[1]["url"] = "https://lessons.example/foreign"
    elif mutation == "source-kind": e[1]["kind"] = "search"
    elif mutation == "source-provenance": e[1]["source"] = "search.snippet"
    else: r["description"] = e[1]["text"] = "音频坏了 不想录了 就这样吧"
    assert grounded.project_reference(p, r, e, request, sealed) is None


@pytest.mark.parametrize("mutation", ["search-discovered", "foreign-video-proof", "stale-video-proof", "top-level-stale"])
def test_current_own_video_identity_must_be_fresh_and_bound(mutation):
    p, r, e, request = case()
    proof = e[2]
    if mutation == "search-discovered":
        r["video_evidence_status"] = "search_discovered"
        r["field_provenance"]["video_evidence_status"]["source"] = "search_template"
        proof.update(kind="search", source="search_template", type_source="search_template", resource_type_hint="video")
    elif mutation == "foreign-video-proof": proof["url"] = "https://foreign.example/another-video"
    elif mutation == "stale-video-proof": proof["cache"] = {"stale": True}
    else: r["stale"] = True
    assert grounded.prepare_pair(p, r, e, request) is None


def test_wrong_technology_and_mixed_parent_do_not_supply_topic_context():
    assert grounded.prepare_pair(*case(technology="Python", title="JavaScript form input values", description="JavaScript event handlers")) is None
    pair = grounded.prepare_pair(*case(topic="表单输入", technology="Streamlit", title="Streamlit and Flet course", description="Form input controls"))
    # The mixed title itself may be sent as uncertain source text. It must not
    # donate Streamlit ownership to the otherwise unqualified description.
    assert pair is None or all(s["basis"] == "title" for s in pair["sources"])


@pytest.mark.parametrize("text", ["HTML input values are not covered in this lesson.",
    "This is only a demo. HTML input values and event handlers.",
    "Prerequisites:\nHTML input values and event handlers."])
def test_negated_showcase_or_prerequisite_quote_cannot_pass_exact_quote_check(text):
    pair = grounded.prepare_pair(*case(description=text))
    if pair is not None and any(s["basis"] == "description" for s in pair["sources"]):
        assert grounded.validate_support(pair, decision(pair)) is None


def test_compound_undo_without_redo_still_requires_independent_semantic_review(monkeypatch):
    args = case(topic="操作历史栈与撤销/重做游标", technology="JavaScript",
        title="JavaScript undo history", description="JavaScript: maintain a history stack and undo the last action.")
    pair = grounded.prepare_pair(*args); assert pair
    sealed, calls = reviewed(monkeypatch, pair, accepted=False)
    assert sealed is None and len(calls) == 2
    assert calls[1]["claims"][0]["topic"] == args[0]["text"]
    assert calls[1]["claims"][0]["own_context"] == args[1]["description"]


def test_review_timeout_does_not_return_a_decision_or_mutate_sources(monkeypatch):
    args = case(); pair = grounded.prepare_pair(*args); before = deepcopy(pair); calls = []

    async def answer(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {"decisions": [decision(pair)]}
        raise asyncio.TimeoutError("simulated review deadline")

    monkeypatch.setattr(grounded, "complete_json", answer)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(grounded.judge_batch(settings(), [pair]))
    assert len(calls) == 2 and pair == before


def test_independent_review_payload_does_not_reintroduce_removed_source_secret(monkeypatch):
    quote = "HTML: read form input values and bind event handlers."
    body = quote + "\n" + "Ordinary introduction. " * 40 + "\napi_key=public-fixture-marker\nSafe closing text."
    pair = grounded.prepare_pair(*case(description=body)); assert pair
    calls = []

    async def answer(config, prompt, payload, client=None, **kwargs):
        calls.append(payload)
        assert "public-fixture-marker" not in json.dumps(payload)
        if len(calls) == 1:
            return {"decisions": [decision(pair, quote=quote)]}
        return {"decisions": [{"pair_id": pair["pair_id"], "accepted": True}]}

    monkeypatch.setattr(grounded, "complete_json", answer)
    assert asyncio.run(grounded.judge_batch(settings(), [pair]))
    assert len(calls) == 2


def test_review_context_contains_exact_late_quote_and_its_local_clause(monkeypatch):
    quote = "HTML readValue reads form input values and binds event handlers."
    body = "HTML introduction.\n" + "Ordinary background sentence. " * 100 + "\n" + quote
    args = case(topic="HTML readValue 值读取与事件绑定", description=body)
    pair = grounded.prepare_pair(*args); assert pair
    sealed, calls = reviewed(monkeypatch, pair, quote=quote)
    assert sealed and len(calls) == 2
    assert quote in calls[1]["claims"][0]["own_context"]


@pytest.mark.parametrize("mutation", ["proof-text", "proof-stale", "proof-provenance", "resource-top-stale"])
def test_already_reviewed_decision_rebinds_current_own_identity(monkeypatch, mutation):
    p, r, e, request = case()
    sealed, _ = reviewed(monkeypatch, grounded.prepare_pair(p, r, e, request))
    if mutation == "proof-text": e[2]["text"] = "different current identity observation"
    elif mutation == "proof-stale": e[2]["stale"] = True
    elif mutation == "proof-provenance": r["field_provenance"]["video_evidence_status"]["cache"] = {"stale": True}
    else: r["stale"] = True
    assert grounded.project_reference(p, r, e, request, sealed) is None


@pytest.mark.parametrize("description", [
    "This lesson uses JavaScript, not Python, to read values and bind handlers.",
    "This lesson uses JavaScript instead of Python to read values and bind handlers.",
    "Python is not used to read values and bind handlers in this lesson.",
])
def test_explicitly_denied_technology_cannot_be_rescued_by_positive_verdicts(description):
    args = case(topic="读取值与绑定事件", technology="Python", title="Python and JavaScript form lessons", description=description)
    assert grounded.prepare_pair(*args) is None


def indexed_chapter(resource, evidence, title):
    index = len(resource["chapters"])
    chapter = {"title": title, "url": resource["canonical_url"], "start_seconds": index * 300,
        "end_seconds": (index + 1) * 300, "duration_seconds": 300,
        "evidence_id": f"own-chapter-{index}", "source": "html.own-catalog"}
    resource["chapters"].append(chapter)
    evidence.append({"evidence_id": chapter["evidence_id"], "kind": "catalog",
        "source": chapter["source"], "field": f"chapters.{index}", "url": resource["canonical_url"],
        "fetched_at": resource["fetched_at"], "text": json.dumps(chapter, ensure_ascii=False)})
    return chapter


def test_indexed_neighbor_chapter_cannot_donate_technology():
    args = case(topic="表单输入", technology="Streamlit", title="Streamlit and Flet course", description="An overview of two frameworks.")
    _, resource, evidence, _ = args
    indexed_chapter(resource, evidence, "Streamlit introduction")
    target = indexed_chapter(resource, evidence, "Input widgets and form values")
    pair = grounded.prepare_pair(*args)
    assert pair
    assert target["evidence_id"] not in {s["evidence_id"] for s in pair["sources"]}
    explicit = indexed_chapter(resource, evidence, "Streamlit input widgets and form values")
    pair = grounded.prepare_pair(*args)
    assert explicit["evidence_id"] in {s["evidence_id"] for s in pair["sources"]}


def test_cached_projection_cannot_leak_a_review_into_another_job_context(monkeypatch):
    args = case(); pair = grounded.prepare_pair(*args)
    sealed, _ = reviewed(monkeypatch, pair)
    cache = ReadRelatedCache()
    assert cache.project(*args) is None
    positive = cache.project(*args, grounded_decision=sealed)
    assert positive
    positive["reference"]["source_quote"] = "caller mutation"
    assert cache.project(*args, grounded_decision=sealed)["reference"]["source_quote"] != "caller mutation"
    # Another job with identical point/resource metadata but no private decision
    # must retain the negative result, not inherit this service-instance cache.
    assert cache.project(*args) is None
    assert cache.stats()["hits"] == 2


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
async def test_background_review_failure_never_seals_or_covers_a_point(recovery_service, monkeypatch, failure):
    from dataclasses import replace
    from backend.app.ai_video_service import _recover_from_own_metadata, visible_point_ids
    service, searches, _ = recovery_service()
    _, resource, evidence, request = case()
    job = service.store.get_job(service.create(request)["job_id"])
    pid = job["knowledge_points"][0]["knowledge_point_id"]
    service.store.save_resource(job["job_id"], resource)
    for row in evidence:
        service.store.add_evidence(job["job_id"], resource["resource_id"], pid, row)
    service.settings = replace(service.settings, llm_provider="openai_compatible", llm_model="offline",
        llm_api_key="offline-test-placeholder", llm_base_url="https://model.example/v1")
    state = {"request": request, "points": job["knowledge_points"], "resources": {resource["resource_id"]: resource},
             "candidate_groups": {pid: [resource["resource_id"]]}, "reserved": 1}
    async def interrupted(_settings, pairs, *, phase, **kwargs):
        phase("judgment"); phase("review")
        if failure == "cancel": raise asyncio.CancelledError()
        raise asyncio.TimeoutError()
    monkeypatch.setattr(grounded, "judge_batch", interrupted)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await _recover_from_own_metadata(service, job, state, state["points"])
    else:
        await _recover_from_own_metadata(service, job, state, state["points"])
    saved = service.store.get_job(job["job_id"])["grounded_related"]
    assert saved["decisions"] == {} and saved["accepted"] == 0
    assert saved["status"] == ("interrupted" if failure == "cancel" else "unavailable")
    assert saved["judgment_calls"] == saved["review_calls"] == 1
    assert not visible_point_ids(service, job)
    assert not searches and not service.fetcher.calls and state["reserved"] == 1


@pytest.mark.parametrize("followup", ["new-source", "changed-source", "final-old-pool"])
async def test_second_semantic_slot_is_preserved_until_final_complete_pool(recovery_service, monkeypatch, followup):
    from dataclasses import replace
    from backend.app.ai_video_service import _recover_from_own_metadata
    service, searches, _ = recovery_service()
    request = case()[3]
    job = service.store.get_job(service.create(request)["job_id"])
    pid = job["knowledge_points"][0]["knowledge_point_id"]
    service.settings = replace(service.settings, llm_provider="openai_compatible", llm_model="offline",
        llm_api_key="offline-test-placeholder", llm_base_url="https://model.example/v1")
    state = {"request": request, "points": job["knowledge_points"], "resources": {},
             "candidate_groups": {pid: []}, "reserved": 0}

    def add(rid, *, relevant=False):
        _, resource, evidence, _ = case(title="HTML form input values and event handlers" if relevant else "HTML fundamentals",
            description="HTML: read form input values and bind event handlers." if relevant else "HTML document structure and headings.")
        url = "https://lessons.example/" + rid
        resource.update(resource_id=rid, url=url, canonical_url=url, resolved_url=url)
        for provenance in resource["field_provenance"].values():
            provenance.update(url=url, evidence_id=rid + "-" + provenance["evidence_id"])
        for row in evidence:
            row.update(url=url, evidence_id=rid + "-" + row["evidence_id"])
        service.store.save_resource(job["job_id"], resource)
        for row in evidence:
            service.store.add_evidence(job["job_id"], rid, pid, row)
        state["resources"][rid] = resource
        if rid not in state["candidate_groups"][pid]: state["candidate_groups"][pid].append(rid)
        return evidence

    calls = []
    async def reject(_settings, pairs, *, phase, **kwargs):
        calls.append([p["core"]["resource_id"] for p in pairs]); phase("judgment")
        kwargs["on_judged"]({p["pair_id"]: "unknown" for p in pairs})
        return {}
    monkeypatch.setattr(grounded, "judge_batch", reject)
    add("early-a"); add("early-b")
    await _recover_from_own_metadata(service, job, state, state["points"])
    assert calls == [["early-a"]]
    assert job["grounded_related"]["point_attempts"][pid] == 1
    # Re-entering the old pool must not consume the only later opportunity.
    await _recover_from_own_metadata(service, job, state, state["points"])
    assert len(calls) == 1
    if followup == "new-source":
        evidence = add("late-own-source", relevant=True)
        assert grounded.prepare_pair(job["knowledge_points"][0], state["resources"]["late-own-source"], evidence, request)
        # The full pool preserves the existing rank's stable tie order; a new
        # source no longer displaces an earlier unassessed source merely by age.
        from backend.app.ai_video_service import _discovery_priority
        old, new = state["resources"]["early-b"], state["resources"]["late-own-source"]
        assert _discovery_priority(service, job["knowledge_points"][0], request, old["title"], old["description"]) == _discovery_priority(
            service, job["knowledge_points"][0], request, new["title"], new["description"])
        expected = "early-b"
    elif followup == "changed-source":
        # A refetch updates both the current resource and its existing own rows.
        resource = state["resources"]["early-b"]
        resource["fetched_at"] = "2026-10-21T01:00:00+00:00"
        service.store.save_resource(job["job_id"], resource)
        for row in service.store.evidence(job["job_id"], "early-b"):
            row["fetched_at"] = resource["fetched_at"]
            service.store.connection.execute("UPDATE evidence SET data=? WHERE job_id=? AND id=?",
                (json.dumps(row), job["job_id"], row["evidence_id"]))
        service.store.connection.commit()
        expected = "early-b"
    else:
        expected = "early-b"
    await _recover_from_own_metadata(service, job, state, state["points"])
    assert calls == [["early-a"]]  # New/changed sources still wait for final.
    await _recover_from_own_metadata(service, job, state, state["points"], final=True)
    assert calls == [["early-a"], [expected]]
    assert job["grounded_related"]["point_attempts"][pid] == 2
    assert job["grounded_related"]["batches"] == 2
    await _recover_from_own_metadata(service, job, state, state["points"], final=True)
    assert len(calls) == 2 and not searches and not service.fetcher.calls


@pytest.mark.parametrize("weak_kind", ["search", "unqualified-page"])
def test_weak_lexical_observation_cannot_shadow_reviewed_own_catalog(monkeypatch, weak_kind):
    from backend.app.related_recommendations import related_recommendation
    args = case(technology="JavaScript", title="JavaScript and Python course", description="A comparison of two technologies.")
    point, resource, evidence, request = args
    chapter = indexed_chapter(resource, evidence, "JavaScript form input values and event handlers")
    pair = grounded.prepare_pair(*args)
    sealed, _ = reviewed(monkeypatch, pair, basis="catalog", quote=chapter["title"])
    assert sealed and grounded.project_reference(*args, sealed)
    if weak_kind == "search":
        evidence.append({"evidence_id": "weak-lexical", "kind": "search", "source": "fixture-search",
            "knowledge_point_id": point["knowledge_point_id"], "url": resource["canonical_url"],
            "title": point["text"], "snippet": point["text"]})
    else:
        evidence.append({"evidence_id": "weak-lexical", "kind": "page", "field": "video_topic_summary",
            "source": "html.own-summary", "url": resource["canonical_url"], "text": point["text"]})
    weak = related_recommendation(*args)
    assert weak is None  # The weak observation has no bound technical context.
    projected = related_recommendation(*args, grounded_decision=sealed)
    assert projected["reference"]["technical_context"] == "observed"
    assert projected["reference"]["basis"] == ["catalog"]
    assert chapter["evidence_id"] in projected["reference"]["evidence_ids"]
