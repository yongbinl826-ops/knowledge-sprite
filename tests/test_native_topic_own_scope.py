"""Retained public metadata and clearly synthetic hostile-search boundaries."""
from copy import deepcopy
from pathlib import Path
import json
import pytest

from backend.app.ranking import (assess_topic_evidence, compound_english_match,
    _json_stringify_serialization, topic_observations)

FIXTURE=json.loads((Path(__file__).parent/'fixtures/native_topic_scope/retained.json').read_text('utf8'))
JS='localStorage 读写与 JSON 序列化'
AR='按键消抖状态检测'

def resource(bvid):return deepcopy(FIXTURE['resources'][bvid])
def point(text):return {'knowledge_point_id':'original-literal-point','text':text}
def add_search(r,title,snippet):
    r['evidence'].append({'evidence_id':'synthetic-search','kind':'search','source':'synthetic-adversarial-test',
        'url':r['url'],'title':title,'snippet':snippet,'knowledge_point_id':'original-literal-point'})
def replace_title(r,text):
    r['title']=text
    eid=r['field_provenance']['title']['evidence_id']
    next(e for e in r['evidence'] if e['evidence_id']==eid)['text']=text

def test_real_json_catalog_gives_only_serialization_partial_without_search_or_read_write():
    r=resource('BV183411B7nJ');add_search(r,'localStorage JSON读写完整教程','读写、序列化、完整项目全部实现')
    original=deepcopy(r);a=assess_topic_evidence(point(JS),r,r['evidence'])
    assert a['topic_evidence_status']=='partial'
    assert [(x['text'],x['status']) for x in a['subtopic_coverage']]==[('读写','unknown'),('JSON 序列化','supported')]
    assert a['supporting_evidence_ids']==[r['chapters'][0]['evidence_id']]
    assert r==original

def test_real_key_title_is_limited_own_topic_support_without_search_tail():
    r=resource('BV1cJ411h7kU');add_search(r,'Arduino按键教程','外课的小电视电脑副屏状态监控')
    a=assess_topic_evidence(point(AR),r,r['evidence']);assert a['topic_evidence_status']=='supported'
    assert 'synthetic-search' not in a['supporting_evidence_ids']
    assert r['field_provenance']['title']['evidence_id'] in a['supporting_evidence_ids']
    assert all(next(e for e in r['evidence'] if e['evidence_id']==eid)['kind'] in {'page','catalog'} for eid in a['supporting_evidence_ids'])
    assert not any(x in a['topic_evidence_reasons'][0]['message'] for x in ['millis','非阻塞','稳定时间窗'])

@pytest.mark.parametrize('title',['Arduino数字输入教程','按键消抖','松手检测','按键消抖。另一课松手检测',
    '按键消抖，相关视频：松手检测','先修知识：按键消抖与松手检测','不讲按键消抖与松手检测'])
def test_search_cannot_rescue_missing_own_compound_topic(title):
    r=resource('BV1cJ411h7kU');replace_title(r,title)
    add_search(r,AR,'按键消抖状态检测完整教学；外课状态监控')
    assert assess_topic_evidence(point(AR),r,r['evidence']) is None

@pytest.mark.parametrize('damage',['title-id','title-text','title-source','all-own-urls','video-proof-id'])
def test_broken_own_binding_is_never_repaired_with_search(damage):
    r=resource('BV1cJ411h7kU');add_search(r,AR,AR)
    if damage=='title-id':r['field_provenance']['title']['evidence_id']='missing'
    elif damage=='title-text':r['title']=AR
    elif damage=='title-source':r['field_provenance']['title']['source']='forged-source'
    elif damage=='video-proof-id':r['field_provenance']['video_evidence_status']['evidence_id']='missing'
    else:
        for e in r['evidence']:
            if e['kind']!='search':e['url']='https://www.bilibili.com/video/BV1111111111/'
    assert assess_topic_evidence(point(AR),r,r['evidence']) is None

def test_discovery_search_remains_search_and_is_not_mutated_into_own_evidence():
    r={'url':'https://www.bilibili.com/video/BV1111111111','title':'','field_provenance':{},
       'fetch_status':'not_fetched','metadata_evidence_level':'search','evidence':[]}
    add_search(r,AR,'按键消抖状态检测教程');before=deepcopy(r)
    observations=topic_observations(point(AR),r,r['evidence'])
    assert observations and observations[0]['evidence_ids']==['synthetic-search']
    assert r==before and r['evidence'][0]['kind']=='search'

@pytest.mark.parametrize('body',['localStorage JSON.stringify','localStorage JSON.stringify()用法',
    'localStorage存储、JSON.parse、JSON.stringify'])
def test_exact_standard_json_stringify_can_support_serialization_part(body):
    assert _json_stringify_serialization('JSON 序列化',body,whole_topic=JS)

@pytest.mark.parametrize('body',['localStorage JSON.parse','localStorage stringify','localStorage JSON.Stringify',
    'localStorage Other.JSON.stringify','localStorage JSON.stringifyOther','localStorage Java JSON.stringify',
    'localStorage 不讲JSON.stringify','localStorage 先修知识JSON.stringify','localStorage API列表 JSON.stringify',
    'localStorage 后续会讲JSON.stringify','localStorage 参考文档JSON.stringify',
    'localStorage https://example.org/JSON.stringify','localStorage。相关视频：JSON.stringify'])
def test_json_mapping_never_borrows_other_operation_namespace_url_or_non_teaching(body):
    assert not _json_stringify_serialization('JSON 序列化',body,whole_topic=JS)

@pytest.mark.parametrize('body',['按键消抖 松手检测','按钮去抖 释放检测','按键消抖 按下状态判断'])
def test_state_detection_equivalence_needs_same_clause_debounce_and_specific_button_state(body):
    assert compound_english_match(AR,[body])

@pytest.mark.parametrize('body',['按键消抖；松手检测','按键消抖 外课状态监控','松手检测',
    '按键状态检测','按键消抖 只做边沿检测','按键消抖 参考资料：释放检测'])
def test_state_equivalence_does_not_add_debounce_or_unobserved_state(body):
    assert not compound_english_match(AR,[body])

def test_json_mapping_does_not_invent_unknown_owner_or_storage_io():
    assert not _json_stringify_serialization('JSON 序列化','QuillFlow JSON.stringify',whole_topic='QuillFlow 读写与 JSON 序列化')
    assert not _json_stringify_serialization('读写','localStorage JSON.stringify',whole_topic=JS)


@pytest.mark.parametrize('origin_url',[None,'https://www.bilibili.com/video/BV1111111111/'])
def test_scalar_provenance_itself_must_name_the_own_page(origin_url):
    r=resource('BV1cJ411h7kU');add_search(r,AR,AR)
    if origin_url is None:r['field_provenance']['title'].pop('url')
    else:r['field_provenance']['title']['url']=origin_url
    assert assess_topic_evidence(point(AR),r,r['evidence']) is None


@pytest.mark.parametrize('title,description',[
    ('localStorage JSON.stringify','JSON.stringify is not covered in this lesson.'),
    ('localStorage JSON.stringify','JSON.stringify is never taught.'),
    ('localStorage介绍','其他课程：JSON.stringify。'),
])
def test_own_heading_cannot_override_explicit_denial_or_foreign_lesson_scope(title,description):
    r=resource('BV1cJ411h7kU');r['chapters']=[];replace_title(r,title)
    r['description']=description
    eid=r['field_provenance']['description']['evidence_id']
    next(e for e in r['evidence'] if e['evidence_id']==eid)['text']=description
    assert assess_topic_evidence(point(JS),r,r['evidence']) is None


@pytest.mark.parametrize('body',['以后会讲按键消抖与松手检测','其他课程：按键消抖与松手检测'])
def test_specific_state_alias_cannot_complete_future_or_foreign_teaching(body):
    assert not compound_english_match(AR,[body])


def test_this_lesson_teaching_plan_remains_positive():
    assert compound_english_match(AR,['本课将讲按键消抖与松手检测'])
    assert _json_stringify_serialization('JSON 序列化','本课将讲localStorage JSON.stringify',whole_topic=JS)


def test_own_supported_card_explains_own_metadata_without_claiming_search_or_algorithm():
    from backend.app.ranking import rank_resource
    from backend.app.models import SearchRequest
    r=resource('BV1cJ411h7kU');add_search(r,AR,'外课状态监控')
    r['resource_id']='synthetic-test-resource'
    result=rank_resource(point(AR),r,r['evidence'],SearchRequest(knowledge_points=[AR]))
    assert result and result['topic_evidence_status']=='supported'
    assert '本视频自身' in result['recommendation_reason'] and '搜索摘要' not in result['recommendation_reason']
    assert '教学深度' in result['recommendation_reason'] and '非阻塞' not in result['recommendation_reason']


def replace_catalog_title(r,title):
    chapter=r['chapters'][0];chapter['title']=title
    entry=next(e for e in r['evidence'] if e['evidence_id']==chapter['evidence_id'])
    value=json.loads(entry['text']);value['title']=title
    entry['text']=json.dumps(value,ensure_ascii=False,sort_keys=True)


@pytest.mark.parametrize('title',[
    "localStorage JSON.stringify isn't covered",
    'localStorage JSON.stringify will be covered next week',
    'localStorage JSON.stringify will be covered in a later lesson',
    'localStorage 明天讲JSON.stringify',
])
def test_bound_catalog_future_and_contracted_denial_do_not_prove_current_serialization(title):
    r=resource('BV183411B7nJ');replace_catalog_title(r,title)
    assert assess_topic_evidence(point(JS),r,r['evidence']) is None


@pytest.mark.parametrize('title',[
    '按键消抖与松手检测 is not covered',
    '按键消抖与松手检测 will be covered next week',
])
def test_bound_button_title_postposed_denial_and_future_are_not_current_support(title):
    r=resource('BV1cJ411h7kU');replace_title(r,title)
    assert assess_topic_evidence(point(AR),r,r['evidence']) is None


def test_unrelated_future_css_does_not_retract_current_serialization():
    r=resource('BV183411B7nJ');replace_catalog_title(r,'localStorage 本课讲JSON.stringify，之后会讲CSS布局')
    result=assess_topic_evidence(point(JS),r,r['evidence'])
    assert result and result['topic_evidence_status']=='partial'
    assert result['subtopic_coverage'][0]['status']=='unknown'


@pytest.mark.parametrize('suffix',['，之后会讲舵机控制','，不需要额外电容'])
def test_unrelated_future_or_nonrequired_component_does_not_retract_current_button_topic(suffix):
    r=resource('BV1cJ411h7kU');replace_title(r,'本课讲按键消抖与松手检测'+suffix)
    assert assess_topic_evidence(point(AR),r,r['evidence'])['topic_evidence_status']=='supported'


def test_verified_own_audience_cannot_be_replaced_by_adversarial_search_title():
    from backend.app.ranking import rank_resource
    from backend.app.models import SearchRequest
    r=resource('BV1cJ411h7kU');r['resource_id']='synthetic-test-resource'
    request=SearchRequest(knowledge_points=[AR],student_level='beginner')
    baseline=rank_resource(point(AR),r,r['evidence'],request)
    add_search(r,'Arduino 按键消抖状态检测 高级进阶 不适合初学者','')
    contaminated=rank_resource(point(AR),r,r['evidence'],request)
    assert baseline and contaminated
    assert baseline['recommendation_reason']==contaminated['recommendation_reason']
    assert '不适合初学者' not in contaminated['recommendation_reason']


@pytest.mark.parametrize('title',[
    '本课localStorage JSON.stringify，不像其他课程只讲概念',
    '不像其他课程只讲概念，本课localStorage JSON.stringify',
    '本课localStorage JSON.stringify，unlike other courses that only discuss concepts',
])
def test_explicit_comparison_with_other_course_does_not_remove_current_api_topic(title):
    r=resource('BV183411B7nJ');replace_catalog_title(r,title)
    result=assess_topic_evidence(point(JS),r,r['evidence'])
    assert result and result['topic_evidence_status']=='partial'
    assert result['subtopic_coverage'][0]['status']=='unknown'


def test_instruction_cleaning_cannot_move_css_denial_onto_json_api():
    r=resource('BV183411B7nJ')
    replace_catalog_title(r,'localStorage存储，JSON.stringify is covered, but CSS is not covered')
    result=assess_topic_evidence(point(JS),r,r['evidence'])
    assert result and result['topic_evidence_status']=='partial'


def test_relative_clause_still_denies_the_same_api():
    r=resource('BV183411B7nJ')
    replace_catalog_title(r,"localStorage JSON.stringify, which isn't covered here")
    assert assess_topic_evidence(point(JS),r,r['evidence']) is None
