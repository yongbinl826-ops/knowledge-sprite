"""Seal platform catalog evidence without changing any historical acceptance files."""
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/platform-catalog-20261017'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
baseline = json.loads((OUT/'baseline-v7/manifest.json').read_text(encoding='utf-8'))
comparison = json.loads((OUT/'extraction-comparison.json').read_text(encoding='utf-8'))
ui = json.loads((OUT/'browser/review-checks.json').read_text(encoding='utf-8'))
historical_drift = [name for name, digest in baseline['historical_artifact_hashes'].items()
                    if not (ROOT/name).is_file() or sha(ROOT/name) != digest]
source_changes = [name for name, digest in baseline['source_hashes'].items()
                  if not (ROOT/name).is_file() or sha(ROOT/name) != digest]
checks = {
    'historical_v7_artifacts_unchanged': not historical_drift,
    'historical_v7_validation_unchanged': sha(ROOT/'reports/evidence-followup-20261014/final-validation.json') == baseline['v7_validation_sha256'],
    'v7_source_archive_unchanged': sha(OUT/'baseline-v7/source.zip') == baseline['archive_sha256'],
    'same_captures_old_zero_new_15_84': [(r['before_catalog_count'], r['after_catalog_count']) for r in comparison['records']] == [(0, 15), (0, 84)],
    'independent_title_order_duration_check': all(r['matches_independent_audit'] for r in comparison['records']),
    'ui_catalog_counts': [r['catalog_items'] for r in ui['records']] == [15, 84],
    'ui_source_links': [r['source_links'] for r in ui['records']] == [15, 84],
    'no_invented_direct_links': all(r['direct_links'] == 0 for r in ui['records']),
    'no_horizontal_overflow': all(not r['overflow'] for r in ui['records']),
    'ui_mooc_access_notice': ui['records'][1]['access_notice'] == '来源访问提示：老师已关闭该学期，无法查看',
    'production_build_matches_checked_build': all((ROOT/'frontend/dist'/p.relative_to(OUT/'frontend-dist')).is_file()
        and sha(ROOT/'frontend/dist'/p.relative_to(OUT/'frontend-dist')) == sha(p)
        for p in (OUT/'frontend-dist').rglob('*') if p.is_file()),
}
test_ids = set()
test_reports = []
for name in ['all-tests.xml', 'integration-tests-final.xml']:
    tree = ET.parse(OUT/name)
    cases = tree.findall('.//testcase')
    ids = {(c.get('classname'), c.get('name')) for c in cases}
    passed = not tree.findall('.//failure') and not tree.findall('.//error') and not tree.findall('.//skipped')
    checks[name + '_passed'] = passed
    test_ids.update(ids)
    test_reports.append({'path': name, 'unique_cases': len(ids), 'passed': passed})
checks['691_distinct_test_cases'] = len(test_ids) == 691
source_files = [p for folder in ['backend/app', 'frontend/src', 'tests', 'backend/tests']
                for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
source_files += [ROOT/name for name in ['README.md', 'scripts/audit_platform_catalogs.py',
    'scripts/freeze_platform_catalog_baseline.py', 'scripts/validate_platform_catalog_audit.py']]
sources = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(source_files)}
artifacts = {p.relative_to(OUT).as_posix(): sha(p) for p in sorted(OUT.rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and 'code' not in p.relative_to(OUT).parts
             and not p.name.endswith(('.log', '.pid')) and p.name != 'final-validation.json'}
result = {'at': datetime.now(timezone.utc).isoformat(), 'passed': all(checks.values()), 'checks': checks,
    'scope': 'Live ordinary-browser inspection of two real platform pages; actual-DOM extraction and UI verification. Automated platform fetching and complete playback NOT verified.',
    'historical_artifact_count': len(baseline['historical_artifact_hashes']), 'historical_artifact_drift': historical_drift,
    'changed_or_replaced_v7_source_paths': source_changes, 'source_hashes': sources,
    'test_reports': test_reports, 'distinct_tests': len(test_ids), 'artifact_hashes': artifacts}
(OUT/'final-validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': result['passed'], 'failed': [k for k, v in checks.items() if not v],
                  'historical_artifacts_preserved': len(baseline['historical_artifact_hashes']),
                  'changed_source_paths': source_changes, 'distinct_tests': len(test_ids),
                  'sha256': sha(OUT/'final-validation.json')}, ensure_ascii=False))
assert result['passed']
