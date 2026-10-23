"""Read-only audit of the verified external restart reused for final acceptance."""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_ai_video_runtime_restart5 import history_presence

OUT = ROOT / 'evidence/ai-video-repair-20261021/runtime-final-restart9.json'
REUSE = ROOT / 'evidence/ai-video-fallback-repair-20261021/runtime/restart-9-runtime-reuse.json'
TARGETS = ('related_concepts.py', 'related_recommendations.py', 'ai_video_service.py',
    'ai_video_fallback.py', 'fetcher.py', 'config.py', 'service.py', 'extractor.py',
    'video_availability.py', 'read_related_cache.py', 'read_rank_cache.py', 'queries.py',
    'source_adapters/bilibili.py', 'source_adapters/video_leads.py')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def served_build(port, directory):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f'http://127.0.0.1:{port}'
    with opener.open(base + '/', timeout=20) as response:
        body = response.read()
    local = directory / 'index.html'
    result = {'port': port, 'index_matches_disk': digest(body) == digest(local.read_bytes()), 'assets': []}
    paths = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"?#]+)', body.decode('utf-8'))))
    for path in paths:
        target = (directory / path.lstrip('/')).resolve()
        assert target.is_relative_to(directory.resolve()) and target.is_file()
        with opener.open(base + path, timeout=20) as response:
            data = response.read()
        result['assets'].append({'path': path, 'served_sha256': digest(data),
            'disk_sha256': digest(target.read_bytes()), 'matches': digest(data) == digest(target.read_bytes())})
    result['all_served_assets_match'] = bool(paths) and result['index_matches_disk'] and all(x['matches'] for x in result['assets'])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--successor-receipt', type=Path)
    args = parser.parse_args()
    assert not OUT.exists(), 'Preserve the earlier audit'
    spec = importlib.util.spec_from_file_location('restart_helper', ROOT / 'scripts/restart_ai_video_runtime_20261021.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    reuse = json.loads(REUSE.read_text(encoding='utf-8'))
    external_path = Path(reuse['external_receipt'])
    assert digest(external_path.read_bytes()) == reuse['external_receipt_sha256']
    external = json.loads(external_path.read_text(encoding='utf-8-sig'))
    successor = None
    if args.successor_receipt:
        successor = json.loads(args.successor_receipt.read_text(encoding='utf-8-sig'))
        assert successor['status'] == 'passed'
        for name in TARGETS:
            key = 'backend\\app\\' + name.replace('/', '\\')
            assert successor['source_hashes'][key] == external['source_hashes'][key]
    expected = {k.replace('\\', '/'): v for k, v in external['source_hashes'].items()}
    current = {k.replace('\\', '/'): v for k, v in helper.source_hashes().items()}
    changes = [{'path': k, 'loaded_sha256': expected.get(k), 'current_sha256': current.get(k)}
        for k in sorted(set(expected) | set(current)) if expected.get(k) != current.get(k)]
    target_names = {'backend/app/' + x for x in TARGETS}
    target_rows = [{'path': name, 'loaded_sha256': expected.get(name), 'current_sha256': current.get(name),
        'matches': expected.get(name) is not None and expected.get(name) == current.get(name)} for name in sorted(target_names)]
    report = {'captured_at': helper.stamp(), 'operation': 'read_only_final_delivery_audit',
        'runtime_reuse_confirmation': str(REUSE), 'external_restart_receipt': str(external_path),
        'production_writes': 0, 'configuration_changes': 0, 'restarts': 0, 'search_queries': 0, 'new_jobs': 0,
        'idle_required': False, 'hashes': {'targeted_video_files': target_rows,
        'targeted_video_files_match': all(x['matches'] for x in target_rows),
        'unrelated_source_changes': [x for x in changes if x['path'] not in target_names],
        'web_build_match': not any(x['path'].startswith('frontend/dist/') for x in changes),
        'mobile_preview_build_match': not any(x['path'].startswith('frontend/dist-mobile-preview/') for x in changes)},
        'services': [], 'database_history': [], 'protected_history': []}
    if successor:
        report['subsequent_external_restart'] = {'receipt': str(args.successor_receipt.resolve()),
            'receipt_sha256': digest(args.successor_receipt.read_bytes()), 'started_at': successor['started_at'],
            'finished_at': successor['finished_at'], 'video_repair_hashes_unchanged': True,
            'not_pid_continuity_of_acceptance_baseline': True}
    secrets = set()
    for baseline in reuse['services']:
        port = baseline['port']
        observed = helper.listeners(port)
        current_start = next(x for x in successor['started'] if x['port'] == port) if successor else None
        expected_pid = current_start['listeners'][0][1] if current_start else baseline['pid']
        expected_parent = current_start['launcher_pid'] if current_start else baseline['parent_pid']
        assert observed == [('127.0.0.1', expected_pid)], f'Listener identity changed on {port}'
        process, parent = psutil.Process(expected_pid), psutil.Process(expected_parent)
        if successor:
            begin = datetime.fromisoformat(successor['started_at']).timestamp()
            end = datetime.fromisoformat(successor['finished_at']).timestamp()
            creation_matches = begin <= parent.create_time() <= process.create_time() <= end
        else:
            creation_matches = process.create_time() == baseline['created'] and parent.create_time() == baseline['parent_created']
        exact_identity = (creation_matches
            and process.ppid() == parent.pid and process.cmdline() == baseline['command']
            and Path(process.cwd()).resolve() == ROOT and Path(parent.exe()).resolve() == (ROOT / '.venv/Scripts/python.exe').resolve())
        environment = process.environ()
        for key in ('TAVILY_API_KEY', 'SERPER_API_KEY', 'LLM_API_KEY'):
            if environment.get(key):
                secrets.add(environment[key])
        safe = {key: environment.get(key) for key in helper.SAFE_KEYS}
        report['services'].append({'port': port, 'pid': process.pid, 'parent_pid': parent.pid,
            'pid_matches_acceptance_baseline': process.pid == baseline['pid'],
            'created_at': datetime.fromtimestamp(process.create_time(), timezone.utc).isoformat(),
            'exact_identity_matches': exact_identity, 'safe_flags_match': safe == baseline['settings'], 'safe_flags': safe,
            'health': helper.request(port, '/health'), 'ready': helper.request(port, '/health/ready'),
            'capabilities': helper.request(port, '/api/capabilities')})
        old = next(row for row in external['before'] if row['port'] == port)
        report['database_history'].append(history_presence(Path(old['database']['path']), Path(old['backup']['path'])))
    with sqlite3.connect((ROOT / 'data/discovery.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
        for key, before in reuse['protected_terminal_history'].items():
            if '/v' in key:
                project, version = key.rsplit('/v', 1)
                row = connection.execute('select status,data from project_versions where project_id=? and version=?', (project, int(version))).fetchone()
            else:
                row = connection.execute('select status,data from jobs where id=?', (key,)).fetchone()
            report['protected_history'].append({'id': key, 'exists': row is not None,
                'status_unchanged': bool(row) and row[0] == before['status'],
                'content_hash_unchanged': bool(row) and digest(row[1].encode()) == before['raw_data_sha256']})
    report['served_frontend'] = [served_build(8001, ROOT / 'frontend/dist'), served_build(8928, ROOT / 'frontend/dist-mobile-preview')]
    from backend.app.config import Settings
    settings = Settings.from_env()
    for key in ('tavily_api_key', 'serper_api_key', 'llm_api_key'):
        value = getattr(settings, key, '')
        if value:
            secrets.add(value)
    scope = [ROOT / 'evidence/ai-video-repair-20261021', ROOT / 'evidence/ai-video-fallback-repair-20261021', ROOT / 'docs/ai-video-fallback-20261021.md']
    scan = {'configured_unique_secret_count': len(secrets), 'files_scanned': 0, 'bytes_scanned': 0,
        'matching_file_count': 0, 'exact_match_occurrences': 0, 'unreadable_file_count': 0,
        'scope': [str(x.relative_to(ROOT)) for x in scope], 'secret_values_or_hashes_recorded': False}
    needles = {value.encode() for value in secrets}
    for area in scope:
        for path in area.rglob('*') if area.is_dir() else [area]:
            if not path.is_file() or path == OUT:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                scan['unreadable_file_count'] += 1
                continue
            scan['files_scanned'] += 1
            scan['bytes_scanned'] += len(data)
            matches = sum(data.count(needle) for needle in needles)
            scan['matching_file_count'] += bool(matches)
            scan['exact_match_occurrences'] += matches
    report['configured_secret_scan'] = scan
    report['finished_at'] = helper.stamp()
    with OUT.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'output': str(OUT), 'video_hashes_match': report['hashes']['targeted_video_files_match'],
        'unrelated_drift': [x['path'] for x in report['hashes']['unrelated_source_changes']],
        'all_old_keys_retained': all(x['all_old_rows_present'] for x in report['database_history']),
        'protected_contents_unchanged': all(x['content_hash_unchanged'] for x in report['protected_history']),
        'served_assets_match': all(x['all_served_assets_match'] for x in report['served_frontend']),
        'secret_match_files': scan['matching_file_count'], 'secret_match_occurrences': scan['exact_match_occurrences']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
