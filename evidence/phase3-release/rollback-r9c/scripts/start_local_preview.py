"""Run the current workspace build with existing local credentials, without copying them.

Usage: python scripts/start_local_preview.py [--port 8000] [--source-env PATH]
Only loopback is exposed. No original database or configuration is overwritten.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--source-env', type=Path)
    parser.add_argument('--model-audit-dir', type=Path, help='Optional acceptance-only sanitized model metadata directory')
    parser.add_argument('--application-default-budgets', action='store_true', help='Use application defaults of 30 searches/40 detail pages per job for this preview only')
    parser.add_argument('--public-catalog-fallback', action='store_true', help='Enable bounded public course-index discovery for this preview only')
    args = parser.parse_args()
    from dotenv import load_dotenv
    if args.source_env:
        if not args.source_env.is_file():
            parser.error('The specified local environment file does not exist')
        load_dotenv(args.source_env, override=False)
    (ROOT / 'data').mkdir(exist_ok=True)
    os.environ['DATABASE_PATH'] = str(ROOT / 'data' / 'preview.sqlite3')
    overrides = {}
    if args.application_default_budgets:
        overrides = {'MAX_SEARCH_REQUESTS': '30', 'MAX_DETAIL_PAGES': '40'}
        os.environ.update(overrides)
    if args.public_catalog_fallback:
        overrides['PUBLIC_CATALOG_FALLBACK'] = 'true'
        os.environ['PUBLIC_CATALOG_FALLBACK'] = 'true'
    os.chdir(ROOT)
    # Non-sensitive provenance lets acceptance distinguish the running source
    # snapshot from later disk edits. Credentials and database contents are omitted.
    sources = [path for directory in (ROOT / 'backend/app', ROOT / 'frontend/dist')
               for path in directory.rglob('*') if path.is_file() and '__pycache__' not in path.parts]
    runtime = {'pid': os.getpid(), 'root': str(ROOT), 'port': args.port,
               'preview_configuration_overrides': overrides,
               'started_at': datetime.now(timezone.utc).isoformat(),
               'files': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}
    (ROOT / 'tmp').mkdir(exist_ok=True)
    (ROOT / 'tmp' / 'preview-runtime-manifest.json').write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.model_audit_dir:
        audit_dir = args.model_audit_dir.resolve()
        if not audit_dir.is_relative_to(ROOT / 'evidence'):
            parser.error('Acceptance metadata must stay under this workspace evidence directory')
        audit_dir.mkdir(parents=True, exist_ok=True)
        from scripts.serve_project_acceptance import install_model_observer
        install_model_observer(audit_dir, {'output': str(audit_dir), 'acceptance_valid': True, 'audit_errors': [], 'jobs': {}})
    import uvicorn
    uvicorn.run('backend.app.main:app', host='127.0.0.1', port=args.port, log_level='info', access_log=False)

if __name__ == '__main__':
    main()
