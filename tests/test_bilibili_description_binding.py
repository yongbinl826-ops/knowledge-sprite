"""Retained value replay uses a reconstructed native envelope, not a new HTTP call."""
import copy
import hashlib
import html as html_escape
import json
from pathlib import Path

import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.models import Resource
from backend.app.source_adapters.bilibili import (
    BILIBILI_DESCRIPTION_LIMIT, BILIBILI_DESCRIPTION_SOURCE,
    BILIBILI_DESCRIPTION_STATUS_SOURCE,
)
from backend.app.teaching_match import prepare_pair, validate_decision, _valid_quote

FIXTURE=json.loads(Path(__file__).with_name('fixtures').joinpath('bilibili-own-long-description.json').read_text(encoding='utf-8'))
URL=FIXTURE['resource']['canonical_url']


def envelope(description, *, bvid='BV14T2cB8EXT', og=None):
    state={'videoData':{'bvid':bvid,'title':FIXTURE['resource']['title'],'desc':description,
                       'pages':[{'page':1,'part':FIXTURE['resource']['title'],'duration':100}]}}
    meta='' if og is None else '<meta name="description" content="'+html_escape.escape(og,quote=True)+'">'
    return '<html><head>'+meta+'</head><body><script>window.__INITIAL_STATE__='+json.dumps(state,ensure_ascii=True)+';</script></body></html>'


def extract(description, **kwargs):
    return MetadataExtractor().extract(envelope(description,**kwargs),URL,'2026-10-18T23:00:00+00:00')


def resource_metadata(metadata):
    r=copy.deepcopy(FIXTURE['resource'])
    r.update({k:v for k,v in metadata.items() if k not in {'evidence'}})
    return Resource.model_validate(r).model_dump(), metadata['evidence']


def test_retained_2496_description_and_evidence_now_fully_equal():
    original=copy.deepcopy(FIXTURE)
    text=FIXTURE['resource']['description']
    assert len(text)==2496
    metadata=extract(text)
    origin=metadata['field_provenance']['description']
    row=next(e for e in metadata['evidence'] if e['evidence_id']==origin['evidence_id'])
    assert origin['source']==BILIBILI_DESCRIPTION_SOURCE
    assert metadata['description']==row['text']==text
    assert hashlib.sha256(row['text'].encode()).hexdigest()==hashlib.sha256(text.encode()).hexdigest()
    r,ev=resource_metadata(metadata)
    pair=prepare_pair(FIXTURE['point'],r,ev,'advanced')
    assert pair and any(o['basis']=='description' and 'pd.to_datetime' in o['text'] and 'print(df.info())' in o['text'] for o in pair['observations'])
    assert FIXTURE==original


def test_actual_own_column_parse_and_type_check_quote_is_structurally_bound():
    metadata=extract(FIXTURE['resource']['description']);r,ev=resource_metadata(metadata)
    p=FIXTURE['point'];pair=prepare_pair(p,r,ev,'advanced')
    quote='df[&#39;datetime&#39;] = pd.to_datetime(df[&#39;date&#39;]) print(df) print(df.info())'
    obs=next(o for o in pair['observations'] if o['basis']=='description')
    proposal={'fingerprint':pair['fingerprint'],'supports':[{'skill_id':'skill_1','skill':p['learning_skills'][0],
        'evidence_id':obs['evidence_id'],'quote':quote,'basis':'description','source_text_sha256':obs['source_text_sha256']}]}
    assert _valid_quote(obs, pair['_records'][obs['evidence_id']], p['learning_skills'][0],
                        quote, pair['_scope_records'][obs['evidence_id']])
    checked=validate_decision(p,r,ev,proposal,'advanced')
    assert checked and checked['fingerprint']==pair['fingerprint']
    # The new conservative compound-method gate may keep the semantically valid
    # API example unknown. The binding repair remains true independently of
    # that recorded recall limitation (covered in test_necessary_skill_components).
    # This probe makes no review/model call and cannot fill missing-row masks.
    assert not any(s['skill_id']=='skill_2' for s in checked['supports'])


def test_old_mismatched_cache_stays_unknown_and_immutable():
    frozen=copy.deepcopy(FIXTURE)
    pair=prepare_pair(FIXTURE['point'],FIXTURE['resource'],FIXTURE['evidence'],'advanced')
    assert pair and not any(o['basis']=='description' for o in pair['observations'])
    assert FIXTURE==frozen


@pytest.mark.parametrize('count',[1,1999,2000,2001,3999,4000])
def test_entire_own_description_is_kept_through_existing_4000_limit(count):
    text='字'*count
    m=extract(text)
    assert m['description']==text
    row=next(e for e in m['evidence'] if e.get('field')=='description')
    assert row['text']==text and len(row['text'])==count


@pytest.mark.parametrize('text',['x'*4001,'字'*4001,'😀'*4001,'x'*4000+' This lesson does not teach datetime conversion.'], ids=['ascii-over','cjk-over','astral-over','trailing-negative-over'])
def test_over_limit_is_omitted_with_explicit_notice_and_no_meta_prefix_fallback(text):
    m=extract(text,og=text[:4000])
    assert 'description' not in m
    assert m['description_extraction_status']=='limit_exceeded'
    assert m['access_notice']
    assert not any(e.get('field')=='description' for e in m['evidence'])
    diagnostic=next(e for e in m['evidence'] if e.get('field')=='description_extraction_status')
    assert diagnostic['source']==BILIBILI_DESCRIPTION_STATUS_SOURCE
    assert 'normalized_characters=' in diagnostic['text'] and len(diagnostic['text'])<250
    r,ev=resource_metadata(m);r.pop('description',None) # no prior cached field may be donated in the probe
    assert not any(o['basis']=='description' for o in prepare_pair(FIXTURE['point'],r,ev,'advanced')['observations'])


def test_invalid_unicode_is_omitted_without_crashing_or_leaking_invalid_text():
    m=extract('Own description \ud800')
    assert 'description' not in m
    assert m['description_extraction_status']=='invalid_encoding'
    json.dumps(m,ensure_ascii=False).encode('utf-8')


def test_wrong_bv_cannot_borrow_native_description_or_limit_marker():
    m=extract('x'*4001,bvid='BV1pE4m1R7JE')
    assert not any(e.get('source') in {BILIBILI_DESCRIPTION_SOURCE,BILIBILI_DESCRIPTION_STATUS_SOURCE} for e in m['evidence'])


def test_other_source_description_evidence_rule_is_not_expanded():
    text='q'*2496
    doc='<script type="application/ld+json">'+json.dumps({'@type':'VideoObject','name':'Other course','description':text})+'</script>'
    m=MetadataExtractor().extract(doc,'https://example.org/course/','2026-10-18T23:00:00+00:00')
    row=next(e for e in m['evidence'] if e.get('field')=='description')
    assert row['source']=='jsonld.description' and len(row['text'])==2000


@pytest.mark.parametrize('mutation',['prefix','wrong_source','wrong_url','duplicate_evidence'])
def test_full_equality_and_source_binding_not_relaxed(mutation):
    m=extract(FIXTURE['resource']['description']);r,ev=resource_metadata(m)
    row=next(e for e in ev if e.get('field')=='description')
    if mutation=='prefix':row['text']=row['text'][:2000]
    elif mutation=='wrong_source':row['source']='search'
    elif mutation=='wrong_url':row['url']='https://www.bilibili.com/video/BV1pE4m1R7JE/'
    else:ev.append(copy.deepcopy(row))
    p=prepare_pair(FIXTURE['point'],r,ev,'advanced')
    assert p is None or not any(o['basis']=='description' for o in p['observations'])


def test_hard_utf8_bound_is_unchanged_for_full_four_byte_characters():
    m=extract('😀'*BILIBILI_DESCRIPTION_LIMIT)
    assert len(m['description'].encode('utf-8'))==16000
