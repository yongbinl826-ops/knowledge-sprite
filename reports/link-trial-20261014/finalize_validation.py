"""Read-only evidence verification plus final manifest; never calls the network."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def relative(path): return path.relative_to(ROOT).as_posix()

cases=[read(p) for p in sorted((HERE/'live-v1').glob('[DH]0*.json'))]
requests=[r for c in cases for a in c['results']['search_attempts'] for r in a.get('provider_requests',[])]
progress=Counter()
for c in cases: progress.update({k:v for k,v in c['job']['progress'].items() if isinstance(v,int)})
frozen=read(HERE/'live-v1/frozen-scope.json')
finished=read(HERE/'live-v1/finished.json')
replay=read(HERE/'offline-replay-v3-final/summary.json')
assert len(cases)==8 and progress['search_requests']==64
assert len(requests)==64 and all(r.get('retry_index',0)==0 for r in requests)
assert finished['source_hashes_unchanged'] and replay['source_database_unchanged']
assert digest(HERE/'live-v1/live.sqlite3')==replay['source_database_sha256']
assert digest(HERE/'evaluation-cases.json')==frozen['manifest_sha256']
current_backend={relative(p):digest(p) for p in sorted((ROOT/'backend/app').rglob('*.py'))}
assert current_backend=={Path(p).as_posix():h for p,h in replay['backend_hashes'].items()}
post_live_changes=[Path(p).as_posix() for p,h in frozen['source_hashes'].items() if digest(ROOT/p)!=h]
assert set(post_live_changes)=={'backend/app/ranking.py','backend/app/service.py'}
replayed=[read(p) for p in sorted((HERE/'offline-replay-v3-final').glob('[DH]0*.json'))]
visible={i['resource']['resource_id']:i for c in replayed for g in c['results']['groups']
         for i in [*g['items'],*(i for items in g['platform_items'].values() for i in items) ]}
wrong={'res_4a5c8ba7ca1fd4bc531450d3','res_2a5b07262e65a3ef79f7e779','res_2c2d83de03dcd1df0f6e3d3f'}
restored={'res_7273464738a20d7d5a3292b8','res_fa78a19d2b6e64ad63fee816','res_d2a2a2ee5b10905b6aa3bc7d','res_1adfa84aece04ff59027aa48'}
assert not wrong & visible.keys() and restored <= visible.keys()
assert len(visible)==20
assert sum(len(g['items']) for c in replayed for g in c['results']['groups'])==14
suite=ET.parse(HERE/'backend-tests-v3-final.xml').getroot()
suites=list(suite.iter('testsuite'))
assert all(int(s.get('failures','0'))==0 and int(s.get('errors','0'))==0 for s in suites)
baseline=read(HERE/'baseline-hashes.json')
dep_paths=['pyproject.toml','uv.lock','frontend/package.json','frontend/package-lock.json','requirements.lock.txt']
deps={p:{'sha256':digest(ROOT/p),'unchanged':digest(ROOT/p)==baseline[p]} for p in dep_paths}
assert all(d['unchanged'] for d in deps.values())
health=read(HERE/'runtime-v3-health.json')
assert health['status']=='ok' and health['worker_alive'] and health['database_ok']
assert health['queue_depth']==0 and health['active_jobs']==0
ui=read(HERE/'main-v3-ui-checks.json')
assert not ui['logs'] and not ui['checks']['overlay'] and ui['checks']['cards']==5
assert all(link['target']=='_blank' and link['rel']=='noopener noreferrer' for link in ui['checks']['links'])
sources=list((ROOT/'backend/app').rglob('*.py'))+list((ROOT/'frontend/src').rglob('*'))
sources += [ROOT/p for p in ('scripts/evaluate_link_discovery.py','scripts/local_admission_load.py','scripts/replay_saved_link_evidence.py',
    'tests/test_link_trial.py','tests/test_saved_link_relevance.py','tests/test_platform_results.py',
    'tests/fixtures/link_relevance_saved_20261014.json','frontend/tests/search.spec.ts','README.md','docs/api-contract.md','.env.example')]
sources += list((ROOT/'frontend/dist').rglob('*'))
source_hashes={relative(p):digest(p) for p in sorted(set(sources)) if p.is_file()}
# Active runtime logs can grow as a user visits the app. Do not freeze them.
artifacts={relative(p):digest(p) for p in sorted(HERE.rglob('*')) if p.is_file()
    and p.name not in {'final-validation.json','final-validation.sha256'}
    and not (p.name.startswith('main') and p.suffix=='.log')
    and not p.name.endswith(('-wal','-shm'))}
validation={'at':datetime.now(timezone.utc).isoformat(),'scope':'link discovery, optional catalog, zero playback tests',
 'status':'bounded verification complete; platform coverage remains partial',
 'live_v1':{'cases':8,'planned_queries':40,'executed_queries':36,'search_budget_http':64,'searxng_endpoint_http':62,
     'official_target_http':2,'official_doh_http':4,'direct_course_video_http':0,'physical_upstream_http':'unknown',
     'raw_hit_cases':5,'default_links':15,'all_job_statuses':'partial','backend_unchanged_during_run':True,
     'post_run_modified_backend_files':post_live_changes,'independent_holdout_after_repairs':False},
 'offline_v3':{'source_candidates':sum(r['rechecked_persisted_resources'] for r in replay['cases']),
     'default_links':14,'unique_default_and_platform_links':20,'hit_cases':5,'external_requests':0,
     'three_known_wrong_removed':True,'four_known_relevant_restored':True,'source_database_unchanged':True,
     'new_live_verification':'not performed','p_at_3_ndcg':'unknown; no independent human gold labels'},
 'tests':{'backend_passed':534,'subtests_passed':26,'xml_testsuite_attributes':[s.attrib for s in suites],
     'frontend_first_run':{'passed':29,'failed':1,'cause':'obsolete UI text assertion'},
     'frontend_followup':'same failed test passed after assertion update; final copy passed again',
     'frontend_build':'passed','ui_existing_live_job':ui['url'],'ui_console_errors_warnings':0},
 'local_load':{'external_http':0,'clients':[5,20],'scope':'ASGI burst with isolated fixture, not sustained production capacity',
     'summary':'local-load-v1/summary.json'},
 'runtime':{'host':'127.0.0.1','port':8000,'health':health,'launcher':read(HERE/'main-v3-launch.json'),
     'actual_public_config':'runtime-effective-config.txt','same_engine_groups_as_live_v1':True,
     'different_budgets':{'main':[12,12,240],'evaluation':[8,2,90]},'env_sha256_only':digest(ROOT/'.env')},
 'dependencies':deps,'source_hashes':source_hashes,'artifact_hashes':artifacts,
 'unknowns':['MOOC reliable recall','first three Chinese topics full chain','independent generalization',
     'new live queries after final ranking repair','automatic Bilibili/MOOC catalog extraction',
     '32 unexecuted cases','long-term external availability','production multiuser capacity'],
 'mutable_log_hashes_excluded':True,'validation_self_hash':'final-validation.sha256'}
(HERE/'final-validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
(HERE/'final-validation.sha256').write_text(digest(HERE/'final-validation.json')+'  final-validation.json\n',encoding='utf-8')
print(json.dumps({'verified':True,'source_files':len(source_hashes),'artifact_files':len(artifacts),
    'source_candidates':validation['offline_v3']['source_candidates'],'dependency_files_unchanged':len(deps)},ensure_ascii=False))
