"""Offline provider payloads and backend-only accounting; never paid requests."""
import json
from dataclasses import replace

import httpx
import pytest

from backend.app.llm import LLM_OBSERVER, _usage, complete_json
from backend.app.project_analysis import project_analysis_settings
from tests.test_project_analysis_provider_config import bailian, configured


@pytest.mark.asyncio
async def test_project_qwen_and_deepseek_keep_video_payload_and_credentials_unchanged():
    original = configured(project_analysis_thinking_mode="disabled")
    cases = [original, project_analysis_settings(original), project_analysis_settings(bailian())]
    requests, observations = [], []
    def respond(request):
        requests.append((str(request.url), request.headers['authorization'], json.loads(request.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'},
                                                     "finish_reason": "stop"}],
                                        "usage": {"completion_tokens": 12,
                                                  "completion_tokens_details": {"reasoning_tokens": 0}}})
    token = LLM_OBSERVER.set(observations.append)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for settings in cases:
                assert await complete_json(settings, "JSON", {}, client) == {"ok": True}
    finally:
        LLM_OBSERVER.reset(token)
    assert len(requests) == len(observations) == 3
    video, deepseek, qwen = [row[2] for row in requests]
    assert video['thinking'] == deepseek['thinking'] == {"type": "disabled"}
    assert 'enable_thinking' not in video and 'enable_thinking' not in deepseek
    assert qwen['enable_thinking'] is False
    assert 'thinking' not in qwen and 'reasoning_effort' not in qwen
    assert qwen['max_tokens'] == deepseek['max_tokens'] == 16000
    assert video['max_tokens'] == original.llm_max_output_tokens
    assert requests[0][1] == requests[1][1] == 'Bearer offline-global-key'
    assert requests[2][1] == 'Bearer offline-project-key'
    assert requests[2][0] == 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
    for row in observations:
        assert row['usage']['reasoning_tokens'] == 0 and row['usage']['answer_tokens'] == 12
        assert all(value >= 0 for value in row['transport_timing'].values())
    assert 'offline-project-key' not in json.dumps(observations)


@pytest.mark.parametrize('details,expected', [
    (None, (None, None)), ({'reasoning_tokens': 0}, (0, 20)),
    ({'reasoning_tokens': 5}, (5, 15)), ({'reasoning_tokens': True}, (None, None)),
    ({'reasoning_tokens': -1}, (None, None)), ({'reasoning_tokens': 21}, (21, None)),
])
def test_reasoning_accounting_preserves_unknown(details, expected):
    result = _usage({'usage': {'completion_tokens': 20, 'completion_tokens_details': details}})
    assert (result['reasoning_tokens'], result['answer_tokens']) == expected


@pytest.mark.asyncio
async def test_unknown_compatible_host_receives_no_inferred_qwen_extension():
    settings = replace(configured(), llm_base_url='https://example.test/v1', llm_model='qwen3.8-max')
    sent = []
    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await complete_json(settings, 'JSON', {}, client)
    assert 'enable_thinking' not in sent[0]
