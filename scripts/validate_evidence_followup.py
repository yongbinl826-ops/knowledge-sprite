"""Final local acceptance gates; never issues an external request."""
import hashlib,json,sys,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/evidence-followup-20261014'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
checks={}
def check(name,value):
    checks[name]=bool(value)
def test_result(path):
    root=ET.parse(path).getroot()
    suites=[root] if root.tag=='testsuite' else root.findall('testsuite')
    result={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    if not suites:
        cases=root.findall('testcase')
        result={'tests':len(cases),**{key:sum(c.find(tag) is not None for c in cases) for key,tag in [('failures','failure'),('errors','error'),('skipped','skipped')]}}
    check(path.name,result['tests']>0 and result['failures']==result['errors']==0)
    return result

baseline=load(OUT/'baseline-v6/manifest.json')
check('v6_manifest_fixed',sha(OUT/'baseline-v6/manifest.json')=='359120c29045962f01fe0149da7f16248fa9117bd26cf782591d9839d4dc3b1e')
check('v6_archives_unchanged',all(sha(OUT/'baseline-v6'/p)==h for p,h in baseline['archive_hashes'].items()))
check('historical_reports_unchanged',all(sha(ROOT/p)==h for p,h in baseline['report_hashes'].items()))
check('main_frontend_dist_unchanged',all(sha(ROOT/p)==h for p,h in baseline['source_hashes'].items() if p.startswith('frontend/dist/')))
check('credentials_unchanged',sha(ROOT/'.env')==baseline['env_sha256_only'])
before,after=load(OUT/'main-preservation-before.json'),load(OUT/'main-preservation-after.json')
check('main_listener_unchanged',before['listeners']==after['listeners'])
check('main_process_identity_unchanged',sorted(before['processes'],key=lambda r:r['ProcessId'])==sorted(after['processes'],key=lambda r:r['ProcessId']))
check('main_health_ok',after['health']['worker_alive'] and after['health']['database_ok'])
tests={p:test_result(OUT/p) for p in ['backend-full-final.xml','backend-source-tests.xml','frontend-unit-v2.xml','process-validation/ownership-tests-v2.xml']}

offline=load(OUT/'offline-40-final/summary.json')
check('offline_40_without_external_requests',len(offline['cases'])==40 and offline['external_requests']==0 and offline['source_database_unchanged'])
weak={'D06':'res_17c43ef75d7764b5d472b963','D13':'res_644d25cf2bb3ff52915b575c','H09':'res_73edc3b2ad065fb5bba0ca30','H16':'res_a3b13c278ed9659dbf95e70a'}
for case,rid in weak.items():
    result=load(OUT/'offline-40-final'/f'{case}.json')['results']
    group=result['groups'][0]
    strong=[*group['items'],*(x for xs in group['platform_items'].values() for x in xs)]
    review=[*group['review_items'],*(x for xs in group['review_platform_items'].values() for x in xs)]
    hits=[x for x in review if x['resource']['resource_id']==rid]
    check(case+'_weak_in_review_only',bool(hits) and all(x['resource']['resource_id']!=rid for x in strong) and all(x['match']['topic_evidence_status']=='needs_review' and x['match']['topic_evidence_reasons'] for x in hits))
negative=[r for r in offline['cases'] if r['id'] in {'D20','H20'}]
check('two_negative_controls_empty',len(negative)==2 and all(r['after_supported']==r['after_partial']==r['after_review']==0 for r in negative))
check('no_resource_id_hardcodes_in_product',not any(rid in p.read_text(encoding='utf-8') for rid in weak.values() for p in (ROOT/'backend/app').rglob('*.py')))

live=load(OUT/'live/finished.json'); checkpoint=load(OUT/'live/checkpoint.json'); frozen=load(OUT/'live/frozen-scope.json')
check('five_live_terminal',live['terminal_cases']==5 and all(r['state']=='terminal' for r in checkpoint['cases']))
check('live_within_budget',all(live['counts'][kind]<=cap for kind,cap in live['caps'].items()))
check('live_code_frozen_during_requests',live['source_hashes_unchanged'])
check('live_consumed_not_holdout',all(r['purpose']=='development_consumed' for r in checkpoint['cases']))
check('no_playback_claim',live['playback_tests']==0)
replay=load(OUT/'live-final-replay-v2/summary.json')
check('final_live_replay_is_offline',len(replay['cases'])==5 and replay['external_requests']==0 and replay['source_database_unchanged'])
check('final_replays_current_backend',all(sha(ROOT/p)==h for summary in [offline,replay] for p,h in summary['backend_hashes'].items()))

process=load(OUT/'process-validation/run-6/summary.json')
check('process_full_acceptance',process['passed'] and process['functional_checks_passed'] and process['source_hashes_unchanged'] and process['production_identity_and_bindings_unchanged'])
check('process_same_current_backend',all(sha(ROOT/p)==h for p,h in process['source_hashes'].items()))
check('process_no_external_dispatch',process['network']['external_connections_observed']==0 and not process['network']['blocked_events'])
check('process_fixture_cleanup',not process['remaining_fixture_listeners'] and process['temporary_directory_removed'])
check('process_active_1_queue_2_observed',load(OUT/'process-validation/run-6/queue-full-before-cancel.json')['health']['active_jobs']==1 and load(OUT/'process-validation/run-6/queue-full-before-cancel.json')['health']['queue_depth']==2)
restart=process['checks']['kill_restart']
check('process_real_pid_change_same_db',restart['old_identity']['pid']!=restart['new_identity']['pid'] and restart['old_identity']['db']==restart['new_identity']['db'])
check('process_no_duplicate_observed',not restart['duplicate_attempt_keys'] and restart['interrupted_jobs_not_replayed'])
check('process_new_job_completed',restart['fresh_job']['status']=='completed')

ui=load(OUT/'ui-final/verification.json')
check('ui_real_browser_acceptance',ui['passed'] and ui['four_weak_checked'] and ui['platform_no_promotion'] and ui['complement_filter_recomputed'] and ui['mobile_no_horizontal_overflow'] and ui['console_errors']==0)
check('ui_current_build',all(sha(ROOT/p)==h for p,h in ui['source_hashes'].items()))
check('ui_current_api',ui['backend_hashes']==offline['backend_hashes'])
source_paths=set()
for folder in ['backend/app','frontend/src','frontend/tests','frontend/e2e','tests','scripts','docs']:
    source_paths.update(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
source_paths.update(ROOT/p for p in baseline['source_hashes'] if not p.startswith('frontend/dist/') and (ROOT/p).exists())
source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(source_paths)}
source_hashes['.env']=sha(ROOT/'.env')
artifacts={}
for p in OUT.rglob('*'):
    if not p.is_file() or p.name in {'final-validation.json','final-validation.sha256'} or p.name.endswith(('-wal','-shm','.lock','.tmp')):continue
    if p.parent.name=='ui-final' and p.name in {'review.sqlite3','server.stdout.log','server.stderr.log'}:continue
    artifacts[p.relative_to(ROOT).as_posix()]=sha(p)
result={'at':datetime.now(timezone.utc).isoformat(),'passed':all(checks.values()),'checks':checks,'tests':tests,
    'source_hashes':source_hashes,'artifact_hashes':artifacts,
    'live_counts':live['counts'],'offline_counts':{k:sum(r[k] for r in offline['cases']) for k in ['after_supported','after_partial','after_review']},
    'limits':['5 topics are development-consumed; not an unseen holdout','Final semantic fix was replayed on exactly the saved live evidence, not re-requested','Directory extraction and playback are not accepted','Local process test: one active plus queue capacity two; not production capacity or external exactly-once proof','Main localhost8000 remains v6; current preview on localhost18007 is read-only']}
(OUT/'final-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'final-validation.sha256').write_text(sha(OUT/'final-validation.json')+'  final-validation.json\n',encoding='utf-8')
print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[k for k,v in checks.items() if not v],'source_files':len(source_hashes),'artifacts':len(artifacts),'sha256':sha(OUT/'final-validation.json')},ensure_ascii=False))
sys.exit(0 if result['passed'] else 1)
