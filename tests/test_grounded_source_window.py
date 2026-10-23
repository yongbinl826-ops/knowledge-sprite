"""Source ordering stays within the existing window; no model/network calls."""
from copy import deepcopy
import json

import pytest

from backend.app import grounded_related as grounded
from backend.app.models import SearchRequest
from test_bilibili_multipart_identity import DATA, case, field_rows


def long_catalog(topic, technology, target_title):
    p,r,e,_=case()
    p.update(text=topic,technology=technology)
    r['title']=technology+' course'
    _,title=field_rows(r,e,'title'); title['text']=r['title']
    r['description']=technology+' training lessons'
    _,description=field_rows(r,e,'description'); description['text']=r['description']
    e=[row for row in e if row.get('kind')!='catalog']
    r['chapters']=[]
    url=r['url']
    for i,name in enumerate([f'Orientation {i}' for i in range(30)]+[target_title]):
        eid=f'chapter-{i}'
        chapter={'title':name,'url':url+f'?p={i+1}','source_url':url,
                 'start_seconds':None,'end_seconds':None,'duration_seconds':100,'page_number':i+1}
        source='html.bilibili.__INITIAL_STATE__.videoData.pages'
        r['chapters'].append({**chapter,'source':source,'evidence_id':eid})
        e.append({'evidence_id':eid,'kind':'catalog','field':f'chapters.{i}',
                  'url':url,'source':source,'text':json.dumps(chapter,ensure_ascii=False),
                  'fetched_at':r['fetched_at']})
    request=SearchRequest(knowledge_points=[topic],topic_technologies={topic:technology})
    return p,r,e,request


def assert_same_limits(pair):
    assert grounded.MAX_SOURCES==20
    assert len(pair['sources'])<=20
    assert sum(len(segment) for s in pair['sources'] for segment in s['segments'])<=5000


def test_retained_late_set_difference_chapter_enters_default_window():
    p,r,e,request=case('set_difference')
    before=deepcopy((p,r,e))
    target=r['chapters'][DATA['set_difference']['target_chapter_index']]
    pair=grounded.prepare_pair(p,r,e,request)
    assert target['evidence_id'] in {s['evidence_id'] for s in pair['sources']}
    observed=next(s for s in pair['sources'] if s['evidence_id']==target['evidence_id'])
    assert observed['_projected']==target['title']
    assert observed['_raw']==next(row['text'] for row in e if row['evidence_id']==target['evidence_id'])
    assert_same_limits(pair)
    assert before==(p,r,e)


@pytest.mark.parametrize('topic,technology,title',[
    ('参数化提示词模板','Python','Prompt templates'),
    ('参数化提示词模板','Python','ChatPromptTemplate'),
    ('CSV 文件读取与导入','pandas','Loading a CSV file'),
    ('集合差集比对','Python','集合的交集、并集和差集运算'),
])
def test_late_related_mechanism_with_changed_wording_is_prioritized(topic,technology,title):
    args=long_catalog(topic,technology,title)
    pair=grounded.prepare_pair(*args)
    assert pair
    sources={s['evidence_id']:s for s in pair['sources']}
    assert sources['chapter-30']['_projected']==title
    assert_same_limits(pair)


@pytest.mark.parametrize('title',[
    'JavaScript Prompt templates',
    'Prompt templates are not covered',
    'Prompt templates are never taught',
])
def test_high_priority_words_do_not_bypass_technology_or_negative_evidence(title):
    args=long_catalog('参数化提示词模板','Python',title)
    pair=grounded.prepare_pair(*args)
    assert pair
    assert 'chapter-30' not in {s['evidence_id'] for s in pair['sources']}
    assert_same_limits(pair)


def test_field_validation_cannot_supply_cross_field_mechanism_after_ranking():
    args=long_catalog('跨字段业务规则校验','Pydantic','Pydantic Field constraints and field validation')
    pair=grounded.prepare_pair(*args)
    assert pair is None or 'chapter-30' not in {s['evidence_id'] for s in pair['sources']}


def test_explicit_source_id_order_is_not_reranked_during_rebind():
    args=long_catalog('参数化提示词模板','Python','ChatPromptTemplate')
    ids=['chapter-10','chapter-30','chapter-3']
    pair=grounded.prepare_pair(*args,source_ids=ids)
    assert [s['evidence_id'] for s in pair['sources']]==ids
    again=grounded.prepare_pair(*args,source_ids=ids)
    assert pair['fingerprint']==again['fingerprint']
