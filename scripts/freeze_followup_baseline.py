"""Archive the delivered v6 sources and evidence before follow-up edits."""
import hashlib,json,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'reports/evidence-followup-20261014/baseline-v6'
out.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
v6=ROOT/'reports/link-completion-20261014/final-validation.json'
validation=json.loads(v6.read_text(encoding='utf-8'))
assert sha(v6)=='f06c406c8d14709af2bf8be0f01455ca2607f531296c3226094345c98b634e98'
assert all(sha(ROOT/p)==h for p,h in validation['source_hashes'].items())
assert all(sha(ROOT/p)==h for p,h in validation['artifact_hashes'].items())
roots=['backend','tests','scripts','docs','frontend/src','frontend/tests','frontend/e2e','frontend/dist']
files={p for r in roots if (ROOT/r).exists() for p in (ROOT/r).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
files.update(p for p in ROOT.iterdir() if p.is_file() and p.name!='.env')
files.update(p for p in (ROOT/'frontend').iterdir() if p.is_file())
files.discard(Path(__file__).resolve())
source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}
report_files={p for r in ['link-completion-20261014','link-trial-20261014'] for p in (ROOT/'reports'/r).rglob('*') if p.is_file() and p.suffix not in {'.log','.lock','.tmp'} and not p.name.endswith(('-wal','-shm'))}
report_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(report_files)}
for name,paths in [('source.zip',files),('reports.zip',report_files)]:
    with zipfile.ZipFile(out/name,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(paths):z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(out/name) as z:
        assert z.testzip() is None
manifest={'at':datetime.now(timezone.utc).isoformat(),'scope':'delivered v6 before final targeted follow-up','previous_validation_sha256':sha(v6),
 'source_hashes':source_hashes,'report_hashes':report_hashes,'env_sha256_only':sha(ROOT/'.env'),
 'archive_hashes':{name:sha(out/name) for name in ['source.zip','reports.zip']},
 'exclusions':'environment credentials, dependency runtimes, Python caches, mutable logs and SQLite sidecars; original historical directories retained'}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'manifest.sha256').write_text(sha(out/'manifest.json')+'  manifest.json\n',encoding='utf-8')
print(json.dumps({'source_files':len(files),'report_files':len(report_files),'archives':manifest['archive_hashes'],'baseline_manifest_sha256':sha(out/'manifest.json')}))
