"""Offline result integration: discovery pointers cannot inflate teaching claims."""
from unittest.mock import AsyncMock, patch
from copy import deepcopy
from types import SimpleNamespace

from backend.app import teaching_match, teaching_review
from test_learning_support_service import setup


def link(service, job, resource, point):
    service.store.add_evidence(job['job_id'], resource['resource_id'], point['knowledge_point_id'], {
        'evidence_id': 'search-' + resource['resource_id'] + '-' + point['knowledge_point_id'],
        'kind': 'search', 'knowledge_point_id': point['knowledge_point_id'],
        'title': resource['title'], 'snippet': resource['description'],
        'url': resource['url'], 'source': 'offline'})


def pointer(pair):
    return {'knowledge_point_id': pair['_binding']['point_id'],
            'resource_id': pair['_binding']['resource_id'], 'skill_id': 'skill_1',
            'skill': pair['skills'][0]['text'], 'evidence_id': 'catalog-fixture',
            'quote': 'bounded queues', 'basis': 'catalog', 'source_text_sha256': '0' * 64,
            'source_url': 'https://lessons.example/course',
            'target_url': pair['_binding']['canonical'],
            'scope': 'topic_declared', 'missing_components': ['unproved method']}


def reject_rank(*args, **kwargs):
    return None


def test_related_pointers_are_capped_separate_and_get_is_read_only():
    service, job, resources, _ = setup(resources_count=6)
    point = job['knowledge_points'][0]
    for resource in resources.values():
        link(service, job, resource, point)
    model = AsyncMock(side_effect=AssertionError('GET must not call a model'))
    with patch.object(teaching_match, 'topic_pointers', side_effect=lambda pair: [pointer(pair)], create=True), \
            patch('backend.app.service.rank_resource', reject_rank), \
            patch.object(teaching_match, 'judge_batch', model), \
            patch.object(teaching_review, 'review_batch', model):
        before = service.store.connection.total_changes
        first = service.results(job['job_id'])
        second = service.results(job['job_id'])
        assert first == second
        assert service.store.connection.total_changes == before
        model.assert_not_called()
    group = first['groups'][0]
    assert len(group['related_topic_pointers']) == 4
    assert group['total_matches'] == group['total_partial_matches'] == group['total_review_matches'] == 0
    assert group['items'] == group['partial_items'] == group['review_items'] == []
    assert group['platform_items'] == group['partial_platform_items'] == group['review_platform_items'] == {}
    assert all(not row['content_resource_ids'] and not row['title_resource_ids'] for row in group['learning_coverage']['skills'])


def test_other_point_or_unbound_resource_cannot_enter_pointer_pool():
    service, job, resources, _ = setup(count=2, resources_count=1)
    first_point, second_point = job['knowledge_points']
    resource = next(iter(resources.values()))
    link(service, job, resource, first_point)
    with patch.object(teaching_match, 'topic_pointers', side_effect=lambda pair: [pointer(pair)], create=True), \
            patch('backend.app.service.rank_resource', reject_rank):
        groups = service.results(job['job_id'])['groups']
    assert len(groups[0]['related_topic_pointers']) == 1
    assert groups[1]['related_topic_pointers'] == []
    assert groups[0]['related_topic_pointers'][0]['pointer']['knowledge_point_id'] == first_point['knowledge_point_id']
    assert first_point['knowledge_point_id'] != second_point['knowledge_point_id']


def test_already_recommended_resource_is_not_duplicated_as_an_unproved_pointer():
    service, job, resources, _ = setup()
    point = job['knowledge_points'][0]
    resource = next(iter(resources.values()))
    link(service, job, resource, point)
    with patch.object(teaching_match, 'topic_pointers', side_effect=AssertionError('Already matched'), create=True):
        group = service.results(job['job_id'])['groups'][0]
    assert group['partial_items']
    assert group['related_topic_pointers'] == []


def test_historical_owner_mismatch_hides_related_pointers_too():
    from backend.app.project_service import ProjectService
    point = {'id': 'k1', 'name': 'Streamlit 图表', 'technology': 'Streamlit',
             'concepts': ['图表'], 'learning_skills': ['Streamlit 条形图'], 'selection': 'learn'}
    batch = {'project_knowledge_point_ids': ['k1'], 'job_id': 'job', 'batch_id': 'batch',
             'mappings': [{'project_knowledge_point_id': 'k1', 'knowledge_point_id': 'p1'}],
             'status': 'partial', 'job_status': 'completed'}
    view = {'version': {'analysis': {'knowledge_points': [point]}, 'batches': [batch], 'warnings': []}}
    group = {'knowledge_point_id': 'p1', 'text': 'pandas 图表',
             'related_topic_pointers': [{'pointer': {'scope': 'topic_declared'}}]}
    before = deepcopy((view, group))
    service = ProjectService.__new__(ProjectService)
    service.view = lambda *args, **kwargs: deepcopy(view)
    service.jobs = SimpleNamespace(results=lambda *args: {'groups': [group]})
    observed = service.results('project')['points'][0]
    assert observed['status'] == 'scope_mismatch'
    assert observed['result']['related_topic_pointers'] == []
    assert (view, group) == before
