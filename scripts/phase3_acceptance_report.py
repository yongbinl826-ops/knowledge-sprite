"""Derive observations from retained real trials; never infer quality from counts."""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse, csv, hashlib, json

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-root', type=Path, default=ROOT/'evidence/phase3-live')
    parser.add_argument('--output', type=Path, default=ROOT/'evidence/phase3-summary')
    args = parser.parse_args()
    live, output = args.live_root.resolve(), args.output.resolve()
    assert live.is_relative_to(ROOT/'evidence') and output.is_relative_to(ROOT/'evidence')
    output.mkdir(parents=True,exist_ok=True)
    run = read(live/'run.json')
    rows = []
    for record in run['records']:
        base = live/record['case_id']
        path = base/'project-view.json'
        view = read(path)
        version = view['version']
        analysis = version.get('analysis') or {}
        row = {'case_id':record['case_id'],'cohort':record['cohort'],'project_id':record['project_id'],
               'version':version['version'],'status':version['status'],'origin':version.get('origin'),
               'prompt_version':version.get('prompt_version'),'analysis_units':len(analysis.get('knowledge_points',[])),
               'declared_skills':sum(len(x.get('learning_skills') or []) for x in analysis.get('knowledge_points',[])),
               'student_edited':version.get('origin')=='student_edit',
               'error_code':(version.get('error') or {}).get('code'),
               'source_view_sha256':sha(path),'prior_analysis_trials':record.get('prior_analysis_trials',[]),
               'prior_search_trials':record.get('prior_search_trials',[]),
               'post_fix_analysis_trial':record.get('post_fix_analysis_trial'),
               'shown_cards':0,'content_skills':0,'title_only_skills':0,'unknown_skills':0,'units_with_content':0,
               'units_with_title_only':0,'units_without_confirmed_support':0,'jobs':[]}
        results = base/'project-results.json'
        if results.exists():
            result = read(results)
            if result['version']['version'] == version['version']:
                row['source_results_sha256'] = sha(results)
                for point in result['points']:
                    group = point.get('result') or {}
                    cards = [*group.get('items',[]),*group.get('partial_items',[])]
                    row['shown_cards'] += len({x['resource']['resource_id'] for x in cards})
                    skills = (group.get('learning_coverage') or {}).get('skills',[])
                    content = sum(bool(x.get('content_resource_ids')) for x in skills)
                    title = sum(not x.get('content_resource_ids') and bool(x.get('title_resource_ids')) for x in skills)
                    row['content_skills'] += content
                    row['title_only_skills'] += title
                    row['unknown_skills'] += sum(not x.get('content_resource_ids') and not x.get('title_resource_ids') for x in skills)
                    row['units_with_content'] += bool(content)
                    row['units_with_title_only'] += bool(title and not content)
                    row['units_without_confirmed_support'] += not content and not title
                row['jobs'] = [{'ordinal':x['ordinal'],'job_id':x.get('job_id'),'status':x.get('job_status',x['status']),
                    'progress':x.get('progress'),'warnings':x.get('warnings',[]),'errors':x.get('errors',[])}
                    for x in result['version']['batches']]
        rows.append(row)
    # Dedupe exact actual call IDs. JSON-returned means transport/parser success,
    # never automatic semantic success or a human content verdict.
    events = {}
    files = []
    for directory in sorted(live.glob('model-audit*')):
        path = directory/'model-events.jsonl'
        if not path.exists():
            continue
        files.append({'path':str(path.relative_to(ROOT)),'sha256':sha(path)})
        for line in path.read_text(encoding='utf8').splitlines():
            event = json.loads(line)
            if event.get('event_type')=='model_call_finished':
                events[event['call_id']] = event
    tasks = defaultdict(lambda:{'calls':0,'prompt_tokens':0,'completion_tokens':0,'total_tokens':0,'usage_unknown_calls':0,'outcomes':Counter()})
    for event in events.values():
        summary = tasks[event['task']]
        summary['calls'] += 1
        summary['outcomes'][event.get('outcome','unknown')] += 1
        usage = event.get('usage') or {}
        if not all(type(usage.get(key)) is int for key in ('prompt_tokens','completion_tokens','total_tokens')):
            summary['usage_unknown_calls'] += 1
        for key in ('prompt_tokens','completion_tokens','total_tokens'):
            summary[key] += usage.get(key,0) if type(usage.get(key)) is int else 0
    report = {'generated_at':datetime.now(timezone.utc).isoformat(),'scope':'real retained phase3 trials, not production acceptance',
        'source_run_sha256':sha(live/'run.json'),'cases':rows,'model_calls':dict(tasks),'model_event_files':files,
        'boundaries':['Card and skill counts are observations, not independent relevance grades.',
            'Title-only and content evidence remain separate; neither proves mastery or project completion.',
            'Student edits and repaired trials are not first-generation passes.',
            'No automatic playback validation is required or claimed.',
            'The separate retained-source claim control is excluded from this live-trial model total.']}
    (output/'observations.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    fields = ['case_id','version','status','origin','analysis_units','declared_skills','shown_cards','content_skills','title_only_skills','unknown_skills','units_without_confirmed_support','error_code']
    with (output/'matrix.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
    print(json.dumps({'output':str(output),'cases':len(rows),'actual_model_calls':len(events),'totals':{key:sum(row[key] for row in rows) for key in ['analysis_units','declared_skills','shown_cards','content_skills','title_only_skills','unknown_skills']}}))

if __name__ == '__main__':
    main()
