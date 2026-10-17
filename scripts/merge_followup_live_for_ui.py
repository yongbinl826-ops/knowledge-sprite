"""Copy five completed live jobs into the isolated UI evidence database."""
import hashlib,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'reports/evidence-followup-20261014'
source=out/'live-final-replay-v2/offline.sqlite3'
before=hashlib.sha256(source.read_bytes()).hexdigest()
checkpoint=json.loads((out/'live/checkpoint.json').read_text(encoding='utf-8'))
src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
target=sqlite3.connect(out/'ui-final/review.sqlite3')
jobs={}
with target:
    for case in checkpoint['cases']:
        jid=case['job_id'];jobs['live_'+case['id']]=jid
        for table,column in [('jobs','id'),('knowledge_points','job_id'),('resources','job_id'),('matches','job_id'),('evidence','job_id')]:
            rows=src.execute(f'SELECT * FROM {table} WHERE {column}=?',(jid,)).fetchall()
            for row in rows:target.execute(f'INSERT INTO {table} VALUES('+','.join('?' for _ in row)+')',row)
        for row in src.execute('SELECT job_id,data FROM search_attempts WHERE job_id=?',(jid,)):
            target.execute('INSERT INTO search_attempts(job_id,data) VALUES(?,?)',row)
src.close();target.close()
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
manifest_path=out/'ui-final/manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'));manifest['jobs'].update(jobs)
manifest['live_source']={'path':str(source),'sha256':before,'external_requests':0,'source_unchanged':True}
manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(jobs))
