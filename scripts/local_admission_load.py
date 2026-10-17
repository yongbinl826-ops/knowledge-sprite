"""Local ASGI admission/queue load only. No external HTTP and no live-search claim."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.main import create_app

TERMINAL={'completed','partial','failed','cancelled','interrupted'}

class LocalFixtureProvider:
    name='isolated_load_fixture'
    def __init__(self):
        self.active=0
        self.peak=0
        self.calls=0
        self.block=False
        self.entered=asyncio.Event()
    async def search(self,*args):
        self.active+=1
        self.calls+=1
        self.peak=max(self.peak,self.active)
        try:
            if self.block:
                self.entered.set()
                await asyncio.Event().wait()
            await asyncio.sleep(.03)
            return []
        finally:
            self.active-=1

def distribution(values):
    ordered=sorted(values)
    return {'count':len(values),'p50_ms':round(statistics.median(values),3),
            'p95_ms':round(ordered[max(0,__import__('math').ceil(.95*len(ordered))-1)],3),
            'max_ms':round(max(values),3)} if values else {'count':0}

async def phase(out,clients):
    provider=LocalFixtureProvider()
    settings=Settings(database_path=str(out/f'fixture-{clients}.sqlite3'),fetch_enabled=False,
        max_detail_pages=0,max_search_requests=4,global_concurrency=1,max_pending_jobs=20,
        submission_limit_per_minute=30,deadline_seconds=10,max_queue_wait_seconds=30)
    app=create_app(settings,provider=provider)
    accepted=[]
    codes=Counter()
    latencies={'submit':[],'poll':[],'health':[]}
    peak_queue=0
    retry_headers=True
    start=time.monotonic()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture.local') as client:
            async def request(method,url,category,**kwargs):
                before=time.perf_counter()
                r=await client.request(method,url,**kwargs)
                latencies[category].append((time.perf_counter()-before)*1000)
                codes[r.status_code]+=1
                return r
            async def submit(index):
                nonlocal retry_headers,peak_queue
                for n in range(4):
                    r=await request('POST','/api/search-jobs','submit',json={'knowledge_points':[f'fixture client {index} request {n}'],'preferred_platforms':[]})
                    if r.status_code==202: accepted.append(r.json()['job_id'])
                    elif r.status_code==429: retry_headers &= int(r.headers.get('Retry-After','0'))>0
                    peak_queue=max(peak_queue,app.state.service.queue.qsize())
                    await asyncio.sleep(0)
            await asyncio.gather(*(submit(i) for i in range(clients)))
            async with asyncio.timeout(25):
                pending=set(accepted)
                while pending:
                    for job_id in list(pending):
                        job=(await request('GET',f'/api/search-jobs/{job_id}','poll')).json()
                        result=await request('GET',f'/api/search-jobs/{job_id}/results','poll')
                        assert result.status_code==200
                        if job['status'] in TERMINAL: pending.remove(job_id)
                    health=(await request('GET','/health','health')).json()
                    peak_queue=max(peak_queue,health['queue_depth'])
                    await asyncio.sleep(.05)
            # Confirm running cancellation cleans up the worker's child task,
            # then a new job completes on the same worker.
            provider.block=True
            r=await client.post('/api/search-jobs',json={'knowledge_points':['fixture cancellation'],'preferred_platforms':[]})
            assert r.status_code==202
            cancelled_id=r.json()['job_id']
            await asyncio.wait_for(provider.entered.wait(),2)
            provider.block=False
            cancelled=(await client.post(f'/api/search-jobs/{cancelled_id}/cancel')).json()
            assert cancelled['status']=='cancelled'
            r=await client.post('/api/search-jobs',json={'knowledge_points':['fixture recovery'],'preferred_platforms':[]})
            assert r.status_code==202
            recovery_id=r.json()['job_id']
            await asyncio.wait_for(app.state.service.queue.join(),5)
            recovered=(await client.get(f'/api/search-jobs/{recovery_id}')).json()
            final=(await client.get('/health')).json()
            assert recovered['status']=='completed' and final['worker_alive']
            assert final['queue_depth']==0 and final['active_jobs']==0 and provider.active==0
            assert provider.peak<=1 and peak_queue<=20 and retry_headers
            assert not any(code>=500 for code in codes)
    return {'clients':clients,'submissions':clients*4,'accepted':len(accepted),'rejected':clients*4-len(accepted),
        'elapsed_seconds':round(time.monotonic()-start,3),'recorded_http_codes':dict(codes),
        'api_latencies':{k:distribution(v) for k,v in latencies.items()},'queue_peak':peak_queue,
        'provider_concurrency_peak':provider.peak,'fixture_calls':provider.calls,'retry_after_valid':retry_headers,
        'cancellation':'passed','next_job_recovery':'passed','final_health':final,
        'limits':{'queue':20,'submissions_per_minute':30,'global_concurrency':1},
        'external_http_requests':0,'scope':'in-process ASGI burst, 4 submissions per client, fixture provider, not network throughput or sustained production capacity'}

async def main(args):
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=False)
    results=[]
    for clients in (5,20):
        result=await phase(out,clients)
        results.append(result)
        (out/f'{clients}-clients.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:result[k] for k in ('clients','accepted','rejected','queue_peak','provider_concurrency_peak','elapsed_seconds')},ensure_ascii=False),flush=True)
    (out/'summary.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'results':results},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    asyncio.run(main(parser.parse_args()))
