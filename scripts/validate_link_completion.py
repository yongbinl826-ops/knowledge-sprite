"""Validate frozen campaign evidence locally; no external requests."""
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / sys.argv[1]
load = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
digest = lambda v: hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
checks = {}

def check(name, value):
    checks[name] = bool(value)
    if not value:
        raise AssertionError(name)

state = load(out / 'live/checkpoint.json')
finished = load(out / 'live/finished.json')
frozen = load(out / 'live' / state['frozen_file'])
rows = load(out / 'coverage-detailed.json')
summary = load(out / 'summary.json')
review = load(out / 'review-decisions.json')
links = load(out / 'reviewed-links.json')
cases = load(ROOT / 'reports/link-trial-20261014/evaluation-cases.json')
if isinstance(cases, dict):
    cases = cases['cases']
check('original_40_manifest_unchanged', sha(ROOT / 'reports/link-trial-20261014/evaluation-cases.json') == frozen['manifest_sha256'])
check('all_original_case_ids_once', len(rows) == 40 and {r['id'] for r in rows} == {c['id'] for c in cases})
check('all_cases_terminal', all(r['state'] == 'terminal' for r in rows) and finished['terminal_cases'] == 40 and finished['pending_cases'] == 0)
check('no_unknown_inflight', state['inflight'] is None and state['active_case'] is None)
check('latest_source_hashes_match', all(sha(ROOT / p) == h for p, h in frozen['source_hashes'].items()))
check('runner_confirmed_freeze', finished['source_hashes_unchanged'])
check('requests_unchanged', all(r['request_sha256'] == digest(next(c['request'] for c in cases if c['id'] == r['id'])) for r in rows))
check('result_hashes_match', all(sha(out / 'live' / r['evidence_file']) == r['evidence_sha256'] for r in rows))
check('reviewed_every_case', set(review['reviewed_cases']) == {r['id'] for r in rows})
check('reviews_match_result_hashes', all(review['case_evidence_hashes'][r['id']] == r['evidence_sha256'] for r in rows))
check('review_classified_every_unique_link', len(links) == summary['visible_unique_case_resource_pairs'] and all(i['evidence_review'] in {'direct_topic','application','neighboring_or_insufficient','off_topic'} for i in links))
check('known_quality_failures_retained', all(any(i['case_id'] == e['case_id'] and i['resource_id'] == e['resource_id'] and i['evidence_review'] in {'neighboring_or_insufficient','off_topic'} for i in links) for e in review['exceptions']))
check('resolved_mismatches_not_displayed', all(not any(i['case_id'] == e['case_id'] and i['resource_id'] == e['resource_id'] for i in links) for e in review.get('resolved_exceptions',[])))
check('both_platforms_queried_all_40', all(summary['platforms'][p]['queries_executed'] == 40 for p in ('bilibili','icourse163')))
check('negative_controls_returned_zero', len(summary['negative_controls']) == 2 and all(r['returned'] == 0 for r in summary['negative_controls']))

requests = state['requests']
counts = dict(Counter(r['kind'] for r in requests))
check('http_counts_reconcile', counts == state['counts'] == finished['counts'] == summary['transport_counts_including_probe_and_recheck'])
check('request_ids_contiguous', [r['id'] for r in requests] == list(range(1, len(requests) + 1)))
end_time = lambda r: r.get('finished_at') or (r.get('trace',{}).get('finished_at') if r['kind']=='dns_http' else None)
check('no_inflight_request_rows', all(r['status'] != 'inflight' and end_time(r) for r in requests))
check('budgets_not_exceeded', all(counts[k] <= v for k, v in frozen['caps'].items()))
prior = load(out / 'live/epoch-1-checkpoint.json')
check('first_epoch_request_prefix_preserved', requests[:len(prior['requests'])] == prior['requests'])
epoch2 = load(out / 'live/frozen-scope-epoch-2.json')['source_hashes']
epoch3 = load(out / 'live/frozen-scope-epoch-3.json')['source_hashes']
check('epoch2_epoch3_application_identical', {k:v for k,v in epoch2.items() if k.startswith('backend')} == {k:v for k,v in epoch3.items() if k.startswith('backend')})
attempts = sum(1 + len(r.get('previous_attempts', [])) for r in rows)
check('exactly_four_recorded_rechecks', attempts == 44 and {r['id'] for r in rows if r.get('previous_attempts')} == {'D02','D18','H14','H15'})
check('rechecked_holdout_marked_consumed', all(r['purpose']=='development_consumed' for r in rows if r['id'] in {'H14','H15'}))
parse = lambda t: datetime.fromisoformat(t)
intervals = [(parse(b['started_at']) - parse(a['started_at'])).total_seconds() for a,b in zip(requests, requests[1:])]
check('visible_transport_pacing_at_least_2_seconds', min(intervals) >= 2)
check('visible_transport_concurrency_one', all(parse(end_time(a)) <= parse(b['started_at']) for a,b in zip(requests, requests[1:])))

old_path = ROOT / 'reports/link-trial-20261014/final-validation.json'
old = load(old_path)
check('prior_validation_unchanged', sha(old_path) == '971222c73f6bcc06966a35aa94b16fce4c9fd864e50db24ce560c904d1645837')
check('all_prior_static_artifacts_preserved', all(sha(ROOT / p) == h for p,h in old['artifact_hashes'].items()))
full = ElementTree.parse(out / 'epoch4-backend-tests.xml').getroot().find('testsuite')
runner = ElementTree.parse(out / 'epoch4-runner-final.xml').getroot().find('testsuite')
check('full_suite_no_failure', full is not None and full.attrib['errors'] == '0' and full.attrib['failures'] == '0')
check('runner_final_no_failure', runner is not None and runner.attrib['errors'] == '0' and runner.attrib['failures'] == '0')
backend_count=len(full.findall('testcase'));subtest_count=int(full.attrib['tests'])-backend_count
ui = load(out / 'main-visible-cards.json')
check('main_real_browser_visible_cards', len(ui['resourceCards']) == 5)
health=load(out/'main-health.json');launch=load(out/'main-launch.json');browser=load(out/'main-epoch4-ui-checks.json')
check('final_runtime_health',health['status']=='ok' and health['single_worker'] and health['worker_alive'] and health['active_jobs']==0 and health['queue_depth']==0 and launch['source_epoch']==4)
check('final_browser_no_warning_or_error',browser['source_epoch']==4 and browser['console']==[])

excluded = {'main-out.log','main-err.log','main-epoch4-out.log','main-epoch4-err.log','final-validation.json','final-validation.sha256'}
artifact_hashes = {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name not in excluded and p.suffix not in {'.sqlite3','.lock','.tmp'} and not p.name.endswith(('-wal','-shm'))}
source_paths = [ROOT / p for p in frozen['source_hashes']]
source_paths += [ROOT / 'README.md', *sorted((ROOT / 'scripts').glob('*link*.py')), *sorted((ROOT / 'scripts').glob('*completion*.py')), ROOT / 'tests/test_completion_repairs.py', ROOT / 'tests/test_link_campaign.py']
result = {
    'at':datetime.now(timezone.utc).isoformat(),
    'status':'40 topics executed; link evidence reviewed; page/catalog/playback boundaries remain',
    'checks':checks,
    'summary':summary,
    'tasks_including_rechecks':attempts,
    'review_counts':dict(Counter(i['evidence_review'] for i in links)),
    'transport_min_start_interval_seconds':min(intervals),
    'transport_peak_concurrency':1,
    'transport_end_time_source':'top-level finished_at; historical DNS uses preserved trace.finished_at',
    'physical_searx_upstream_http':'unknown',
    'tests':{'full_backend_passed':backend_count,'subtests_passed':subtest_count,'runner_final_targeted_passed':len(runner.findall('testcase')),'full_xml':full.attrib,'runner_xml':runner.attrib},
    'prior_static_artifacts_verified':len(old['artifact_hashes']),
    'source_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in source_paths},
    'artifact_hashes':artifact_hashes,
    'excluded_from_static_hashes':['main rolling logs','SQLite runtime databases and sidecars','lock/temp files','validation itself'],
    'unknowns':['independent human accuracy','actual course/page availability','playback','Bili and MOOC automatic catalogs','SearXNG physical upstream request count','production capacity'],
}
target = out / 'final-validation.json'
target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(out / 'final-validation.sha256').write_text(sha(target)+'  final-validation.json\n',encoding='utf-8')
print(json.dumps({'checks':len(checks),'all_passed':all(checks.values()),'artifact_hashes':len(artifact_hashes),'validation_sha256':sha(target)},ensure_ascii=False))
