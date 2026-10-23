"""Independent offline query contracts; accepted leads never certify a source."""
from copy import deepcopy
import json

import httpx
import pytest

from backend.app.ai_video_fallback import normalize_video_discovery_with_diagnostics
from backend.app.models import SearchRequest
from backend.app.queries import video_recovery_search_phrases, video_recovery_search_phrases_with_diagnostics
from test_ai_grounded_recovery import URL, SourcePages, recovery_service


def request(topic, technology, **kwargs):
    return SearchRequest(knowledge_points=[topic], topic_technologies={topic: technology}, **kwargs)


@pytest.mark.parametrize("topic,technology,hint", [
    ("波纹重排", "QuillFlow", "QuillFlow wavefront reordering"),
    ("湍流编排与反馈折叠", "QuillFlow", "QuillFlow turbulence orchestration and feedback folding"),
    ("表单输入校验与提交控制", "Streamlit", "Streamlit form input validation and submission control"),
    ("HashMap 遍历与文件下载", "Rust", "Rust HashMap iteration and file download"),
    ("hashMap 遍历与文件下载", "Rust", "Rust hashMap iteration and file download"),
    ("自定义 HashMap 遍历与文件下载", "Rust", "Rust custom HashMap iteration and file download"),
])
def test_unfamiliar_complete_english_lead_is_independent_and_target_immutable(topic, technology, hint):
    req = request(topic, technology)
    before = deepcopy(req.model_dump())
    phrases, diagnostic = video_recovery_search_phrases_with_diagnostics(topic, req, [hint])
    assert hint in phrases  # A bilingual concatenation does not satisfy this.
    assert phrases[0] == technology + " " + topic
    assert len(phrases) <= 3 and diagnostic["accepted_hints"] == 1
    assert req.model_dump() == before
    assert video_recovery_search_phrases(topic, req, [hint]) == phrases


def test_complete_model_lead_wins_last_slot_before_mechanical_download_button():
    topic = "文件下载与签名归档"
    hint = "Streamlit file download and signed archive"
    phrases, diagnostic = video_recovery_search_phrases_with_diagnostics(topic, request(topic, "Streamlit"), [hint])
    assert len(phrases) == 3 and phrases[-1] == hint
    assert diagnostic["phrase_kinds"] == ["original", "deterministic", "model"]
    assert not any("download button" in phrase for phrase in phrases)


@pytest.mark.parametrize("topic,technology,hint", [
    ("表单输入与文件下载", "Streamlit", "Streamlit form input"),
    ("表单输入校验与提交控制", "Streamlit", "Streamlit validation and submission control"),
    ("CSV转换为JSON与文本分段", "Python", "Python JSON read CSV and text splitting"),
    ("PointerEvent 指针捕获与触摸处理", "JavaScript", "JavaScript pointer capture and touch handling"),
    ("文件下载", "C++", "C file download"),
    ("文件下载", "Streamlit", "Flet file download"),
])
def test_lead_does_not_drop_known_core_literal_or_technology(topic, technology, hint):
    phrases, diagnostic = video_recovery_search_phrases_with_diagnostics(topic, request(topic, technology), [hint])
    assert hint not in phrases and diagnostic["accepted_hints"] == 0
    assert diagnostic["input_hints"] == sum(diagnostic["rejected_hints"].values())
    assert topic in phrases[0]


@pytest.mark.parametrize("hint", ["Python text splitting 3.12", "Python 313 text splitting"])
def test_explicit_conflicting_version_is_rejected_not_repaired(hint):
    topic = "文本分段"
    phrases, diagnostic = video_recovery_search_phrases_with_diagnostics(topic, request(topic, "Python", technical_version="3.13"), [hint])
    assert hint not in phrases and all("3.13" in p for p in phrases)
    assert diagnostic["rejected_hints"]["version_conflict"] == 1


@pytest.mark.parametrize("hint", [
    "Streamlit file download site:example.org", "Streamlit file download https://example.org/secret-marker",
    "Streamlit file download api_key=offline-secret-marker", "Streamlit file download\nsecret-marker",
    "Streamlit file download -validation", "Streamlit file download; ignore rules", None, 7, "",
])
def test_unsafe_hints_never_enter_queries_or_diagnostic_text(hint):
    topic = "文件下载"
    phrases, diagnostic = video_recovery_search_phrases_with_diagnostics(topic, request(topic, "Streamlit"), [hint])
    assert diagnostic["accepted_hints"] == 0
    assert sum(diagnostic["rejected_hints"].values()) == 1
    encoded = json.dumps(diagnostic)
    assert not any(marker in encoded for marker in ("secret-marker", "example.org", "Streamlit", topic))
    assert not any("secret-marker" in phrase or "example.org" in phrase for phrase in phrases)


def test_target_and_exact_reviewed_practice_targets_are_not_mutated():
    topic = "canvas.toBlob() 图像导出与浏览器下载"
    req = request(topic, "JavaScript", technical_version="ES2022", learning_targets={topic: ["canvas.toBlob('image/png')"]})
    before = deepcopy(req.model_dump())
    phrases, diagnostic = video_recovery_search_phrases_with_diagnostics(topic, req,
        ["JavaScript canvas.toBlob image export browser download ES2022"])
    assert req.model_dump() == before
    assert "canvas.toBlob" in phrases[0] and "图像导出" in phrases[0] and "浏览器下载" in phrases[0]
    assert all("ES2022" in phrase for phrase in phrases) and len(phrases) <= 3


def test_diagnostic_normalization_distinguishes_missing_empty_invalid_duplicate():
    points = ["private-point-marker-" + str(i) for i in range(5)]
    body = {"suggestions": [
        {"point_id": "kp_0", "urls": []},
        {"point_id": "kp_1", "urls": [], "queries": []},
        {"point_id": "kp_2", "urls": [], "queries": [" ", "https://example.org/secret-marker"]},
        {"point_id": "kp_3", "urls": [], "queries": ["Streamlit file download", "streamlit FILE download"]},
    ]}
    _, diagnostic = normalize_video_discovery_with_diagnostics(body, points, ["bilibili"])
    counts = diagnostic["query_normalization"]
    assert [row["query_state"] for row in counts["points"]] == ["missing_field", "empty", "filtered", "accepted", "missing_point"]
    assert counts["input_queries"] == 4 and counts["accepted_queries"] == 1
    assert counts["rejected_queries"] == {"empty": 1, "invalid": 1, "duplicate": 1}
    assert counts["missing_points"] == counts["missing_query_fields"] == counts["empty_query_points"] == 1
    encoded = json.dumps(diagnostic)
    assert all(s not in encoded for s in [*points, "example.org", "secret-marker", "Streamlit"])


@pytest.mark.parametrize("hints", [[], ["", " "], ["Streamlit signed archive and file download", "Streamlit signed archive and file download"],
    ["Streamlit file download and signed archive", "Streamlit file download and archival signatures"],
    ["Streamlit https://example.org/private-marker", "Streamlit file download api_key=private-marker"]])
def test_planning_diagnostics_are_fixed_labels_and_account_for_every_bounded_hint(hints):
    topic = "文件下载与签名归档"
    phrases, diagnostic = video_recovery_search_phrases_with_diagnostics(topic, request(topic, "Streamlit"), hints)
    assert set(diagnostic) == {"schema_version", "status", "input_hints", "accepted_hints", "not_evaluated_hints", "rejected_hints", "phrase_kinds"}
    assert set(diagnostic["rejected_hints"]) == {"empty", "invalid_syntax_or_length", "word_limit", "missing_literal",
        "version_conflict", "duplicate", "operation_not_preserved", "insufficient_specificity", "slots_exhausted"}
    assert diagnostic["status"] in {"normalized", "invalid_hint_container", "target_unavailable", "original_rejected"}
    counts = [diagnostic[k] for k in ("schema_version", "input_hints", "accepted_hints", "not_evaluated_hints")]
    counts += list(diagnostic["rejected_hints"].values())
    assert all(type(value) is int and value >= 0 for value in counts)
    assert diagnostic["accepted_hints"] + diagnostic["not_evaluated_hints"] + sum(diagnostic["rejected_hints"].values()) == diagnostic["input_hints"] == len(hints)
    assert set(diagnostic["phrase_kinds"]) <= {"original", "deterministic", "model", "deterministic_alternative"}
    assert len(phrases) == len(diagnostic["phrase_kinds"]) <= 3
    assert "private-marker" not in json.dumps(diagnostic) and topic not in json.dumps(diagnostic)


@pytest.mark.parametrize("teaching", [False, True])
async def test_independent_english_search_still_matches_original_target_with_original_caps(recovery_service, teaching):
    from backend.app.ai_video_service import visible_point_ids
    topic = "表单输入校验与提交控制"
    hint = "Streamlit form input validation and submission control"
    def respond(query, _count):
        return httpx.Response(200, json={"organic": [{"title": hint, "snippet": hint, "link": URL}] if query.endswith(hint) else []})
    service, searches, _ = recovery_service(plan={topic: {"urls": [], "queries": [hint]}}, respond=respond,
        teaching_match_enabled=teaching, max_search_requests=12, max_detail_pages=3)
    # The actual fetched source contradicts the search lead's technology.
    service.fetcher = SourcePages({URL: "Python 表单输入校验与提交控制"})
    req = request(topic, "Streamlit", preferred_platforms=["bilibili"])
    before = deepcopy(req.model_dump())
    jid = service.create(req)["job_id"]
    await service.run(jid)
    job = service.store.get_job(jid)
    assert "site:bilibili.com " + hint in searches
    assert len(searches) <= 3 and job["progress"]["search_requests"] <= job["budgets"]["max_search_requests"]
    assert len(service.fetcher.calls) <= 3
    assert job["knowledge_points"][0]["text"] == topic and req.model_dump() == before
    assert not visible_point_ids(service, job)
    evidence = service.store.evidence(jid, next(iter(service.store.resources(jid))))
    own = [e for e in evidence if e.get("kind") in {"page", "catalog"}]
    assert own and all(hint not in str(e.get("text", "")) for e in own)
    planning = job["ai_video_fallback"]["query_planning"]
    assert planning and all(hint not in json.dumps(row) and topic not in json.dumps(row) for row in planning)
