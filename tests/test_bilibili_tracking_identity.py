"""Public retained identity plus boundary controls; no search/model/network."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.video_availability import _bili_part_identity, _bound_page_video

CASES = json.loads((Path(__file__).parent / 'fixtures/bilibili-multipart-tracking-v5.json').read_text(encoding='utf8'))['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda item: item['sql_resource_id'])
def test_actual_tracked_page_binds_its_own_metadata_without_mutation(case):
    original = deepcopy(case)
    assert _bound_page_video(case['resource'], case['evidence'])
    assert case == original


@pytest.mark.parametrize('query', ['uid=1', 'utm_source=share', 'vd_source=example', 'spm_id_from=1', 'uid=1&utm_medium=share'])
@pytest.mark.parametrize('location', ['url', 'canonical_url', 'resolved_url', 'proof', 'type'])
def test_known_tracking_on_any_identity_endpoint_keeps_own_binding(query, location):
    case = deepcopy(CASES[0]); resource, evidence = case['resource'], case['evidence']
    # Use the same native root, then vary one independently bound endpoint.
    resource['url'] = resource['canonical_url']
    if location in resource:
        resource[location] += '?' + query
    else:
        field = 'video_evidence_status' if location == 'proof' else 'resource_type'
        proof = resource['field_provenance'][field]
        row = next(item for item in evidence if item['evidence_id'] == proof['evidence_id'])
        proof['url'] += '?' + query
        row['url'] += '?' + query
    assert _bound_page_video(resource, evidence)


@pytest.mark.parametrize('suffix', ['?p=2', '?unknown=1', '?p=2&p=2', '?%70=2', '?p=%32', '?p=0', '#part'])
@pytest.mark.parametrize('location', ['url', 'canonical_url', 'resolved_url', 'proof', 'type'])
def test_tracking_does_not_hide_part_or_unknown_query_conflicts(suffix, location):
    case = deepcopy(CASES[0]); resource, evidence = case['resource'], case['evidence']
    resource['url'] = resource['canonical_url']
    if location in resource:
        resource[location] += suffix
    else:
        field = 'video_evidence_status' if location == 'proof' else 'resource_type'
        proof = resource['field_provenance'][field]
        row = next(item for item in evidence if item['evidence_id'] == proof['evidence_id'])
        proof['url'] += suffix
        row['url'] += suffix
    assert not _bound_page_video(resource, evidence)


@pytest.mark.parametrize('url', [
    'https://www.bilibili.com/video/BV1T5411e7N7/?p=7&uid=1',
    'https://www.bilibili.com/zh-Hans/video/BV1T5411e7N7/?utm_source=x&p=7',
])
def test_tracking_keeps_the_explicit_native_part(url):
    assert _bili_part_identity(url) == ('www.bilibili.com', 'BV1T5411e7N7', '7')


@pytest.mark.parametrize('replacement', [
    'https://www.bilibili.com/video/BV1KV411q7yw/?uid=1',
    'https://m.bilibili.com/video/BV1T5411e7N7/?uid=1',
    'https://evil.bilibili.com/video/BV1T5411e7N7/?uid=1',
])
def test_tracking_never_equates_other_video_or_host(replacement):
    case = deepcopy(CASES[0]); case['resource']['resolved_url'] = replacement
    assert not _bound_page_video(case['resource'], case['evidence'])
