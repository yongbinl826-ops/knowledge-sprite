"""Separate UI copy of saved results plus labeled local complement fixtures."""
import argparse,hashlib,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest,Resource,now
from backend.app.service import JobService

parser=argparse.ArgumentParser()
parser.add_argument('--output',default='reports/evidence-followup-20261014/ui')
parser.add_argument('--source',default='reports/evidence-followup-20261014/offline-40/offline.sqlite3')
args=parser.parse_args()
out=Path(args.output).resolve()
assert out.is_relative_to(ROOT/'reports/evidence-followup-20261014')
out.mkdir(parents=True,exist_ok=False)
source=Path(args.source).resolve()
assert source.is_relative_to(ROOT/'reports/evidence-followup-20261014')
target=out/'review.sqlite3';shutil.copyfile(source,target)
store=Store(str(target));service=JobService(Settings(fetch_enabled=False,database_path=str(target),max_results_per_point=3),store)
v6=json.loads((ROOT/'reports/link-completion-20261014/live/checkpoint.json').read_text(encoding='utf-8'))
jobs={r['id']:r['job_id'] for r in v6['cases'] if r['id'] in {'D06','D13','H06','H09','H16'}}
template=store.get_job(jobs['H06']);request=SearchRequest(**template['request'])
job=json.loads(json.dumps(template));job_id=str(uuid.uuid4());point_id=str(uuid.uuid4());stamp=now()
job.update(job_id=job_id,status='completed',phase='done',created_at=stamp,updated_at=stamp,
    warnings=['本任务仅为隔离界面的模拟来源夹具，无联网请求；用于验证筛选后的互补覆盖计算。'],errors=[])
job['knowledge_points']=[{'knowledge_point_id':point_id,'text':request.knowledge_points[0]}]
job['progress']={key:0 for key in template['progress']}
store.create_job(job)
definitions=[
 ('concurrency','bilibili','video','JavaScript Promise 并发请求教程（模拟来源）','本节讲解JavaScript Promise.all组织并发请求，逐项介绍并发调用。'),
 ('errors','icourse163','course','JavaScript Promise 错误处理课程（模拟来源）','本课程讲解JavaScript Promise异常处理，演示catch捕获与处理错误。'),
]
for name,platform,kind,title,snippet in definitions:
    rid='fixture_'+name;eid='fixture_evidence_'+name;url='https://example.org/'+('video/' if kind=='video' else 'course/')+name
    provenance={'source':'search_template','evidence_id':eid,'url':url}
    resource=Resource(resource_id=rid,title=title,url=url,canonical_url=url,platform=platform,resource_type=kind,
        video_evidence_status='search_discovered' if kind=='video' else 'none',metadata_evidence_level='search',discovered_at=stamp,
        field_provenance={'title':{'source':'search','evidence_id':eid},'resource_type':provenance,'video_evidence_status':provenance}).model_dump()
    evidence={'evidence_id':eid,'kind':'search','source':'explicit_local_ui_fixture','url':url,'title':title,'snippet':snippet,
        'knowledge_point_id':point_id,'observed_at':stamp,'type_source':'search_template','resource_type_hint':kind}
    store.save_resource(job_id,resource);store.add_evidence(job_id,rid,point_id,evidence);service._rank(job,job['knowledge_points'][0],resource,request)
result=service.results(job_id)
(out/'complement-fixture-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
jobs['synthetic_complement']=job_id
store.close()
manifest={'created_at':stamp,'database':str(target),'source_database':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'jobs':jobs,'synthetic_case':'synthetic_complement only; example.org URLs are fixture labels, not discovered resources','external_requests':0}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False))
