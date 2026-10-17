"""Replay the v6 final forty jobs into a separate SQLite with current rules."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.service import JobService

def visible(results):
    seen={}
    for group in results['groups']:
        for key,platform_key in [('items','platform_items'),('partial_items','partial_platform_items'),('review_items','review_platform_items')]:
            for item in [*group.get(key,[]),*(i for values in group.get(platform_key,{}).values() for i in values)]:
                seen[item['resource']['resource_id']]=item
    return seen

def main(args):
    source=Path(args.source).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    save=lambda p,v:p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
    before=sha(source/'live.sqlite3');shutil.copyfile(source/'live.sqlite3',out/'offline.sqlite3')
    store=Store(str(out/'offline.sqlite3'));svc=JobService(Settings(fetch_enabled=False,database_path=str(out/'offline.sqlite3'),max_results_per_point=3),store)
    rows=[]
    for row in load(source/'checkpoint.json')['cases']:
        original=load(source/row['evidence_file']);job=store.get_job(row['job_id']);resources=store.resources(row['job_id'])
        request=SearchRequest(**job['request'])
        for point in job['knowledge_points']:
            for resource in resources.values():svc._rank(job,point,resource,request)
        result=svc.results(job['job_id']);old,new=visible(original['results']),visible(result)
        record={'id':row['id'],'job_id':row['job_id'],'purpose':'saved_evidence_development_regression','original_request_sha256':row['request_sha256'],
            'source_evidence_file':row['evidence_file'],'source_evidence_sha256':sha(source/row['evidence_file']),
            'saved_resource_count':len(resources),'before_default':sum(len(g['items']) for g in original['results']['groups']),
            'after_supported':sum(len(g['items']) for g in result['groups']),
            'after_partial':sum(len(g.get('partial_items',[])) for g in result['groups']),
            'after_review':sum(len(g.get('review_items',[])) for g in result['groups']),
            'removed_visible_ids':sorted(old.keys()-new.keys()),'newly_visible_saved_ids':sorted(new.keys()-old.keys()),
            'status_changes':[{'resource_id':rid,'old_status':old[rid]['match'].get('topic_evidence_status','unclassified_v6'),'new_status':i['match'].get('topic_evidence_status'),
                'reasons':i['match'].get('topic_evidence_reasons',[])} for rid,i in new.items() if rid in old and i['match'].get('topic_evidence_status')!=old[rid]['match'].get('topic_evidence_status','supported')]}
        save(out/(row['id']+'.json'),{'comparison':record,'request':job['request'],'results':result});rows.append(record)
    store.close();assert before==sha(source/'live.sqlite3')
    negative=[r for r in rows if r['id'] in {'D20','H20'}]
    assert all(r['after_supported']==r['after_partial']==r['after_review']==0 for r in negative)
    summary={'external_requests':0,'mode':'synchronous saved SQLite/evidence replay; no provider/fetch execution','source_database_unchanged':True,
        'source_database_sha256':before,'cases':rows,'backend_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'backend/app').rglob('*.py'))}}
    save(out/'summary.json',summary)
    print(json.dumps({'cases':len(rows),'supported':sum(r['after_supported'] for r in rows),'partial':sum(r['after_partial'] for r in rows),'review':sum(r['after_review'] for r in rows),
        'changed_cases':[r['id'] for r in rows if r['status_changes'] or r['removed_visible_ids'] or r['newly_visible_saved_ids']]},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',default='reports/link-completion-20261014/live');parser.add_argument('--output',default='reports/evidence-followup-20261014/offline-40');main(parser.parse_args())
