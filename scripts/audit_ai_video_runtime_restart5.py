"""Read-only delivery audit; configured secret values are never emitted."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'evidence/ai-video-repair-20261021/runtime-final-restart5.json'
RECEIPT = ROOT / 'evidence/ai-video-fallback-repair-20261021/runtime/restart-5.json'
TARGET_FILES = ('related_concepts.py', 'related_recommendations.py', 'ai_video_service.py',
    'ai_video_fallback.py', 'fetcher.py', 'config.py', 'service.py', 'extractor.py',
    'video_availability.py', 'source_adapters/bilibili.py', 'source_adapters/video_leads.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def history_presence(current_path, backup_path):
    result = {'current_path': str(current_path), 'backup_path': str(backup_path), 'tables': []}
    with sqlite3.connect(current_path.as_uri() + '?mode=ro', uri=True) as current:
        with sqlite3.connect(backup_path.as_uri() + '?mode=ro', uri=True) as previous:
            current.execute('begin')
            tables = {x[0] for x in previous.execute("select name from sqlite_master where type='table'")}
            for table in ('jobs', 'resources', 'evidence', 'projects', 'project_versions'):
                if table not in tables:
                    continue
                pk = [x[1] for x in sorted(previous.execute('pragma table_info(' + table + ')'), key=lambda row: row[5]) if x[5]]
                if not pk:
                    raise RuntimeError('History table lacks stable primary key: ' + table)
                columns = ','.join('"' + x + '"' for x in pk)
                old = set(previous.execute('select ' + columns + ' from ' + table))
                now = set(current.execute('select ' + columns + ' from ' + table))
                result['tables'].append({'table': table, 'old_primary_key_count': len(old), 'current_primary_key_count': len(now),
                                         'missing_old_primary_keys': len(old - now), 'all_old_rows_present': old <= now})
    result['all_old_rows_present'] = all(x['all_old_rows_present'] for x in result['tables'])
    result['content_immutability_checked'] = False
    return result


def main():
    spec = importlib.util.spec_from_file_location('restart_helper', ROOT / 'scripts/restart_ai_video_runtime_20261021.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    prior = json.loads(RECEIPT.read_text(encoding='utf-8'))
    expected = {k.replace('\\', '/'): v for k, v in prior['source_hashes_at_restart'].items()}
    current = {k.replace('\\', '/'): v for k, v in helper.source_hashes().items()}
    changes = [{'path': k, 'restart_sha256': expected.get(k), 'current_sha256': current.get(k)}
               for k in sorted(set(expected) | set(current)) if expected.get(k) != current.get(k)]
    target_names = {'backend/app/' + name for name in TARGET_FILES}
    target_rows = [{'path': name, 'restart_sha256': expected.get(name), 'current_sha256': current.get(name),
                    'matches': expected.get(name) is not None and expected.get(name) == current.get(name)} for name in sorted(target_names)]
    final_dir = ROOT / 'evidence/ai-video-repair-20261021/live-project-final'
    directory_state = {'exists': final_dir.exists(), 'entry_count': len(list(final_dir.iterdir())) if final_dir.is_dir() else None,
                       'modified_ns': final_dir.stat().st_mtime_ns if final_dir.exists() else None}
    report = {'captured_at': datetime.now(timezone.utc).isoformat(), 'operation': 'read_only_delivery_audit',
              'restart_receipt': str(RECEIPT), 'production_writes': 0, 'configuration_changes': 0,
              'restarts': 0, 'search_queries': 0, 'new_jobs': 0, 'idle_required': False,
              'hashes': {'targeted_video_files': target_rows, 'targeted_video_files_match': all(x['matches'] for x in target_rows),
                  'all_changes': changes, 'other_file_changes': [x for x in changes if x['path'] not in target_names],
                  'web_build_match': not any(x['path'].startswith('frontend/dist/') for x in changes),
                  'mobile_preview_build_match': not any(x['path'].startswith('frontend/dist-mobile-preview/') for x in changes)},
              'services': [], 'database_history': [], 'live_project_final_directory_before': directory_state}
    secrets = set()
    for started in prior['started']:
        port = started['port']
        listeners = helper.listeners(port)
        matching = listeners == [tuple(x) for x in started['listeners']]
        if not matching:
            raise RuntimeError('Unexpected listener identity during read-only audit: ' + str(port))
        proc = psutil.Process(listeners[0][1])
        env = proc.environ()
        for key in ('TAVILY_API_KEY', 'SERPER_API_KEY', 'LLM_API_KEY'):
            value = env.get(key, '')
            if value:
                secrets.add(value)
        before = next(x for x in prior['before'] if x['port'] == port)
        safe = {key: env.get(key) for key in helper.SAFE_KEYS}
        report['services'].append({'port': port, 'listeners': listeners, 'matches_restart5_listener': matching,
            'created_at_utc': datetime.fromtimestamp(proc.create_time(), timezone.utc).isoformat(),
            'safe_flags_match_restart5': safe == before['settings'], 'safe_flags': safe,
            'health': helper.request(port, '/health'), 'ready': helper.request(port, '/health/ready'),
            'capabilities': helper.request(port, '/api/capabilities')})
        report['database_history'].append(history_presence(Path(before['database']['path']), Path(before['backup']['path'])))
    # Also check the currently configured .env values without printing them or
    # recording hashes from which low-entropy secrets could be guessed.
    from backend.app.config import Settings
    settings = Settings.from_env()
    for key in ('tavily_api_key', 'serper_api_key', 'llm_api_key'):
        value = getattr(settings, key, '')
        if value:
            secrets.add(value)
    scope = [ROOT / 'evidence/ai-video-repair-20261021', ROOT / 'evidence/ai-video-fallback-repair-20261021',
             ROOT / 'docs/ai-video-fallback-20261021.md']
    scan = {'configured_unique_secret_count': len(secrets), 'files_scanned': 0, 'bytes_scanned': 0,
            'matching_file_count': 0, 'exact_match_occurrences': 0, 'unreadable_file_count': 0,
            'scope': [str(x.relative_to(ROOT)) for x in scope], 'secret_values_or_hashes_recorded': False}
    needles = {value.encode('utf-8') for value in secrets}
    for area in scope:
        files = area.rglob('*') if area.is_dir() else [area]
        for path in files:
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
            scan['exact_match_occurrences'] += matches
            scan['matching_file_count'] += bool(matches)
    report['configured_secret_scan'] = scan
    after_dir = {'exists': final_dir.exists(), 'entry_count': len(list(final_dir.iterdir())) if final_dir.is_dir() else None,
                 'modified_ns': final_dir.stat().st_mtime_ns if final_dir.exists() else None}
    report['live_project_final_directory_after'] = after_dir
    report['live_project_final_directory_untouched'] = after_dir == directory_state
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(OUT), 'targeted_video_files_match': report['hashes']['targeted_video_files_match'],
        'web_build_match': report['hashes']['web_build_match'], 'mobile_preview_build_match': report['hashes']['mobile_preview_build_match'],
        'other_file_changes': report['hashes']['other_file_changes'],
        'old_history_rows_present': all(x['all_old_rows_present'] for x in report['database_history']),
        'services': [{'port': x['port'], 'ready': x['ready']['status'], 'flags_match': x['safe_flags_match_restart5'],
                      'active_jobs': x['health'].get('active_jobs'), 'project_search_pending': x['health'].get('project_search_pending')}
                     for x in report['services']], 'secret_scan': scan,
        'live_project_final_directory_untouched': report['live_project_final_directory_untouched']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
