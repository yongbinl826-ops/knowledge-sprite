"""Actual application modules, synthetic HTTP/pages, accelerated event-loop clock.
These tests are offline integration evidence, NOT real provider/video results.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
import json
import httpx
import pytest
from backend.app import ai_video_service as av, grounded_related as gr
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.fetcher import FETCH_DEADLINE_AT
from backend.app.models import Candidate, SearchRequest, now
from backend.app.service import JobService
from test_grounded_related import TOPIC, TITLE, DESCRIPTION, source, inputs, decision, reply

OUT = None

@pytest.fixture(autouse=True)
def isolate_report_output(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "OUT", tmp_path)

GOOD='https://www.bilibili.com/video/BV1xx411c7Df/'
HANG='https://www.bilibili.com/video/BV1xx411c7Dg/'

class NoIOSelector:
    def get_map(self): return {}
    def select(self,timeout=None): return []
    def close(self): pass
    def register(self,*args): raise AssertionError("REAL_IO_FORBIDDEN")
    def unregister(self,*args): raise AssertionError("REAL_IO_FORBIDDEN")

class VirtualLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        self.virtual_now=1000.0
        super().__init__(selector=NoIOSelector())
    def _make_self_pipe(self): pass
    def _close_self_pipe(self): pass
    def _write_to_self(self): pass
    def time(self):
        return self.virtual_now
    def _run_once(self):
        if not self._ready and self._scheduled:
            self.virtual_now=max(self.virtual_now,self._scheduled[0]._when)
        super()._run_once()

def virtual(coroutine):
    with asyncio.Runner(loop_factory=VirtualLoop) as runner:
        return runner.run(coroutine)

class InitialSearch:
    name='offline-initial'
    async def search(self,*_):
        await asyncio.sleep(181)
        return []

class RecoverySearch:
    name='offline-source'
    def __init__(self,events): self.events=events
    async def search(self,query,*_):
        self.events.append({'phase':'search','at':asyncio.get_running_loop().time()})
        await asyncio.sleep(1)
        return [Candidate(id='fixture'+str(i), title='HTML learning '+str(i), url=url,
            snippet='HTML introduction',query=query,source=self.name,discovered_at=now())
            for i,url in enumerate([GOOD,HANG])]

class Pages:
    def __init__(self,events): self.events=events
    async def enrich(self,candidate):
        start=asyncio.get_running_loop().time()
        self.events.append({'phase':'page_start','url':candidate['url'],'at':start})
        if candidate['url']==HANG:
            try: await asyncio.Event().wait()
            finally: self.events.append({'phase':'hanging_page_stopped','at':asyncio.get_running_loop().time()})
        await asyncio.sleep(35)
        node={'@context':'https://schema.org','@type':'VideoObject','name':TITLE,
            'description':DESCRIPTION,'contentUrl':'https://media.example.org/video.mp4'}
        self.events.append({'phase':'good_page_returned','at':asyncio.get_running_loop().time()})
        return MetadataExtractor().extract('<script type="application/ld+json">'+json.dumps(node)+'</script>',candidate['url'],now())

class Discovery:
    def __init__(self,events): self.events=events;self.calls=0
    async def expand(self,*_): return []
    async def suggest_video_discovery(self,points,*_,**__):
        self.calls+=1
        self.events.append({'phase':'discovery','at':asyncio.get_running_loop().time()})
        await asyncio.sleep(20)
        return {point:{'urls':[],'queries':[]} for point in points}

def make_settings(path):
    return replace(Settings(),database_path=str(path),shared_course_library_enabled=False,
        mooc_gap_search_enabled=False,mooc_refresh_enabled=False,public_catalog_fallback=False,
        official_sitemap_fallback=False,teaching_match_enabled=False,search_min_interval_seconds=0,
        search_max_retries=0,max_search_requests=30,max_detail_pages=15,
        bilibili_public_metadata=True,ai_video_fallback_enabled=True,deadline_seconds=360,
        llm_provider='openai_compatible',llm_api_key='offline-key',llm_model='offline-model',
        llm_base_url='https://model.example/v1')

async def own_answer(request,events,delay=18):
    payload=json.loads(json.loads(request.content)['messages'][1]['content'])
    stage='judgment' if 'pairs' in payload else 'review'
    events.append({'phase':stage,'at':asyncio.get_running_loop().time()})
    await asyncio.sleep(delay)
    if stage=='judgment':
        decisions=[]
        for pair in payload['pairs']:
            observed=next(o for o in pair['observations'] if o['basis']=='description')
            decisions.append({'pair_id':pair['pair_id'],'fingerprint':pair['fingerprint'],'support':{
                'evidence_id':observed['evidence_id'],'basis':'description','quote':observed['segments'][0],
                'source_text_sha256':observed['source_text_sha256']}})
        return reply({'decisions':decisions})
    return reply({'decisions':[{'pair_id':c['pair_id'],'accepted':True} for c in payload['claims']]})

@pytest.mark.parametrize('query_count',[1,3])
def test_real_pipeline_pending_sibling_cannot_cancel_late_page_final_review(tmp_path,monkeypatch,query_count):
    async def execute():
        events=[];settings=make_settings(tmp_path/'actual.sqlite3');store=Store(settings.database_path)
        model=Discovery(events)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: own_answer(request,events))) as client:
            model.client=client
            service=JobService(settings,store,provider=InitialSearch(),fetcher=Pages(events),llm=model)
            provider=RecoverySearch(events)
            service._ai_search_source=lambda *_: ('offline-source',provider,None)
            monkeypatch.setattr(av,'video_recovery_search_phrases_with_diagnostics',
                lambda *_: ([TOPIC+' '+str(i) for i in range(query_count)],{'status':'synthetic_test'}))
            identifier=service.create(inputs()[1])['job_id']
            await service.run(identifier)
            job=store.get_job(identifier)
            covered=av.visible_point_ids(service,job)
            assert len(covered)==1,job.get('grounded_related')
            assert model.calls==1
            assert job['grounded_related']['judgment_calls']==1
            assert job['grounded_related']['review_calls']==1
            assert job['grounded_related']['accepted']==1
            stages=[e['phase'] for e in events]
            assert stages.index('good_page_returned') < stages.index('hanging_page_stopped') < stages.index('judgment') < stages.index('review')
            assert asyncio.get_running_loop().time()<=1360
            assert all(t is asyncio.current_task() or t.done() for t in asyncio.all_tasks())
            result={'kind':'actual_module_offline_virtual_time','query_count':query_count,'events':events,
                'ended_at':asyncio.get_running_loop().time(),'deadline':1360,'covered':len(covered),
                'grounded':job['grounded_related'],'fallback':job['ai_video_fallback']}
            (OUT/f'actual-pipeline-{query_count}-queries.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        store.close()
    virtual(execute())

@pytest.mark.parametrize('failure',['timeout','schema','httpx_timeout','json_parse'])
def test_actual_function_transport_failure_preserves_slot_then_old_pool_is_reviewed(tmp_path,failure):
    async def execute():
        settings=make_settings(tmp_path/'transport.sqlite3');store=Store(settings.database_path);events=[]
        model=Discovery(events);service=JobService(settings,store,provider=InitialSearch(),fetcher=Pages(events),llm=model)
        job=store.get_job(service.create(inputs()[1])['job_id']);point=job['knowledge_points'][0];pid=point['knowledge_point_id']
        resources={}
        for rid,title,description in [('old-rank1','HTML fundamentals','HTML document structure and headings.'),('old-rank2',TITLE,DESCRIPTION)]:
            resource,evidence=source(title,description);resource['resource_id']=rid
            url=HANG if rid=='old-rank1' else GOOD
            resource.update(url=url,canonical_url=url,resolved_url=url)
            for provenance in resource['field_provenance'].values(): provenance.update(url=url,evidence_id=rid+'-'+provenance['evidence_id'])
            for row in evidence: row.update(url=url,evidence_id=rid+'-'+row['evidence_id'])
            resources[rid]=resource;store.save_resource(job['job_id'],resource)
            for row in evidence: store.add_evidence(job['job_id'],rid,pid,row)
        state={'request':inputs()[1],'points':[point],'resources':resources,'candidate_groups':{pid:list(resources)},'reserved':2}
        calls=0
        async def respond(request):
            nonlocal calls
            calls+=1
            if calls==1:
                if failure=='timeout': await asyncio.sleep(25)
                if failure=='httpx_timeout': raise httpx.ReadTimeout('PRIVATE_SYNTHETIC_TIMEOUT')
                if failure=='json_parse': return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{invalid'}}]})
                return reply({'bad':'schema'})
            return await own_answer(request,events,delay=18)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model.client=client
            token=FETCH_DEADLINE_AT.set(1360)
            try:
                # Force the current generic rank to reproduce old/new accounting;
                # the final selection must still consider the old rank2 source.
                original=av._discovery_priority
                av._discovery_priority=lambda _s,_p,_r,title,_d: (1,2 if title=='HTML fundamentals' else 1,0)
                await av._recover_from_own_metadata(service,job,state,[point])
                assert job['grounded_related']['point_attempts'].get(pid,0)==0
                assert job['grounded_related']['judgment_calls']==1
                await av._recover_from_own_metadata(service,job,state,[point],final=True)
                assert job['grounded_related']['review_calls']==1
                assert job['grounded_related']['judgment_calls']==2
                assert av.visible_point_ids(service,job)=={pid}
                assert 'old-rank2' in job['grounded_related']['decisions'][pid]
                assert max(job['grounded_related']['transport_starts'].values())<=2
                ledger=job['grounded_related']['calls']
                expected_failure='timeout' if failure in {'timeout','httpx_timeout'} else 'schema'
                assert [r['outcome'] for r in ledger]==[expected_failure,'ok','ok']
                assert [r['call_index'] for r in ledger]==[1,2,3]
                assert job['grounded_related']['status']=='completed'
                assert 'error_type' not in job['grounded_related']
                assert job['grounded_related']['last_error']['outcome']==expected_failure
                assert all(set(row)=={'call_index','phase','elapsed_seconds','outcome'} for row in ledger)
                (OUT/f'actual-transport-{failure}.json').write_text(json.dumps({'kind':'actual_module_offline_virtual_time',
                    'events':events,'grounded':job['grounded_related']},ensure_ascii=False,indent=2),encoding='utf-8')
            finally:
                av._discovery_priority=original
                FETCH_DEADLINE_AT.reset(token)
        store.close()
    virtual(execute())

def test_actual_effective_deadline_does_not_use_later_global_deadline(tmp_path):
    async def execute():
        settings=make_settings(tmp_path/'deadline.sqlite3');store=Store(settings.database_path);events=[]
        service=JobService(settings,store,provider=InitialSearch(),fetcher=Pages(events),llm=Discovery(events))
        token=FETCH_DEADLINE_AT.set(1360)
        try:
            assert av._fallback_deadline(service,{'fallback_effective_deadline':1330})==1330
            assert av._grounded_final_reserve(service,{}, {'fallback_effective_deadline':1330})==80
        finally: FETCH_DEADLINE_AT.reset(token);store.close()
    virtual(execute())



@pytest.mark.parametrize('mode',['no_detail','legacy_urls','no_queries','no_search_budget','no_platforms'])
def test_actual_final_audits_existing_pool_without_new_source_capacity(tmp_path,monkeypatch,mode):
    async def execute():
        settings=make_settings(tmp_path/(mode+'.sqlite3'));store=Store(settings.database_path);events=[]
        model=Discovery(events)
        async def legacy(*args,**kwargs): model.calls+=1;return {}
        if mode=='legacy_urls':
            model.suggest_video_discovery=None
            model.suggest_video_urls=legacy
        request=inputs()[1]
        if mode=='no_platforms': request=request.model_copy(update={'preferred_platforms':['xuetangx']})
        service=JobService(settings,store,provider=InitialSearch(),fetcher=Pages(events),llm=model)
        provider=RecoverySearch(events)
        service._ai_search_source=lambda *_: ('offline-source',provider,None)
        job=store.get_job(service.create(request)['job_id']);pid=job['knowledge_points'][0]['knowledge_point_id']
        resource,evidence=source()
        if mode=='no_platforms':
            url='https://www.xuetangx.com/course/offline-source'
            resource.update(url=url,canonical_url=url,resolved_url=url,platform='xuetangx')
            for provenance in resource['field_provenance'].values():provenance['url']=url
            for row in evidence:row['url']=url
        rid=resource['resource_id'];store.save_resource(job['job_id'],resource)
        for row in evidence:store.add_evidence(job['job_id'],rid,pid,row)
        state={'request':request,'points':job['knowledge_points'],'resources':{rid:resource},
            'candidates':{},'candidate_groups':{pid:[rid]},'started':{rid},'reserved':1,
            'network_slots':asyncio.Semaphore(2)}
        if mode=='no_detail':state['reserved']=settings.max_detail_pages
        if mode=='no_search_budget':job['progress']['search_requests']=job['budgets']['max_search_requests']
        if mode=='no_queries':monkeypatch.setattr(av,'video_recovery_search_phrases_with_diagnostics',lambda *_:([],{}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:own_answer(request,events))) as client:
            model.client=client;token=FETCH_DEADLINE_AT.set(1360)
            try:
                await av.run_ai_video_fallback(service,job,state,effective_deadline=1100)
                assert av.visible_point_ids(service,job)=={pid}
                assert job['grounded_related']['judgment_calls']==1
                assert job['grounded_related']['review_calls']==1
                assert not [e for e in events if e['phase'] in {'search','page_start'}]
                assert model.calls==(0 if mode=='no_detail' else 1)
                assert asyncio.get_running_loop().time()<=1100
            finally:FETCH_DEADLINE_AT.reset(token)
        store.close()
    virtual(execute())


def test_actual_positive_review_timeout_can_be_rejudged_once_then_reviewed(tmp_path):
    async def execute():
        settings=make_settings(tmp_path/'review-retry.sqlite3');store=Store(settings.database_path);events=[]
        model=Discovery(events);service=JobService(settings,store,provider=InitialSearch(),fetcher=Pages(events),llm=model)
        request=inputs()[1];job=store.get_job(service.create(request)['job_id']);point=job['knowledge_points'][0];pid=point['knowledge_point_id']
        resource,evidence=source();rid=resource['resource_id'];store.save_resource(job['job_id'],resource)
        for row in evidence:store.add_evidence(job['job_id'],rid,pid,row)
        state={'request':request,'points':[point],'resources':{rid:resource},'candidate_groups':{pid:[rid]},'reserved':1}
        calls=0
        async def respond(request):
            nonlocal calls
            calls+=1
            return await own_answer(request,events,delay=25 if calls==2 else 18)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model.client=client;token=FETCH_DEADLINE_AT.set(1360)
            try:
                await av._recover_from_own_metadata(service,job,state,[point])
                stats=job['grounded_related']
                assert stats['judgment_calls']==stats['review_calls']==1
                assert stats['point_attempts'].get(pid,0)==0
                assert stats['judged']=={} and not av.visible_point_ids(service,job)
                await av._finish_grounded_recovery(service,job,state,[point])
                assert stats['judgment_calls']==stats['review_calls']==2
                assert stats['point_attempts'][pid]==1
                assert list(stats['transport_starts'].values())==[2]
                assert [r['outcome'] for r in stats['calls']]==['ok','timeout','ok','ok']
                assert stats['status']=='completed' and 'error_type' not in stats
                assert av.visible_point_ids(service,job)=={pid}
                (OUT/'actual-review-timeout-retry.json').write_text(json.dumps({'kind':'actual_module_offline_virtual_time',
                    'events':events,'grounded':stats},ensure_ascii=False,indent=2),encoding='utf-8')
            finally:FETCH_DEADLINE_AT.reset(token)
        store.close()
    virtual(execute())

@pytest.mark.parametrize('third_result',['unknown','support'])
def test_actual_three_judgment_attempts_report_consistent_caps_without_fourth(tmp_path,third_result):
    async def execute():
        settings=make_settings(tmp_path/'three-attempts.sqlite3');store=Store(settings.database_path);events=[]
        model=Discovery(events);service=JobService(settings,store,provider=InitialSearch(),fetcher=Pages(events),llm=model)
        request=inputs()[1];job=store.get_job(service.create(request)['job_id']);point=job['knowledge_points'][0];pid=point['knowledge_point_id']
        resources={}
        for index in range(2):
            resource,evidence=source();rid='candidate_'+str(index);url=GOOD if index==0 else HANG
            resource.update(resource_id=rid,url=url,canonical_url=url,resolved_url=url)
            for provenance in resource['field_provenance'].values():provenance.update(url=url,evidence_id=rid+'-'+provenance['evidence_id'])
            for row in evidence:row.update(url=url,evidence_id=rid+'-'+row['evidence_id'])
            store.save_resource(job['job_id'],resource)
            for row in evidence:store.add_evidence(job['job_id'],rid,pid,row)
            resources[rid]=resource
        state={'request':request,'points':[point],'resources':resources,'candidate_groups':{pid:list(resources)},'reserved':2}
        calls=0
        async def respond(request):
            nonlocal calls
            calls+=1
            if calls<=2:await asyncio.sleep(25)
            data=json.loads(json.loads(request.content)['messages'][1]['content'])
            if calls==3 and third_result=='unknown':
                return reply({'decisions':[{'pair_id':p['pair_id'],'fingerprint':p['fingerprint'],'support':None} for p in data['pairs']]})
            return await own_answer(request,events,delay=18)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model.client=client;token=FETCH_DEADLINE_AT.set(1360)
            try:
                await av._recover_from_own_metadata(service,job,state,[point])
                await av._finish_grounded_recovery(service,job,state,[point])
                stats=job['grounded_related'];before=calls
                assert stats['batches']==stats['judgment_calls']==3
                assert stats['review_calls']==int(third_result=='support')
                assert calls==(4 if third_result=='support' else 3)
                assert len(stats['calls'])==calls
                assert max(stats['transport_starts'].values())==2
                assert job['budgets']['grounded_related_max_batches']==3
                assert job['budgets']['grounded_related_max_model_calls']==4
                assert gr.MAX_BATCHES==3 and gr.MAX_MODEL_CALLS==4
                text=json.dumps(service.capabilities())
                assert '"max_batches_per_job": 3' in text and '"max_model_calls_per_job": 4' in text
                await av._finish_grounded_recovery(service,job,state,[point])
                assert calls==before  # Fourth judgment may not consume its review reserve.
                assert bool(av.visible_point_ids(service,job))==(third_result=='support')
                (OUT/f'actual-three-attempts-{third_result}.json').write_text(json.dumps({'kind':'actual_module_offline_virtual_time',
                    'grounded':stats,'budget':{k:v for k,v in job['budgets'].items() if k.startswith('grounded_')}},indent=2),encoding='utf-8')
            finally:FETCH_DEADLINE_AT.reset(token)
        store.close()
    virtual(execute())
