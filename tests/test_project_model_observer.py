"""Offline-only HTTP transports verify the acceptance observer, never live evidence."""
import asyncio
import hashlib
import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.llm import complete_json, LLMCompletionTruncated, LLMResponseTooLarge
import backend.app.llm as llm_module
import backend.app.project_analysis as analysis_module
from scripts import serve_project_acceptance as runner


def settings():
    return Settings(llm_provider="openai_compatible", llm_base_url="https://model.example/v1",
                    llm_api_key="offline-credential-do-not-record", llm_model="offline-model")


def registry(path):
    return {"output": str(path), "acceptance_valid": True, "audit_errors": [], "jobs": {}}


def events(path):
    return [json.loads(line) for line in (path / "model-events.jsonl").read_text(encoding="utf-8").splitlines()]


def envelope(content='{"ok":true}', **values):
    return {"id": "offline-response-id", "model": "offline-model", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14,
                      "prompt_tokens_details": {"cached_tokens": 2}, "completion_tokens_details": {"reasoning_tokens": 1}}, **values}


@pytest.mark.asyncio
async def test_owned_hook_preserves_exact_request_and_timeout_and_logs_only_metadata(tmp_path):
    calls, options, state = [], [], registry(tmp_path)
    raw = envelope()
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=raw)
    def factory(**kwargs):
        options.append(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    observed = runner.observed_complete_json(tmp_path, state, complete_json, client_factory=factory)
    system = analysis_module.SYSTEM_PROMPT
    request_data = {"project": "PRIVATE STUDENT INPUT"}
    result = await observed(settings(), system, request_data, timeout_seconds=60, max_content_chars=120_000)
    assert result == {"ok": True} and len(calls) == 1
    assert json.loads(calls[0].content) == {"model": "offline-model", "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": json.dumps(request_data, ensure_ascii=False)}],
        "response_format": {"type": "json_object"}, "max_tokens": 6000}
    assert calls[0].headers["authorization"] == "Bearer " + settings().llm_api_key
    assert options[0]["timeout"].read == 60 and options[0]["timeout"].connect == 5
    assert options[0]["follow_redirects"] is False
    recorded = events(tmp_path)
    assert len(recorded) == 2 and recorded[0]["event_type"] == "model_call_started"
    event = recorded[1]
    assert event["call_id"] == recorded[0]["call_id"] and event["task"] == "project_analysis"
    assert event["system_prompt_sha256"] == hashlib.sha256(system.encode()).hexdigest()
    assert event["provider_response_id"] == "offline-response-id" and event["provider_model"] == "offline-model"
    assert event["finish_reason"] == "stop" and event["http_status"] == 200
    assert event["usage"]["completion_tokens_details"] == {"reasoning_tokens": 1}
    assert event["message_content_sha256"] == hashlib.sha256(b'{"ok":true}').hexdigest()
    assert event["started_at"] <= event["finished_at"] and event["elapsed_seconds"] >= 0
    assert event["outcome"] == "json_returned" and event["failure_type"] is None
    text = (tmp_path / "model-events.jsonl").read_text()
    for private in (settings().llm_api_key, "PRIVATE STUDENT INPUT", system, '"content":', '"headers":', '"Authorization":'):
        assert private not in text
    assert state["acceptance_valid"] is True and state["model_event_count"] == 2


@pytest.mark.asyncio
async def test_borrowed_client_not_closed_or_reconfigured_and_unsafe_metadata_removed(tmp_path):
    key, state = settings().llm_api_key, registry(tmp_path)
    body = envelope(id="provider-" + key, model="https://model.example/" + key,
                    usage={"prompt_tokens": True, "completion_tokens": 8, "total_tokens": -1,
                           "leak": key, "prompt_tokens_details": {"cached_tokens": 4, "private": key}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        observed = runner.observed_complete_json(tmp_path, state, complete_json)
        assert await observed(settings(), 'Return {"keywords" : []}', {"untrusted": "private"}, client) == {"ok": True}
        assert not client.is_closed
    event = events(tmp_path)[1]
    assert event["provider_response_id"] is None and event["provider_model"] is None
    assert event["task"] == "keyword_expansion"
    assert event["usage"] == {"completion_tokens": 8, "prompt_tokens_details": {"cached_tokens": 4}}
    assert key not in (tmp_path / "model-events.jsonl").read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content,error", [(401, "private-provider-error", httpx.HTTPStatusError),
                                                 (200, "private-malformed-json", json.JSONDecodeError)])
async def test_provider_failures_propagate_same_type_without_error_text(tmp_path, status, content, error):
    state = registry(tmp_path)
    def respond(request):
        return httpx.Response(status, json=envelope(content))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        observed = runner.observed_complete_json(tmp_path, state, complete_json)
        with pytest.raises(error):
            await observed(settings(), "private-system-instructions", {"data": "private-input"}, client)
    event = events(tmp_path)[1]
    assert event["http_status"] == status and event["failure_type"] == error.__name__ and event["outcome"] == "failed"
    assert event["response_body_sha256"] and state["acceptance_valid"] is True
    text = (tmp_path / "model-events.jsonl").read_text()
    assert content not in text and "private-input" not in text and "private-system-instructions" not in text


@pytest.mark.asyncio
async def test_length_finish_reason_and_timeout_are_observed_without_masking(tmp_path):
    state = registry(tmp_path)
    body = envelope()
    body["choices"][0]["finish_reason"] = "length"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        observed = runner.observed_complete_json(tmp_path, state, complete_json)
        with pytest.raises(LLMCompletionTruncated):
            await observed(settings(), "private prompt", {}, client)
    def timeout(request):
        raise httpx.ReadTimeout(settings().llm_api_key + " error body", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await observed(settings(), "private prompt", {}, client)
    finished = [event for event in events(tmp_path) if event["event_type"] == "model_call_finished"]
    assert finished[0]["finish_reason"] == "length" and finished[0]["failure_type"] == "LLMCompletionTruncated"
    assert finished[1]["failure_type"] == "ReadTimeout" and finished[1]["http_status"] is None
    assert settings().llm_api_key not in (tmp_path / "model-events.jsonl").read_text()


@pytest.mark.asyncio
async def test_model_log_failure_invalidates_audit_but_success_remains_success(tmp_path):
    (tmp_path / "model-events.jsonl").mkdir()
    state = registry(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope()))) as client:
        observed = runner.observed_complete_json(tmp_path, state, complete_json)
        assert await observed(settings(), "private prompt", {}, client) == {"ok": True}
    assert state["acceptance_valid"] is False
    assert len(state["audit_errors"]) == 2
    assert all(error["operation"] == "write_model_event" for error in state["audit_errors"])
    assert settings().llm_api_key not in (tmp_path / "audit-errors.jsonl").read_text()


@pytest.mark.asyncio
async def test_metadata_observation_failure_invalidates_audit_not_production_result(tmp_path, monkeypatch):
    def broken(*_):
        raise ValueError(settings().llm_api_key)
    monkeypatch.setattr(runner, "_response_metadata", broken)
    state = registry(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope()))) as client:
        observed = runner.observed_complete_json(tmp_path, state, complete_json)
        assert await observed(settings(), "private prompt", {}, client) == {"ok": True}
    assert state["acceptance_valid"] is False and events(tmp_path)[1]["metadata_observation_failed"] is True
    assert settings().llm_api_key not in (tmp_path / "audit-errors.jsonl").read_text()


@pytest.mark.asyncio
async def test_cancelled_call_records_completion_and_propagates_cancellation(tmp_path):
    entered = asyncio.Event()
    async def block(request):
        entered.set()
        await asyncio.Event().wait()
    state = registry(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(block)) as client:
        observed = runner.observed_complete_json(tmp_path, state, complete_json)
        task = asyncio.create_task(observed(settings(), "private prompt", {}, client))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert events(tmp_path)[1]["failure_type"] == "CancelledError"


def test_install_observes_both_call_sites_without_stacking(tmp_path, monkeypatch):
    from backend.app import analysis_review as review_module
    monkeypatch.setattr(llm_module, "complete_json", complete_json)
    monkeypatch.setattr(analysis_module, "complete_json", complete_json)
    monkeypatch.setattr(review_module, "complete_json", complete_json)
    state = registry(tmp_path)
    runner.install_model_observer(tmp_path, state)
    assert llm_module.complete_json is analysis_module.complete_json
    assert review_module.complete_json is analysis_module.complete_json
    runner.install_model_observer(tmp_path, state)
    assert llm_module.complete_json._unobserved_complete_json is complete_json


def test_non_json_response_hash_is_recorded_without_dumping_body():
    response = httpx.Response(502, text="private provider failure")
    metadata = runner._response_metadata(response, settings().llm_api_key)
    assert metadata["http_status"] == 502
    assert metadata["response_body_sha256"] == hashlib.sha256(response.content).hexdigest()
    assert "private provider failure" not in json.dumps(metadata)


@pytest.mark.asyncio
async def test_owned_response_hook_observes_status_even_when_body_times_out(tmp_path):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":'
            raise httpx.ReadTimeout("private provider error")
    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=BrokenStream())), **kwargs)
    state = registry(tmp_path)
    observed = runner.observed_complete_json(tmp_path, state, complete_json, client_factory=factory)
    with pytest.raises(httpx.ReadTimeout):
        await observed(settings(), "private prompt", {})
    event = events(tmp_path)[1]
    assert event["http_status"] == 200 and event["failure_type"] == "ReadTimeout"
    assert event["response_read_complete"] is False and event["response_body_sha256"] is None


@pytest.mark.asyncio
async def test_stream_observer_closes_oversize_response_without_saving_partial_body(tmp_path):
    class OversizedStream(httpx.AsyncByteStream):
        closed = False
        read_count = 0

        async def __aiter__(self):
            for _ in range(1000):
                self.read_count += 1
                yield b"private-output-" * 1200

        async def aclose(self):
            self.closed = True

    stream = OversizedStream()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        observed = runner.observed_complete_json(tmp_path, registry(tmp_path), complete_json)
        with pytest.raises(LLMResponseTooLarge):
            await observed(settings(), "private prompt", {}, client)
        assert not client.is_closed and stream.closed and stream.read_count < 20
    event = events(tmp_path)[1]
    assert event["http_status"] == 200 and event["failure_type"] == "LLMResponseTooLarge"
    assert not event["response_read_complete"] and event["response_body_sha256"] is None
    assert "private-output" not in (tmp_path / "model-events.jsonl").read_text()
