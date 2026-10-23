"""Service persistence of bounded model diagnostics through the real LLM adapter.

Only the completion HTTP boundary is mocked. No live model/search requests run.
"""
import json

import httpx
import pytest

from backend.app.ai_video_service import run_ai_video_fallback
from backend.app.config import Settings
from backend.app.llm import OpenAICompatibleLLM
from test_ai_grounded_recovery import recovery_service
from test_ai_retained_recovery import URL, retain, setup_retained


POINTS = ("表单输入", "文件下载")


def response_client(body, calls):
    def respond(request):
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(body, ensure_ascii=False),
        }}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


async def execute_batch(service, body, points=POINTS, *, prepare=None):
    job, state = setup_retained(service, points)
    if prepare:
        prepare(service, job, state)
    calls = []
    async with response_client(body, calls) as client:
        service.llm = OpenAICompatibleLLM(Settings(llm_api_key="offline-model-key"), client)
        await run_ai_video_fallback(service, job, state)
        # Re-entry must not issue another completion for this batch.
        await run_ai_video_fallback(service, job, state)
    persisted = service.store.get_job(job["job_id"])
    assert len(calls) == 1
    assert persisted["ai_video_fallback"]["model_calls"] == 1
    sent = json.loads(calls[0]["messages"][1]["content"])
    assert [row["knowledge_point"] for row in sent["points"]] == list(points)
    # Diagnostic details are retained in the backend job, not result cards.
    assert "model_output" not in json.dumps(service.results(job["job_id"]))
    return persisted, calls


async def test_persisted_model_output_distinguishes_empty_arrays_from_filtered_urls(recovery_service):
    service, searches, _ = recovery_service()
    body = {"suggestions": [
        {"point_id": "kp_0", "urls": [], "queries": ["Streamlit form"]},
        {"point_id": "kp_1", "urls": ["  ",
            "https://search.bilibili.com/all?keyword=private-query",
            "https://unapproved.invalid/private-response"], "queries": ["Streamlit download button"]},
    ]}
    job, _ = await execute_batch(service, body)
    diagnostic = job["ai_video_fallback"]
    assert not searches
    assert diagnostic["candidate_count"] == 0
    assert diagnostic["model_output"] == {
        "schema_version": 1, "status": "normalized", "requested_points": 2,
        "returned_points": 2, "missing_points": 0, "empty_url_points": 1,
        "input_urls": 3, "accepted_urls": 0,
        "rejected_urls": {"empty": 1, "invalid": 2, "duplicate": 0, "already_seen": 0},
        "query_normalization": {
            "schema_version": 1, "status": "normalized", "requested_points": 2,
            "returned_query_fields": 2, "missing_points": 0, "missing_query_fields": 0,
            "empty_query_points": 0, "input_queries": 2, "accepted_queries": 2,
            "rejected_queries": {"empty": 0, "invalid": 0, "duplicate": 0},
            "points": [
                {"point_index": index, "query_state": "accepted", "input_queries": 1,
                 "accepted_queries": 1, "rejected_queries": {"empty": 0, "invalid": 0, "duplicate": 0}}
                for index in range(2)],
        },
        "points": [
            {"point_index": 0, "returned": True, "url_state": "empty", "input_urls": 0,
             "accepted_urls": 0,
             "rejected_urls": {"empty": 0, "invalid": 0, "duplicate": 0, "already_seen": 0}},
            {"point_index": 1, "returned": True, "url_state": "filtered", "input_urls": 3,
             "accepted_urls": 0,
             "rejected_urls": {"empty": 1, "invalid": 2, "duplicate": 0, "already_seen": 0}},
        ],
    }
    saved = json.dumps(job, ensure_ascii=False)
    assert "private-query" not in saved
    assert "private-response" not in saved
    assert "offline-model-key" not in saved


async def test_missing_model_point_is_not_reported_as_an_empty_array(recovery_service):
    service, _, _ = recovery_service()
    job, _ = await execute_batch(service, {"suggestions": [{"point_id": "kp_0", "urls": []}]})
    output = job["ai_video_fallback"]["model_output"]
    assert output["returned_points"] == output["missing_points"] == output["empty_url_points"] == 1
    assert output["points"][0]["url_state"] == "empty"
    assert output["points"][1]["url_state"] == "missing"
    assert output["points"][1]["returned"] is False


async def test_seen_aliases_are_counted_without_refetching_or_claiming_empty_output(recovery_service):
    service, searches, _ = recovery_service()

    def existing(service, job, state):
        rid = retain(service, job, state, URL)
        state["started"].add(rid)

    job, calls = await execute_batch(service, {"suggestions": [{"point_id": "kp_0", "urls": [
        URL, URL.replace("www.", "").rstrip("/"), "https://unapproved.invalid/private-value"]}]},
        points=(POINTS[0],), prepare=existing)
    output = job["ai_video_fallback"]["model_output"]
    assert output["input_urls"] == 3 and output["accepted_urls"] == 0
    assert output["empty_url_points"] == 0
    assert output["rejected_urls"] == {"empty": 0, "invalid": 1, "duplicate": 0, "already_seen": 2}
    assert output["points"][0]["url_state"] == "filtered"
    assert not service.fetcher.calls and not searches
    assert URL in json.loads(calls[0]["messages"][1]["content"])["excluded_urls"]
    assert "private-value" not in json.dumps(job)


async def test_duplicate_accepted_url_is_counted_once_and_fetched_once(recovery_service):
    service, searches, _ = recovery_service(pages={})
    job, _ = await execute_batch(service, {"suggestions": [{"point_id": "kp_0", "urls": [
        URL, URL.replace("www.", "").rstrip("/")]}]}, points=(POINTS[0],))
    output = job["ai_video_fallback"]["model_output"]
    assert output["input_urls"] == 2 and output["accepted_urls"] == 1
    assert output["rejected_urls"] == {"empty": 0, "invalid": 0, "duplicate": 1, "already_seen": 0}
    assert job["ai_video_fallback"]["candidate_count"] == 1
    assert [row["url"] for row in service.fetcher.calls] == [URL]
    assert not searches


@pytest.mark.parametrize(("body", "error_type"), [
    ({"suggestions": [{"point_id": "kp_0", "urls": [{"private": "private-model-response"}]}]}, "ValidationError"),
    ({"suggestions": [{"point_id": "kp_0", "urls": [], "extra": "private-model-response"}]}, "ValidationError"),
    ({"suggestions": [{"point_id": "private-model-response", "urls": []}]}, "ValidationError"),
    ({"suggestions": [{"point_id": "kp_4", "urls": []}]}, "ValueError"),
])
async def test_bad_model_schema_records_error_without_fabricating_raw_zero_counts(recovery_service, body, error_type):
    service, searches, _ = recovery_service()
    job, _ = await execute_batch(service, body)
    diagnostic = job["ai_video_fallback"]
    assert diagnostic["error_type"] == error_type
    assert "model_output" not in diagnostic
    assert "input_urls" not in diagnostic
    assert not searches and not service.fetcher.calls
    assert "private-model-response" not in json.dumps(job)


async def test_separate_batches_keep_independent_one_call_diagnostics(recovery_service):
    service, _, _ = recovery_service()
    first, first_calls = await execute_batch(service, {"suggestions": [{"point_id": "kp_0", "urls": []}]})
    # A distinct request creates a separate batch; identical active requests
    # intentionally reuse their existing job and must not call the model again.
    second, second_calls = await execute_batch(service, {"suggestions": [
        {"point_id": "kp_0", "urls": [" "]}]}, points=(POINTS[0],))
    assert first["job_id"] != second["job_id"]
    assert len(first_calls) == len(second_calls) == 1
    first_output = service.store.get_job(first["job_id"])["ai_video_fallback"]["model_output"]
    second_output = service.store.get_job(second["job_id"])["ai_video_fallback"]["model_output"]
    assert first_output["missing_points"] == 1 and first_output["input_urls"] == 0
    assert second_output["missing_points"] == 0 and second_output["input_urls"] == 1
