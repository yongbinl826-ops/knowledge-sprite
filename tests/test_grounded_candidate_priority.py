"""Own-source candidate priority; offline real fixtures, no network/DB calls."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from backend.app import ai_video_service as proposal
from backend.app import grounded_related as gr
from backend.app.config import Settings
from backend.app.extractor import MetadataExtractor
from backend.app.models import SearchRequest, now
from backend.app.ranking import relevance

TESTS_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = TESTS_DIR / "fixtures" / "grounded_candidate_priority"
FIXTURE = json.loads((FIXTURE_DIR / "actual-v22-k6-selection-fixture.json").read_text(encoding="utf-8"))


def prepared(index):
    item = FIXTURE["entries"][index]
    return gr.prepare_pair(FIXTURE["point"], item["resource"], item["evidence"], SearchRequest.model_validate(FIXTURE["request"]))


def minimal_pair(topic, technology, segments, *, context=""):
    return {"core": {"text": topic, "technology": technology, "sources": [
        {"segments": segments, "technology_context": context, "_raw": topic, "_projected": topic}]}}


def own_pair(topic, technology, title, description):
    url = "https://www.bilibili.com/video/BV1xx411c7Df/"
    node = {"@context": "https://schema.org", "@type": "VideoObject", "name": title,
        "description": description, "contentUrl": "https://media.example.org/video.mp4"}
    data = MetadataExtractor().extract('<script type="application/ld+json">' + json.dumps(node, ensure_ascii=False) + '</script>', url, now())
    evidence = data.pop("evidence")
    resource = {**data, "resource_id": "synthetic", "url": url, "canonical_url": url, "platform": "bilibili"}
    point = {"knowledge_point_id": "p", "text": topic, "technology": technology}
    request = SearchRequest(knowledge_points=[topic], topic_technologies={topic: technology}, preferred_platforms=["bilibili"])
    return gr.prepare_pair(point, resource, evidence, request), resource, evidence, point, request


def test_real_k6_own_chapter_priority_outweighs_linked_generic_candidates():
    pairs = [prepared(i) for i in range(3)]
    assert all(pairs)
    assert all(proposal._prepared_reference_priority(p) == 0 for p in pairs[:2])
    assert proposal._prepared_reference_priority(pairs[2]) > 0
    # Deliberately give both irrelevant candidates the stronger discovery link;
    # this must not outrank the admitted current own content signal.
    rows = [(True, pairs[0]), (True, pairs[1]), (False, pairs[2])]
    rows.sort(key=lambda row: (proposal._prepared_reference_priority(row[1]), row[0]), reverse=True)
    assert rows[0][1]["core"]["resource_id"] == FIXTURE["entries"][2]["resource"]["resource_id"]
    assert any("错误重试机制" in segment for source in rows[0][1]["core"]["sources"] for segment in source["segments"])
    assert rows[0][1]["fingerprint"] not in FIXTURE["actual_ledger"]["attempted"]


@pytest.mark.parametrize("topic,technology,content", [
    ("SQL 事务回滚", "SQL", "事务提交与回滚"),
    ("集合差集比对", "Python", "集合交集、并集、差集"),
    ("会话状态管理", "Streamlit", "会话状态更新与持久化"),
    ("字符串分割", "Python", "Splitting a string into words"),
    ("碰撞检测", "Pygame", "Collision detection using colliderect()"),
    ("缺失值处理", "pandas", "Missing values: fillna() and dropna()"),
])
def test_cross_domain_own_observation_beats_framework_only_metadata(topic, technology, content):
    relevant, *_ = own_pair(topic, technology, technology + " video tutorial", content)
    generic, *_ = own_pair(topic, technology, technology + " video tutorial", "Introduction and installation")
    assert relevant and generic
    assert proposal._prepared_reference_priority(relevant) > proposal._prepared_reference_priority(generic)


@pytest.mark.parametrize("topic,technology", [
    ("Python exception retries", "Python"),
    ("python-docx document generation", "python-docx"),
    ("JavaScript event handlers", "JavaScript"),
    ("C++ memory allocation", "C++"),
])
def test_technology_alone_never_contributes_priority(topic, technology):
    assert proposal._prepared_reference_priority(minimal_pair(topic, technology, [technology + " tutorial"])) == 0


def test_source_context_private_fields_and_search_claims_do_not_score():
    pair = minimal_pair("碰撞检测", "Pygame", ["Pygame installation"], context="Collision detection using colliderect()")
    pair["search_snippet"] = "Collision detection using colliderect()"
    pair["hints"] = ["碰撞检测"]
    assert proposal._prepared_reference_priority(pair) == 0


def test_unknown_topic_remains_a_zero_score_candidate_not_rejected():
    pair = minimal_pair("非线性约束求解", "Julia", ["A specialized numerical method"])
    assert proposal._prepared_reference_priority(pair) == 0
    assert sorted([pair], key=proposal._prepared_reference_priority) == [pair]


@pytest.mark.parametrize("mutation", ["paid", "stale", "no_identity", "missing_source"])
def test_real_source_admission_is_still_required(mutation):
    item = deepcopy(FIXTURE["entries"][2])
    resource, evidence = item["resource"], item["evidence"]
    if mutation == "paid": resource["requires_payment"] = True
    if mutation == "stale": resource["cache"] = {"stale": True}
    if mutation == "no_identity": resource["field_provenance"].pop("video_evidence_status", None)
    if mutation == "missing_source": evidence.clear()
    assert gr.prepare_pair(FIXTURE["point"], resource, evidence, SearchRequest.model_validate(FIXTURE["request"])) is None


def test_wrong_technology_source_does_not_gain_priority_or_admission():
    pair, *_ = own_pair("会话状态管理", "Streamlit", "Flet tutorial", "Flet session state management")
    assert pair is None


@pytest.mark.asyncio
async def test_scheduler_uses_real_retry_pair_first_keeps_two_attempt_cap_and_no_auto_acceptance(monkeypatch):
    values = deepcopy(FIXTURE)
    point = values["point"]
    resources = {x["resource"]["resource_id"]: x["resource"] for x in values["entries"]}
    evidence = {x["resource"]["resource_id"]: x["evidence"] for x in values["entries"]}
    settings = replace(Settings(), llm_provider="openai_compatible", llm_api_key="offline-only-key",
        llm_base_url="https://offline.invalid/v1", llm_model="offline-model", deadline_seconds=120)
    service = SimpleNamespace(settings=settings, llm=None,
        results=lambda _jid: {"groups": []},
        store=SimpleNamespace(resources=lambda _jid: resources, evidence=lambda _jid, rid: evidence[rid]),
        _point_relevance=lambda p, text: relevance(p["text"], text), _save=lambda _job: None)
    job = {"job_id": "offline-job", "budgets": {}}
    state = {"request": SearchRequest.model_validate(values["request"]), "resources": resources,
        "candidate_groups": {point["knowledge_point_id"]: list(resources)[:2]}}
    captured = []
    async def capture(_settings, pairs, **kwargs):
        captured.extend(deepcopy(pairs))
        kwargs["phase"]("judgment")
        kwargs["on_call"]({"phase": "judgment", "elapsed_seconds": 0.0, "outcome": "ok"})
        kwargs["on_judged"]({pair["pair_id"]: "unknown" for pair in pairs})
        return {}
    monkeypatch.setattr(gr, "judge_batch", capture)
    await proposal._recover_from_own_metadata(service, job, state, [point])
    assert captured[0]["core"]["resource_id"] == values["entries"][2]["resource"]["resource_id"]
    await proposal._recover_from_own_metadata(service, job, state, [point], final=True)
    await proposal._recover_from_own_metadata(service, job, state, [point], final=True)
    assert len(captured) == 2
    assert job["grounded_related"]["point_attempts"][point["knowledge_point_id"]] == 2
    assert job["grounded_related"]["accepted"] == 0
    assert job["grounded_related"]["decisions"] == {}
    assert job["budgets"]["grounded_related_max_pairs_per_point"] == gr.MAX_PER_POINT == 2


@pytest.mark.asyncio
async def test_reordered_pair_still_requires_independent_review(monkeypatch):
    pair = prepared(2)
    source = next(s for s in pair["sources"] if any("错误重试机制" in t for t in s["segments"]))
    calls = []
    async def complete(_settings, _prompt, payload, _client, **_kwargs):
        calls.append(payload)
        if "pairs" in payload:
            return {"decisions": [{"pair_id": pair["pair_id"], "fingerprint": pair["fingerprint"], "support": {
                "evidence_id": source["evidence_id"], "source_text_sha256": source["source_text_sha256"],
                "quote": source["segments"][0], "basis": source["basis"]}}]}
        return {"decisions": [{"pair_id": pair["pair_id"], "accepted": False}]}
    monkeypatch.setattr(gr, "complete_json", complete)
    settings = replace(Settings(), llm_provider="openai_compatible", llm_api_key="offline-only-key",
        llm_base_url="https://offline.invalid/v1", llm_model="offline-model")
    assert await gr.judge_batch(settings, [pair]) == {}
    assert len(calls) == 2


def test_real_canvas_candidate_does_not_drop_behind_longer_generic_form_description():
    fixture = json.loads((FIXTURE_DIR / "actual-canvas-k6-selection-fixture.json").read_text(encoding="utf-8"))
    req = SearchRequest.model_validate(fixture["request"])
    rows = []
    for item in fixture["entries"]:
        resource = item["resource"]
        pair = gr.prepare_pair(fixture["point"], resource, item["evidence"], req)
        assert pair
        # Existing legacy priority is reproducible; no IDF/remote catalog used.
        service = SimpleNamespace(_point_relevance=lambda p, text: relevance(p["text"], text))
        prior = proposal._discovery_priority(service, fixture["point"], req, resource["title"], resource["description"])
        rows.append((item["linked_to_point"], prior, resource["resource_id"], pair))
    old_order = sorted(rows, key=lambda r: (r[0], r[1]), reverse=True)
    new_order = sorted(rows, key=lambda r: (proposal._prepared_reference_priority(r[3]), r[0], r[1]), reverse=True)
    actual = fixture["minimal_actual_pair"]
    good = next(row for row in rows if row[3]["fingerprint"] == actual["fingerprint"])
    assert good[3]["core"]["sources"] == actual["observations"]
    assert new_order.index(good) <= old_order.index(good) == 1
    assert [r[2] for r in new_order] == [r[2] for r in old_order]


def test_excluded_external_course_promotion_cannot_contribute_to_priority():
    fixture = json.loads((TESTS_DIR / "fixtures" / "external-course-own-scope-actual.json").read_text(encoding="utf-8"))
    # Ask for the explicit API mentioned only in the excluded external course.
    topic = "ChatCompletion"
    point = {"knowledge_point_id": "external-scope", "text": topic, "technology": "OpenAI API"}
    request = SearchRequest(knowledge_points=[topic], topic_technologies={topic: "OpenAI API"}, preferred_platforms=["bilibili"])
    pair = gr.prepare_pair(point, fixture["resource"], fixture["evidence"], request)
    assert pair
    assert not any("ChatCompletion" in segment for source in pair["core"]["sources"] for segment in source["segments"])
    assert proposal._prepared_reference_priority(pair) == 0
