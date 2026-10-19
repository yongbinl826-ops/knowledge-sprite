"""Offline link acceptance and conservative single-worker admission regressions."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.main import create_app
from backend.app.models import Candidate, Query, SearchRequest
from backend.app.providers import SearXNGProvider, SearchError
from backend.app.ranking import candidate_topic_signal, search_course_evidence
from backend.app.service import AdmissionRejected, JobService


class EmptyProvider:
    name = 'fixture'
    async def search(self, *args):
        return []


def course(title='Python lists and dictionaries course', url='https://example.org/courses/python', snippet='Learn Python lists and dictionaries in this course.'):
    return {'evidence_id': 'e', 'kind': 'search', 'source': 'fixture', 'title': title, 'url': url, 'snippet': snippet}


@pytest.mark.parametrize('title,url,snippet', [
    ('Python course notes', 'https://example.org/courses/python/notes.pdf', 'Learn Python course notes'),
    ('Python course', 'https://example.org/blog/courses/python', 'Learn Python in this course'),
    ('Best Python courses', 'https://example.org/courses/python', 'Learn Python course comparison'),
    ('Python 列表与字典课程笔记', 'https://example.org/courses/python', 'Python 列表与字典课程学习笔记'),
    ('Python course', 'https://127.0.0.1/courses/python', 'Learn Python course'),
    ('Python course', 'https://example.org/courses/python', ''),
])
def test_non_course_search_evidence_not_promoted(title, url, snippet):
    assert not search_course_evidence(url, course(title, url, snippet))


def test_relevant_article_does_not_stop_link_fallback():
    c = Candidate(id='article',title='SQL joins tutorial',url='https://example.org/blog/sql-joins',snippet='Learn SQL joins',source='fixture',query='SQL joins')
    assert not candidate_topic_signal(c,'SQL joins',SearchRequest(knowledge_points=['SQL joins'],language='en'))


def test_course_with_supplementary_lecture_notes_is_still_course():
    e=course(snippet='Learn Python lists and dictionaries. Includes lecture notes and exercises.')
    assert search_course_evidence(e['url'],e)


@pytest.mark.asyncio
async def test_empty_official_fallback_preserves_distinct_search_observations():
    rows=[Candidate(id=str(i),title=title,url='https://example.org/unknown',snippet=title,
          source='fixture',query='Python',source_engines=[str(i)]) for i,title in enumerate(['weak observation','another observation'])]
    class Primary(EmptyProvider):
        async def search(self,*args): return rows
    class Official(EmptyProvider):
        last_requests=[]
        last_dns_requests=[]
        last_discovery={}
        async def search(self,*args,**kwargs): return []
    store=Store(':memory:')
    svc=JobService(Settings(fetch_enabled=False),store,provider=Primary())
    svc.official_fallback=Official()
    assert await svc._discover(Query(knowledge_point_id='p',query='Python'),SearchRequest(knowledge_points=['Python']),'Python')==rows
    store.close()


@pytest.mark.asyncio
async def test_prune_read_failure_retains_order_and_join_accounting(monkeypatch):
    store=Store(':memory:')
    svc=JobService(Settings(fetch_enabled=False),store,provider=EmptyProvider())
    ids=[svc.create(SearchRequest(knowledge_points=[p]))['job_id'] for p in ['A','B','C']]
    original=store.get_job
    def failed(job_id):
        if job_id==ids[1]: raise RuntimeError('fixture database read failure')
        return original(job_id)
    monkeypatch.setattr(store,'get_job',failed)
    with pytest.raises(RuntimeError): svc._prune_queue()
    assert [svc.queue.get_nowait() for _ in ids]==ids
    assert svc.queue._unfinished_tasks==3
    for _ in ids: svc.queue.task_done()
    await asyncio.wait_for(svc.queue.join(),1)
    store.close()


@pytest.mark.asyncio
async def test_telemetry_read_failure_does_not_kill_worker(monkeypatch):
    store=Store(':memory:')
    svc=JobService(Settings(fetch_enabled=False),store,provider=EmptyProvider())
    svc.start()
    original=store.get_job
    fail=[False]
    ran=[]
    async def run(job_id):
        ran.append(job_id)
        job=original(job_id)
        job['status']='completed'
        store.save_job(job)
        fail[0]=True
    def read(job_id):
        if fail[0]:
            fail[0]=False
            raise RuntimeError('fixture telemetry read failure')
        return original(job_id)
    monkeypatch.setattr(svc,'run',run)
    monkeypatch.setattr(store,'get_job',read)
    for p in ['A','B']:
        svc.create(SearchRequest(knowledge_points=[p]))
        await asyncio.wait_for(svc.queue.join(),1)
    assert len(ran)==2 and svc.health()['worker_alive']
    await svc.stop()
    assert not svc.health()['worker_alive']
    store.close()


@pytest.mark.asyncio
async def test_search_course_without_catalog_returns_link_but_not_video():
    class Provider(EmptyProvider):
        async def search(self, *args):
            return [Candidate(id='c', title=course()['title'], url=course()['url'], snippet=course()['snippet'], source='fixture', query=args[0])]
    store = Store(':memory:')
    svc = JobService(Settings(fetch_enabled=False, max_detail_pages=0), store, provider=Provider())
    job = svc.create(SearchRequest(knowledge_points=['Python lists and dictionaries'], language='en', preferred_platforms=[]))
    await svc.run(job['job_id'])
    items = svc.results(job['job_id'])['groups'][0]['items']
    assert len(items) == 1
    assert items[0]['resource']['resource_type'] == 'course'
    assert items[0]['resource']['chapters'] == []
    assert items[0]['resource']['metadata_evidence_level'] == 'search'
    assert items[0]['resource']['video_evidence_status'] == 'none'
    assert items[0]['match']['matched_evidence_ids']
    store.close()


@pytest.mark.asyncio
async def test_content_soft_failure_uses_independent_source_and_keeps_budget():
    calls = []
    def respond(req):
        calls.append(req.url.params['engines'])
        if len(calls) == 1:
            return httpx.Response(200, json={'results': [{'title': 'Artificial film', 'url': 'https://example.org/film'}]})
        return httpx.Response(200, json={'results': [course()]})
    settings = Settings(searxng_url='http://fixture', searxng_engines=('primary',), searxng_fallback_engines=('backup',), search_min_interval_seconds=0)
    request = SearchRequest(knowledge_points=['Python lists and dictionaries'], language='en')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = SearXNGProvider(settings, client)
        items = await provider.search('Python lists dictionaries course', 'en', 5, [], candidate_check=lambda c: candidate_topic_signal(c, request.knowledge_points[0], request))
    assert calls == ['primary', 'backup'] and len(items) == 2
    assert provider.last_requests[0]['content_status'] == 'no_topic_signal'
    assert provider.last_requests[1]['topic_signal_count'] == 1


@pytest.mark.asyncio
async def test_dedup_and_topic_signal_before_limit():
    rows = [{'title': 'Python lists dictionaries course', 'url': 'https://127.0.0.1/courses/python'}]
    rows += [{'title': 'Unrelated film', 'url': f'https://example.org/film?utm_source={i}'} for i in range(8)]
    rows.append(course())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={'results':rows}))) as client:
        p = SearXNGProvider(Settings(searxng_url='http://fixture', search_min_interval_seconds=0), client)
        req = SearchRequest(knowledge_points=['Python lists and dictionaries'], language='en')
        items = await p.search('Python lists dictionaries course', 'en', 1, [], candidate_check=lambda c: candidate_topic_signal(c,req.knowledge_points[0],req))
    assert len(items) == 1 and items[0].url == course()['url']


@pytest.mark.asyncio
async def test_backup_same_url_preserves_stronger_search_observation():
    def respond(req):
        row = dict(course(), engines=[req.url.params['engines']])
        if req.url.params['engines']=='primary': row.update(title='Unrelated content',snippet='Unrelated')
        return httpx.Response(200,json={'results':[row]})
    req=SearchRequest(knowledge_points=['Python lists and dictionaries'],language='en')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        p=SearXNGProvider(Settings(searxng_url='http://fixture',searxng_engines=('primary',),searxng_fallback_engines=('backup',),search_min_interval_seconds=0),client)
        rows=await p.search('Python lists dictionaries course','en',5,[],candidate_check=lambda c:candidate_topic_signal(c,req.knowledge_points[0],req))
    assert len(rows)==2 and len({c.url for c in rows})==1
    assert any(candidate_topic_signal(c,req.knowledge_points[0],req) for c in rows)
    assert {c.source_engines[0] for c in rows}=={'primary','backup'}


@pytest.mark.asyncio
async def test_one_response_preserves_course_and_video_observations_for_one_url():
    body={'results':[dict(course(),engines=['web']),dict(course(),engines=['video'],template='videos.html')]}
    req=SearchRequest(knowledge_points=['Python lists and dictionaries'],language='en')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))) as client:
        p=SearXNGProvider(Settings(searxng_url='http://fixture',search_min_interval_seconds=0),client)
        rows=await p.search('Python lists dictionaries course','en',1,[],candidate_check=lambda c:candidate_topic_signal(c,req.knowledge_points[0],req))
    assert len({c.url for c in rows})==1 and len(rows)==2
    assert {c.resource_type_hint for c in rows}=={'unknown','video'}


@pytest.mark.asyncio
async def test_merged_sources_keep_unique_url_limit_and_prefer_relevant():
    def respond(req):
        row=course() if req.url.params['engines']=='backup' else {'title':'Unrelated film','url':'https://example.org/film'}
        return httpx.Response(200,json={'results':[row]})
    req=SearchRequest(knowledge_points=['Python lists and dictionaries'],language='en')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        p=SearXNGProvider(Settings(searxng_url='http://fixture',searxng_engines=('primary',),searxng_fallback_engines=('backup',),search_min_interval_seconds=0),client)
        rows=await p.search('Python lists dictionaries course','en',1,[],candidate_check=lambda c:candidate_topic_signal(c,req.knowledge_points[0],req))
    assert len(rows)==1 and rows[0].url==course()['url']


@pytest.mark.asyncio
async def test_queue_capacity_idempotency_cancel_and_wait_expiry():
    store = Store(':memory:')
    svc = JobService(Settings(max_pending_jobs=1, max_queue_wait_seconds=2, fetch_enabled=False), store, provider=EmptyProvider())
    req = SearchRequest(knowledge_points=['point A'])
    first = svc.create(req,'same')
    assert svc.create(req,'same')['reused']
    with pytest.raises(AdmissionRejected) as error:
        svc.create(SearchRequest(knowledge_points=['point B']),'rejected')
    assert error.value.code == 'queue_full' and store.idempotent_request('rejected') is None
    await svc.cancel(first['job_id'])
    next_job = svc.create(SearchRequest(knowledge_points=['point B']),'rejected')
    job = store.get_job(next_job['job_id'])
    job['created_at'] = (datetime.now(timezone.utc)-timedelta(seconds=3)).isoformat()
    store.save_job(job)
    await svc.run(job['job_id'])
    assert store.get_job(job['job_id'])['errors'][0]['code'] == 'queue_wait_expired'
    assert store.get_job(job['job_id'])['progress']['search_requests'] == 0
    store.close()


def test_http_admission_retry_after_and_live_health(tmp_path):
    with TestClient(create_app(Settings(database_path=str(tmp_path/'trial.sqlite'), submission_limit_per_minute=1,fetch_enabled=False),provider=EmptyProvider()), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as c:
        assert c.get('/health').json()['worker_alive']
        assert c.post('/api/search-jobs',json={'knowledge_points':['point A']}).status_code==202
        rejected=c.post('/api/search-jobs',json={'knowledge_points':['point B']})
        assert rejected.status_code==429 and int(rejected.headers['Retry-After'])>0
        assert rejected.json()['code']=='submission_rate_limited'
        assert c.get('/health').json()['admission_rejections']==1


@pytest.mark.asyncio
async def test_rate_limit_cooldown_expiry_recovers_once(monkeypatch):
    clock=[100.0]
    monkeypatch.setattr('backend.app.providers.time.monotonic',lambda:clock[0])
    calls=[]
    def respond(req):
        calls.append(1)
        return httpx.Response(429,headers={'Retry-After':'2'}) if len(calls)==1 else httpx.Response(200,json={'results':[]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        p=SearXNGProvider(Settings(searxng_url='http://fixture',search_min_interval_seconds=0),client)
        for _ in range(2):
            with pytest.raises(SearchError): await p.search('topic','en',5,[])
        assert len(calls)==1
        clock[0]=102.1
        assert await p.search('topic','en',5,[])==[]
        assert len(calls)==2 and p.last_status=='available'
