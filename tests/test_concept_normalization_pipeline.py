"""Two bounded model responses; drafts are never a fallback final result."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from backend.app import project_analysis as module
from backend.app.db import Store
from backend.app.llm import LLMCompletionTruncated
from backend.app.project_analysis import AnalysisError, ProjectAnalyzer
from backend.app.project_service import ProjectService
from tests.test_project_analysis import flat_analysis_fixture, request, settings, response


def replies(monkeypatch, items):
    calls = []

    async def complete(_settings, prompt, payload, *_args, **kwargs):
        calls.append({'prompt': prompt, 'payload': deepcopy(payload), **kwargs})
        item = items[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return deepcopy(item)

    monkeypatch.setattr(module, 'complete_json', complete)
    return calls


def draft_and_normalized():
    draft = flat_analysis_fixture()
    draft['knowledge_points'] = [
        {'name': '上传完整性校验', 'description': '比较哈希摘要检测上传前后的变化。'},
        {'name': '下载完整性校验', 'description': '比较哈希摘要检测下载前后的变化。'},
        {'name': '集合差集', 'description': '通过集合成员差异找出清单缺项。'},
    ]
    final = deepcopy(draft)
    final['knowledge_points'] = [
        {'name': '哈希校验', 'description': '学习用哈希摘要检测内容变化，用于上传和下载两处完整性核对。'},
        draft['knowledge_points'][2],
    ]
    return draft, final


@pytest.mark.asyncio
async def test_valid_draft_is_normalized_before_delivery_and_both_raw_responses_are_audited(monkeypatch):
    draft, final = draft_and_normalized()
    calls = replies(monkeypatch, [draft, final])
    audit, rejected = [], []
    result = await ProjectAnalyzer(settings()).analyze(
        request(), on_analysis_attempt=audit.append, on_rejected_attempt=rejected.append)
    assert len(calls) == 2 and rejected == []
    assert module.NORMALIZATION_PROMPT == calls[1]['prompt']
    assert module.NORMALIZATION_PROMPT not in calls[0]['prompt']
    assert calls[1]['payload']['normalization_required'] is True
    assert calls[1]['payload']['project'] == request().model_dump()
    assert [p['name'] for p in calls[1]['payload']['previous_analysis']['knowledge_points']] == [
        p['name'] for p in draft['knowledge_points']]
    assert [entry['outcome'] for entry in audit] == ['draft', 'accepted']
    assert [entry['phase'] for entry in audit] == ['generation', 'normalization']
    assert [entry['analysis'] for entry in audit] == [draft, final]
    assert [p.name for p in result.knowledge_points] == ['哈希校验', '集合差集']
    assert result.knowledge_points[0].description == final['knowledge_points'][0]['description']
    assert all(set(p) == {'id', 'name', 'description', 'technology', 'selection'}
               for p in result.model_dump()['knowledge_points'])
    # This tests routing and retention using synthetic responses, not LLM semantics.


@pytest.mark.asyncio
@pytest.mark.parametrize('bad,code', [({}, 'schema'), (httpx.ReadTimeout('private failed response'), 'timeout'),
                                   (LLMCompletionTruncated('private failed response'), 'output_truncated')])
async def test_second_stage_failure_never_delivers_the_first_draft_or_calls_a_third_time(monkeypatch, bad, code):
    draft, _ = draft_and_normalized()
    calls = replies(monkeypatch, [draft, bad])
    audit = []
    with pytest.raises(AnalysisError) as caught:
        await ProjectAnalyzer(settings()).analyze(request(), on_analysis_attempt=audit.append)
    assert caught.value.code == code and len(calls) == 2
    assert [entry['outcome'] for entry in audit] == ['draft', 'rejected']
    assert audit[0]['analysis'] == draft
    assert audit[1]['phase'] == 'normalization'
    assert 'private failed response' not in json.dumps(audit)


@pytest.mark.asyncio
async def test_structural_repair_and_normalization_share_the_second_call(monkeypatch):
    _, final = draft_and_normalized()
    calls = replies(monkeypatch, [{}, final])
    audit = []
    result = await ProjectAnalyzer(settings()).analyze(request(), on_analysis_attempt=audit.append)
    assert len(calls) == 2 and len(result.knowledge_points) == 2
    assert calls[1]['payload']['validation_feedback']
    assert calls[1]['payload']['normalization_required']
    assert module.NORMALIZATION_PROMPT in calls[1]['prompt']
    assert [entry['outcome'] for entry in audit] == ['rejected', 'accepted']


@pytest.mark.asyncio
async def test_second_stage_cannot_escape_remaining_shared_budget(monkeypatch):
    draft, _ = draft_and_normalized()
    timeouts = []

    async def complete(*_args, **kwargs):
        timeouts.append(kwargs['timeout_seconds'])
        if len(timeouts) == 1:
            await asyncio.sleep(.015)
            return draft
        await asyncio.sleep(5)

    monkeypatch.setattr(module, 'complete_json', complete)
    monkeypatch.setattr(module, 'ANALYSIS_TOTAL_TIMEOUT_SECONDS', .05)
    with pytest.raises(AnalysisError) as caught:
        await ProjectAnalyzer(settings()).analyze(request())
    assert caught.value.code == 'timeout'
    assert len(timeouts) == 2 and 0 < timeouts[1] < timeouts[0] <= .05


@pytest.mark.asyncio
async def test_cancel_during_normalization_keeps_private_draft_without_an_accepted_analysis(monkeypatch):
    draft, _ = draft_and_normalized()
    second_started = asyncio.Event()
    never_finish = asyncio.Event()
    count = 0

    async def complete(*_args, **_kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return draft
        second_started.set()
        await never_finish.wait()

    monkeypatch.setattr(module, 'complete_json', complete)
    configured = settings()
    store = Store(':memory:')
    service = ProjectService(configured, store, None, ProjectAnalyzer(configured))
    try:
        project_id = service.create(request())['project_id']
        service.analyze(project_id, 0)
        await asyncio.wait_for(second_started.wait(), 2)
        task = service.analysis_tasks[(project_id, 1)]
        data = service.db.version(project_id, 1)
        assert data['status'] == 'analyzing' and data['analysis'] is None
        assert data['analysis_attempts'][0]['analysis'] == draft
        assert data['analysis_attempts'][0]['outcome'] == 'draft'
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        service.db.recover_analysis()
        data = service.db.version(project_id, 1)
        assert data['analysis'] is None and data['status'] == 'analysis_failed'
        assert len(data['analysis_attempts']) == 1
        assert data['analysis_attempts'][0]['analysis'] == draft
    finally:
        await service.stop()
        store.close()


@pytest.mark.asyncio
async def test_normalization_secret_is_not_retained_in_either_audit(monkeypatch):
    draft, final = draft_and_normalized()
    secret = 'private-normalization-key'
    configured = replace(settings(), llm_api_key=secret)
    final['scope'] = secret
    calls = replies(monkeypatch, [draft, final])
    audit, rejected = [], []
    with pytest.raises(AnalysisError):
        await ProjectAnalyzer(configured).analyze(
            request(), on_analysis_attempt=audit.append, on_rejected_attempt=rejected.append)
    assert len(calls) == 2 and len(rejected) == 1
    assert audit[-1]['analysis'] is None and rejected[0]['analysis'] is None
    assert secret not in json.dumps(audit) + json.dumps(rejected)


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint,model,mode,effort,expected_thinking,expected_effort', [
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'auto', 'auto', {'type': 'enabled'}, 'high'),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'disabled', 'auto', {'type': 'disabled'}, None),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'enabled', 'high', {'type': 'enabled'}, 'high'),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'enabled', 'low', {'type': 'enabled'}, 'low'),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'provider_default', 'provider_default', None, None),
    ('https://gateway.example/v1', 'deepseek-flash', 'auto', 'auto', None, None),
    ('https://api.openai.com/v1', 'offline-other-model', 'auto', 'auto', None, None),
])
async def test_normalization_reasoning_is_provider_scoped_and_preserves_explicit_budget(
        endpoint, model, mode, effort, expected_thinking, expected_effort):
    configured = replace(settings(), llm_base_url=endpoint, llm_model=model,
                         llm_thinking_mode=mode, llm_reasoning_effort=effort, llm_max_output_tokens=2048,
                         project_analysis_normalization_max_output_tokens=4096)
    payloads = []

    def respond(req):
        payloads.append(json.loads(req.content))
        return response(flat_analysis_fixture())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await ProjectAnalyzer(configured, client).analyze(request())
    assert len(payloads) == 2
    assert payloads[1].get('thinking') == expected_thinking
    assert payloads[1].get('reasoning_effort') == expected_effort
    assert [payload['max_tokens'] for payload in payloads] == [2048, 4096]
    assert configured.llm_max_output_tokens == 2048
    assert configured.project_analysis_normalization_max_output_tokens == 4096
    assert configured.llm_thinking_mode == mode and configured.llm_reasoning_effort == effort
    if mode == 'enabled' and effort == 'low':
        assert [payload.get('reasoning_effort') for payload in payloads] == ['low', 'low']
    if endpoint == 'https://api.deepseek.com/v1' and mode == 'auto':
        assert payloads[0].get('thinking') == {'type': 'disabled'}
        assert 'reasoning_effort' not in payloads[0]
