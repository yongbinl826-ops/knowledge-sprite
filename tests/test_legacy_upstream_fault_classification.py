"""Offline legacy scheduler: observed faults are not erased by budget stops."""
import httpx
import pytest

from backend.app.db import Store
from backend.app.models import Query,SearchRequest
from backend.app.providers import QueryBudgetReached,SearchBudgetReached,SearXNGProvider
from backend.app.service import JobService
import backend.app.service as service_module
from test_search_budget_preservation import NoFetch,options


def config(tmp_path):
    return options(tmp_path,max_search_requests=2,parallel_platform_search=False,teaching_match_enabled=False,
        public_catalog_fallback=False,official_sitemap_fallback=False,fetch_enabled=False,llm_provider='none',
        llm_api_key='',search_max_retries=1)


async def run_body(tmp_path,body):
    calls=[]
    def respond(request):
        calls.append({'query':request.url.params['q'],'engine':request.url.params['engines']})
        payload=body(request) if callable(body) else body
        return httpx.Response(200,json=payload)
    settings=config(tmp_path);store=Store(settings.database_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        jobs=JobService(settings,store,provider=SearXNGProvider(settings,client),fetcher=NoFetch())
        jid=jobs.create(SearchRequest(knowledge_points=['Python 列表'],preferred_platforms=['icourse163']))['job_id']
        await jobs.run(jid)
        result=(store.get_job(jid),store.attempts(jid),store.resources(jid),calls,
            store.connection.execute("SELECT COUNT(*) FROM cache WHERE kind='search'").fetchone()[0])
    store.close()
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize('reason',['timeout','offline unclassified engine failure'])
async def test_legacy_query_and_global_budget_preserve_each_executed_http200_engine_failure(tmp_path,reason):
    def body(request):return {'results':[],'unresponsive_engines':[[request.url.params['engines'],reason]]}
    job,attempts,resources,calls,cache_count=await run_body(tmp_path,body)
    assert len(calls)==job['progress']['search_requests']==job['budgets']['max_search_requests']==2
    assert job['status']=='failed'
    assert job['progress']['search_successes']==0 and job['progress']['search_failures']==2
    assert len(attempts)==2 and all(len(row['provider_requests'])==1 for row in attempts)
    assert all(row['status']=='failed' and row['error_code']=='upstream_engine_failed' for row in attempts)
    assert all(row['provider_requests'][0]['http_status']==200 for row in attempts)
    assert all(row['upstream_warnings'] and row['candidate_count']==0 for row in attempts)
    assert all(row['provider_requests'][0]['upstream_warnings'] for row in attempts)
    assert not resources and cache_count==0


@pytest.mark.asyncio
@pytest.mark.parametrize('body,raw,filters',[
    ({'results':[]},0,{}),
    ({'results':[{'url':'https://example.org/outside-course','title':'Python 列表课程'}]},1,{'domain_mismatch':1}),
])
async def test_legacy_clean_empty_and_scoped_domain_mismatch_remain_distinct_from_engine_failure(tmp_path,monkeypatch,body,raw,filters):
    # Explicit scoped queries exercise the real legacy request loop and parser;
    # this fixture does not change production query planning.
    def scoped(pid,text,request,*args,**kwargs):
        return [Query(knowledge_point_id=pid,query=f'site:icourse163.org/course {text} {index}',
            domain_filters=['icourse163.org']) for index in range(2)]
    monkeypatch.setattr(service_module,'generate_queries',scoped)
    job,attempts,resources,calls,cache_count=await run_body(tmp_path,body)
    assert len(calls)==job['progress']['search_requests']==2 and len(attempts)==2
    assert [row['status'] for row in attempts]==['query_budget_exhausted','budget_exhausted']
    assert [row['error_code'] for row in attempts]==['query_budget_exhausted','budget_exhausted']
    assert job['progress']['search_failures']==0 and not resources and cache_count==0
    for row in attempts:
        trace=row['provider_requests'][0]
        assert trace['raw_candidate_count']==raw and trace['filter_counts']==filters
        assert not trace['upstream_warnings'] and not row.get('upstream_warnings')


@pytest.mark.asyncio
async def test_legacy_actual_partial_candidates_survive_both_budget_stops_even_with_faults(tmp_path):
    def body(request):return {'results':[{'url':'https://www.icourse163.org/course/OFFLINE-123456',
        'title':'意大利面烹饪课程','content':'Explicit synthetic response, unrelated to the requested skill'}],
        'unresponsive_engines':[[request.url.params['engines'],'offline unclassified engine failure']]}
    job,attempts,resources,calls,cache_count=await run_body(tmp_path,body)
    assert len(calls)==job['progress']['search_requests']==2 and len(attempts)==2
    assert [row['status'] for row in attempts]==['partial','partial']
    assert [row['error_code'] for row in attempts]==['query_budget_exhausted','budget_exhausted']
    assert all(row['candidate_count']==1 and row['upstream_warnings'] for row in attempts)
    assert job['progress']['search_successes']==2 and job['progress']['search_failures']==0
    assert len(resources)==1 and cache_count==0


@pytest.mark.asyncio
@pytest.mark.parametrize('budget_error',[QueryBudgetReached,SearchBudgetReached])
@pytest.mark.parametrize('paused_warning',[False,True])
async def test_legacy_unstarted_budget_stop_does_not_invent_request_failure_or_success(tmp_path,budget_error,paused_warning):
    warnings=([{'code':'upstream_engine_failed','engine':'web','reason_code':'suspended',
        'reason':'suspended','message':'Synthetic engine paused before budget stop'}] if paused_warning else [])
    class StoppedBeforeHTTP(SearXNGProvider):
        async def search(self,*args,**kwargs):
            self.last_requests=[];self.last_warnings=warnings
            raise budget_error()
    settings=config(tmp_path);store=Store(settings.database_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:pytest.fail('Budget stopped before HTTP'))) as client:
        jobs=JobService(settings,store,provider=StoppedBeforeHTTP(settings,client),fetcher=NoFetch())
        jid=jobs.create(SearchRequest(knowledge_points=['Python 列表'],preferred_platforms=[]))['job_id']
        await jobs.run(jid)
        job=store.get_job(jid)
        assert job['progress']['search_requests']==job['progress']['search_successes']==job['progress']['search_failures']==0
        assert not store.resources(jid)
        assert all(row['status']=='query_budget_exhausted' and not row['provider_requests']
                   and row['upstream_warnings']==warnings for row in store.attempts(jid))
    store.close()
