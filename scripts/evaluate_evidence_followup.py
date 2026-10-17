"""Five consumed topics, real bounded transports, separate from immutable v6."""
import argparse,asyncio,copy,hashlib,json,sys,time
from dataclasses import replace
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.fetcher import FetchStopped
from backend.app.main import create_app
from scripts.evaluate_link_discovery import Campaign,campaign_lock,save,now,digest,safe_config,TERMINAL

CASE_IDS=['D06','D13','H06','H09','H16']
FOLLOWUP_CAPS={'search_http':60,'target_http':20,'dns_http':40}

class FollowupCampaign(Campaign):
    async def reserve(self,kind,fields):
        if self.state['counts'][kind]>=FOLLOWUP_CAPS[kind]:
            raise FetchStopped('followup_budget','Targeted follow-up budget reached')
        return await super().reserve(kind,fields)

def hashes():
    paths=list((ROOT/'backend/app').rglob('*.py'))+[Path(__file__),ROOT/'scripts/evaluate_link_discovery.py']
    paths += [ROOT/p for p in ['.env','requirements.lock.txt','uv.lock','pyproject.toml','compose.yaml','deploy/searxng/settings.yml']]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

def section_counts(results):
    return {name:sum(len(g.get(key,[])) for g in results['groups']) for name,key in [('supported','items'),('partial','partial_items'),('needs_review','review_items')]}

async def run(args):
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    origin=ROOT/'reports/link-trial-20261014/evaluation-cases.json'
    source=json.loads(origin.read_text(encoding='utf-8'))['cases']
    cases=[next(c for c in source if c['id']==identifier) for identifier in CASE_IDS]
    old=ROOT/'reports/link-completion-20261014/live/checkpoint.json'
    prior=json.loads(old.read_text(encoding='utf-8'))
    settings=replace(Settings.from_env(),database_path=str(out/'live.sqlite3'),global_concurrency=1,
        max_search_requests=12,max_detail_pages=2,deadline_seconds=90,search_max_retries=0,
        search_min_interval_seconds=2,fetch_min_interval_seconds=2,max_results_per_point=3,
        js_render_enabled=False,llm_provider='none',llm_api_key='',submission_limit_per_minute=30)
    assert settings.search_provider=='searxng'
    assert set((*settings.searxng_engines,*settings.searxng_video_engines,*settings.searxng_fallback_engines))=={'bing','duckduckgo videos'}
    frozen={'at':now(),'source_hashes':hashes(),'settings':safe_config(settings),'cases':cases,'caps':FOLLOWUP_CAPS,
        'original_manifest_sha256':hashlib.sha256(origin.read_bytes()).hexdigest(),'v6_checkpoint_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),
        'scope':'five development-consumed topics only; original requests unchanged; no playback; no new sources or permissions',
        'old_campaign_counts':prior['counts'],'old_restrictions':prior['restrictions'],'batch_size':4,'batch_wait_seconds':60,
        'transport':'real API routes in-process ASGI and real external HTTP; UI tested separately'}
    checkpoint=out/'checkpoint.json'
    if args.resume:
        state=json.loads(checkpoint.read_text(encoding='utf-8'))
        saved=json.loads((out/'frozen-scope.json').read_text(encoding='utf-8'))
        assert saved['source_hashes']==frozen['source_hashes'] and saved['cases']==cases and saved['settings']==frozen['settings']
        if state.get('inflight') or any(r['state'] not in {'pending','terminal'} for r in state['cases']):
            raise RuntimeError('uncertain_state_no_automatic_resubmission')
        frozen=saved
    else:
        if checkpoint.exists() or (out/'live.sqlite3').exists():raise RuntimeError('existing_run_requires_resume')
        save(out/'frozen-scope.json',frozen)
        state={'created_at':now(),'counts':dict.fromkeys(FOLLOWUP_CAPS,0),'restrictions':copy.deepcopy(prior['restrictions']),
            'requests':[],'inflight':None,'active_case':None,'cases':[{'id':c['id'],'original_split':c['split'],
            'purpose':'development_consumed','request_sha256':digest(c['request']),'state':'pending'} for c in cases]}
    campaign=FollowupCampaign(out,state);campaign.persist()
    app=create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.service.fetcher.config=replace(app.state.service.fetcher.config,max_retries=0)
        campaign.install(app.state.service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://followup.local') as client:
            for case,row in zip(cases,state['cases']):
                if row['state']!='pending':continue
                if hashes()!=frozen['source_hashes']:raise RuntimeError('source_drift')
                finished=sum(r['state']=='terminal' for r in state['cases'])
                if finished and finished%4==0:
                    remaining=max(0,60-(time.time()-state.get('last_finished_epoch',0)))
                    if remaining:print(json.dumps({'batch_wait_seconds':round(remaining,1)}),flush=True);await asyncio.sleep(remaining)
                started=time.monotonic();job=results=None;job_id=None;first=None
                state['active_case']=case['id'];row.update(state='started',started_at=now(),evidence_file=case['id']+'.json');campaign.persist()
                try:
                    response=await client.post('/api/search-jobs',json=case['request'],headers={'Idempotency-Key':'evidence-followup-v7-'+case['id']})
                    response.raise_for_status();job_id=response.json()['job_id'];row['job_id']=job_id;campaign.persist()
                    async with asyncio.timeout(105):
                        while True:
                            j=await client.get(f'/api/search-jobs/{job_id}');j.raise_for_status();job=j.json()
                            r=await client.get(f'/api/search-jobs/{job_id}/results');r.raise_for_status();results=r.json()
                            counts=section_counts(results)
                            if sum(counts.values()) and first is None:first=round(time.monotonic()-started,3)
                            if job['status'] in TERMINAL:break
                            await asyncio.sleep(.25)
                    record={'case':case,'purpose':'development_consumed','job':job,'results':results,
                        'first_any_evidence_seconds':first,'completed_seconds':round(time.monotonic()-started,3)}
                    save(out/row['evidence_file'],record)
                    row.update(state='terminal',status=job['status'],section_counts=counts,progress=job['progress'],completed_seconds=record['completed_seconds'])
                except BaseException as exc:
                    row.update(state='runner_error',error_type=type(exc).__name__)
                    save(out/row['evidence_file'],{'case':case,'job':job,'results':results,'error_type':type(exc).__name__});campaign.persist()
                    if job_id:
                        try:await app.state.service.cancel(job_id)
                        except BaseException:pass
                    raise
                finally:
                    row['finished_at']=now();state['last_finished_epoch']=time.time();campaign.snapshot();state['active_case']=None;campaign.persist()
                print(json.dumps(row,ensure_ascii=False),flush=True)
    save(out/'finished.json',{'at':now(),'terminal_cases':sum(r['state']=='terminal' for r in state['cases']),
        'counts':state['counts'],'caps':FOLLOWUP_CAPS,'restrictions':state['restrictions'],
        'source_hashes_unchanged':hashes()==frozen['source_hashes'],'playback_tests':0,'physical_searx_upstream_http':'unknown'})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='reports/evidence-followup-20261014/live');parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    with campaign_lock(args.output):asyncio.run(run(args))
