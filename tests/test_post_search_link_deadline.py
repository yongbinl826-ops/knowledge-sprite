"""Offline real-module regression for post-search own-page links.
HTTP, page content and time are synthetic; no source or model network is used.
"""
import asyncio
import json
import os
from pathlib import Path
import httpx
import pytest
from backend.app import ai_video_service as av
from backend.app.db import Store
from backend.app.extractor import MetadataExtractor
from backend.app.models import Candidate, now
from backend.app.service import JobService
from test_ai_page_link_recovery import page, video
from test_phase_actual_pipeline import virtual, InitialSearch, Discovery, make_settings
from test_grounded_related import TOPIC, TITLE, DESCRIPTION, inputs, reply


@pytest.mark.parametrize('parent_delay,child_delay',[(5,5),(5,100),(62,5)])
def test_post_search_own_link_has_round_window_after_legacy_deadline(tmp_path,monkeypatch,parent_delay,child_delay):
    async def execute():
        events=[];settings=make_settings(tmp_path/'post-search.sqlite3')
        store=Store(settings.database_path);model=Discovery(events)
        parent,child=video(71),video(72)
        class Search:
            name='offline-parent-source'
            async def search(self,query,*_):
                events.append({'phase':'search','at':asyncio.get_running_loop().time()})
                await asyncio.sleep(16)
                return [Candidate(id='observed-parent',title='HTML setup',url=parent,snippet='HTML basics',
                    source=self.name,query=query,discovered_at=now())]
        class Pages:
            async def enrich(self,candidate):
                url=candidate['url'];stage='parent' if url==parent else 'child'
                assert url in {parent,child},'No invented or unexpected source may be fetched'
                events.append({'phase':stage+'_start','at':asyncio.get_running_loop().time()})
                try:
                    await asyncio.sleep(parent_delay if url==parent else child_delay)
                    if url==parent:
                        content=page(parent,title='HTML setup',leads=[(child,TOPIC)])
                    else:
                        node={'@context':'https://schema.org','@type':'VideoObject','name':TITLE,
                            'description':DESCRIPTION,'contentUrl':'https://media.example.org/video.mp4'}
                        content='<script type="application/ld+json">'+json.dumps(node)+'</script>'
                    result=MetadataExtractor().extract(content,url,now())
                    events.append({'phase':stage+'_returned','at':asyncio.get_running_loop().time()})
                    return result
                finally:
                    events.append({'phase':stage+'_stopped','at':asyncio.get_running_loop().time()})
        async def answer(request):
            payload=json.loads(json.loads(request.content)['messages'][1]['content'])
            stage='judgment' if 'pairs' in payload else 'review'
            events.append({'phase':stage,'at':asyncio.get_running_loop().time()})
            await asyncio.sleep(18)
            if stage=='review':
                return reply({'decisions':[{'pair_id':c['pair_id'],'accepted':True} for c in payload['claims']]})
            decisions=[]
            for pair in payload['pairs']:
                observed=next((s for s in pair['observations'] if s['basis']=='description' and DESCRIPTION in s['segments']),None)
                support=None if observed is None else {'evidence_id':observed['evidence_id'],'basis':'description',
                    'quote':DESCRIPTION,'source_text_sha256':observed['source_text_sha256']}
                decisions.append({'pair_id':pair['pair_id'],'fingerprint':pair['fingerprint'],'support':support})
            return reply({'decisions':decisions})
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            model.client=client;service=JobService(settings,store,provider=InitialSearch(),fetcher=Pages(),llm=model)
            provider=Search();service._ai_search_source=lambda *_:('offline-parent-source',provider,None)
            monkeypatch.setattr(av,'video_recovery_search_phrases_with_diagnostics',lambda *_:([TOPIC],{'status':'offline_fixture'}))
            identifier=service.create(inputs()[1])['job_id']
            await service.run(identifier)
            job=store.get_job(identifier);resources=store.resources(identifier)
            covered=av.visible_point_ids(service,job)
            current=asyncio.get_running_loop().time()
            report={'kind':'actual_module_mock_http_virtual_time','parent_delay':parent_delay,'child_delay':child_delay,'events':events,
                'legacy_deadline':1215,'recovery_source_deadline':1280,'job_deadline':1360,
                'ended':current,'covered':len(covered),'grounded':job.get('grounded_related'),
                'fallback':job.get('ai_video_fallback'),'details_attempted':job['progress']['details_attempted']}
            folder=Path(os.environ.get('HOTFIX_EVIDENCE_DIR',str(tmp_path)));folder.mkdir(parents=True,exist_ok=True)
            (folder/('post-search-'+os.environ.get('HOTFIX_STAGE','test')+'-'+str(parent_delay)+'-'+str(child_delay)+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            stages={e['phase']:e['at'] for e in events}
            assert stages['parent_returned']>1215
            assert stages['child_start']==stages['parent_returned']
            assert stages['child_stopped']<=1280
            assert stages['judgment']>=stages['child_stopped']
            assert current<=1360
            assert all(t is asyncio.current_task() or t.done() for t in asyncio.all_tasks())
            assert model.calls==1
            assert job['progress']['details_attempted']==2
            if parent_delay==5 and child_delay==5:
                assert stages['child_returned']==stages['child_start']+5
                assert len(covered)==1
                assert job['grounded_related']['judgment_calls']==job['grounded_related']['review_calls']==1
                child_resource=next(r for r in resources.values() if r['canonical_url']==child)
                observations=store.evidence(identifier,child_resource['resource_id'])
                assert any(r['kind']=='page_link' and r['source_url']==parent for r in observations)
                assert any(r['kind']=='page' for r in observations)
            else:
                assert 'child_returned' not in stages
                assert stages['child_stopped']==min(stages['child_start']+20,1280)
                assert not covered
                if parent_delay==5:
                    assert job['ai_video_fallback']['page_link_fetch_timed_out'] is True
                else:
                    assert job['ai_video_fallback']['search_round_timeouts']==1
                assert job['grounded_related']['review_calls']==0
        store.close()
    virtual(execute())
