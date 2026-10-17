"""Bounded live link evaluation. No playback, seeded results, or automatic reruns.

Uses the real API routes in-process and real configured search/fetch transports.
All fixtures belong to the separate local load script/tests, never this runner.
"""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.main import create_app

TERMINAL={'completed','partial','failed','interrupted','cancelled'}


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


async def run(args):
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(Path(args.cases).read_text(encoding='utf-8'))
    selected=[c for c in manifest['cases'] if c.get('execute')]
    settings=replace(Settings.from_env(),database_path=str(out/'live.sqlite3'),global_concurrency=1,
        searxng_fallback_engines=('bing','duckduckgo videos'),max_search_requests=8,max_detail_pages=2,
        deadline_seconds=90,search_max_retries=0,max_results_per_point=3,js_render_enabled=False,
        llm_provider='none',llm_api_key='',submission_limit_per_minute=30)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'backend/app').rglob('*.py'))}
    save(out/'frozen-scope.json',{'at':datetime.now(timezone.utc).isoformat(),'selected_cases':selected,
        'manifest_sha256':hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(),'source_hashes':hashes,
        'budgets_per_case':{'search_http':8,'detail_slots':2,'deadline_seconds':90,'global_concurrency':1,'retries':0},
        'max_cases':len(selected),'max_application_search_http':8*len(selected),
        'playback_tests':0,'transport':'in-process actual FastAPI routes, real configured external transports',
        'source_groups':{'primary':list(settings.searxng_engines),'video':list(settings.searxng_video_engines),'fallback':list(settings.searxng_fallback_engines)},
        'official_fallback':settings.official_sitemap_fallback,'cache':'new SQLite; within-run caches retain original TTL',
        'holdout_policy':'frozen before all live cases; no edits or sample replacement after development results',
        'restricted_engine_policy':'first explicit denial/captcha/rate limit closes that engine for the remaining evaluation, without replacement'})
    app=create_app(settings)
    summaries=[]
    async with app.router.lifespan_context(app):
        app.state.service.fetcher.config=replace(app.state.service.fetcher.config,max_retries=0)
        provider=app.state.service.provider
        original_search=provider.search
        async def search_and_lock_restrictions(*positional,**keywords):
            try:
                return await original_search(*positional,**keywords)
            finally:
                # This bounded run lasts < 1000 s; a finite day-long hold also
                # keeps health JSON valid. No restricted source is retried here.
                until=time.monotonic()+86400
                for engine in getattr(provider,'engine_pauses',{}):
                    provider.engine_pauses[engine]=until
                if getattr(provider,'paused_until',0)>0: provider.paused_until=until
                if getattr(provider,'default_group_pause_until',0)>0: provider.default_group_pause_until=until
        provider.search=search_and_lock_restrictions
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://evaluation.local') as client:
            for case in selected:
                started=time.monotonic()
                first=None
                job_id=None
                try:
                    created=await client.post('/api/search-jobs',json=case['request'])
                    created.raise_for_status()
                    job_id=created.json()['job_id']
                    async with asyncio.timeout(100):
                        while True:
                            job=(await client.get(f'/api/search-jobs/{job_id}')).json()
                            results=(await client.get(f'/api/search-jobs/{job_id}/results')).json()
                            count=sum(len(g['items']) for g in results['groups'])
                            if count and first is None: first=round(time.monotonic()-started,3)
                            if job['status'] in TERMINAL: break
                            await asyncio.sleep(.25)
                    record={'case':case,'job':job,'results':results,'first_link_seconds':first,
                            'completed_seconds':round(time.monotonic()-started,3)}
                    save(out/(case['id']+'.json'),record)
                    summary={'id':case['id'],'split':case['split'],'language':case['request']['language'],'status':job['status'],'returned':count,
                             'first_link_seconds':first,'completed_seconds':record['completed_seconds'],
                             'progress':job['progress'],'manual_relevance':'pending_evidence_review'}
                except BaseException as exc:
                    if job_id: await app.state.service.cancel(job_id)
                    summary={'id':case['id'],'split':case['split'],'language':case['request']['language'],'outcome':'runner_error','error_type':type(exc).__name__}
                    save(out/(case['id']+'.json'),summary)
                    summaries.append(summary)
                    save(out/'summary.json',summaries)
                    raise
                summaries.append(summary)
                save(out/'summary.json',summaries)
                print(json.dumps(summary,ensure_ascii=False),flush=True)
    strata={}
    for field in ('split','language'):
        strata[field]={}
        for value in sorted({x[field] for x in summaries}):
            rows=[x for x in summaries if x[field]==value]
            strata[field][value]={'attempted':len(rows),'terminal':sum(x.get('status') in TERMINAL for x in rows),
                'raw_hit_cases':sum(x.get('returned',0)>0 for x in rows),
                'raw_hit_fraction':sum(x.get('returned',0)>0 for x in rows)/len(rows)}
    save(out/'finished.json',{'at':datetime.now(timezone.utc).isoformat(),'cases':len(summaries),'strata':strata,
        'source_hashes_unchanged':hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'backend/app').rglob('*.py'))},
        'raw_hit_rate':sum(x.get('returned',0)>0 for x in summaries)/len(summaries),
        'end_latency_median':statistics.median(x['completed_seconds'] for x in summaries),
        'end_latency_max':max(x['completed_seconds'] for x in summaries),
        'physical_upstream_request_count':'unknown','p_at_3_and_ndcg':'not calculated without independent relevance judgments',
        'source_links_not_played':True,'limitation':'8 exploratory cases only; split and language are confounded; 32 cases not executed; not a generalization estimate'})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',required=True)
    parser.add_argument('--output',required=True)
    asyncio.run(run(parser.parse_args()))
