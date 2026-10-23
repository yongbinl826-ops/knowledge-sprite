"""Retained own-page records and synthetic negative controls; no model/network.

Synthetic sealed decisions below test rebind integrity, not video relevance.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app import grounded_related as grounded
from backend.app.models import SearchRequest
from backend.app.video_availability import _bound_page_video

DATA = json.loads((Path(__file__).parent / 'fixtures/multip_identity/retained.json').read_text(encoding='utf-8'))['cases']
MULTIP = 'html.bilibili.video_pod.multip'


def case(name='pydantic'):
    c = deepcopy(DATA[name])
    return c['point'], c['resource'], c['evidence'], SearchRequest.model_validate(c['request'])


def field_rows(r, e, field):
    proof = r['field_provenance'][field]
    return proof, next(row for row in e if row.get('evidence_id') == proof['evidence_id'])


@pytest.fixture(autouse=True)
def forbid_model_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('This is an offline provenance test')
    monkeypatch.setattr(grounded, 'complete_json', forbidden)
    import socket
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def sealed_catalog(pair, expected_title):
    source = next(s for s in pair['sources'] if s['_projected'] == expected_title)
    value = {'pair_id':pair['pair_id'],'fingerprint':pair['fingerprint'],
        'support':{'evidence_id':source['evidence_id'],'source_text_sha256':source['source_text_sha256'],
                   'basis':'catalog','quote':expected_title}}
    assert grounded.validate_support(pair, value)
    value.update(version=grounded.VERSION, source_ids=[s['evidence_id'] for s in pair['sources']])
    return {**value,'review_seal':grounded._hash(value)}


@pytest.mark.parametrize('name', ['pydantic','set_difference'])
def test_retained_multipart_identity_reaches_exact_own_chapter_and_rebinds(name):
    p, r, e, request = case(name)
    before = deepcopy((p,r,e))
    assert _bound_page_video(r,e)
    chapter = r['chapters'][DATA[name]['target_chapter_index']]
    assert grounded.prepare_pair(p,r,e,request) is not None
    # A long catalog has an independent source-window budget. Select the actual
    # retained source explicitly here to test its identity/binding, not recall.
    pair = grounded.prepare_pair(p,r,e,request,source_ids=[chapter['evidence_id']])
    assert pair is not None
    source = next(s for s in pair['sources'] if s['evidence_id'] == chapter['evidence_id'])
    assert source['_projected'] == chapter['title']
    assert source['_target'] == chapter['url']
    assert pair['core']['canonical'] == r['field_provenance']['video_evidence_status']['url']
    # Prepared URL view can use an observed slash spelling; stored URLs stay raw.
    again = grounded.prepare_pair(p,r,e,request,source_ids=[s['evidence_id'] for s in pair['sources']])
    assert again['fingerprint'] == pair['fingerprint']
    value = sealed_catalog(pair, chapter['title'])
    projected = grounded.project_reference(p,r,e,request,value)
    assert projected['resource']['url'] == chapter['url']
    assert projected['reference']['exact_teaching_verified'] is False
    assert projected['reference']['source_quote'] == chapter['title']
    assert before == (p,r,e)


@pytest.mark.parametrize('type_source',['meta.og:type','jsonld.@type',MULTIP])
def test_multipart_requires_an_independently_bound_video_type(type_source):
    _,r,e,_=case()
    proof,row=field_rows(r,e,'resource_type')
    proof['source']=row['source']=type_source
    row['text']='video' if type_source != MULTIP else 'Observed native multipart video selector'
    assert _bound_page_video(r,e)


@pytest.mark.parametrize('mutation',[
    'only-ogtype','proof-search-kind','proof-search-source','proof-wrong-field','proof-wrong-id',
    'proof-blank','proof-foreign-host','proof-other-bv','proof-other-part','proof-unknown-query',
    'type-search-kind','type-search-source','type-wrong-field','type-wrong-id','type-blank',
    'type-other-part','type-unknown-query','type-value','no-type','search-status','search-level','not-fetched',
    'canonical-conflict','raw-unknown-query','canonical-unknown-query','malformed-type-proof',
])
def test_multipart_does_not_upgrade_unbound_or_search_labels(mutation):
    p,r,e,request=case()
    proof,row=field_rows(r,e,'video_evidence_status')
    tp,tr=field_rows(r,e,'resource_type')
    if mutation=='only-ogtype':
        r['field_provenance'].pop('video_evidence_status'); e.remove(row)
    elif mutation=='proof-search-kind': row['kind']='search'
    elif mutation=='proof-search-source': proof['source']=row['source']='search_template'
    elif mutation=='proof-wrong-field': row['field']='title'
    elif mutation=='proof-wrong-id': row['evidence_id']='unbound-video-proof'
    elif mutation=='proof-blank': row['text']=' '
    elif mutation=='proof-foreign-host': row['url']=row['url'].replace('www.bilibili.com','foreign.example.org')
    elif mutation=='proof-other-bv': row['url']=row['url'].replace('BV18hFAeJEcQ','BV1xx411c7Df')
    elif mutation=='proof-other-part': row['url']+='?p=2'
    elif mutation=='proof-unknown-query': row['url']+='?unknown_source=another-page'
    elif mutation=='type-search-kind': tr['kind']='search'
    elif mutation=='type-search-source': tp['source']=tr['source']='search_template'
    elif mutation=='type-wrong-field': tr['field']='title'
    elif mutation=='type-wrong-id': tr['evidence_id']='unbound-type-proof'
    elif mutation=='type-blank': tr['text']=' '
    elif mutation=='type-other-part': tr['url']+='?p=2'
    elif mutation=='type-unknown-query': tr['url']+='?unknown_source=another-page'
    elif mutation=='type-value': tr['text']='article'
    elif mutation=='no-type': r['resource_type']='unknown'
    elif mutation=='search-status': r['video_evidence_status']='search_discovered'
    elif mutation=='search-level': r['metadata_evidence_level']='search'
    elif mutation=='not-fetched': r['fetch_status']='not_fetched'
    elif mutation=='canonical-conflict': r['canonical_url']+='?p=2'
    elif mutation=='raw-unknown-query': r['url']+='?unknown_source=unexpected'
    elif mutation=='canonical-unknown-query': r['canonical_url']+='?unknown_source=unexpected'
    elif mutation=='malformed-type-proof': r['field_provenance']['resource_type']='invalid'
    assert not _bound_page_video(r,e)
    assert grounded.prepare_pair(p,r,e,request) is None


@pytest.mark.parametrize('replacement',[
    'https://foreign.example.org/video/', 'https://evil.bilibili.com/video/',
    'https://www.bilibili.com.evil.example.org/video/','http://www.bilibili.com/video/',
    'https://www.bilibili.com/list/',
])
def test_fully_consistent_forged_multipart_on_another_host_or_route_fails(replacement):
    p,r,e,request=case()
    r,e=json.loads(json.dumps([r,e]).replace('https://www.bilibili.com/video/',replacement))
    assert not _bound_page_video(r,e)
    assert grounded.prepare_pair(p,r,e,request) is None


@pytest.mark.parametrize('resolved',[
    'https://www.bilibili.com/video/BV1VL411f7a3/?p=1',
    'https://www.bilibili.com/video/BV1xx411c7Df/',
    'https://m.bilibili.com/video/BV1VL411f7a3/',
    'https://foreign.example.org/video/BV1VL411f7a3/',
    'https://www.bilibili.com/video/BV1VL411f7a3/?p=2&p=2',
    'https://www.bilibili.com/video/BV1VL411f7a3/?unknown_source=unexpected',
    'https://www.bilibili.com/video/BV1VL411f7a3/?unknown_uid=1',
    'https://www.bilibili.com/video/BV1VL411f7a3/?%70=2',
    'https://www.bilibili.com/video/BV1VL411f7a3?unknown_source=unexpected',
    'https://www.bilibili.com/video/BV1VL411f7a3?unknown_uid=1',
])
def test_observed_page_alias_does_not_allow_another_resolved_identity(resolved):
    p,r,e,request=case('set_difference')
    r['resolved_url']=resolved
    assert grounded.prepare_pair(p,r,e,request) is None


@pytest.mark.parametrize('mutation',['identity-text','identity-source','identity-id','source-text','source-id','source-kind','source-part','seal','fingerprint'])
def test_old_synthetic_seal_cannot_survive_changed_identity_or_source(mutation):
    p,r,e,request=case('set_difference')
    chapter=r['chapters'][DATA['set_difference']['target_chapter_index']]
    pair=grounded.prepare_pair(p,r,e,request,source_ids=[chapter['evidence_id']])
    sealed=sealed_catalog(pair,chapter['title'])
    source=next(row for row in e if row['evidence_id']==chapter['evidence_id'])
    proof,row=field_rows(r,e,'video_evidence_status')
    if mutation=='identity-text': row['text']+=' changed proof'
    elif mutation=='identity-source': proof['source']=row['source']='jsonld.VideoObject'
    elif mutation=='identity-id': proof['evidence_id']=row['evidence_id']='new-video-proof'
    elif mutation=='source-text': source['text']+=' '
    elif mutation=='source-id': chapter['evidence_id']=source['evidence_id']='new-chapter'
    elif mutation=='source-kind': source['kind']='search'
    elif mutation=='source-part': source['url']+='?p=2'
    elif mutation=='seal': sealed['review_seal']='0'*64
    elif mutation=='fingerprint':
        sealed['fingerprint']='0'*64
        sealed['review_seal']=grounded._hash({k:v for k,v in sealed.items() if k!='review_seal'})
    assert grounded.project_reference(p,r,e,request,sealed) is None


@pytest.mark.parametrize('source',['jsonld.VideoObject','html.bilibili.__INITIAL_STATE__.videoData.bvid'])
def test_existing_video_proof_kinds_keep_their_original_behavior(source):
    p,r,e,request=case()
    proof,row=field_rows(r,e,'video_evidence_status')
    proof['source']=row['source']=source
    # These existing proof kinds do not depend on the new selector/type branch.
    r['field_provenance'].pop('resource_type')
    assert _bound_page_video(r,e)
    assert grounded.prepare_pair(p,r,e,request)
