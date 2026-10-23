"""Independent preselected search index; all HTTP boundaries are mocked."""
from dataclasses import replace
import asyncio
import time
import httpx
import pytest
from backend.app.ai_video_service import _search_one
from backend.app.models import Query
from backend.app.providers import TavilyProvider
from backend.app.service import JobService
from test_ai_grounded_recovery import POINT, URL, recovery_service, run, visible
from test_ai_retained_recovery import setup_retained


def configure(service,provider,*,selected='auto',stop='engine_access_pause'):
    service.settings=replace(service.settings,serper_api_key='offline-test-key',
        ai_video_search_provider=selected,searxng_engines=('bing',),
        searxng_video_engines=('duckduckgo videos',),searxng_fallback_engines=('bing',))
    service._providers['serper']=provider
    service._provider_errors['serper']=None
    ordinary=service.provider
    if stop=='engine_access_pause':
        ordinary.engine_pauses={'duckduckgo videos':time.monotonic()+3600}
        ordinary.engine_timeout_cooldowns={}
    elif stop=='access_denied':ordinary.access_denied=True
    elif stop=='rate_limited':ordinary.paused_until=time.monotonic()+60
    service._ai_search_source=JobService._ai_search_source.__get__(service)
    return ordinary


def prepared(service):
    job,state=setup_retained(service,points=(POINT,),stopped=False)
    job['ai_video_fallback']={'search_requests':0}
    query=Query(knowledge_point_id=state['points'][0]['knowledge_point_id'],
        query='site:bilibili.com/video/ '+POINT,domain_filters=['bilibili.com'])
    return job,state,query


@pytest.mark.parametrize('selected',['auto','serper'])
@pytest.mark.parametrize('stop',['engine_access_pause','access_denied','rate_limited'])
async def test_preselected_independent_index_does_not_request_original_stopped_source(recovery_service,selected,stop):
    service,calls,provider=recovery_service()
    ordinary=configure(service,provider,selected=selected,stop=stop)
    job,state,query=prepared(service)
    before=dict(vars(ordinary))
    rows=await _search_one(service,job,state,query)
    assert len(calls)==1 and rows and not ordinary.calls
    assert vars(ordinary)==before
    assert service._providers['serper'] is provider and service.provider is ordinary
    assert job['progress']['search_requests']==1 and job['ai_video_fallback']['search_requests']==1
    attempt=service.store.attempts(job['job_id'])[-1]
    assert attempt['provider']=='serper' and len(attempt['provider_requests'])==1
    assert attempt['network_attempted'] is True


@pytest.mark.parametrize('stop',['engine_access_pause','access_denied','rate_limited'])
async def test_same_provider_still_respects_original_strong_stop(recovery_service,stop):
    service,calls,provider=recovery_service()
    ordinary=configure(service,provider,selected='default',stop=stop)
    job,state,query=prepared(service)
    assert await _search_one(service,job,state,query)==[]
    assert not calls and not ordinary.calls and job['progress']['search_requests']==0
    assert service.store.attempts(job['job_id'])[-1]['error_code']=='source_stopped'


@pytest.mark.parametrize('status',[401,403,429])
async def test_selected_provider_own_http_stop_never_switches_index_or_retries(recovery_service,status):
    service,calls,provider=recovery_service(respond=lambda *_:httpx.Response(status,headers={'Retry-After':'120'},json={}))
    ordinary=configure(service,provider)
    job,state,query=prepared(service)
    await _search_one(service,job,state,query)
    assert len(calls)==1
    assert 'serper' in state['recovery_stopped_sources']
    assert provider.access_denied if status in {401,403} else provider.paused_until>time.monotonic()
    await _search_one(service,job,state,query)
    assert len(calls)==1 and not ordinary.calls
    assert job['progress']['search_requests']==1
    second=service.store.attempts(job['job_id'])[-1]
    assert second['provider']=='serper' and second['provider_requests']==[] and not second['network_attempted']


async def test_request_hook_rechecks_selected_source_after_route_election(recovery_service):
    service,calls,provider=recovery_service()
    configure(service,provider)
    job,state,query=prepared(service)
    actual=service._ai_search_source
    route_calls=[]
    def elect(value):
        route_calls.append(value)
        if len(route_calls)==2:provider.paused_until=time.monotonic()+60
        return actual(value)
    service._ai_search_source=elect
    await _search_one(service,job,state,query)
    assert len(route_calls)==2 and not calls
    assert job['progress']['search_requests']==0
    assert service.store.attempts(job['job_id'])[-1]['error_code']=='rate_limited'


async def test_job_source_stop_survives_selected_provider_health_reset(recovery_service):
    service,calls,provider=recovery_service()
    configure(service,provider)
    job,state,query=prepared(service)
    state['recovery_stopped_sources']={'serper'}
    await _search_one(service,job,state,query)
    assert not calls and job['progress']['search_requests']==0
    assert service.store.attempts(job['job_id'])[-1]['error_code']=='source_stopped'


async def test_independent_index_uses_shared_remaining_request_cap(recovery_service):
    service,calls,provider=recovery_service(respond=lambda *_:httpx.Response(200,json={'organic':[]}))
    configure(service,provider)
    job,state,query=prepared(service)
    job['budgets']['max_search_requests']=2
    job['progress']['search_requests']=1
    await asyncio.gather(*[_search_one(service,job,state,query) for _ in range(3)])
    assert len(calls)==1 and job['progress']['search_requests']==2
    assert job['ai_video_fallback']['search_requests']==1


async def test_query_retry_cap_does_not_expand_for_independent_source(recovery_service):
    def unavailable(*_):raise httpx.ReadTimeout('offline synthetic timeout')
    service,calls,provider=recovery_service(respond=unavailable,search_max_retries=8)
    configure(service,provider)
    job,state,query=prepared(service)
    await _search_one(service,job,state,query)
    assert len(calls)==2 and job['progress']['search_requests']==2


async def test_independent_source_still_requires_verified_own_page_before_visible(recovery_service):
    service,calls,provider=recovery_service()
    configure(service,provider)
    _,result=await run(service)
    matches=visible(result['groups'][0])
    assert calls and len(matches)==1
    assert matches[0]['resource']['url']==URL
    assert matches[0]['resource']['video_evidence_status']=='page_verified'
    assert service.fetcher.calls


async def test_independent_search_hint_cannot_make_irrelevant_page_a_match(recovery_service):
    service,calls,provider=recovery_service(pages={URL:'Python 数据分析'})
    configure(service,provider)
    _,result=await run(service)
    assert calls and service.fetcher.calls
    assert not visible(result['groups'][0])


@pytest.mark.parametrize('selected',['auto','tavily'])
async def test_preselected_tavily_uses_its_own_transport_without_touching_paused_searx(recovery_service,selected):
    service,serper_calls,serper=recovery_service()
    ordinary=configure(service,serper)
    service.settings=replace(service.settings,serper_api_key='',tavily_api_key='offline-tavily-key',
        ai_video_search_provider=selected)
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'results':[{'url':URL,'title':POINT,'content':POINT+' 视频教学'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider=TavilyProvider(service.settings,client)
        service._providers['tavily']=provider
        service._provider_errors['tavily']=None
        job,state,query=prepared(service)
        rows=await _search_one(service,job,state,query)
    assert len(calls)==1 and rows and not serper_calls and not ordinary.calls
    assert service.store.attempts(job['job_id'])[-1]['provider']=='tavily'
    assert job['progress']['search_requests']==1
