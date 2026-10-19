"""Offline protocol/safety checks, not semantic accuracy claims."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app import teaching_match as match
from backend.app import teaching_review as review
from test_teaching_match import lesson, point, support, verdict, settings
assert Path(match.__file__).resolve().is_relative_to(ROOT)


def fixture():
    p = point(); r, e = lesson(); pair = match.prepare_pair(p, r, e)
    decisions = {pair['pair_id']: verdict(pair)}
    claims, mapping = review.prepare_claims([pair], decisions)
    assert len(claims) == 1
    return p, r, e, pair, decisions, claims, mapping


def test_only_known_own_source_quote_context_is_sent_without_private_binding():
    _, _, _, pair, _, claims, mapping = fixture()
    encoded = json.dumps(claims)
    assert all(key not in encoded for key in ['https://', '_binding', '_records', 'canonical', 'project_task'])
    assert claims[0]['quote'] in claims[0]['own_source_context']
    assert mapping[claims[0]['claim_id']]['pair_id'] == pair['pair_id']


def test_invalid_or_target_vetoed_claim_is_not_presented_to_model():
    _, _, _, pair, decisions, _, _ = fixture()
    broken = deepcopy(decisions)
    broken[pair['pair_id']]['supports'][0]['quote'] = 'invented render operation'
    assert review.prepare_claims([pair], broken) == ([], {})


@pytest.mark.parametrize('verdict_value', [False, None])
def test_rejected_or_omitted_claim_is_saved_as_reviewed_unknown(verdict_value):
    p, r, e, pair, decisions, claims, mapping = fixture()
    report = {} if verdict_value is None else {claims[0]['claim_id']: verdict_value}
    sealed = review.reviewed_decisions([pair], decisions, mapping, report)[pair['pair_id']]
    assert review.validate_reviewed(p, r, e, sealed)['supports'] == []


def test_positive_seal_and_every_read_binding_are_required():
    p, r, e, pair, decisions, claims, mapping = fixture()
    saved = review.reviewed_decisions([pair], decisions, mapping, {claims[0]['claim_id']: True})[pair['pair_id']]
    assert review.validate_reviewed(p, r, e, saved) == decisions[pair['pair_id']]
    assert review.validate_reviewed(p, r, e, decisions[pair['pair_id']]) is None
    changed = deepcopy(saved); changed['supports'][0]['skill'] += ' and UI rendering'
    assert review.validate_reviewed(p, r, e, changed) is None
    r = {**r, 'resource_id': 'other-own-resource'}
    assert review.validate_reviewed(p, r, e, saved) is None


def test_unknown_review_ids_cannot_add_or_change_claims():
    _, _, _, pair, decisions, _, mapping = fixture()
    saved = review.reviewed_decisions([pair], decisions, mapping, {'claim_'+'0'*24: True})[pair['pair_id']]
    assert not saved['supports']


@pytest.mark.parametrize('mode', ['accept', 'reject', 'empty', 'unknown', 'duplicate', 'extra', 'wrong-bool', 'http-error', 'bad-json'])
def test_real_http_contract_is_mocked_and_strict(mode):
    _, _, _, _, _, claims, _ = fixture()
    calls = []
    async def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload['max_tokens'] == 1500
        assert payload['response_format'] == {'type': 'json_object'}
        body = {'decisions': [{'claim_id': claims[0]['claim_id'], 'accepted': mode != 'reject'}]}
        if mode == 'empty': body = {'decisions': []}
        if mode == 'unknown': body['decisions'][0]['claim_id'] = 'claim_'+'0'*24
        if mode == 'duplicate': body['decisions'] *= 2
        if mode == 'extra': body['decisions'][0]['explanation'] = 'invented details'
        if mode == 'wrong-bool': body['decisions'][0]['accepted'] = 'true'
        if mode == 'http-error': return httpx.Response(503)
        content = 'bad JSON' if mode == 'bad-json' else json.dumps(body)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await review.review_batch(settings(), claims, client)
    value = asyncio.run(run())
    assert len(calls) == 1
    assert value == ({claims[0]['claim_id']: mode == 'accept'} if mode in {'accept', 'reject'} else {} if mode == 'empty' else None)


@pytest.mark.parametrize('damage', ['url', 'secret', 'over-size', 'too-many', 'unconfigured'])
def test_invalid_payload_cannot_reach_transport(damage):
    _, _, _, _, _, claims, _ = fixture()
    config = settings()
    if damage == 'url': claims[0]['own_source_context'] += ' https://example.com/private'
    if damage == 'secret': claims[0]['own_source_context'] += config.llm_api_key
    if damage == 'over-size': claims[0]['own_source_context'] = 'a' * 40_001
    if damage == 'too-many': claims *= 41
    if damage == 'unconfigured': config = replace(config, llm_provider='none')
    async def fail(request): raise AssertionError('Unexpected network call')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            return await review.review_batch(config, claims, client)
    assert asyncio.run(run()) is None


def test_cancellation_propagates_without_retry(monkeypatch):
    _, _, _, _, _, claims, _ = fixture()
    async def cancel(*args, **kwargs): raise asyncio.CancelledError()
    monkeypatch.setattr(review, 'complete_json', cancel)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(review.review_batch(settings(), claims))
