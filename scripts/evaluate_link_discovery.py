"""Frozen 40-topic live campaign: real routes/transports, no playback or retries."""
import argparse, asyncio, hashlib, json, sys, time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.fetcher import NETWORK_OBSERVER, FetchStopped

TERMINAL={'completed','partial','failed','interrupted','cancelled'}
CAPS={'search_http':480,'target_http':240,'dns_http':480}
def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def save(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    # Windows readers may briefly deny delete-sharing. Retry only the local
    # atomic rename, never replay any network callback or task submission.
    for attempt in range(21):
        try:temporary.replace(path);return
        except PermissionError:
            if attempt==20:raise
            time.sleep(.05)
def source_hashes():
    paths=list((ROOT/'backend/app').rglob('*.py'))+[Path(__file__)]
    paths += [p for p in (ROOT/'requirements.lock.txt',ROOT/'uv.lock',ROOT/'pyproject.toml',ROOT/'frontend/package-lock.json',ROOT/'deploy/searxng/settings.yml',ROOT/'compose.yaml',ROOT/'.env') if p.exists()]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
def safe_config(settings):
    values=asdict(settings)
    for key,value in list(values.items()):
        if any(word in key for word in ('key','token','password','secret')): values[key]={'configured':bool(value),'sha256':digest(value)}
    return json.loads(json.dumps(values))
def assert_resume_safe(state,frozen,current):
    if frozen!=current: raise RuntimeError('frozen_manifest_or_config_drift')
    if state.get('inflight') or any(row['state']=='started' for row in state['cases']):
        raise RuntimeError('uncertain_inflight_no_automatic_resubmission')

def prepare_repeat_rows(rows, repeated, consumed):
    """Explicitly mark newly inspected holdout cases as development, keeping originals."""
    assert consumed <= repeated, 'consumed_holdout_must_be_repeated'
    lookup = {row['id']: row for row in rows}
    assert repeated <= lookup.keys(), 'unknown_repeat_case'
    for identifier in repeated:
        row=lookup[identifier]
        assert row['state']=='terminal' and not row.get('negative_control'), 'only_terminal_positive_may_repeat'
        assert row['purpose']!='holdout' or identifier in consumed, 'only_consumed_development_may_repeat'
    assert all(lookup[i]['purpose']=='holdout' for i in consumed), 'only_unconsumed_holdout_can_be_consumed'
    result=deepcopy(rows)
    for row in result:
        if row['id'] not in repeated:continue
        prior=deepcopy(row); previous=prior.pop('previous_attempts',[])
        row.clear();row.update({k:prior[k] for k in ('id','split','purpose','language','negative_control','request_sha256')})
        if row['id'] in consumed:row['purpose']='development_consumed'
        row.update(state='pending',previous_attempts=[*previous,prior])
    return result

@contextmanager
def campaign_lock(output):
    directory=Path(output);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'campaign.lock').open('a+b') as handle:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            handle.seek(0)
            if sys.platform=='win32':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

class Campaign:
    def __init__(self,out,state):
        self.out,self.state,self.service=out,state,None
        self.lock=asyncio.Lock();self.last_send=0.0
    def persist(self):
        save(self.out/'checkpoint.json',self.state);save(self.out/'coverage.json',self.state['cases'])
    def snapshot(self):
        if self.service is None:return
        p,f,o=self.service.provider,self.service.fetcher,self.service.official_fallback
        def latch(key,expiry=0,permanent=True,**evidence):
            stamp=time.time()+(expiry-time.monotonic()) if expiry else None
            record=self.state['restrictions'].get(key)
            old=datetime.fromisoformat(record['retry_after_expiry_utc']).timestamp() if record and record.get('retry_after_expiry_utc') else 0
            if record is None or permanent and not record['evaluation_latched'] or not permanent and not record['evaluation_latched'] and stamp and stamp>old+1:
                history=record.get('history',[])+[{k:v for k,v in record.items() if k!='history'}] if record else []
                self.state['restrictions'][key]={'observed_at':now(),'evaluation_latched':permanent,
                    'retry_after_expiry_utc':datetime.fromtimestamp(stamp,timezone.utc).isoformat() if stamp else None,'history':history,**evidence}
        if p.access_denied:latch('search_service',reason='access_denied')
        if p.paused_until:latch('search_service_pause',p.paused_until,permanent=False,reason='rate_limited')
        if p.default_group_pause_until:latch('search_defaults',p.default_group_pause_until,reason='default_group_restricted')
        for engine,expiry in p.engine_pauses.items():
            warnings=[w for w in p.last_warnings if w.get('engine')==engine and w.get('reason_code') in {'captcha','access_denied','rate_limited'}]
            existing=self.state['restrictions'].get('engine:'+engine)
            permanent=any(w.get('reason_code') in {'captcha','access_denied'} for w in warnings) if warnings else existing.get('evaluation_latched',True) if existing else True
            latch('engine:'+engine,expiry,permanent=permanent,warnings=warnings or (existing or {}).get('warnings',[]))
        for host,record in f._blocked_hosts.items():latch('host:'+host,record=record)
        for host,expiry in f._paused_until.items():latch('host_pause:'+host,expiry,permanent=False,reason='rate_limited')
        if o and o._stopped_code:latch('official',reason=o._stopped_code,hard_stopped=o._hard_stopped,target_trace=list(o.last_requests),dns_trace=list(o.last_dns_requests))
        self.persist()
    def restore(self):
        p,f,o=self.service.provider,self.service.fetcher,self.service.official_fallback
        for key,record in self.state['restrictions'].items():
            expiry=record.get('retry_after_expiry_utc')
            remaining=max(0,datetime.fromisoformat(expiry).timestamp()-time.time()) if expiry else 0
            until=time.monotonic()+(86400 if record['evaluation_latched'] else remaining)
            if key=='search_service':p.access_denied=True
            elif key=='search_service_pause':p.paused_until=until
            elif key=='search_defaults':p.default_group_pause_until=until
            elif key.startswith('engine:'):p.engine_pauses[key[7:]]=until
            elif key.startswith('host:'):f._blocked_hosts[key[5:]]=record['record']
            elif key.startswith('host_pause:'):f._paused_until[key[11:]]=until
            elif key=='official' and o:o._stopped_code=record['reason'];o._hard_stopped=record['hard_stopped']
    async def reserve(self,kind,fields):
        if self.state['counts'][kind]>=CAPS[kind]:raise FetchStopped('campaign_budget','Frozen campaign HTTP budget reached')
        delay=self.last_send+2-time.monotonic()
        if delay>0:await asyncio.sleep(delay)
        self.state['counts'][kind]+=1
        record={'id':len(self.state['requests'])+1,'case_id':self.state['active_case'],'source_epoch':self.state.get('epoch',1),'kind':kind,'started_at':now(),'status':'delegated',**fields}
        self.state['requests'].append(record);self.state['inflight']=record['id'];self.last_send=time.monotonic();self.persist()
        return record
    async def transport(self,kind,fields,callback):
        async with self.lock:
            record=await self.reserve(kind,fields)
            try:
                value=await callback();record['status']='returned'
                if kind=='target_http':record.update(http_status=value.status_code,bytes_read=len(value.body))
                return value
            except BaseException as exc:record.update(status='exception',error_type=type(exc).__name__);raise
            finally:record['finished_at']=now();self.state['inflight']=None;self.snapshot()
    def install(self,service):
        self.service=service;p,f=service.provider,service.fetcher;self.restore()
        raw_search=p._bounded_response
        async def search(client,method,url,trace,**kwargs):
            params=kwargs.get('params',{})
            fields={'endpoint':url,'query':params.get('q'),'language':params.get('language'),'engines':params.get('engines'),'query_sha256':digest(params.get('q')),'trace':trace}
            return await self.transport('search_http',fields,lambda:raw_search(client,method,url,trace,**kwargs))
        p._bounded_response=search
        raw_target=f.http.request
        async def target(url,addresses,max_bytes):
            parts=urlsplit(url)
            return await self.transport('target_http',{'host':parts.hostname,'path':parts.path,'url_sha256':digest(url)},lambda:raw_target(url,addresses,max_bytes))
        f.http.request=target
        resolver=f.resolver
        async def resolve(url,timeout=8):
            parent=NETWORK_OBSERVER.get() or {};record=None;dns_records=[]
            async def before_dns():
                nonlocal record
                if 'dns_service' in self.state['restrictions']:raise FetchStopped('dns_service_restricted','Recorded DNS service restriction')
                if parent.get('before_dns_http'):await parent['before_dns_http']()
                record=await self.reserve('dns_http',{'host':urlsplit(url).hostname})
                dns_records.append(record)
            def dns_trace(trace):
                if record is not None:record['trace']=trace
                if parent.get('dns_trace'):parent['dns_trace'](trace)
            token=NETWORK_OBSERVER.set({**parent,'before_dns_http':before_dns,'dns_trace':dns_trace})
            async with self.lock:
                try:return await resolver(url,timeout)
                finally:
                    NETWORK_OBSERVER.reset(token)
                    for row in dns_records:
                        if row['kind']=='dns_http':
                            trace=row.get('trace',{});row['status']=trace.get('status','unknown')
                            if trace.get('finished_at'):row['finished_at']=trace['finished_at'];row['finished_at_source']='trace.finished_at'
                            if trace.get('http_status') in {401,403,429,503}:self.state['restrictions'].setdefault('dns_service',{'observed_at':now(),'evaluation_latched':True,'request_id':row['id'],'http_status':trace['http_status'],'reason':'service_unavailable' if trace['http_status']==503 else 'explicit_http_restriction','retry_after':'unknown'})
                    self.state['inflight']=None;self.snapshot()
        f.resolver=resolve
        raw_trace=f._trace
        def trace(event,url,**fields):
            raw_trace(event,url,**fields)
            if event in {'host_blocked','host_paused'}:self.snapshot()
        f._trace=trace
        for source in (p,service.official_fallback):
            if not source:continue
            original=source.search
            async def wrapped(*args,_original=original,**kwargs):
                self.restore()
                try:return await _original(*args,**kwargs)
                finally:self.snapshot()
            source.search=wrapped

async def run(args):
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    cases=json.loads(Path(args.cases).read_text(encoding='utf-8'))['cases']
    assert len(cases)==40 and len({c['id'] for c in cases})==40
    settings=replace(Settings.from_env(),database_path=str(out/'live.sqlite3'),global_concurrency=1,max_search_requests=12,max_detail_pages=2,deadline_seconds=90,search_max_retries=0,search_min_interval_seconds=2,fetch_min_interval_seconds=2,max_results_per_point=3,js_render_enabled=False,llm_provider='none',llm_api_key='',submission_limit_per_minute=30)
    assert settings.search_provider=='searxng'
    assert set((*settings.searxng_engines,*settings.searxng_video_engines,*settings.searxng_fallback_engines))=={'bing','duckduckgo videos'}
    frozen={'source_hashes':source_hashes(),'settings':safe_config(settings),'cases':cases,'manifest_sha256':hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(),'caps':CAPS,'batch_size':4,'batch_wait_seconds':60,'playback_tests':0,
        'policy':'all original 40; no new source/credential; denial/captcha persist, rate limits obey UTC expiry then next scheduled budgeted request; unknown is not rate limiting',
        'cache':'isolated SQLite retained across batches/resume; memory robots cache resets on process resume',
        'holdout':'H01-H04 consumed by earlier repairs; H05-H20 heldout until frozen execution',
        'transport':'actual routes in-process ASGI; actual external transports; not browser submission E2E'}
    checkpoint=out/'checkpoint.json'
    if args.resume:
        state=json.loads(checkpoint.read_text(encoding='utf-8'))
        previous=json.loads((out/state.get('frozen_file','frozen-scope.json')).read_text(encoding='utf-8'))
        if args.new_epoch:
            assert_resume_safe(state,previous,previous)
            assert {k:v for k,v in previous.items() if k!='source_hashes'}=={k:v for k,v in frozen.items() if k!='source_hashes'},'epoch_cannot_change_cases_settings_or_budget'
            epoch=state.get('epoch',1)
            repeated=set(args.repeat_cases.split(',')) if args.repeat_cases else set()
            consumed=set(args.consume_holdout.split(',')) if args.consume_holdout else set()
            repeated_rows=prepare_repeat_rows(state['cases'],repeated,consumed)
            archive=out/f'epoch-{epoch}-checkpoint.json'
            if archive.exists():raise RuntimeError('epoch_archive_exists')
            save(archive,state)
            for row in state['cases']:
                if row['state']=='terminal':row.setdefault('source_epoch',epoch);row.setdefault('evidence_file',row['id']+'.json')
            state['cases']=repeated_rows
            state.update(epoch=epoch+1,frozen_file=f'frozen-scope-epoch-{epoch+1}.json')
            save(out/state['frozen_file'],frozen)
            save(out/f'epoch-{epoch+1}-transition.json',{'at':now(),'reason':args.new_epoch,'previous_checkpoint_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'repeated_development':sorted(repeated),'newly_consumed_holdout':sorted(consumed),'counts_carried_forward':state['counts'],'restrictions_carried_forward':state['restrictions']})
        else:assert_resume_safe(state,previous,frozen)
    else:
        if checkpoint.exists() or (out/'live.sqlite3').exists():raise RuntimeError('existing_campaign_requires_resume')
        save(out/'frozen-scope.json',frozen)
        state={'created_at':now(),'counts':dict.fromkeys(CAPS,0),'restrictions':{},'requests':[],'inflight':None,'active_case':None,'cases':[{'id':c['id'],'split':c['split'],'purpose':'development_consumed' if c['id'] in {'H01','H02','H03','H04'} else c['split'],'language':c['request']['language'],'negative_control':c['id'] in {'D20','H20'},'request_sha256':digest(c['request']),'state':'pending'} for c in cases]}
    campaign=Campaign(out,state);campaign.persist()
    selected=set(args.case_ids.split(',')) if args.case_ids else {c['id'] for c in cases}
    if not selected<={c['id'] for c in cases}:raise RuntimeError('unknown_case_id')
    app=create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.service.fetcher.config=replace(app.state.service.fetcher.config,max_retries=0);campaign.install(app.state.service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://evaluation.local') as client:
            for case,row in zip(cases,state['cases']):
                if case['id'] not in selected or row['state']!='pending':continue
                if source_hashes()!=frozen['source_hashes']:raise RuntimeError('source_drift_during_campaign')
                finished=sum(r['state']!='pending' for r in state['cases'])
                if finished and finished%4==0:
                    remaining=max(0,60-(time.time()-state.get('last_finished_epoch',0)))
                    if remaining:print(json.dumps({'event':'batch_interval','seconds':round(remaining,1)}),flush=True);await asyncio.sleep(remaining)
                started=time.monotonic();first=None;job_id=None;job=None;results=None
                epoch=state.get('epoch',1)
                evidence_dir=out if epoch==1 else out/f'epoch-{epoch}'
                evidence_dir.mkdir(exist_ok=True)
                state['active_case']=case['id'];row.update(state='started',started_at=now(),batch=finished//4+1,source_epoch=epoch,evidence_file=str((evidence_dir/(case['id']+'.json')).relative_to(out)));campaign.persist()
                try:
                    response=await client.post('/api/search-jobs',json=case['request'],headers={'Idempotency-Key':f'completion-20261014-e{epoch}-'+case['id']})
                    response.raise_for_status();job_id=response.json()['job_id'];row['job_id']=job_id;campaign.persist()
                    async with asyncio.timeout(105):
                        while True:
                            job_response=await client.get(f'/api/search-jobs/{job_id}');job_response.raise_for_status();job=job_response.json()
                            result_response=await client.get(f'/api/search-jobs/{job_id}/results');result_response.raise_for_status();results=result_response.json()
                            count=sum(len(g['items']) for g in results['groups'])
                            if count and first is None:first=round(time.monotonic()-started,3)
                            if job['status'] in TERMINAL:break
                            await asyncio.sleep(.25)
                    record={'case':case,'job':job,'results':results,'first_link_seconds':first,'completed_seconds':round(time.monotonic()-started,3)}
                    save(evidence_dir/(case['id']+'.json'),record);row.update(state='terminal',status=job['status'],returned=count,first_link_seconds=first,completed_seconds=record['completed_seconds'],progress=job['progress'])
                except BaseException as exc:
                    row.update(state='runner_error',error_type=type(exc).__name__);save(evidence_dir/(case['id']+'.json'),{'case':case,'error_type':type(exc).__name__,'job':job,'results':results});campaign.persist()
                    if job_id:
                        try:await app.state.service.cancel(job_id)
                        except BaseException as cleanup:row['cleanup_error_type']=type(cleanup).__name__
                    raise
                finally:
                    row['finished_at']=now();state['last_finished_epoch']=time.time();campaign.snapshot();state['active_case']=None;campaign.persist()
                print(json.dumps(row,ensure_ascii=False),flush=True)
    save(out/'finished.json',{'at':now(),'terminal_cases':sum(r['state']=='terminal' for r in state['cases']),'pending_cases':sum(r['state']=='pending' for r in state['cases']),'counts':state['counts'],'source_hashes_unchanged':source_hashes()==frozen['source_hashes'],'physical_searx_upstream_http':'unknown','source_links_not_played':True})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cases',required=True);parser.add_argument('--output',required=True);parser.add_argument('--case-ids');parser.add_argument('--resume',action='store_true');parser.add_argument('--new-epoch');parser.add_argument('--repeat-cases');parser.add_argument('--consume-holdout')
    args=parser.parse_args()
    with campaign_lock(args.output):asyncio.run(run(args))
