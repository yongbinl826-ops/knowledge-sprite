"""Re-evaluate preserved candidates offline after review; not a fresh holdout test."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.service import JobService

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main(args):
    source=Path(args.source);out=Path(args.output)
    out.mkdir(parents=True,exist_ok=False)
    before=hashlib.sha256((source/'live.sqlite3').read_bytes()).hexdigest()
    shutil.copyfile(source/'live.sqlite3',out/'offline.sqlite3')
    store=Store(str(out/'offline.sqlite3'))
    svc=JobService(Settings(fetch_enabled=False,database_path=str(out/'offline.sqlite3'),max_results_per_point=3),store)
    rows=[]
    for path in sorted(source.glob('[DH]0*.json')):
        original=json.loads(path.read_text(encoding='utf-8'));job=store.get_job(original['job']['job_id'])
        resources=store.resources(job['job_id']);request=SearchRequest(**job['request'])
        for point in job['knowledge_points']:
            for resource in resources.values(): svc._rank(job,point,resource,request)
        result=svc.results(job['job_id'])
        save(out/path.name,{'original_case':original['case'],'mode':'offline_saved_evidence_development_replay','results':result})
        prior={i['resource']['resource_id'] for g in original['results']['groups'] for i in [*g['items'],*(i for v in g.get('platform_items',{}).values() for i in v)]}
        after={i['resource']['resource_id'] for g in result['groups'] for i in [*g['items'],*(i for v in g.get('platform_items',{}).values() for i in v)]}
        rows.append({'id':path.stem,'before_default':sum(len(g['items']) for g in original['results']['groups']),
            'after_default':sum(len(g['items']) for g in result['groups']),
            'platform_counts':{p:sum(len(g.get('platform_items',{}).get(p,[])) for g in result['groups']) for p in ('bilibili','icourse163','other')},
            'removed_visible_ids':sorted(prior-after),'newly_visible_saved_ids':sorted(after-prior),
            'rechecked_persisted_resources':len(resources)})
    store.close()
    save(out/'summary.json',{'mode':'offline development repair validation; previous holdout consumed',
        'external_requests':0,'source_database_unchanged':before==hashlib.sha256((source/'live.sqlite3').read_bytes()).hexdigest(),
        'source_database_sha256':before,'cases':rows,
        'backend_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'backend/app').rglob('*.py'))}})
    print(json.dumps(rows,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    main(parser.parse_args())
