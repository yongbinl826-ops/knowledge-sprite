"""Offline outgoing HTTP routing: platform intent outranks topic vocabulary."""
import httpx
import pytest

from backend.app.config import Settings
from backend.app.models import SearchRequest
from backend.app.platform_search import platform_query
from backend.app.providers import QueryBudgetReached,SearchError,SearXNGProvider
from backend.app.queries import generate_queries


TOPICS=[('zh','OpenCV 视频帧读取'),('en','OpenCV video frame reading')]


def config(**overrides):
    return Settings(searxng_url='https://offline-search.example',searxng_engines=('web',),
        searxng_video_engines=('video',),searxng_fallback_engines=(),
        search_min_interval_seconds=0,**overrides)


@pytest.mark.asyncio
@pytest.mark.parametrize('language,topic',TOPICS)
@pytest.mark.parametrize('route',['parallel_initial','parallel_followup','nonparallel'])
async def test_explicit_mooc_uses_general_engine_even_when_topic_contains_video(language,topic,route):
    request=SearchRequest(knowledge_points=[topic],language=language,preferred_platforms=['bilibili','icourse163'])
    point={'knowledge_point_id':'offline-point','text':topic}
    query=(next(q for q in generate_queries(point['knowledge_point_id'],topic,request) if q.domain_filters==['icourse163.org'])
        if route=='nonparallel' else platform_query(point,'icourse163',request,followup=route=='parallel_followup'))
    calls=[];count=0
    def respond(outgoing):
        calls.append(outgoing)
        return httpx.Response(200,json={'results':[{'url':'https://www.icourse163.org/course/OFFLINE-123456',
            'title':topic+' 课程','content':'Explicit offline course discovery fixture'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider=SearXNGProvider(config(),client)
        async def reserve():
            nonlocal count
            count+=1
        provider.request_hook=reserve
        items=await provider.search(query.query,language,6,query.domain_filters)
    assert len(calls)==count==len(provider.last_requests)==1 and len(items)==1
    assert calls[0].url.params['engines']=='web'
    assert calls[0].url.params['q']==query.query and calls[0].url.params['q'].startswith('site:icourse163.org')
    assert provider.last_requests[0]['engines_requested']=='web'
    assert provider.last_requests[0]['filter_counts']=={'accepted':1}


@pytest.mark.asyncio
@pytest.mark.parametrize('language,topic',TOPICS)
@pytest.mark.parametrize('domains',[['bilibili.com'],[],['icourse163.org','bilibili.com']])
async def test_bilibili_unrestricted_and_mixed_scopes_keep_video_routing(language,topic,domains):
    calls=[]
    url=('https://www.bilibili.com/video/BVoffline001/' if domains==['bilibili.com'] else
         'https://www.icourse163.org/course/OFFLINE-123456')
    def respond(outgoing):
        calls.append(outgoing)
        return httpx.Response(200,json={'results':[{'url':url,'title':topic+' video tutorial'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider=SearXNGProvider(config(),client)
        assert await provider.search(topic,language,6,domains)
    assert len(calls)==1 and calls[0].url.params['engines']=='video'
    expected=f'site:{domains[0]} {topic}' if domains else topic
    assert calls[0].url.params['q']==expected


@pytest.mark.asyncio
@pytest.mark.parametrize('language,topic',TOPICS)
@pytest.mark.parametrize('fallback',[(),('video',)])
async def test_empty_general_engine_config_never_uses_video_or_implicit_default_for_mooc(language,topic,fallback):
    calls=[];reservations=[]
    def forbidden(outgoing):
        calls.append(outgoing)
        pytest.fail('No course engine configured: neither video fallback nor instance defaults are authorized by this route')
    settings=Settings(searxng_url='https://offline-search.example',searxng_engines=(),
        searxng_video_engines=('video',),searxng_fallback_engines=fallback,search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        provider=SearXNGProvider(settings,client)
        async def reserve():reservations.append(1)
        provider.request_hook=reserve
        with pytest.raises(SearchError) as error:
            await provider.search(f'site:icourse163.org/course {topic} course lessons',language,6,['icourse163.org'])
    assert error.value.code=='configuration_error'
    assert not calls and not reservations and not provider.last_requests


@pytest.mark.asyncio
async def test_mooc_routing_does_not_expand_existing_query_budget_or_fallback_group():
    calls=[];reserved=0
    def empty(outgoing):calls.append(outgoing);return httpx.Response(200,json={'results':[]})
    settings=Settings(searxng_url='https://offline-search.example',searxng_engines=('web',),
        searxng_video_engines=('video',),searxng_fallback_engines=('backup',),search_min_interval_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(empty)) as client:
        provider=SearXNGProvider(settings,client)
        async def one_request():
            nonlocal reserved
            if reserved==1:raise QueryBudgetReached()
            reserved+=1
        provider.request_hook=one_request
        with pytest.raises(QueryBudgetReached) as error:
            await provider.search('site:icourse163.org/course OpenCV video frames course lessons','en',6,['icourse163.org'])
    assert reserved==len(calls)==len(provider.last_requests)==1
    assert calls[0].url.params['engines']=='web' and not error.value.partial_candidates
