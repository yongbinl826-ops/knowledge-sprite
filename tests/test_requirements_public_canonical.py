"""Retained real own metadata; no live source or fabricated evidence."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from backend.app.config import Settings
from backend.app.mobile_public import MobilePublicStore, public_course, public_source_snapshot, stamp
from backend.app.models import SearchRequest
from backend.app.video_availability import _bili_part_identity, _bound_page_video

PACKET=json.loads((Path(__file__).parent/'fixtures/requirements-public-canonical.json').read_text(encoding='utf-8'))


def test_real_tracking_alias_public_fact_uses_own_canonical_without_mutating_observation(tmp_path):
    resource,evidence=deepcopy(PACKET['resource']),deepcopy(PACKET['evidence'])
    original=deepcopy((resource,evidence)); observed=stamp(resource['fetched_at'])
    assert '?uid=' in resource['url']
    assert _bili_part_identity(resource['url']) == _bili_part_identity(resource['canonical_url'])
    assert _bound_page_video(resource,evidence)
    settings=Settings(mobile_public_database_path=str(tmp_path/'public.sqlite3'))
    public=MobilePublicStore(settings,clock=lambda:observed+60)
    try:
        assert public.observe(resource,evidence)
        item=public.browse()['items'][0]
        assert item['url']==resource['canonical_url'] and '?' not in item['url']
        assert item['observed_at']==resource['fetched_at']
        snapshot=public_source_snapshot(resource,evidence)
        assert snapshot['resource']['url']==snapshot['resource']['canonical_url']==item['url']
        assert {row['id'] for row in snapshot['evidence']}=={row['id'] for row in evidence}
        request=SearchRequest(knowledge_points=['Streamlit 图表展示'],preferred_platforms=['bilibili'])
        hits=public.lookup({'knowledge_point_id':'current','text':request.knowledge_points[0]},request)
        assert hits and public.is_current(hits[0]['resource']|{'public_library':hits[0]},hits[0]['evidence'])
        assert (resource,evidence)==original
    finally:
        public.close()


@pytest.mark.parametrize('change', ['other_bv','other_part','unknown_query','unsafe_raw','foreign_host','no_own_proof'])
def test_canonical_public_fact_cannot_borrow_foreign_or_unverified_raw_alias(change):
    resource,evidence=deepcopy(PACKET['resource']),deepcopy(PACKET['evidence'])
    if change=='other_bv':resource['canonical_url']=resource['canonical_url'].replace('BV19T411t71G','BV1q741157jG')
    elif change=='other_part':resource['url']+='&p=2'
    elif change=='unknown_query':resource['url']+='&unknown_scope=2'
    elif change=='unsafe_raw':resource['url']='http://127.0.0.1/video/BV19T411t71G/'
    elif change=='foreign_host':resource['url']=resource['url'].replace('www.bilibili.com','foreign.example.org')
    else:resource['field_provenance']['video_evidence_status']['evidence_id']='absent'
    assert public_course(resource,evidence,604800,stamp(resource['fetched_at'])+60) is None
    assert public_source_snapshot(resource,evidence) is None


@pytest.mark.parametrize('change', ['wrong_type_hash','unregistered_type_source','cross_url_type'])
def test_registered_explanatory_type_keeps_original_extractor_binding(change):
    import hashlib
    from backend.app.extractor import MetadataExtractor
    from scripts.validate_mobile_boundary import fixture_page
    # Explicit synthetic envelope, normal registered Bili extractor output.
    url='https://www.bilibili.com/video/BV1AAAAAAAAA/'
    raw=MetadataExtractor().extract(fixture_page(url),url,PACKET['resource']['fetched_at'])
    evidence=raw.pop('evidence');resource={**raw,'url':url,'canonical_url':url,'platform':'bilibili'}
    proof=resource['field_provenance']['resource_type']
    row=next(row for row in evidence if row['evidence_id']==proof['evidence_id'])
    assert row['text'] != resource['resource_type']  # Registered adapter's actual explanatory proof.
    if change=='wrong_type_hash':row['id']='ev_forged'
    elif change=='unregistered_type_source':
        row['source']=proof['source']='client'
        row['id']='ev_'+hashlib.sha256(f"{row['url']}|resource_type|client|{resource['resource_type']}".encode()).hexdigest()[:20]
    else:row['url']='https://www.bilibili.com/video/BV1q741157jG/'
    assert public_source_snapshot(resource,evidence) is None


def test_actual_long_own_description_is_preserved_only_when_full_original_evidence_exists():
    from backend.app.mobile_public import bound_fact
    from test_bilibili_description_binding import FIXTURE, extract, URL
    raw=extract(FIXTURE['resource']['description'])
    evidence=raw.pop('evidence')
    resource={**raw,'url':URL,'canonical_url':URL,'platform':'bilibili'}
    original=deepcopy((resource,evidence))
    assert len(resource['description'])==2496
    assert bound_fact(resource,evidence,'description')==resource['description']
    assert public_source_snapshot(resource,evidence)['resource']['description']==resource['description']
    # A historical 2000-character excerpt cannot be filled from Resource's tail.
    excerpt=deepcopy(evidence)
    row=next(row for row in excerpt if row.get('field')=='description')
    row['text']=row['text'][:2000]
    assert bound_fact(resource,excerpt,'description') is None
    assert 'description' not in public_source_snapshot(resource,excerpt)['resource']
    assert (resource,evidence)==original


def test_other_description_source_keeps_original_2000_excerpt_contract():
    from backend.app.extractor import MetadataExtractor
    from backend.app.mobile_public import bound_fact
    URL='https://www.bilibili.com/video/BV1AAAAAAAAA/'
    page='<title>Python course</title><meta property="og:type" content="video"><meta name="description" content="'+('x'*2496)+'">'
    raw=MetadataExtractor().extract(page,URL,'2026-10-18T23:00:00+00:00')
    evidence=raw.pop('evidence');resource={**raw,'url':URL,'canonical_url':URL,'platform':'bilibili'}
    row=next(row for row in evidence if row.get('field')=='description')
    assert len(row['text'])==2000
    assert bound_fact(resource,evidence,'description')==resource['description']
    row['text']=resource['description']
    assert bound_fact(resource,evidence,'description') is None
