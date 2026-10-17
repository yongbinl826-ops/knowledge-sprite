"""Re-rank the original forty saved jobs offline without changing source evidence."""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.service import JobService
out=ROOT/'reports/link-completion-20261014'
source=out/'live/live.sqlite3'; target=out/(sys.argv[1] if len(sys.argv)>1 else 'offline-final-40')
target.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=sha(source);shutil.copyfile(source,target/'offline.sqlite3')
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
save=lambda p,v:p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
store=Store(str(target/'offline.sqlite3'))
service=JobService(Settings(fetch_enabled=False,database_path=str(target/'offline.sqlite3'),max_results_per_point=3),store)
ids=lambda results:{i['resource']['resource_id'] for g in results['groups'] for i in [*g['items'],*(i for v in g.get('platform_items',{}).values() for i in v)]}
rows=[]
for row in load(out/'pre-repair-40/checkpoint.json')['cases']:
    original=load(out/'live'/row['evidence_file']);job=store.get_job(row['job_id'])
    resources=store.resources(job['job_id']);request=SearchRequest(**job['request'])
    for point in job['knowledge_points']:
        for resource in resources.values():service._rank(job,point,resource,request)
    result=service.results(job['job_id'])
    prior,after=ids(original['results']),ids(result)
    record={'id':row['id'],'source_evidence_file':row['evidence_file'],'source_evidence_sha256':sha(out/'live'/row['evidence_file']),
            'saved_resource_count':len(resources),'before_default':sum(len(g['items']) for g in original['results']['groups']),
            'after_default':sum(len(g['items']) for g in result['groups']),
            'removed_visible_ids':sorted(prior-after),'newly_visible_saved_ids':sorted(after-prior)}
    save(target/(row['id']+'.json'),{'mode':'offline saved evidence development replay, not fresh holdout','comparison':record,'results':result})
    rows.append(record)
store.close()
assert before==sha(source)
removed={(r['id'],rid) for r in rows for rid in r['removed_visible_ids']}
assert ('H14','res_e99b1d31c2f83fab4e5c3d59') in removed
assert ('H15','res_3ba5bc8d1a7cdde1a3bbe014') in removed
save(target/'summary.json',{'external_requests':0,'source_database_unchanged':True,'source_database_sha256':before,'cases':rows,
    'backend_hashes':{str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'backend/app').rglob('*.py'))}})
print(json.dumps({'cases':len(rows),'removed':sorted(removed),'new':[(r['id'],r['newly_visible_saved_ids']) for r in rows if r['newly_visible_saved_ids']]},ensure_ascii=False))
