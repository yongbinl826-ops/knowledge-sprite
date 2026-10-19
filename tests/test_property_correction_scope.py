"""Canonical-import drop-in tests for the one-function proposal."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.models import SearchRequest
from backend.app.ranking import (
    _confirmed_target_non_teaching, rank_resource, topic_observations,
)

FIXTURE = Path(__file__).parent / 'fixtures/add-event-listener-own-source.json'


def observation(text, body='', field_ids=None):
    return {'title':text,'body':body,'evidence_ids':['own-title'],
            'field_evidence_ids':field_ids if field_ids is not None else {'title':['own-title'],'body':['own-body']}}


def test_actual_retained_property_correction_does_not_mean_not_taught():
    f = json.loads(FIXTURE.read_text(encoding='utf-8'))
    own = topic_observations(f['point'], f['resource'], f['evidence'])
    assert own and not _confirmed_target_non_teaching('JavaScript addEventListener','JavaScript',own)


@pytest.mark.parametrize('target,text', [
    ('JavaScript addEventListener','JavaScript addEventListener不是window对象，介绍监听器的应用场景'),
    ('JavaScript AbortController','JavaScript AbortController不是Promise，讲解控制器的用法'),
    ('JavaScript querySelector','JavaScript querySelector不是数组，返回匹配的单个元素'),
    ('Python asyncio.Task','Python asyncio.Task不是线程，展示协程任务的使用'),
    ('Python dict.get','Python dict.get不是下标表达式，演示访问映射的用法'),
    ('JavaScript fetch','JavaScript fetch is not XMLHttpRequest; learn the fetch API'),
])
def test_unseen_api_property_corrections_do_not_veto_teaching(target,text):
    assert not _confirmed_target_non_teaching(target,target.split()[0],[observation(text)])


@pytest.mark.parametrize('text', [
    '本课不教 addEventListener',
    '本课不包含 addEventListener',
    'addEventListener 不是本课内容',
    '本课不是 addEventListener 教程',
    '这里不是教 addEventListener 的地方',
    'addEventListener 不是我们将要讲解的内容',
    'addEventListener 仅作为先修知识',
    '先修 addEventListener，本课处理其他内容',
    'TODO addEventListener implementation',
    'Next lesson: addEventListener',
    'This lesson does not teach addEventListener',
    "We don't cover addEventListener",
    'API list: addEventListener',
    'addEventListener不是window对象，本课不教addEventListener',
    'addEventListener不是window对象，addEventListener只作先修',
])
def test_real_teaching_exclusion_prerequisite_or_future_stays_vetoed(text):
    assert _confirmed_target_non_teaching('JavaScript addEventListener','JavaScript',[observation(text)])


def test_unrelated_topic_negation_does_not_veto_known_target():
    assert not _confirmed_target_non_teaching('JavaScript AbortController','JavaScript',[
        observation('JavaScript AbortController 使用详解','本课不教 querySelector')])


def test_unbound_field_is_not_used_and_source_text_is_immutable():
    own = observation('JavaScript addEventListener不是window对象','本课不教 addEventListener',{'title':['own-title']})
    before = deepcopy(own)
    assert not _confirmed_target_non_teaching('JavaScript addEventListener','JavaScript',[own])
    assert own == before


def test_actual_full_rank_only_api_core_changes_and_original_click_state_parameters_stay_unknown():
    f = json.loads(FIXTURE.read_text(encoding='utf-8'))
    result = rank_resource(f['point'],f['resource'],f['evidence'],SearchRequest.model_validate(f['request']))
    assert result and result['topic_evidence_status'] == 'partial'
    cores = [r for r in result['subtopic_coverage'] if r.get('status') == 'supported' and 'addEventListener' in r['text']]
    assert cores
    original = [r for r in result['subtopic_coverage'] if r['id'].startswith('learning_target_')]
    assert original and all(r['status']=='unknown' for r in original)


@pytest.mark.parametrize('text', ['本课不教 addEventListener','本课只展示最终效果，不包含任何代码教学'])
def test_whole_or_target_teaching_veto_still_wins_full_rank(text):
    f = json.loads(FIXTURE.read_text(encoding='utf-8'))
    r, ev = deepcopy(f['resource']), deepcopy(f['evidence'])
    r['title'] = r['description'] = text
    for row in ev:
        if row.get('field') in {'title','description'}:
            row['text'] = text
    result = rank_resource(f['point'],r,ev,SearchRequest.model_validate(f['request']))
    assert not result or not any(row['status']=='supported' for row in result.get('subtopic_coverage',[]))
