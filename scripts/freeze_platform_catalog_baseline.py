"""Preserve v7 before real platform-page investigation; no credentials copied."""
import hashlib,json,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'reports/platform-catalog-20261017/baseline-v7';out.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
validation=ROOT/'reports/evidence-followup-20261014/final-validation.json'
old=json.loads(validation.read_text(encoding='utf-8'))
source_drift=[p for p,h in old['source_hashes'].items() if sha(ROOT/p)!=h]
artifact_drift=[p for p,h in old['artifact_hashes'].items() if sha(ROOT/p)!=h]
assert not source_drift and not artifact_drift,(source_drift,artifact_drift)
with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for name in old['source_hashes']:
        if name!='.env':archive.write(ROOT/name,name)
manifest={'at':datetime.now(timezone.utc).isoformat(),'v7_validation_sha256':sha(validation),
          'source_hashes':old['source_hashes'],'historical_artifact_hashes':old['artifact_hashes'],
          'archive_sha256':sha(out/'source.zip'),'credentials':'hash only; .env not copied',
          'source_drift':source_drift,'artifact_drift':artifact_drift}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'baseline':str(out),'sha256':sha(out/'manifest.json'),'files':len(old['source_hashes'])},ensure_ascii=False))
