"""Fully offline provider HTTP and real platform-lane budget regressions."""
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest

from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.platform_search import platform_query
from backend.app.providers import SearXNGProvider
from backend.app.queries import generate_queries
from backend.app.service import JobService
from test_parallel_platform_search import NoFetch,options


def course_request(**extra):
    return SearchRequest(knowledge_points=['Python 列表'],preferred_platforms=['icourse163'],**extra)


async def run_body(tmp_path,body):
    calls=[]
    def reply(request):
        calls.append({'query':request.url.params['q'],'engine':request.url.params['engines']})
        return httpx.Response(200,json=body)
    config=options(tmp_path,global_concurrency=2)
    store=Store(config.database_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        service=JobService(config,store,provider=SearXNGProvider(config,client),fetcher=NoFetch())
        jid=service.create(course_request())['job_id']
        await service.run(jid)
        job,attempts,resources=store.get_job(jid),store.attempts(jid),store.resources(jid)
    store.close()
    return job,attempts,resources,calls


@pytest.mark.asyncio
@pytest.mark.parametrize('reason',['timeout','offline unclassified engine failure'])
async def test_http200_engine_fault_with_no_candidates_is_failed_even_when_backup_hits_slice(tmp_path,reason):
    job,attempts,resources,calls=await run_body(tmp_path,{'results':[],
        'unresponsive_engines':[['web',reason]]})
    assert len(calls)==job['progress']['search_requests']==2
    assert job['progress']['platform_search_requests']=={'icourse163':2}
    assert job['budgets']['max_search_requests']==2
    assert len(attempts)==2 and all(len(row['provider_requests'])==1 for row in attempts)
    assert all(row['provider_requests'][0]['http_status']==200 for row in attempts)
    assert all(row['status']=='failed' and row['error_code']=='upstream_engine_failed' for row in attempts)
    assert job['progress']['search_failures']==2 and job['progress']['search_successes']==0
    assert calls[0]['query']==calls[1]['query']  # Failed first pass retries only in its reserved followup.
    assert all(row['engine']=='web' for row in calls) and not resources
    assert all(row['candidate_count']==0 and row['upstream_warnings'] for row in attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize('body,raw,filters',[
    ({'results':[]},0,{}),
    ({'results':[{'url':'https://example.org/foreign-course','title':'Python 列表课程'}]},1,{'domain_mismatch':1}),
])
async def test_clean_empty_and_offdomain_intersection_do_not_become_engine_failure(tmp_path,body,raw,filters):
    job,attempts,resources,calls=await run_body(tmp_path,body)
    assert len(calls)==2 and job['progress']['search_failures']==0
    assert job['progress']['search_successes']==2
    assert all(row['status']=='partial' and row['error_code']=='query_budget_exhausted' for row in attempts)
    assert not resources
    for row in attempts:
        assert row['candidate_count']==0 and not row['upstream_warnings']
        trace=row['provider_requests'][0]
        assert trace['raw_candidate_count']==raw and trace['filter_counts']==filters


@pytest.mark.asyncio
async def test_real_partial_candidates_survive_engine_fault_and_query_or_global_budget_stop(tmp_path):
    # A genuine source response is retained even when irrelevant to the point;
    # it is discovery metadata, never a fabricated skill recommendation.
    body={'results':[{'url':'https://www.icourse163.org/course/OFFLINE-123456',
        'title':'意大利面烹饪课程','content':'Explicit synthetic metadata'}],
        'unresponsive_engines':[['web','offline unclassified engine failure']]}
    job,attempts,resources,calls=await run_body(tmp_path,body)
    assert len(calls)==job['progress']['search_requests']==job['budgets']['max_search_requests']==2
    assert job['progress']['search_failures']==0 and job['progress']['search_successes']==2
    assert len(resources)==1
    assert all(row['status']=='partial' and row['error_code']=='query_budget_exhausted' for row in attempts)
    assert all(row['candidate_count']==1 and row['upstream_warnings'] for row in attempts)
    assert all(len(row['provider_requests'])==1 for row in attempts)


@pytest.mark.parametrize('language,course_suffix,bili_suffix',[
    ('zh','课程 教学','视频教程'),('en','course lesson','video tutorial')])
@pytest.mark.parametrize('skills',[False,True])
def test_nonparallel_mooc_uses_course_words_and_bilibili_keeps_video_words(language,course_suffix,bili_suffix,skills):
    text='Python 列表'
    req=SearchRequest(knowledge_points=[text],language=language,preferred_platforms=['bilibili','icourse163','xuetangx'],
        learning_skills={text:['Python 列表索引']} if skills else {})
    queries=generate_queries('point-offline',text,req)
    by_domain={q.domain_filters[0]:q.query for q in queries if q.domain_filters}
    assert by_domain['icourse163.org'].endswith(course_suffix)
    assert not by_domain['icourse163.org'].endswith(bili_suffix)
    assert by_domain['bilibili.com'].endswith(bili_suffix)
    assert by_domain['xuetangx.com'].endswith(bili_suffix)  # Unrelated platform policy unchanged.
    assert len(queries)<=6


@pytest.mark.parametrize('language,initial,family,bili_initial,bili_followup',[
    ('zh','课程','Python 程序设计 课程 内容','视频教程','视频教程 示例'),
    ('en','course','Python programming course content','video tutorial','video tutorial examples')])
def test_parallel_mooc_family_followup_preserves_original_scope_and_exact_bilibili_labels(
        language,initial,family,bili_initial,bili_followup):
    request=course_request(language=language)
    point={'knowledge_point_id':'point-offline','text':'Python 列表'}
    before=deepcopy((point,request.model_dump()))
    mooc=[platform_query(point,'icourse163',request,followup=followup) for followup in (False,True)]
    bili=[platform_query(point,'bilibili',request,followup=followup) for followup in (False,True)]
    assert [query.query for query in mooc]==[
        f'site:icourse163.org/course Python 列表 {initial}',f'site:icourse163.org/course {family}']
    assert [query.query for query in bili]==[
        f'site:bilibili.com/video Python 列表 {bili_initial}',
        f'site:bilibili.com/video Python 列表 {bili_followup}']
    assert all(query.domain_filters==['icourse163.org'] for query in mooc)
    assert all(query.domain_filters==['bilibili.com'] for query in bili)
    assert all(query.knowledge_point_id==point['knowledge_point_id'] for query in mooc+bili)
    assert (point,request.model_dump())==before
