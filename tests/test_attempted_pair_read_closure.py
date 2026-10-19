"""Service integration: local invalid pairs cannot revive via GET fallback."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from backend.app import teaching_match, teaching_review
from test_learning_support_service import setup, accept_batch


@pytest.mark.parametrize('outcome', ['failure', 'cancel', 'partial'])
def test_attempted_pairs_stay_unknown_while_independent_valid_pairs_are_reviewed(outcome):
    service, job, resources, _ = setup(resources_count=2)
    point = job['knowledge_points'][0]
    # Both exact phrases would be independently eligible for literal fallback
    # if no attempted-decision marker were retained.
    for rid, resource in resources.items():
        service.store.add_evidence(job['job_id'], rid, point['knowledge_point_id'], {
            'evidence_id':'search-'+rid, 'kind':'search', 'knowledge_point_id':point['knowledge_point_id'],
            'title':resource['title'], 'snippet':resource['description'], 'url':resource['url'], 'source':'offline'})
    assert len(service.results(job['job_id'])['groups'][0]['partial_items']) == 2
    accepted_ids = set()
    async def judge(settings, pairs):
        # Even a concurrent GET after the intent is persisted sees no claims.
        assert not service.results(job['job_id'])['groups'][0]['partial_items']
        if outcome == 'cancel':
            raise asyncio.CancelledError
        if outcome == 'failure':
            return {}
        valid = pairs[:1]
        accepted_ids.update(pair['_binding']['resource_id'] for pair in valid)
        return await accept_batch(settings, valid)
    async def review(settings, claims):
        return {claim['claim_id']:True for claim in claims}
    with patch.object(teaching_match,'judge_batch',AsyncMock(side_effect=judge)) as judged, patch.object(teaching_review,'review_batch',AsyncMock(side_effect=review)) as reviewed:
        if outcome == 'cancel':
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(service._match_learning_skills(job,resources))
        else:
            asyncio.run(service._match_learning_skills(job,resources))
        before = service.store.connection.total_changes
        cards = service.results(job['job_id'])['groups'][0]['partial_items']
        assert {card['resource']['resource_id'] for card in cards} == accepted_ids
        assert service.store.connection.total_changes == before
        assert judged.await_count == 1 and reviewed.await_count == (1 if outcome == 'partial' else 0)
    cached = service.store.connection.execute('SELECT COUNT(*) FROM cache').fetchone()[0]
    assert cached == (1 if outcome == 'partial' else 0)
    if outcome == 'partial':
        assert job['progress']['teaching_pair_validation_failures'] == 1
        assert job['upstream_partial'] is True
        assert any('绑定校验' in value for value in job['warnings'])
