import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from backend.app.ai_video_fallback import (direct_video_url, normalize_video_discovery,
                                          normalize_video_discovery_with_diagnostics,
                                          normalize_video_suggestions,
                                          normalize_video_suggestions_with_diagnostics,
                                          video_search_phrase)
from backend.app.config import Settings
from backend.app.llm import OpenAICompatibleLLM
from backend.app.models import SearchRequest


BILI = "https://www.bilibili.com/video/BV1xx411c7mD/"
MOOC = "https://www.icourse163.org/course/PKU-1002534002"
PLATFORMS = ["bilibili", "icourse163", "xuetangx"]


@pytest.mark.parametrize(("url", "expected"), [
    (BILI + "?p=2&utm_source=share", BILI + "?p=2"),
    ("https://www.bilibili.com/video/av12345", "https://www.bilibili.com/video/av12345"),
    (MOOC, MOOC),
    ("https://www.icourse163.org/course/detail.htm?cid=1002534002&tid=100001", "https://www.icourse163.org/course/detail.htm?cid=1002534002&tid=100001"),
    ("https://www.xuetangx.com/course/THU08091000373/", "https://www.xuetangx.com/course/THU08091000373/"),
])
def test_direct_known_urls_preserve_resource_scope(url, expected):
    assert direct_video_url(url, PLATFORMS) == expected


@pytest.mark.parametrize("url", [
    "http://www.bilibili.com/video/BV1xx411c7mD/",
    "https://b23.tv/abcdef", "https://search.bilibili.com/all?keyword=Python",
    "https://www.bilibili.com/", "https://www.bilibili.com/video/not-a-real-id/",
    BILI + "?redirect=https://example.org", BILI + "?p=2&p=3", BILI + "?p=-2",
    BILI + "#reply", BILI + "\n", BILI.replace("BV1xx", "BV 1xx"),
    "https://api.bilibili.com/video/BV1xx411c7mD/",
    "https://m.bilibili.com/video/BV1xx411c7mD/",
    "https://www.bilibili.com.evil.org/video/BV1xx411c7mD/",
    "https://user:pass@www.bilibili.com/video/BV1xx411c7mD/",
    "https://www.bilibili.com:8080/video/BV1xx411c7mD/",
    "https://127.0.0.1/video/BV1xx411c7mD/",
    "https://metadata.google.internal/video/BV1xx411c7mD/",
    "javascript:alert(1)", "file:///etc/passwd", "//www.bilibili.com/video/BV1xx411c7mD/",
    "https://www.icourse163.org/search.htm?search=Python",
    "https://www.icourse163.org/course/detail.htm?tid=100001",
    MOOC + "?redirect=https://example.org", MOOC + "#chapter",
    "https://www.xuetangx.com/search?query=Python",
    "https://www.xuetangx.com/course/python?redirect=example.org",
    "https://www.youtube.com/watch?v=abcdefghijk",
])
def test_reject_unsafe_nonresource_or_unsupported_urls(url):
    assert direct_video_url(url, PLATFORMS) is None


def test_respects_explicit_requested_platforms():
    assert direct_video_url(BILI, ["icourse163"]) is None
    assert direct_video_url(MOOC, []) is None


def test_bind_points_dedupe_aliases_and_exclude_previous_urls():
    body = {"suggestions": [
        {"point_id": "kp_1", "urls": [BILI, BILI.replace("www.", "").rstrip("/"), MOOC]},
        {"point_id": "kp_0", "urls": [MOOC, "https://www.icourse163.org/course/detail.htm?cid=1002534002"]},
    ]}
    assert normalize_video_suggestions(body, ["列表", "元组"], PLATFORMS) == {
        "列表": [MOOC], "元组": [BILI, MOOC],
    }
    assert normalize_video_suggestions(body, ["列表", "元组"], PLATFORMS,
        excluded_urls=["https://www.icourse163.org/course/detail.htm?cid=1002534002", BILI]) == {
            "列表": [], "元组": [],
        }


def test_incomplete_or_bad_hint_is_not_fabricated():
    assert normalize_video_suggestions({"suggestions": [
        {"point_id": "kp_0", "urls": ["https://search.bilibili.com/all?keyword=Python", BILI]}
    ]}, ["列表", "元组"], PLATFORMS) == {"列表": [BILI], "元组": []}


@pytest.mark.parametrize("body", [
    {"suggestions": [{"point_id": "kp_99", "urls": [BILI]}]},
    {"suggestions": [{"point_id": "kp_0", "urls": []}, {"point_id": "kp_0", "urls": [BILI]}]},
    {"suggestions": [{"point_id": "kp_0", "urls": [BILI], "title": "trusted teaching fact"}]},
    {"suggestions": [{"point_id": "kp_0", "urls": [BILI] * 4}]},
    {"suggestions": [{"point_id": "kp_0", "urls": [42]}]},
    {"suggestions": [{"point_id": "kp_0", "urls": []}], "evidence": "model says verified"},
    {"suggestions": [{"point_id": f"kp_{i}", "urls": []} for i in range(6)]},
])
def test_response_contract_rejects_unknown_ids_or_claims(body):
    with pytest.raises((ValueError, ValidationError)):
        normalize_video_suggestions(body, ["列表"], PLATFORMS)


async def test_llm_uses_separate_bounded_url_prompt_and_confirmed_context():
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"suggestions": [{"point_id": "kp_0", "urls": [MOOC, BILI]}]})
        }}]})

    settings = Settings(llm_api_key="test-llm-key", llm_model="test-model")
    request = SearchRequest(knowledge_points=["列表", "元组"], preferred_platforms=["bilibili"],
        topic_technologies={"列表": "Python"}, learning_skills={"列表": ["遍历列表"]},
        learning_targets={"列表": ["输出元素"]}, project_context="learn Python")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await OpenAICompatibleLLM(settings, client).suggest_video_urls(["列表"], request,
            excluded_urls=[MOOC])
    assert result == {"列表": [BILI]}
    assert len(captured) == 1
    payload = captured[0]
    assert payload["response_format"] == {"type": "json_object"}
    assert "json" in payload["messages"][0]["content"].lower()
    assert "tools" not in payload
    assert "unverified discovery hints" in payload["messages"][0]["content"]
    assert "Never output URLs" not in payload["messages"][0]["content"]
    data = json.loads(payload["messages"][1]["content"])
    assert data["points"] == [{"point_id": "kp_0", "knowledge_point": "列表", "topic_technology": "Python",
                               "required_literals": [],
                               "learning_skills": ["遍历列表"], "learning_targets": ["输出元素"]}]
    assert data["preferred_platforms"] == ["bilibili"]
    assert data["project_context"] == "learn Python"


async def test_empty_selection_or_invalid_points_never_call_provider():
    def unexpected(_request):
        raise AssertionError("Provider must not be called")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        llm = OpenAICompatibleLLM(Settings(), client)
        request = SearchRequest(knowledge_points=["列表"], preferred_platforms=[])
        assert await llm.suggest_video_urls(["列表"], request) == {"列表": []}
        assert await llm.suggest_video_urls([], request) == {}
        with pytest.raises(ValueError):
            await llm.suggest_video_urls(["外来知识点"], request)
        with pytest.raises(ValueError):
            await llm.suggest_video_urls(["列表", "列表"], request)


async def test_transport_timeout_and_exclusion_prompt_are_bounded(monkeypatch):
    captured = {}

    async def fake_complete(settings, instruction, data, client, **kwargs):
        captured.update(kwargs)
        captured["data"] = data
        return {"suggestions": [{"point_id": "kp_0", "urls": [BILI]}]}

    monkeypatch.setattr("backend.app.llm.complete_json", fake_complete)
    request = SearchRequest(knowledge_points=["列表"])
    exclusions = [f"https://www.bilibili.com/video/av{i}/" for i in range(1, 121)] + [BILI]
    result = await OpenAICompatibleLLM(Settings()).suggest_video_urls(["列表"], request,
        excluded_urls=exclusions)
    assert captured["timeout_seconds"] == 20
    assert captured["max_content_chars"] == 40_000
    assert len(captured["data"]["excluded_urls"]) == 100
    # Filtering uses every existing URL even when the prompt exclusion list is capped.
    assert result == {"列表": []}


def test_discovery_keeps_queries_when_urls_are_empty_or_previously_failed():
    body = {"suggestions": [
        {"point_id": "kp_1", "urls": [], "queries": ["Pygame 事件循环教程", "Pygame 游戏开发课程"]},
        {"point_id": "kp_0", "urls": [BILI], "queries": ["Python 列表教程", " python  列表教程 "]},
    ]}
    assert normalize_video_discovery(body, ["列表", "事件循环"], PLATFORMS, excluded_urls=[BILI]) == {
        "列表": {"urls": [], "queries": ["Python 列表教程"]},
        "事件循环": {"urls": [], "queries": ["Pygame 事件循环教程", "Pygame 游戏开发课程"]},
    }


@pytest.mark.parametrize("phrase", [
    "", "x", "x" * 81, "site:bilibili.com Pygame", "https://example.org", "bilibili.com Python",
    "www.example.org", "Python -paid", 'Python "list"', "Python\nevents", "Python\t列表",
    "Python; invoke", "Python $(secret)", "Python <script>", "Python | system", "Python / API",
])
def test_discovery_query_filters_urls_operators_controls_and_unbounded_text(phrase):
    assert video_search_phrase(phrase) is None


@pytest.mark.parametrize("phrase", ["Pygame 事件循环教程", "pygame.event.get 事件队列", "C++ 向量教程"])
def test_discovery_query_allows_teaching_topics_and_api_names(phrase):
    assert video_search_phrase(phrase) == phrase


def test_discovery_invalid_query_does_not_discard_other_valid_leads():
    body = {"suggestions": [{"point_id": "kp_0", "urls": [BILI],
                             "queries": ["site:bilibili.com Python", "Python 列表遍历"]}]}
    assert normalize_video_discovery(body, ["列表", "元组"], PLATFORMS) == {
        "列表": {"urls": [BILI], "queries": ["Python 列表遍历"]},
        "元组": {"urls": [], "queries": []},
    }


@pytest.mark.parametrize("row", [
    {"point_id": "kp_0", "urls": [], "queries": ["Python"] * 3},
    {"point_id": "kp_0", "urls": [], "queries": [42]},
    {"point_id": "kp_0", "urls": [], "queries": "Python"},
    {"point_id": "kp_0", "urls": [], "queries": [], "playable": True},
    {"point_id": "kp_99", "urls": [], "queries": ["Python 列表"]},
])
def test_discovery_rejects_oversized_or_invented_contract_fields(row):
    with pytest.raises((ValueError, ValidationError)):
        normalize_video_discovery({"suggestions": [row]}, ["列表"], PLATFORMS)


async def test_combined_discovery_uses_one_json_call_for_urls_and_live_search_queries():
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"suggestions": [{"point_id": "kp_0", "urls": [],
                "queries": ["Pygame 事件循环教程", "Pygame 游戏开发课程"]}]})
        }}]})

    request = SearchRequest(knowledge_points=["事件循环"], topic_technologies={"事件循环": "Pygame"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await OpenAICompatibleLLM(Settings(llm_api_key="test-key"), client).suggest_video_discovery(
            ["事件循环"], request)
    assert result == {"事件循环": {"urls": [], "queries": ["Pygame 事件循环教程", "Pygame 游戏开发课程"]}}
    assert len(captured) == 1
    assert captured[0]["response_format"] == {"type": "json_object"}
    prompt = captured[0]["messages"][0]["content"]
    assert "JSON" in prompt
    assert "Always provide 1 to 2" in prompt
    assert "including when direct URLs are present or the urls array is empty" in prompt
    assert "Preserve the declared technology and core topic in each query" in prompt
    assert "never as evidence that such a course exists" in prompt
    assert "common Chinese tutorial terminology" in prompt
    assert "ordinary English teaching terms for the same core operation" in prompt
    assert "An existing required API is not optional" in prompt
    assert "Only when the point names no API" in prompt
    assert "A single well-known API name is optional" not in prompt
    assert "complementary rather than duplicates or reordered words" in prompt
    assert "Do not replace the core operation with a generic beginner tutorial" in prompt
    assert "use broader course terminology" not in prompt
    data = json.loads(captured[0]["messages"][1]["content"])
    assert data["points"][0]["topic_technology"] == "Pygame"


def test_url_diagnostics_distinguish_empty_missing_and_filter_reasons_without_text():
    points = [f"private point {index}" for index in range(5)]
    excluded = "https://www.bilibili.com/video/av12345/"
    body = {"suggestions": [
        {"point_id": "kp_4", "urls": [MOOC,
            "https://www.icourse163.org/course/detail.htm?cid=1002534002", BILI + "?p=2"],
            "queries": ["private query text"]},
        {"point_id": "kp_0", "urls": [BILI, BILI.replace("www.", "").rstrip("/"),
            "https://unknown.invalid/secret-private-response"]},
        {"point_id": "kp_1", "urls": [excluded, excluded.replace("www.", ""), " \t "]},
        {"point_id": "kp_2", "urls": []},
    ]}
    plan, diagnostic = normalize_video_discovery_with_diagnostics(
        body, points, PLATFORMS, excluded_urls=[excluded])
    assert plan == normalize_video_discovery(body, points, PLATFORMS, excluded_urls=[excluded])
    assert diagnostic["schema_version"] == 1
    assert diagnostic["status"] == "normalized"
    assert [row["point_index"] for row in diagnostic["points"]] == list(range(5))
    assert [row["url_state"] for row in diagnostic["points"]] == [
        "accepted", "filtered", "empty", "missing", "accepted"]
    assert diagnostic["requested_points"] == 5
    assert diagnostic["returned_points"] == 4
    assert diagnostic["missing_points"] == 1
    assert diagnostic["empty_url_points"] == 1
    assert diagnostic["input_urls"] == 9
    assert diagnostic["accepted_urls"] == 3
    assert diagnostic["rejected_urls"] == {"empty": 1, "invalid": 1, "duplicate": 2, "already_seen": 2}
    for row in diagnostic["points"]:
        assert row["input_urls"] == row["accepted_urls"] + sum(row["rejected_urls"].values())
    for field in ("input_urls", "accepted_urls"):
        assert diagnostic[field] == sum(row[field] for row in diagnostic["points"])
    for reason, count in diagnostic["rejected_urls"].items():
        assert count == sum(row["rejected_urls"][reason] for row in diagnostic["points"])
    serialized = json.dumps(diagnostic)
    assert all(value not in serialized for value in points + [BILI, MOOC, excluded,
        "private query text", "secret-private-response", "https://"])


def test_url_diagnostic_preserves_per_point_dedupe_and_video_part_identity():
    body = {"suggestions": [{"point_id": f"kp_{i}", "urls": [BILI, BILI + "?p=2", BILI + "?p=3"]}
                            for i in range(5)]}
    points = [f"point {index}" for index in range(5)]
    result, diagnostic = normalize_video_suggestions_with_diagnostics(body, points, PLATFORMS)
    assert all(urls == [BILI, BILI + "?p=2", BILI + "?p=3"] for urls in result.values())
    assert diagnostic["input_urls"] == diagnostic["accepted_urls"] == 15
    assert not any(diagnostic["rejected_urls"].values())
    result, diagnostic = normalize_video_suggestions_with_diagnostics(
        body, points, PLATFORMS, excluded_urls=[BILI + "?p=2"])
    assert diagnostic["rejected_urls"]["already_seen"] == 5
    assert diagnostic["accepted_urls"] == 10
    assert all(urls == [BILI, BILI + "?p=3"] for urls in result.values())


@pytest.mark.parametrize("body", [
    {"suggestions": [{"point_id": "kp_9", "urls": []}]},
    {"suggestions": [{"point_id": "kp_0", "urls": []}] * 2},
    {"suggestions": [{"point_id": "kp_0", "urls": [BILI] * 4}]},
    {"suggestions": [{"point_id": "kp_0", "urls": [42]}]},
    {"suggestions": [{"point_id": "kp_0", "queries": []}]},
    {"suggestions": [{"point_id": "kp_0", "urls": [], "diagnostic": "model claim"}]},
])
def test_invalid_response_never_masquerades_as_zero_url_diagnostic(body):
    with pytest.raises((ValueError, ValidationError)):
        normalize_video_discovery_with_diagnostics(body, ["point"], PLATFORMS)


async def test_diagnostic_provider_call_preserves_legacy_outputs_and_has_no_shared_state():
    captured = []

    def respond(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        captured.append(data)
        urls = [] if data["points"][0]["knowledge_point"] == "empty point" else [BILI, BILI]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"suggestions": [{"point_id": "kp_0", "urls": urls,
                "queries": ["Python list iteration"]}]})
        }}]})

    request = SearchRequest(knowledge_points=["empty point", "duplicate point"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        llm = OpenAICompatibleLLM(Settings(llm_api_key="test-key"), client)
        empty, duplicate, plan, urls = await asyncio.gather(
            llm.suggest_video_discovery_with_diagnostics(["empty point"], request),
            llm.suggest_video_discovery_with_diagnostics(["duplicate point"], request),
            llm.suggest_video_discovery(["duplicate point"], request),
            llm.suggest_video_urls(["duplicate point"], request),
        )
    assert len(captured) == 4  # Exactly one HTTP call for each public invocation.
    assert empty[1]["empty_url_points"] == 1
    assert empty[1]["input_urls"] == 0
    assert duplicate[1]["input_urls"] == 2
    assert duplicate[1]["accepted_urls"] == 1
    assert duplicate[1]["rejected_urls"]["duplicate"] == 1
    assert duplicate[0] == plan == {"duplicate point": {"urls": [BILI], "queries": ["Python list iteration"]}}
    assert urls == {"duplicate point": [BILI]}
    duplicate[1]["points"][0]["rejected_urls"]["invalid"] = 1
    assert duplicate[1]["rejected_urls"]["invalid"] == 0
    assert empty[1]["rejected_urls"]["invalid"] == 0


async def test_unrequested_diagnostic_does_not_claim_model_returned_empty_urls():
    def unexpected(_request):
        raise AssertionError("Provider must not be called")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        llm = OpenAICompatibleLLM(Settings(), client)
        request = SearchRequest(knowledge_points=["point"], preferred_platforms=[])
        plan, diagnostic = await llm.suggest_video_discovery_with_diagnostics(["point"], request)
        assert plan == {"point": {"urls": [], "queries": []}}
        assert diagnostic["status"] == "not_requested"
        assert diagnostic["returned_points"] == diagnostic["missing_points"] == diagnostic["empty_url_points"] == 0
        assert diagnostic["points"][0]["url_state"] == "not_requested"
        plan, diagnostic = await llm.suggest_video_discovery_with_diagnostics([], request)
        assert plan == {}
        assert diagnostic["status"] == "not_requested"
        assert diagnostic["points"] == []
