"""Relevance policy: retained real sources and independent synthetic boundaries."""
from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation, related_recommendations

FIXTURES=Path(__file__).parent/'fixtures/related-policy-20261020'
URL='https://www.bilibili.com/video/BV1Ct4y127He/'

def candidate(title,body='',name='矩形碰撞检测',technology='pygame'):
    point={'knowledge_point_id':'point','text':name,'technology':technology}
    resource={'resource_id':'r','title':title,'url':URL,'canonical_url':URL,'platform':'bilibili',
              'resource_type':'video','fetch_status':'search_only','metadata_evidence_level':'search',
              'field_provenance':{'resource_type':{'evidence_id':'e','source':'search_template'}}}
    evidence=[{'evidence_id':'e','kind':'search','source':'synthetic-offline-test','knowledge_point_id':'point',
               'type_source':'search_template','resource_type_hint':'video',
               'url':URL,'title':title,'snippet':body}]
    request=SearchRequest(knowledge_points=[name],topic_technologies={name:technology})
    return point,resource,evidence,request

@pytest.mark.parametrize('title,body,name,technology,expected',[
 ('Pygame碰撞检测','','矩形碰撞检测','pygame',True),
 ('中文编程pygame游戏教程5_检测碰撞','','矩形碰撞检测','pygame',True),
 ('pygame 自定义 Sprite 碰撞区域检测','','矩形碰撞检测','pygame',True),
 ('Pandas 分组聚合教程','','分组聚合','pandas',True),
 ('Arduino 按钮消抖入门','','按钮消抖','Arduino',True),
 ('JavaScript event propagation','','event propagation','JavaScript',True),
 ('Unity 矩形碰撞检测','','矩形碰撞检测','pygame',False),
 ('STM32 CubeMX 按键消抖状态检测教程','','按键消抖','Arduino',False),
 ('Pygame 矩形面积公式和文件检测工具','','矩形碰撞检测','pygame',False),
 ('Pandas 广告分组与素材聚合','','分组聚合','pandas',False),
 ('Pandas资源入口','https://example.org/分组聚合','分组聚合','pandas',False),
 ('Pygame 基础教程','','矩形碰撞检测','pygame',False),
 ('招生包就业 pygame 矩形碰撞检测','','矩形碰撞检测','pygame',False),
])
def test_related_topic_admission_and_obvious_negative_controls(title,body,name,technology,expected):
    args=candidate(title,body,name,technology)
    before=deepcopy(args[:3]);result=related_recommendation(*args)
    assert bool(result)==expected
    assert args[:3]==before
    if result:
        assert result['reference']['exact_teaching_verified'] is False
        assert '未验证精确讲授' in result['reference']['reason']

@pytest.mark.parametrize('field,value',[
 ('url','http://127.0.0.1/video/x'),('canonical_url','javascript:alert(1)'),
 ('resolved_url','http://169.254.169.254/latest/meta-data/'),
 ('fetch_status','not_found'),('fetch_status','unsafe_url'),
])
def test_unsafe_or_known_dead_resources_never_become_references(field,value):
    point,resource,evidence,request=candidate('Pygame 矩形碰撞检测')
    resource[field]=value
    assert related_recommendation(point,resource,evidence,request) is None

def test_query_echo_foreign_page_and_missing_evidence_are_not_relevance():
    point,resource,evidence,request=candidate('Pygame 基础教程')
    evidence[0]['query']='pygame 矩形碰撞检测 视频教程'
    assert related_recommendation(point,resource,evidence,request) is None
    evidence[0].update(title='Pygame 矩形碰撞检测',url='https://example.org/other')
    assert related_recommendation(point,resource,evidence,request) is None
    evidence[0].update(url=URL,evidence_id='')
    assert related_recommendation(point,resource,evidence,request) is None

def test_login_or_payment_notice_does_not_invalidate_actual_video_link():
    point,resource,evidence,request=candidate('Pygame 矩形碰撞检测')
    resource.update(fetch_status='login_required',access_notice='需要登录或付费，播放尚未核验')
    result=related_recommendation(point,resource,evidence,request)
    assert result and result['resource']['access_notice']==resource['access_notice']
    assert '页面详情尚未读取' in result['reference']['reason']

def test_own_title_wrong_stack_outweighs_search_excerpt():
    point,resource,evidence,request=candidate('Pygame 矩形碰撞检测')
    evidence.append({'evidence_id':'own','kind':'page','field':'title','source':'html.title','url':URL,'text':'Unity 矩形碰撞检测'})
    assert related_recommendation(point,resource,evidence,request) is None

def test_declared_parent_course_can_supply_context_but_not_teaching_proof():
    point,resource,evidence,request=candidate('分组聚合',name='分组聚合',technology='pandas')
    parent='https://www.bilibili.com/video/BV1WKH7zZEEw/'
    resource['parent_course_url']=parent
    evidence.append({'evidence_id':'parent','kind':'page','field':'title','source':'html.title','url':parent,'text':'pandas 数据分析课程'})
    result=related_recommendation(point,resource,evidence,request)
    assert result['reference']['technical_context']=='parent_course'
    assert result['reference']['exact_teaching_verified'] is False
    resource['parent_course_url']='https://example.org/different'
    # The selected implementation context cannot come from another course.
    assert related_recommendation(point,resource,evidence,request) is None

@pytest.mark.parametrize('label,name,technology',[('pygame','矩形碰撞检测','pygame'),('dashboard','分组聚合','pandas')])
def test_three_actual_retained_candidates_survive_as_related_references(label,name,technology):
    source=json.loads((FIXTURES/f'{label}-sources.json').read_text('utf8'))
    snapshot=deepcopy(source)
    point={'knowledge_point_id':'replay','text':name,'technology':technology}
    request=SearchRequest(knowledge_points=[name],topic_technologies={name:technology})
    items,platforms=related_recommendations(point,source['resources'],source['evidence'],request,5)
    assert len(items)==3 and len(platforms['bilibili'])==3
    assert len({item['resource']['canonical_url'] for item in items})==3
    assert all(item['reference']['exact_teaching_verified'] is False for item in items)
    assert all(item['reference']['evidence_ids'] for item in items)
    assert source==snapshot
    limited,_=related_recommendations(point,source['resources'],source['evidence'],request,1)
    assert len(limited)==1

def test_service_attaches_new_reference_policy_without_fabricating_teaching_matches():
    from backend.app.service import JobService
    source=json.loads((FIXTURES/'pygame-sources.json').read_text('utf8'))
    point={'knowledge_point_id':'point','text':'矩形碰撞检测','technology':'pygame','items':[],'total_matches':0}
    request=SearchRequest(knowledge_points=['矩形碰撞检测'],topic_technologies={'矩形碰撞检测':'pygame'})
    service=object.__new__(JobService);service.settings=SimpleNamespace(max_results_per_point=5)
    service._add_related_recommendations([point],source['resources'],source['evidence'],request)
    assert point['recommendation_policy']=='related-reference-v1'
    assert point['total_related_recommendations']==3
    assert point['items']==[] and point['total_matches']==0

def test_stream_display_count_includes_related_references_once_without_teaching_claim():
    from backend.app.result_stream import pipeline
    source=json.loads((FIXTURES/'pygame-sources.json').read_text('utf8'))
    point={'knowledge_point_id':'point','text':'矩形碰撞检测','technology':'pygame'}
    request=SearchRequest(knowledge_points=['矩形碰撞检测'],topic_technologies={'矩形碰撞检测':'pygame'})
    items,_=related_recommendations(point,source['resources'],source['evidence'],request,5)
    group={**point,'recommendation_policy':'related-reference-v1','items':[],
           'related_recommendations':[items[0],*items]}
    summary=pipeline([group],[],terminal=True)
    assert summary['displayed']==3 and group['items']==[]

@pytest.mark.asyncio
@pytest.mark.parametrize('chapters,expected',[(('列表','字典'),1),(('列表',),0)])
async def test_compound_topic_keeps_own_qualified_outline_without_admitting_generic_course(chapters,expected):
    from test_mooc_relevance_service import setup, discover, enrich, synthetic_outline
    from backend.app.result_stream import pipeline
    service,job,state,fetcher=setup()
    url='https://www.icourse163.org/course/OWN-123'
    fetcher.documents[url]=synthetic_outline(chapters=chapters)
    rid=discover(service,job,state,url,title='Python程序设计',snippet='程序设计课程')
    await enrich(service,job,state,rid)
    result=service.results(job['job_id'])
    group=result['groups'][0]
    assert len(group['related_recommendations'])==expected
    assert pipeline([group],[],terminal=True)['displayed']==expected
    if expected:
        reference=group['related_recommendations'][0]
        assert reference['reference']['exact_teaching_verified'] is False
        assert reference['reference']['basis']==['catalog']
        assert set(reference['reference']['evidence_ids'])=={row['evidence_id'] for row in reference['evidence']}
        assert all(row in service.store.evidence(job['job_id'],rid) for row in reference['evidence'])
