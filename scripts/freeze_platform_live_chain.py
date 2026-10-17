"""Freeze the preceding catalog audit before automatic-chain changes."""
import hashlib, json, zipfile
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
prior_root = root/'reports/platform-catalog-20261017'
prior = json.loads((prior_root/'final-validation.json').read_text(encoding='utf-8'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
out = root/'reports/platform-live-chain-20261017/baseline'
out.mkdir(parents=True, exist_ok=False)
source_drift = [name for name, digest in prior['source_hashes'].items() if sha(root/name) != digest]
artifact_drift = [name for name, digest in prior['artifact_hashes'].items() if sha(prior_root/name) != digest]
assert not source_drift and not artifact_drift, (source_drift, artifact_drift)
paths = {root/name for name in prior['source_hashes']}
paths.update(p for p in (root/'frontend/dist').rglob('*') if p.is_file())
paths.update(root/name for name in ['.env.example','pyproject.toml','requirements.lock.txt','uv.lock','frontend/package.json','frontend/package-lock.json'] if (root/name).is_file())
hashes = {p.relative_to(root).as_posix(): sha(p) for p in sorted(paths)}
with zipfile.ZipFile(out/'source-and-build.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for name in hashes:
        archive.write(root/name, name)
manifest = {'at': datetime.now(timezone.utc).isoformat(), 'source_hashes': hashes,
            'prior_validation_sha256': sha(prior_root/'final-validation.json'),
            'prior_artifact_hashes': prior['artifact_hashes'],
            'env_sha256_only': sha(root/'.env'), 'source_drift':source_drift,
            'artifact_drift':artifact_drift, 'archive_sha256':sha(out/'source-and-build.zip')}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(hashes),'sha256':sha(out/'manifest.json'),'prior_unchanged':True}))
