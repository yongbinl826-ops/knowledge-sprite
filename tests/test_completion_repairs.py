import pytest

from backend.app.ranking import compound_english_match, relevance, prerequisite_only_match, version_conflict
from backend.app.providers import parse_candidates, SearXNGProvider
from backend.app.config import Settings
from backend.app.ranking import own_resource_snippet, topic_context_conflict, rank_resource
from backend.app.models import SearchRequest
from copy import deepcopy


@pytest.mark.parametrize('point,missing,complete',[
    ('Python 列表与字典','Python 列表入门视频教程','Python 列表与字典视频教程'),
    ('HTML 表单校验','HTML 表单设计视频教程','HTML 表单校验视频教程'),
    ('SQL 多表连接','SQL 多表查询视频教程','SQL 多表连接视频教程'),
])
def test_chinese_compound_requires_whole_concept(point,missing,complete):
    assert not compound_english_match(point,[missing])
    assert compound_english_match(point,[complete])
    assert not compound_english_match('Python 列表与字典',['Python 列表教程','Python 字典教程'])


@pytest.mark.parametrize('term,positive,negative', [('和弦','和弦课程','弦乐课程'),('与门','与门课程','或门课程')])
def test_conjunction_inside_term_is_not_a_single_character_match(term,positive,negative):
    assert relevance(term,positive)==1
    assert relevance(term,negative)==0


def test_local_negation_does_not_turn_teaching_into_prerequisite():
    point='Python 函数与作用域'
    assert not prerequisite_only_match(point,'从零讲解 Python函数与作用域，不需要任何先修知识。','','','')
    assert prerequisite_only_match(point,'需要预先掌握 Python函数与作用域。','','','')
    assert prerequisite_only_match(point,'无需数学，先修要求 Python函数与作用域。','','','')

def test_chinese_concept_boundary_variants():
    for observation in ('SQL 多表的连接课程','SQL 多表 连接课程','SQL 多表 的 连接课程'):
        assert compound_english_match('SQL 多表连接',[observation])
    assert not compound_english_match('SQL 多表连接',['SQL 连接课程'])
    assert compound_english_match('Python与数据分析',['Python数据分析课程'])
    assert compound_english_match('HTML 表单校验',['HTML 表单零基础教程：双重校验安全思路'])
    assert compound_english_match('HTML 表单校验',['HTML5表单可以直接用正则表达式校验啦'])
    assert compound_english_match('HTML 表单校验',['HTML实现表单验证'])
    assert not compound_english_match('HTML 表单校验',['HTML 表单设计视频教程'])
    assert not compound_english_match('HTML 表单校验',['HTML表单课程','校验课程'])
    assert not compound_english_match('HTML 表单校验',['HTML 单个表格在学校检验'])


@pytest.mark.parametrize('point,version,content,conflict',[
    ('Python3.13','','Python3.12 教程',False),
    ('Python3.13','','Python2.7 教程',True),
    ('Python v3.13','','Python v2.7 教程',True),
    ('Python 函数','3.13','Python 2.7 教程',True),
    ('D3.js','','D2.js',False),
    ('D3.js v7','','D3.js v6 tutorial',True),
    ('C++17','','C++11 tutorial',True),
    ('Python 文件读写','3','Python2文件读写课程',True),
    ('Python 文件读写','3','Python3文件读写课程',False),
    ('Python 文件读写','3','Python2abc文件读写课程',False),
])
def test_version_boundaries(point,version,content,conflict):
    assert version_conflict(point,version,content)==conflict


def test_bounded_source_diagnostics_redact_urls_and_fingerprint_unknown():
    audit={}
    parse_candidates([{'title':'HTML 表单设计','url':'https://example.org/course',
        'content':'实际摘要 https://x:SECRET@example.org/?token=SECRET\n'+ '字'*2000}],
        'searxng','HTML 表单校验',3,['bilibili.com'],audit=audit)
    trace=audit['candidate_trace'][0]
    assert trace['reason']=='domain_mismatch' and trace['title']=='HTML 表单设计'
    assert len(trace['snippet'])==1200 and trace['snippet_truncated']
    assert 'SECRET' not in str(audit)
    provider=SearXNGProvider(Settings())
    error=provider._failures({'unresponsive_engines':[['bing','arbitrary SECRET error']]})[0]
    assert error['reason_code']=='unknown' and len(error['reason_sha256'])==64
    assert not provider.engine_pauses and 'SECRET' not in str(error)

def test_source_diagnostics_redact_case_insensitive_credentials():
    audit={}
    parse_candidates([{'title':'HTTPS://user:EXAMPLE_SECRET@example.org/?token=EXAMPLE_TOKEN',
        'content':'Authorization: Bearer EXAMPLE_TOKEN\nCookie: session=EXAMPLE_COOKIE',
        'url':'http://user:EXAMPLE_SECRET@invalid.local'}], 'searxng','topic',3,[],audit=audit)
    assert 'EXAMPLE_' not in str(audit)


@pytest.mark.parametrize('tail',['相关视频：Java Stream Collectors','相关推荐: Java Stream Collectors','Related videos: Java Stream Collectors'])
def test_recommended_resource_is_not_teaching_evidence(tail):
    evidence=[{'evidence_id':'own','kind':'search','source':'test','title':'Java scheduled thread pool','snippet':'周期性定时执行任务线程池，'+tail}]
    original=deepcopy(evidence)
    resource={'resource_id':'thread-pool','url':'https://example.org/video/thread-pool','resource_type':'video'}
    # Relaxed metadata ranking also cannot borrow recommendation terms.
    assert rank_resource({'knowledge_point_id':'p','text':'Java stream collectors'},resource,evidence,SearchRequest(knowledge_points=['Java stream collectors']),require_type=False) is None
    assert evidence==original
    assert 'Stream' not in own_resource_snippet(evidence[0]['snippet'])


def test_actual_course_description_and_recommendation_topics_stay_distinct():
    text='本课程讲解Java Stream Collectors。相关视频：Java线程池'
    assert own_resource_snippet(text)=='本课程讲解Java Stream Collectors。'
    assert own_resource_snippet('讲解相关推荐算法及其课程应用')=='讲解相关推荐算法及其课程应用'
    assert own_resource_snippet('Course outline: Unit Testing; Dependency Injection')=='Course outline: Unit Testing; Dependency Injection'


@pytest.mark.parametrize('text',[
    'UE5 Motion Matching Pose Database Normalization set',
    'Pose Database and Normalization set tutorial',
])
def test_pose_normalization_is_not_database_normal_forms(text):
    assert topic_context_conflict('database normalization',text)
    assert not compound_english_match('database normalization',[text])
    assert compound_english_match('database normalization',[text,'Database normalization tutorial: 1NF 2NF 3NF'])


def test_explicit_competing_context_guard_is_narrow():
    for text in ('Database Normalization tutorial','UE5 database normalization with SQL normal forms','Pose Database normalization compared with relational database normalization'):
        assert not topic_context_conflict('database normalization',text)
        assert compound_english_match('database normalization',[text])
    assert not topic_context_conflict('quaternion rotations','UE5 Motion Matching Pose Database Normalization set')


def test_unrelated_second_observation_cannot_rescue_competing_context():
    resource={'resource_id':'pose','url':'https://example.org/video/pose','resource_type':'video','metadata_evidence_level':'search','field_provenance':{'title':{'source':'search'}}}
    evidence=[{'evidence_id':'pose','kind':'search','title':'UE5 Motion Matching Pose Database Normalization set','snippet':''},
              {'evidence_id':'other','kind':'search','title':'UE5 animation lesson','snippet':''}]
    point={'knowledge_point_id':'p','text':'database normalization'}
    request=SearchRequest(knowledge_points=['database normalization'])
    assert rank_resource(point,resource,evidence,request,require_type=False) is None
    evidence.append({'evidence_id':'relational','kind':'search','title':'Database normalization with 1NF 2NF 3NF','snippet':'Relational database tutorial'})
    match=rank_resource(point,resource,evidence,request,require_type=False)
    assert match and match['matched_evidence_ids']==['relational']
