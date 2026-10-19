"""Explicitly offline professional-term adapter contracts; no real services."""
import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest
import httpx

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import Candidate, SearchRequest, now
from backend.app.project_service import ProjectError, ProjectService
from backend.app.service import JobService
from backend.app.providers import SearXNGProvider
from test_projects import OfflineAnalyzer, NoFetch, analyzed, settle
from test_parallel_platform_search import options as lane_options, request as lane_request, platform, response


class OfflinePlatforms:
    def __init__(self):self.calls=[]
    async def search(self,query,language,limit,domains,**kwargs):
        self.calls.append(query)
        bili='bilibili.com' in domains[0]
        return [Candidate(id='bili' if bili else 'mooc',title='Offline source '+query,
            url='https://www.bilibili.com/video/BV1q741157jG/' if bili else 'https://www.icourse163.org/course/QA-123',
            snippet='An offline course listing',source='offline',query=query,
            resource_type_hint='video' if bili else 'course',type_source='search_template' if bili else None)]


def setup(tmp_path):
    config=Settings(database_path=str(tmp_path/'professional.sqlite3'),parallel_platform_search=True,
        teaching_match_enabled=False,max_search_requests=30,max_detail_pages=0,deadline_seconds=5,
        project_deadline_seconds=60,search_min_interval_seconds=0)
    store=Store(config.database_path);provider=OfflinePlatforms()
    jobs=JobService(config,store,provider=provider,fetcher=NoFetch())
    projects=ProjectService(config,store,jobs,analyzer=OfflineAnalyzer())
    return config,store,jobs,projects,provider


async def prepared(tmp_path,count=1):
    _,store,jobs,projects,provider=setup(tmp_path)
    view=await analyzed(projects,count,preferred_platforms=['bilibili','icourse163'],student_level='intermediate',language='en')
    return store,jobs,projects,provider,view['project_id']


def rewrite(projects,pid,change):
    data=projects.db.version(pid,1);change(data['analysis']);projects.db.save(pid,data)
    return deepcopy(data['analysis'])


@pytest.mark.asyncio
async def test_v1_without_yesterday_fields_confirms_and_searches_professional_names_only(tmp_path,monkeypatch):
    store,jobs,projects,provider,pid=await prepared(tmp_path)
    search_scopes=[];original_cache_key=store.cache_key
    def cache_key(kind,fields):
        if kind=='search':search_scopes.append(deepcopy(fields))
        return original_cache_key(kind,fields)
    monkeypatch.setattr(store,'cache_key',cache_key)
    original=rewrite(projects,pid,lambda a:a['knowledge_points'][0].update(name='Python二维列表索引'))
    jobs.start()
    try:
        confirmation=projects.confirm(pid,1,[])['version']['confirmation']
        assert confirmation['search_mode']=='professional_terms_v1'
        assert confirmation['analysis']==original
        assert not any(k.startswith('reserved_teaching') for k in projects.view(pid)['version']['budgets'])
        projects.search(pid,1);await settle(projects)
        result=projects.results(pid,1);batch=result['version']['batches'][0]
        job=store.get_job(batch['job_id'])
        assert [p['text'] for p in job['knowledge_points']]==['Python 二维列表索引']
        assert not job['request'].get('learning_targets') and not job['request'].get('learning_skills')
        assert job['request']['student_level']=='intermediate' and job['request']['language']=='en'
        assert result['points'][0]['name']=='Python二维列表索引'
        assert result['points'][0]['knowledge_point_id']==job['knowledge_points'][0]['knowledge_point_id']
        group=result['points'][0]['result']
        assert set(group['discovery_platform_items'])=={'bilibili'}
        assert len(group['discovery_items'])==1
        retained=store.resources(batch['job_id'])
        assert {resource['platform'] for resource in retained.values()}=={'bilibili','icourse163'}
        diagnostic=group['mooc_relevance']
        assert diagnostic['candidate_count']==1 and diagnostic['recommended_count']==0
        candidate=diagnostic['candidates'][0]
        assert retained[candidate['resource_id']]['platform']=='icourse163'
        assert candidate['assessment']['display_eligible'] is False
        observations=[row for row in store.evidence(batch['job_id'],candidate['resource_id']) if row['kind']=='search']
        assert len(observations)==2
        assert job['progress']['platform_search_requests']=={'bilibili':2,'icourse163':2}
        bili_queries=[query for query in provider.calls if platform(query)=='bilibili']
        mooc_queries=[query for query in provider.calls if platform(query)=='icourse163']
        assert bili_queries==['site:bilibili.com/video Python 二维列表索引 video tutorial',
                             'site:bilibili.com/video Python 二维列表索引 video tutorial examples']
        assert mooc_queries==['site:icourse163.org/course Python 二维列表索引 course',
                             'site:icourse163.org/course Python programming course content']
        assert len(search_scopes)==4 and all(scope['original_point']=='Python 二维列表索引' for scope in search_scopes)
        assert {row['query'] for row in observations}==set(mooc_queries)
        assert all(row['knowledge_point_id']==job['knowledge_points'][0]['knowledge_point_id']
                   and row['source']=='offline' and row['url']==retained[candidate['resource_id']]['url']
                   and row['title']=='Offline source '+row['query'] and row['snippet']=='An offline course listing'
                   for row in observations)
        assert group['text']=='Python 二维列表索引'
        assert job['request']['knowledge_points']==['Python 二维列表索引']
    finally:
        await projects.stop();await jobs.stop();store.close()


@pytest.mark.asyncio
async def test_invalid_hidden_legacy_fields_and_profile_do_not_gate_new_confirm_or_enter_search(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path)
    def change(a):
        a['technical_plan']='OLD_HIDDEN_PLAN_MUST_NOT_DRIVE_SEARCH'
        a['learner_profile']={'assumed_knowledge':[''],'invalid_legacy':'retained'}
        a['knowledge_points'][0].update(name='CSV 解析',technology='OLD_HIDDEN_TOOL',project_task='',
            concepts=['','https://invalid.example/retained'],learning_skills=['','duplicate','duplicate'],practice_check='')
    original=rewrite(projects,pid,change)
    jobs.start()
    try:
        view=projects.confirm(pid,1,[])
        assert view['version']['analysis']==view['version']['confirmation']['analysis']==original
        assert not any(k.startswith('reserved_teaching') for k in view['version']['budgets'])
        projects.search(pid,1);await settle(projects)
        result=projects.results(pid,1);job=store.get_job(result['version']['batches'][0]['job_id'])
        assert job['request']['knowledge_points']==['CSV 解析']
        assert not job['request'].get('learning_targets') and not job['request'].get('learning_skills')
        assert 'OLD_HIDDEN_PLAN' not in job['request']['project_context']
        assert 'OLD_HIDDEN_TOOL' not in ' '.join(provider.calls)
        assert result['points'][0]['status']!='scope_mismatch'
        assert result['points'][0]['result']['discovery_items']
        assert projects.db.version(pid,1)['analysis']==original
    finally:
        await projects.stop();await jobs.stop();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('names,code',[
    (['Arduino按钮','Arduino 按钮'],'search_target_collision'),
    (['Q'+'中'*159,'Another topic'],'search_target_too_long'),
])
async def test_canonical_collisions_or_expansion_over160_reject_without_truncation_or_jobs(tmp_path,names,code):
    store,jobs,projects,provider,pid=await prepared(tmp_path,2)
    original=rewrite(projects,pid,lambda a:[p.update(name=n) for p,n in zip(a['knowledge_points'],names)])
    before=store.connection.total_changes
    with pytest.raises(ProjectError) as exc:projects.confirm(pid,1,[])
    assert exc.value.code==code
    assert store.connection.total_changes==before and store.job_counts()=={}
    assert projects.db.version(pid,1)['analysis']==original
    assert projects.db.version(pid,1)['confirmation'] is None
    await projects.stop();store.close()


@pytest.mark.asyncio
async def test_skipped_prerequisite_is_not_an_acknowledgement_gate_and_never_auto_acknowledged(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path,2)
    def change(a):
        a['knowledge_points'][0]['selection']='skip'
        a['knowledge_points'][1]['prerequisite_ids']=['k0']
    original=rewrite(projects,pid,change)
    confirmed=projects.confirm(pid,1,[])['version']['confirmation']
    assert confirmed['acknowledged_skipped_prerequisites']==[]
    assert confirmed['selected_ids']==['k1']
    assert confirmed['analysis']==original
    await projects.stop();store.close()


@pytest.mark.asyncio
async def test_unrelated_ack_is_still_rejected(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path)
    with pytest.raises(ProjectError) as exc:projects.confirm(pid,1,['not-a-prerequisite'])
    assert exc.value.code=='invalid_acknowledgement'
    assert projects.db.version(pid,1)['confirmation'] is None
    await projects.stop();store.close()


@pytest.mark.asyncio
async def test_first_search_of_legacy_confirmation_marks_only_mode_and_preserves_snapshot(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path)
    projects.confirm(pid,1,[])
    data=projects.db.version(pid,1);data['confirmation'].pop('search_mode');projects.db.save(pid,data)
    snapshot=deepcopy(data['confirmation']);jobs.start()
    try:
        projects.search(pid,1);await settle(projects)
        after=projects.db.version(pid,1)['confirmation']
        assert after.pop('search_mode')=='professional_terms_v1'
        assert after==snapshot
    finally:
        await projects.stop();await jobs.stop();store.close()


@pytest.mark.asyncio
async def test_already_searched_legacy_confirmation_keeps_technology_scope_guard_and_zero_write_reads(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path)
    original=rewrite(projects,pid,lambda a:a['knowledge_points'][0].update(name='groupby 汇总',technology='Streamlit'))
    projects.confirm(pid,1,[])
    data=projects.db.version(pid,1);data['confirmation'].pop('search_mode')
    jid=jobs.create(SearchRequest(knowledge_points=['groupby 汇总'],preferred_platforms=['bilibili','icourse163']))['job_id']
    await jobs.run(jid);job=store.get_job(jid)
    data.update(search_started_at=now(),status='completed')
    data['batches']=[{'batch_id':'legacy-b1','ordinal':1,'project_knowledge_point_ids':['k0'],'job_id':jid,
        'status':'completed','error':None,'mappings':[{'project_knowledge_point_id':'k0','knowledge_point_id':job['knowledge_points'][0]['knowledge_point_id']}]}]
    projects.db.save(pid,data)
    persisted=deepcopy(projects.db.version(pid,1));before=store.connection.total_changes
    result=projects.results(pid,1)
    assert result['points'][0]['status']=='scope_mismatch'
    assert result['points'][0]['result']['discovery_items']==[]
    assert projects.search(pid,1)['version']['confirmation'].get('search_mode') is None
    assert store.connection.total_changes==before and projects.db.version(pid,1)==persisted
    assert persisted['analysis']==original
    await projects.stop();store.close()


def test_capabilities_advertise_professional_names_two_generation_calls_and_no_critic(tmp_path):
    config,store,jobs,projects,provider=setup(tmp_path)
    capability=projects.capabilities()
    analysis=capability['project_analysis']
    assert analysis['mode']=='professional_knowledge_points'
    assert analysis['max_model_calls']==2
    assert analysis['semantic_review_enabled'] is False
    assert analysis['review_max_calls']==analysis['review_max_output_tokens']==0
    assert capability['project_search']['mode']=='professional_terms_v1'
    store.close()


@pytest.mark.asyncio
async def test_first_search_legacy_confirmation_revalidates_collision_before_mode_or_job_write(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path,2)
    projects.confirm(pid,1,[])
    data=projects.db.version(pid,1);data['confirmation'].pop('search_mode')
    for point,name in zip(data['confirmation']['analysis']['knowledge_points'],['Arduino按钮','Arduino 按钮']):
        point['name']=name
    projects.db.save(pid,data);persisted=deepcopy(projects.db.version(pid,1));before=store.connection.total_changes
    with pytest.raises(ProjectError) as exc:projects.search(pid,1)
    assert exc.value.code=='search_target_collision'
    assert store.connection.total_changes==before and store.job_counts()=={}
    assert projects.db.version(pid,1)==persisted
    await projects.stop();store.close()


@pytest.mark.asyncio
async def test_old_teaching_flag_does_not_create_new_teaching_budget_or_search_axis(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path)
    config=replace(projects.settings,teaching_match_enabled=True)
    projects.settings=jobs.settings=config
    rewrite(projects,pid,lambda a:a['knowledge_points'][0].update(name='Python 列表索引',learning_skills=['legacy skill'],concepts=['legacy concept']))
    jobs.start()
    try:
        confirmed=projects.confirm(pid,1,[])
        assert not any(k.startswith('reserved_teaching') for k in confirmed['version']['budgets'])
        projects.search(pid,1);await settle(projects)
        data=projects.db.version(pid,1);job=store.get_job(data['batches'][0]['job_id'])
        assert not job['request'].get('learning_targets') and not job['request'].get('learning_skills')
        assert not any(k.startswith('teaching_match') for k in job['budgets'])
    finally:
        await projects.stop();await jobs.stop();store.close()


@pytest.mark.asyncio
async def test_user_background_truncation_is_explicit_and_never_injects_old_plan(tmp_path):
    store,jobs,projects,provider,pid=await prepared(tmp_path)
    data=projects.db.version(pid,1);data['input']['requirements']='USER_REQUIREMENT_'*120
    data['analysis']['technical_plan']='OLD_TECHNICAL_PLAN_SENTINEL'
    projects.db.save(pid,data);jobs.start()
    try:
        projects.confirm(pid,1,[]);projects.search(pid,1);await settle(projects)
        saved=projects.db.version(pid,1);job=store.get_job(saved['batches'][0]['job_id'])
        # JobService's existing canonical request contract collapses whitespace
        # after the project adapter takes its <=1000-character user summary.
        source=saved['confirmation']['input']
        expected='\n'.join(part for part in [source['name'],source.get('project_context',''),source['requirements']] if part)
        assert job['request']['project_context']==' '.join(expected[:1000].split())
        assert len(job['request']['project_context'])<=1000
        assert 'OLD_TECHNICAL_PLAN_SENTINEL' not in job['request']['project_context']
        assert any('原始用户背景超过1000字符' in warning for warning in saved['warnings'])
        assert saved['confirmation']['input']['requirements']==data['input']['requirements']
        assert saved['confirmation']['analysis']['technical_plan']=='OLD_TECHNICAL_PLAN_SENTINEL'
    finally:
        await projects.stop();await jobs.stop();store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('slow_platform',['bilibili','icourse163'])
async def test_exact_global_two_allows_fast_platform_results_before_slow_response(tmp_path,slow_platform):
    blocked=asyncio.Event();ready=asyncio.Event();release=asyncio.Event()
    async def respond(req):
        if platform(req.url.params['q'])==slow_platform:
            blocked.set();await release.wait()
        else:ready.set()
        return httpx.Response(200,json=response(req.url.params['q']))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        config=lane_options(tmp_path,global_concurrency=2)
        store=Store(config.database_path)
        jobs=JobService(config,store,provider=SearXNGProvider(config,client),fetcher=NoFetch())
        jid=jobs.create(lane_request(1))['job_id'];task=asyncio.create_task(jobs.run(jid))
        try:
            await asyncio.wait_for(blocked.wait(),1);await asyncio.wait_for(ready.wait(),1)
            result=jobs.results(jid)
            assert not task.done() and store.get_job(jid)['status']=='running'
            fast='icourse163' if slow_platform=='bilibili' else 'bilibili'
            group=result['groups'][0]
            retained=store.resources(jid)
            assert {resource['platform'] for resource in retained.values()}=={fast}
            if fast=='bilibili':
                assert {i['resource']['platform'] for i in group['discovery_items']}=={'bilibili'}
                assert group['mooc_relevance']['candidate_count']==0
            else:
                assert group['discovery_items']==[]
                diagnostic=group['mooc_relevance']
                assert diagnostic['candidate_count']==1 and diagnostic['recommended_count']==0
                candidate=diagnostic['candidates'][0]
                assert candidate['resource_id'] in retained and candidate['assessment']['display_eligible'] is False
                assert any(row['kind']=='search' and row.get('knowledge_point_id')==group['knowledge_point_id']
                           for row in store.evidence(jid,candidate['resource_id']))
        finally:
            release.set();await asyncio.wait_for(task,2)
        assert store.get_job(jid)['progress']['search_requests']==4
        assert store.get_job(jid)['progress']['platform_search_requests']=={'bilibili':2,'icourse163':2}
        store.close()
