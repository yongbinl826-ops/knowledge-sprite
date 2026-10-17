"""Record the completed assistant reviews of H05-H16; no network."""
import json
from pathlib import Path
out=Path('reports/link-completion-20261014')
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
r=load(out/'review-decisions.json'); rows=load(out/'coverage-detailed.json')
done={f'H{i:02d}' for i in range(5,17)}
r['reviewed_cases']=sorted(set(r['reviewed_cases'])|done)
r['case_evidence_hashes'].update({x['id']:x['evidence_sha256'] for x in rows if x['id'] in done})
new=[
('H09','res_73edc3b2ad065fb5bba0ca30','insufficient_evidence','预约直播预告，主题相关，但标题摘要不能证明已有教学内容或回放。'),
('H14','res_e99b1d31c2f83fab4e5c3d59','off_topic','本视频讲周期性定时执行任务线程池，Stream／Collectors只在摘要的“相关视频”推荐项中出现，不能作为本资源教学证据。'),
('H15','res_3ba5bc8d1a7cdde1a3bbe014','off_topic','UE5 Motion Matching的Pose Database／Normalization set，不是关系数据库规范化；摘要为空。'),
('H16','res_a3b13c278ed9659dbf95e70a','insufficient_evidence','标题是泛四元数内容，摘要只有matrix-to-quaternion外链；不能凭外链路径确认本视频讲授旋转。'),
]
existing={(e['case_id'],e['resource_id']) for e in r['exceptions']}
for cid,rid,decision,reason in new:
    if (cid,rid) not in existing:r['exceptions'].append({'case_id':cid,'resource_id':rid,'decision':decision,'reason':reason})
app=[('H09','res_8395bed048592be8b34d142e'),('H09','res_cf6ccaa19a1c0db7abea7f77'),('H16','res_60246d383126503997807e08'),('H16','res_7d92df6fa02dd2a25e502521')]
existing={(e['case_id'],e['resource_id']) for e in r['applications']}
r['applications'] += [{'case_id':c,'resource_id':i} for c,i in app if (c,i) not in existing]
for e in r['exceptions']:
    if e['case_id']=='D06':e['reason']='教学重点是Subgrid对齐，Flexbox作为对照背景出现；目标教学覆盖证据不足，不能判为完全无关。'
    if e['case_id']=='D13':e['reason']='摘要将匿名函数称为闭包，但只说明匿名函数与回调用法，缺少词法作用域或捕获外部变量的教学证据。'
(out/'review-decisions.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print({'reviewed_cases':len(r['reviewed_cases']),'exceptions':len(r['exceptions'])})
