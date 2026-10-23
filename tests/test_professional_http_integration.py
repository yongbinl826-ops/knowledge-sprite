"""Real FastAPI/ProjectAnalyzer integration, wholly offline ASGI/MockTransport.

The native-shaped course URLs and metadata below are explicit test fixtures,
not records from a real platform query or claims about course availability.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from tests.professional_contract_support import flat_proposal

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import Candidate
from backend.app.project_analysis import ProjectAnalyzer


V1=json.loads((Path(__file__).parent/'fixtures/professional_http/original-v1.json').read_text(encoding='utf-8'))


class NoSearchLLM:
    def __init__(self):self.calls=[]
    async def expand(self,*args,**kwargs):
        self.calls.append('expand');raise AssertionError('Search must not call any model')
    async def rerank(self,*args,**kwargs):
        self.calls.append('rerank');raise AssertionError('Search must not call any model')


class MockPlatforms:
    def __init__(self):self.calls=[];self.metrics={'active':0,'peak':0}
    async def search(self,query,language,limit,domains,**kwargs):
        self.calls.append({'query':query,'language':language,'domains':domains})
        # Platform lanes shallow-copy injected providers for isolated trace
        # attributes. A shared dict accurately observes both copies' activity.
        self.metrics['active']+=1;self.metrics['peak']=max(self.metrics['peak'],self.metrics['active'])
        await asyncio.sleep(0)
        self.metrics['active']-=1
        bili=domains==['bilibili.com']
        if not domains:
            assert 'site:' not in query
            return []  # Actual unrestricted lane is exercised, without inventing another course.
        assert bili or domains==['icourse163.org']
        return [Candidate(id='offline-bili' if bili else 'offline-mooc',
            title='Offline fixture video' if bili else 'Offline fixture course',
            url='https://www.bilibili.com/video/BVoffline001/' if bili else 'https://www.icourse163.org/course/OFFLINE-1',
            snippet='Synthetic course metadata for ASGI integration only',source='explicit-offline-fixture',query=query,
            resource_type_hint='video' if bili else 'course',type_source='search_template' if bili else None,
            thumbnail_url='https://images.example/offline-cover.png',thumbnail_source='search.thumbnail')]


class NoPageNetwork:
    def __init__(self):self.calls=[]
    async def enrich(self,*args,**kwargs):
        self.calls.append(args);raise AssertionError('The offline discovery test reserves zero detail pages')


def settings(tmp_path):
    return Settings(database_path=str(tmp_path/'asgi.sqlite3'),
        llm_provider='openai_compatible',llm_base_url='https://offline-model.example/v1',
        llm_api_key='offline-configured-credential-never-in-api',llm_model='offline-professional-model',
        project_semantic_review_enabled=True,parallel_platform_search=True,teaching_match_enabled=False,
        global_concurrency=2,max_search_requests=30,max_detail_pages=0,search_min_interval_seconds=0,
        deadline_seconds=5,project_deadline_seconds=60)


async def poll(api,url,predicate):
    for _ in range(250):
        response=await api.get(url)
        assert response.status_code==200,response.text
        body=response.json()
        if predicate(body):return body
        await asyncio.sleep(.01)
    raise AssertionError('Offline API state did not reach the expected terminal condition')


@pytest.mark.asyncio
async def test_http_create_real_analyze_edit_optional_ack_two_platform_search_history_and_empty_selection(tmp_path,monkeypatch):
    config=settings(tmp_path);model_calls=[];provider=MockPlatforms();fetcher=NoPageNetwork();no_llm=NoSearchLLM()
    def model_response(req):
        assert req.url.host=='offline-model.example' and req.url.path.endswith('/chat/completions')
        model_calls.append(json.loads(req.content))
        # V5 mock output uses an independent concept; original retained v1 bytes stay unchanged.
        generated=deepcopy(V1)
        generated['knowledge_points'][1]['name']='pandas 缺失值处理'
        generated=flat_proposal(generated)
        assert len(model_calls)<=2,'Generation and normalization share the existing call budget'
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(generated,ensure_ascii=False)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(model_response)) as model_client:
        analyzer=ProjectAnalyzer(config,model_client)
        app=create_app(config,provider=provider,fetcher=fetcher,llm=no_llm,analyzer=analyzer)
        async with app.router.lifespan_context(app):
            search_scopes=[];original_cache_key=app.state.store.cache_key
            def cache_key(kind,fields):
                if kind=='search':search_scopes.append(deepcopy(fields))
                return original_cache_key(kind,fields)
            monkeypatch.setattr(app.state.store,'cache_key',cache_key)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',12345)),base_url='http://127.0.0.1') as api:
                original={'name':'  成绩工具  ','requirements':'读取本地 Excel 成绩表\n统计平均分',
                    'student_level':'intermediate','language':'en','project_context':'已有 Python 使用经验',
                    'preferred_platforms':['bilibili','icourse163']}
                created=await api.post('/api/projects',json=original)
                assert created.status_code==201
                pid=created.json()['project_id']
                generated=await api.post(f'/api/projects/{pid}/analyze',json={'expected_version':0})
                assert generated.status_code==202
                view=await poll(api,f'/api/projects/{pid}',lambda b:b['version']['status']!='analyzing')
                assert view['version']['status']=='analyzed'
                assert view['original_input']==view['version']['input']==original|{'technical_version':''}
                assert len(model_calls)==2
                assert [(entry['phase'],entry['outcome']) for entry in view['version']['analysis_attempts']]==[
                    ('generation','draft'),('normalization','accepted')]
                assert not view['version'].get('rejected_analysis_attempts')
                normalization=json.loads(model_calls[1]['messages'][1]['content'])
                assert normalization['normalization_required'] is True
                assert normalization['project']==original|{'technical_version':''}
                assert normalization['previous_analysis']['knowledge_points'][1]['name']=='pandas 缺失值处理'
                assert all(not point.get('learning_skills') and not point.get('concepts') for point in view['version']['analysis']['knowledge_points'])
                capability=(await api.get('/api/capabilities')).json()['project_analysis']
                assert capability['mode']=='professional_knowledge_points'
                assert capability['max_model_calls']==2 and capability['semantic_review_enabled'] is False
                assert capability['review_max_calls']==0
                assert capability['concept_normalization_enabled'] is True
                assert capability['normalization_max_calls']==1
                assert capability['normalization_max_output_tokens']==12000
                assert capability['generation_stages']==['generation','normalization']

                edited=deepcopy(view['version']['analysis'])
                # A current flat analysis lets students select concepts directly.
                edited['knowledge_points'][0].update(name='pandas Excel 文件读取',selection='skip')
                edited['knowledge_points'][1].update(name='pandas分组聚合',selection='learn')
                edit=await api.post(f'/api/projects/{pid}/edit',json={'expected_version':1,'analysis':edited})
                assert edit.status_code==200 and edit.json()['current_version']==2
                confirmed=await api.post(f'/api/projects/{pid}/confirm',json={'version':2})
                assert confirmed.status_code==200
                snapshot=deepcopy(confirmed.json()['version']['confirmation'])
                assert snapshot['selected_ids']==['k2'] and 'acknowledged_skipped_prerequisites' not in snapshot
                assert snapshot['search_mode']=='professional_terms_v1'
                assert snapshot['analysis']['knowledge_points'][1]['name']=='pandas分组聚合'
                assert (await api.post(f'/api/projects/{pid}/search',json={'version':2})).status_code==202
                result=await poll(api,f'/api/projects/{pid}/results',lambda b:b['version']['status'] in {'completed','partial','failed','no_results'})
                assert result['version']['status']=='completed'
                assert len(result['version']['batches'])==1
                batch=result['version']['batches'][0];jid=batch['job_id']
                job_response=await api.get(f'/api/search-jobs/{jid}');assert job_response.status_code==200
                job=job_response.json()
                assert job['request']['knowledge_points']==['pandas 分组聚合']
                assert not job['request'].get('learning_targets') and not job['request'].get('learning_skills')
                assert job['request']['student_level']=='intermediate' and job['request']['language']=='en'
                assert job['progress']['search_requests']==5 and job['progress']['platform_search_requests']=={'bilibili':2,'icourse163':2,'open_web':1}
                selected=next(p for p in result['points'] if p['project_knowledge_point_id']=='k2')
                skipped=next(p for p in result['points'] if p['project_knowledge_point_id']=='k1')
                assert skipped['status']=='skip' and skipped['result'] is None
                assert selected['name']=='pandas分组聚合' and selected['knowledge_point_id']==job['knowledge_points'][0]['knowledge_point_id']
                assert selected['result']['text']=='pandas 分组聚合'
                assert set(selected['result']['discovery_platform_items'])=={'bilibili'}
                assert len(selected['result']['discovery_items'])==1 and all(item['resource']['thumbnail_url'] for item in selected['result']['discovery_items'])
                retained=app.state.store.resources(jid)
                assert {resource['platform'] for resource in retained.values()}=={'bilibili','icourse163'}
                mooc=selected['result']['mooc_relevance']
                assert mooc['candidate_count']==1 and mooc['recommended_count']==0
                mooc_candidate=mooc['candidates'][0]
                assert mooc_candidate['assessment']['display_eligible'] is False
                mooc_resource=retained[mooc_candidate['resource_id']]
                assert mooc_resource['platform']=='icourse163' and mooc_resource['thumbnail_url']
                assert mooc_resource['fetch_status']=='not_fetched' and mooc_resource['chapters']==[]
                observations=[row for row in app.state.store.evidence(jid,mooc_candidate['resource_id']) if row['kind']=='search']
                assert len(observations)==2
                assert selected['result']['items']==selected['result']['partial_items']==[]
                assert 'learning_coverage' not in selected['result']
                assert provider.metrics['peak']==2 and len(provider.calls)==5 and fetcher.calls==no_llm.calls==[]
                bili_queries=[call['query'] for call in provider.calls if call['domains']==['bilibili.com']]
                mooc_queries=[call['query'] for call in provider.calls if call['domains']==['icourse163.org']]
                assert bili_queries==['site:bilibili.com/video pandas 分组聚合 video tutorial',
                                     'site:bilibili.com/video pandas 分组聚合 video tutorial examples']
                assert mooc_queries==['site:icourse163.org/course pandas 分组聚合 course',
                                     'site:icourse163.org/course pandas data analysis course content']
                assert len({scope['query'] for scope in search_scopes})==5 and all(scope['original_point']=='pandas 分组聚合' for scope in search_scopes)
                assert sum(not call['domains'] for call in provider.calls)==1
                assert {row['query'] for row in observations}==set(mooc_queries)
                assert all(row['knowledge_point_id']==selected['knowledge_point_id']
                           and row['source']=='explicit-offline-fixture' and row['url']==mooc_resource['url']
                           and row['title']=='Offline fixture course'
                           and row['snippet']=='Synthetic course metadata for ASGI integration only'
                           for row in observations)
                assert result['version']['confirmation']==snapshot
                assert not any(k.startswith('reserved_teaching') for k in result['version']['budgets'])

                # New empty selection makes no new job, never removes a saved one.
                empty=deepcopy(result['version']['analysis'])
                for point in empty['knowledge_points']:point['selection']='mastered'
                saved_jobs=app.state.store.job_counts();calls_before=len(provider.calls)
                assert (await api.post(f'/api/projects/{pid}/edit',json={'expected_version':2,'analysis':empty})).status_code==200
                assert (await api.post(f'/api/projects/{pid}/confirm',json={'version':3})).status_code==200
                empty_search=await api.post(f'/api/projects/{pid}/search',json={'version':3})
                assert empty_search.status_code==202 and empty_search.json()['version']['status']=='completed'
                assert empty_search.json()['version']['batches']==[]
                assert app.state.store.job_counts()==saved_jobs and len(provider.calls)==calls_before

                before=app.state.store.connection.total_changes
                historic=(await api.get(f'/api/projects/{pid}/results?version=2')).json()
                first=(await api.get(f'/api/projects/{pid}?version=1')).json()
                assert historic['version']['analysis']==result['version']['analysis']
                assert historic['version']['confirmation']==snapshot and first['version']['version']==1
                assert first['version']['analysis']['knowledge_points'][1]['name']=='pandas 缺失值处理'
                assert first['version']['analysis_attempts']==view['version']['analysis_attempts']
                assert V1['knowledge_points'][1]['name']=='pandas 缺失值处理与平均值统计'  # retained v1 fixture stays byte-compatible
                historic_selected=next(p for p in historic['points'] if p['project_knowledge_point_id']=='k2')['result']
                assert len(historic_selected['discovery_items'])==1
                assert historic_selected['mooc_relevance']==mooc
                assert (await api.post(f'/api/projects/{pid}/search',json={'version':2})).status_code==202
                assert (await api.post(f'/api/projects/{pid}/edit',json={'expected_version':1,'analysis':edited})).status_code==409
                assert app.state.store.connection.total_changes==before
                assert len(provider.calls)==calls_before and len(model_calls)==2 and no_llm.calls==[]
                assert config.llm_api_key not in json.dumps([result,historic,first,empty_search.json(),capability],ensure_ascii=False)


@pytest.mark.asyncio
async def test_http_rejected_input_is_not_echoed_and_makes_no_model_or_platform_calls(tmp_path):
    config=settings(tmp_path);provider=MockPlatforms();fetcher=NoPageNetwork();no_llm=NoSearchLLM();model_calls=[]
    def no_model(req):model_calls.append(req);raise AssertionError('Invalid API input must not call a model')
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_model)) as model_client:
        app=create_app(config,provider=provider,fetcher=fetcher,llm=no_llm,analyzer=ProjectAnalyzer(config,model_client))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',12346)),base_url='http://127.0.0.1') as api:
                marker='UNTRUSTED_INPUT_MUST_NOT_BE_ECHOED_20261019'
                rejected=await api.post('/api/projects',json={'name':'','requirements':marker,'llm_api_key':marker})
                assert rejected.status_code==422 and marker not in rejected.text
                assert all('input' not in detail for detail in rejected.json()['detail'])
                assert rejected.headers['cache-control']=='no-store' and rejected.headers['x-content-type-options']=='nosniff'
                assert app.state.store.job_counts()=={} and app.state.projects.db.list()==[]
                assert model_calls==provider.calls==fetcher.calls==no_llm.calls==[]
