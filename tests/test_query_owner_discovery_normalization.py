"""Query serialization only: no source facts, external calls or widened admission."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.app.models import SearchRequest
from backend.app.queries import complementary_search_phrase, query_contextual_concept_name
from backend.app.platform_search import platform_query
from backend.app import ai_video_service


@pytest.mark.parametrize('text,owner,expected', [
    ('Spark 分组与排序','Apache Spark','Apache Spark 分组与排序'),
    ('Quick 事件与状态管理','Qt Quick','Qt Quick 事件与状态管理'),
    ('JavaScript 异步任务','Java','Java JavaScript 异步任务'),
    ('C++ 模板','C','C C++ 模板'),
    ('C# 委托','C++','C++ C# 委托'),
    ('.NET 异步任务','.NET','.NET 异步任务'),
    ('python docx 段落','python-docx','python-docx python docx 段落'),
    ('CanvasKit 绘图','HTML5 Canvas','HTML5 Canvas CanvasKit 绘图'),
])
def test_search_owner_overlap_keeps_complete_identifier_boundaries(text,owner,expected):
    assert query_contextual_concept_name(text,owner)==expected


@pytest.mark.parametrize('text,owner', [
    ('Spark 分组与排序','Apache Spark'),
    ('Quick 事件与状态管理','Qt Quick'),
    ('QueryNode 绑定与取消','Acme Runtime'),
])
def test_declared_point_owner_wins_over_project_stack_without_mutation(text,owner):
    req=SearchRequest(knowledge_points=[text],topic_technologies={text:owner},
        project_context='使用 Python。',technical_version='2.4')
    before=deepcopy(req.model_dump())
    queries=[platform_query({'knowledge_point_id':'same-point','text':text},'bilibili',req,round_index=i) for i in range(3)]
    assert all('Python' not in query.query and owner in query.query and '2.4' in query.query for query in queries)
    assert all(query.knowledge_point_id=='same-point' and query.domain_filters==['bilibili.com'] for query in queries)
    assert req.model_dump()==before


def test_actual_compound_canvas_query_has_one_owner_and_no_borrowed_project_language():
    text='Canvas 逻辑尺寸、设备像素比与坐标换算'
    req=SearchRequest(knowledge_points=[text],topic_technologies={text:'HTML5 Canvas'},project_context='使用 JavaScript。')
    queries=[platform_query({'knowledge_point_id':'same-point','text':text},'bilibili',req,round_index=i).query for i in range(6)]
    assert queries[0]=='site:bilibili.com/video HTML5 Canvas 逻辑尺寸、设备像素比与坐标换算 视频教程'
    assert len(queries)==6
    assert all(query.count('Canvas')==1 and 'JavaScript' not in query for query in queries)
    assert '逻辑尺寸' in queries[1] and '设备像素比' in queries[2] and '坐标换算' in queries[4]


def test_actual_pointer_component_keeps_original_identifier():
    text='Pointer 事件统一鼠标与触摸输入'
    req=SearchRequest(knowledge_points=[text],topic_technologies={text:'JavaScript'},project_context='使用 JavaScript。')
    assert complementary_search_phrase(text,req,2)=='JavaScript Pointer 触摸输入'
    assert all('JavaScript Pointer' in platform_query({'knowledge_point_id':'same-point','text':text},'bilibili',req,round_index=i).query for i in range(6))


def test_unsafe_component_is_not_laundered_by_owner_join():
    text='Spark 数据读取与site:evil'
    req=SearchRequest(knowledge_points=[text],topic_technologies={text:'Apache Spark'})
    assert complementary_search_phrase(text,req,2) is None


@pytest.mark.asyncio
async def test_actual_recovery_round_keeps_domain_scope_without_path_assumption(monkeypatch):
    calls=[]
    async def search(service,job,state,query):
        calls.append(query.model_dump())
        return []
    monkeypatch.setattr(ai_video_service,'_search_one',search)
    point={'knowledge_point_id':'same-point','text':'QueryNode 绑定与取消'}
    request=SearchRequest(knowledge_points=[point['text']],topic_technologies={point['text']:'Acme Runtime'})
    await ai_video_service._recover_search_round(SimpleNamespace(settings=SimpleNamespace(search_results_per_query=10)),
        {'ai_video_fallback':{}},{'request':request},[point],{'same-point':['Acme Runtime QueryNode binding cancellation']},
        0,['bilibili'],asyncio.get_running_loop().time()+2,set())
    assert calls==[{'knowledge_point_id':'same-point',
        'query':'site:bilibili.com Acme Runtime QueryNode binding cancellation','domain_filters':['bilibili.com']}]
