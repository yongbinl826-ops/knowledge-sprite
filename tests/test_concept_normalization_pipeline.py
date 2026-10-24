"""Deliver a valid first response; repair only rejected output within two calls."""
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
        {'name': 'Python', 'description': '比较哈希摘要检测上传前后的变化。'},
        {'name': '集合差集', 'description': '通过集合成员差异找出清单缺项。'},
    ]
    final = deepcopy(draft)
    final['knowledge_points'] = [
        {'name': '哈希校验', 'description': '学习用哈希摘要检测内容变化，用于上传和下载两处完整性核对。'},
        draft['knowledge_points'][1],
    ]
    return draft, final


@pytest.mark.asyncio
async def test_valid_first_response_is_delivered_without_a_second_call(monkeypatch):
    _, valid = draft_and_normalized()
    calls = replies(monkeypatch, [valid])
    audit, rejected = [], []
    result = await ProjectAnalyzer(settings()).analyze(
        request(), on_analysis_attempt=audit.append, on_rejected_attempt=rejected.append)
    assert len(calls) == 1 and rejected == []
    assert [(entry['phase'], entry['outcome']) for entry in audit] == [('generation', 'accepted')]
    assert audit[0]['analysis'] == valid
    assert [point.name for point in result.knowledge_points] == ['哈希校验', '集合差集']


@pytest.mark.asyncio
async def test_invalid_first_response_is_repaired_and_both_raw_responses_are_audited(monkeypatch):
    draft, final = draft_and_normalized()
    calls = replies(monkeypatch, [draft, final])
    audit, rejected = [], []
    result = await ProjectAnalyzer(settings()).analyze(
        request(), on_analysis_attempt=audit.append, on_rejected_attempt=rejected.append)
    assert len(calls) == 2 and len(rejected) == 1
    assert module.NORMALIZATION_PROMPT == calls[1]['prompt']
    assert module.NORMALIZATION_PROMPT not in calls[0]['prompt']
    assert calls[1]['payload']['repair_required'] is True
    assert calls[1]['payload']['validation_feedback'][0]['code'] == 'broad_subject'
    assert calls[1]['payload']['project'] == request().model_dump()
    assert [p['name'] for p in calls[1]['payload']['previous_analysis']['knowledge_points']] == [
        p['name'] for p in draft['knowledge_points']]
    assert [entry['outcome'] for entry in audit] == ['rejected', 'accepted']
    assert [entry['phase'] for entry in audit] == ['generation', 'repair']
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
    assert [entry['outcome'] for entry in audit] == ['rejected', 'rejected']
    assert audit[0]['analysis'] == draft
    assert audit[1]['phase'] == 'repair'
    assert 'private failed response' not in json.dumps(audit)


@pytest.mark.asyncio
async def test_structural_repair_uses_only_the_second_call(monkeypatch):
    _, final = draft_and_normalized()
    calls = replies(monkeypatch, [{}, final])
    audit = []
    result = await ProjectAnalyzer(settings()).analyze(request(), on_analysis_attempt=audit.append)
    assert len(calls) == 2 and len(result.knowledge_points) == 2
    assert calls[1]['payload']['validation_feedback']
    assert calls[1]['payload']['repair_required']
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
async def test_cancel_during_repair_keeps_rejected_draft_without_an_accepted_analysis(monkeypatch):
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
        assert data['analysis_attempts'][0]['outcome'] == 'rejected'
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
async def test_repair_secret_is_not_retained_in_either_audit(monkeypatch):
    draft, final = draft_and_normalized()
    secret = 'private-normalization-key'
    configured = replace(settings(), llm_api_key=secret)
    final['scope'] = secret
    calls = replies(monkeypatch, [draft, final])
    audit, rejected = [], []
    with pytest.raises(AnalysisError):
        await ProjectAnalyzer(configured).analyze(
            request(), on_analysis_attempt=audit.append, on_rejected_attempt=rejected.append)
    assert len(calls) == 2 and len(rejected) == 2
    assert audit[-1]['analysis'] is None and rejected[-1]['analysis'] is None
    assert secret not in json.dumps(audit) + json.dumps(rejected)


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint,model,mode,effort,expected_thinking,expected_effort', [
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'auto', 'auto', {'type': 'disabled'}, None),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'disabled', 'auto', {'type': 'disabled'}, None),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'enabled', 'high', {'type': 'enabled'}, 'high'),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'enabled', 'low', {'type': 'enabled'}, 'low'),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'provider_default', 'provider_default', None, None),
    ('https://gateway.example/v1', 'deepseek-flash', 'auto', 'auto', None, None),
    ('https://api.openai.com/v1', 'offline-other-model', 'auto', 'auto', None, None),
])
async def test_repair_preserves_explicit_reasoning_settings_without_forcing_high(
        endpoint, model, mode, effort, expected_thinking, expected_effort):
    configured = replace(settings(), llm_base_url=endpoint, llm_model=model,
                         llm_thinking_mode=mode, llm_reasoning_effort=effort, llm_max_output_tokens=2048,
                         project_analysis_normalization_max_output_tokens=4096)
    payloads = []

    def respond(req):
        payloads.append(json.loads(req.content))
        return response({} if len(payloads) == 1 else flat_analysis_fixture())

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


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_name,code,repaired_names', [
    ('基于时间增量的运动', 'textbook_descriptive_name', ['数值积分']),
    ('基于时间步长的运动更新', 'textbook_descriptive_name', ['数值积分']),
    ('矩形区域表示与坐标约束', 'textbook_representation_constraint_bundle', ['笛卡尔坐标系', '区间限幅']),
    ('文本渲染与分数显示', 'textbook_mechanism_application_bundle', ['文本渲染']),
])
async def test_descriptive_titles_trigger_only_one_targeted_repair_and_retain_foundations(
        monkeypatch, bad_name, code, repaired_names):
    # This checks routing, retention and diagnostics using synthetic model
    # answers. It does not claim the model always selects a canonical term.
    draft = flat_analysis_fixture()
    foundations = [
        {'name': '变量', 'description': '命名存储与赋值，用于保存当前数值。', 'technology': 'Python'},
        {'name': '循环', 'description': '按条件重复执行语句，用于持续处理交互。', 'technology': 'Python'},
        {'name': '条件分支', 'description': '根据布尔条件选择执行路径，用于不同输入的处理。', 'technology': 'Python'},
    ]
    draft['knowledge_points'] = foundations + [
        {'name': bad_name, 'description': '保持必要的计算、坐标和边界用途。', 'technology': ''}]
    final = deepcopy(draft)
    final['knowledge_points'] = deepcopy(foundations) + [
        {'name': name, 'description': '保持必要的计算、坐标和边界用途。'}
        for name in repaired_names]
    calls = replies(monkeypatch, [draft, final])
    audit = []
    result = await ProjectAnalyzer(settings()).analyze(request(), on_analysis_attempt=audit.append)
    assert len(calls) == 2
    assert [(entry['phase'], entry['outcome']) for entry in audit] == [
        ('generation', 'rejected'), ('repair', 'accepted')]
    feedback = calls[1]['payload']['validation_feedback']
    assert any(item['code'] == code and item['location'] == ['knowledge_points', 3, 'name']
               for item in feedback)
    assert calls[1]['payload']['previous_analysis'] == draft
    assert calls[1]['payload']['project'] == request().model_dump()
    assert [point.name for point in result.knowledge_points] == ['变量', '循环', '条件分支'] + repaired_names
    assert [point.description for point in result.knowledge_points[:3]] == [
        point['description'] for point in foundations]


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_name,code', [
    ('基于时间增量的运动', 'textbook_descriptive_name'),
    ('基于时间步长的运动更新', 'textbook_descriptive_name'),
    ('矩形区域表示与坐标约束', 'textbook_representation_constraint_bundle'),
    ('矩形表示与矩形碰撞检测', 'textbook_mechanism_application_bundle'),
])
async def test_unrepaired_descriptive_title_is_not_displayed_and_never_gets_a_third_call(
        monkeypatch, bad_name, code):
    draft = flat_analysis_fixture()
    draft['knowledge_points'] = [{'name': bad_name, 'description': '保留原始用途。'}]
    calls = replies(monkeypatch, [draft, draft])
    audit = []
    with pytest.raises(AnalysisError) as caught:
        await ProjectAnalyzer(settings()).analyze(request(), on_analysis_attempt=audit.append)
    assert caught.value.code == 'quality' and len(calls) == 2
    assert [entry['outcome'] for entry in audit] == ['rejected', 'rejected']
    assert any(item.get('code') == code for item in caught.value.diagnostics)


@pytest.mark.asyncio
async def test_valid_canonical_names_allow_project_action_details_and_still_return_first_draft(monkeypatch):
    valid = flat_analysis_fixture()
    valid['knowledge_points'] = [
        {'name': '变量', 'description': '理解命名存储和赋值，用于保存与重置当前运行数据。'},
        {'name': '数值积分', 'description': '用离散步长近似累积连续变化，在本项目中实现基于时间增量的运动。'},
        {'name': '笛卡尔坐标系', 'description': '用坐标刻画位置，解释矩形区域表示与坐标约束涉及的坐标含义。'},
    ]
    calls = replies(monkeypatch, [valid])
    result = await ProjectAnalyzer(settings()).analyze(request())
    assert len(calls) == 1
    assert [point.name for point in result.knowledge_points] == ['变量', '数值积分', '笛卡尔坐标系']
    assert [point.description for point in result.knowledge_points] == [
        point['description'] for point in valid['knowledge_points']]


@pytest.mark.asyncio
async def test_domain_state_reset_recipe_repairs_without_deleting_the_required_restart(monkeypatch):
    draft = flat_analysis_fixture()
    description = '重置是把一组相关对象与计数恢复到确定的初始值，使新一局从一致起点开始。'
    draft['knowledge_points'] = [
        {'name': '变量', 'description': '理解命名存储与赋值，用于保存当前运行数据。'},
        {'name': '游戏状态重置', 'description': description},
    ]
    final = deepcopy(draft)
    final['knowledge_points'] = [
        {'name': '变量与赋值', 'description': '理解命名存储与赋值，用于保存当前运行数据。重开时将这些变量恢复到初始值，开始新一局。'},
    ]
    calls = replies(monkeypatch, [draft, final])
    result = await ProjectAnalyzer(settings()).analyze(request())
    assert len(calls) == 2
    assert calls[1]['payload']['validation_feedback'][0]['code'] == 'textbook_operation_label'
    assert calls[1]['payload']['previous_analysis']['knowledge_points'][1]['description'] == description
    assert result.knowledge_points[0].name == '变量与赋值'
    assert '重开' in result.knowledge_points[0].description
