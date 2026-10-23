"""Apply the same read-only final audit to the restart10 runtime confirmation."""
import audit_ai_video_runtime_restart9 as audit
import sqlite3


def history_presence_all(current_path, backup_path):
    """Inventory every user table, including the separate mobile catalog DB."""
    result = {'current_path': str(current_path), 'backup_path': str(backup_path), 'tables': []}
    with sqlite3.connect(current_path.as_uri() + '?mode=ro', uri=True) as current:
        with sqlite3.connect(backup_path.as_uri() + '?mode=ro', uri=True) as previous:
            current.execute('begin')
            names = [x[0] for x in previous.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
            for name in names:
                table = '"' + name.replace('"', '""') + '"'
                columns = list(previous.execute('pragma table_info(' + table + ')'))
                pk = [x[1] for x in sorted(columns, key=lambda row: row[5]) if x[5]]
                selected = ','.join('"' + x.replace('"', '""') + '"' for x in pk) if pk else '*'
                old = set(previous.execute('select ' + selected + ' from ' + table))
                now = set(current.execute('select ' + selected + ' from ' + table))
                result['tables'].append({'table': name, 'comparison': 'primary_keys' if pk else 'whole_rows_no_primary_key',
                    'old_key_count': len(old), 'current_key_count': len(now), 'missing_old_keys': len(old - now),
                    'all_old_rows_present': old <= now})
    result['all_old_rows_present'] = all(x['all_old_rows_present'] for x in result['tables'])
    result['content_immutability_checked'] = False
    return result

audit.OUT = audit.ROOT / 'evidence/ai-video-repair-20261021/runtime-final-restart10.json'
audit.REUSE = audit.ROOT / 'evidence/ai-video-fallback-repair-20261021/runtime/restart-10-runtime-reuse.json'
audit.history_presence = history_presence_all

if __name__ == '__main__':
    audit.main()
