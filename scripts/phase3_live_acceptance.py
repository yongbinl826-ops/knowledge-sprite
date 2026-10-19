"""Checkpointed loopback acceptance: no retries of uncertain mutations.

The default plan is offline. Analyze/search are explicit, one-case operations.
No credentials, prompts, model response bodies or external calls are made by
this client; the separately bound local production service owns its budgets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.project_models import ProjectInput, AnalysisDocument
from backend.app.project_analysis import ANALYSIS_PROMPT_VERSION
from scripts.phase2_acceptance import local_url


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(base_url):
    manifest_path = ROOT / 'tmp/preview-runtime-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('root') != str(ROOT) or base_url != f"http://127.0.0.1:{manifest['port']}":
        raise RuntimeError('Local runtime identity does not match this isolated source tree')
    for relative, expected in manifest['files'].items():
        path = ROOT / relative
        if not path.resolve().is_relative_to(ROOT) or sha(path) != expected:
            raise RuntimeError(f'Runtime source changed: {relative}; no mutation submitted')
    return {'manifest_sha256': sha(manifest_path), 'pid': manifest['pid'], 'port': manifest['port'],
            'started_at': manifest['started_at'], 'backend_files': sum(p.replace('\\', '/').startswith('backend/app/') for p in manifest['files'])}


def plan(source):
    original = json.loads(source.read_text(encoding='utf-8'))
    cases = []
    for case in original['original_projects_and_inputs']:
        cases.append({'case_id': case['case_id'], 'cohort': 'same_synthetic_input',
            'project_id': case['project_id'], 'input': ProjectInput.model_validate(case['input_verbatim']).model_dump(), 'status': 'planned'})
    for case in original['three_unseen_project_plans']:
        value = ProjectInput(name=case['name'], requirements=case['synthetic_input'],
            student_level=case['student_level'], project_context=case['background']).model_dump()
        cases.append({'case_id': case['case_id'], 'cohort': 'unseen_synthetic_input', 'input': value, 'status': 'planned'})
    return {'created_at': now(), 'audit_source': str(source), 'audit_source_sha256': sha(source),
        'prompt_version': ANALYSIS_PROMPT_VERSION, 'max_selected_cases': 8,
        'limits': {'analysis_submissions_per_case': 1, 'max_analysis_model_calls_per_case': 4,
            'max_search_submissions_per_case': 1, 'max_search_jobs_per_case': 5,
            'search_requests_per_job': 30, 'detail_pages_per_job': 40, 'teaching_match_calls_per_job': 2,
            'teaching_pairs_per_job': 20, 'search_job_deadline_seconds': 240},
        'no_mutation_retry': True, 'records': cases}


def read_view(client, record, output):
    response = client.get(f"/api/projects/{record['project_id']}", params={'version': record.get('expected_version')})
    response.raise_for_status()
    value = response.json()
    dump(output / record['case_id'] / 'project-view.json', value)
    return value


def poll(client, record, output, checkpoint, analysis=False):
    deadline = time.monotonic() + (150 if analysis else 1250)
    while time.monotonic() < deadline:
        value = read_view(client, record, output)
        version = value.get('version') or {}
        record['observed_status'] = version.get('status')
        record['observed_at'] = now()
        checkpoint()
        terminal = {'analyzed', 'analysis_failed', 'analysis_rejected'} if analysis else {'completed', 'partial', 'failed', 'cancelled', 'interrupted'}
        if version.get('version') == record.get('expected_version') and version.get('status') in terminal:
            record['status'] = version['status']
            if not analysis:
                result = client.get(f"/api/projects/{record['project_id']}/results", params={'version': record['expected_version']})
                result.raise_for_status()
                dump(output / record['case_id'] / 'project-results.json', result.json())
            checkpoint()
            return value
        time.sleep(2)
    record['status'] = 'observation_deadline'
    checkpoint()
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'analyze', 'search', 'observe-analysis', 'observe-search', 'retry-known-analysis', 'regress-known-analysis', 'repeat-known-search', 'regress-known-search'])
    local_audit = ROOT / 'evidence/phase3-audit/learning-goal-audit.json'
    parser.add_argument('--audit-source', type=Path, default=local_audit if local_audit.exists() else ROOT.parents[1] / 'evidence/phase3-audit/learning-goal-audit.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence/phase3-live')
    parser.add_argument('--base-url', default='http://127.0.0.1:8010')
    parser.add_argument('--case')
    parser.add_argument('--fix-manifest', type=Path, help='Concrete hash-bound fix required for one additional known-failure regression')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'evidence'):
        parser.error('Evidence must stay within the isolated stage evidence directory')
    run_path = output / 'run.json'
    if args.action == 'plan':
        if run_path.exists():
            parser.error('Existing checkpoints must be preserved')
        run = plan(args.audit_source)
        dump(run_path, run)
        print(json.dumps({'action': 'offline_plan', 'cases': [r['case_id'] for r in run['records']], 'external_calls': 0}))
        return
    run = json.loads(run_path.read_text(encoding='utf-8'))
    record = next((r for r in run['records'] if r['case_id'] == args.case), None)
    if record is None:
        parser.error('Choose an existing exact case ID')
    base = local_url(args.base_url)
    run['runtime_binding'] = bind(base)
    def checkpoint():
        run['updated_at'] = now()
        dump(run_path, run)
    with httpx.Client(base_url=base, timeout=15, trust_env=False, follow_redirects=False) as client:
        capability = client.get('/api/capabilities')
        capability.raise_for_status()
        if capability.json()['project_analysis'].get('prompt_version') != ANALYSIS_PROMPT_VERSION:
            raise RuntimeError('Unexpected analysis contract; no mutation submitted')
        if args.action == 'regress-known-analysis':
            if not args.fix_manifest or record.get('post_fix_analysis_trial'):
                raise RuntimeError('One explicit post-fix trial requires a concrete fix manifest')
            fix = args.fix_manifest.resolve(strict=True)
            manifest = json.loads(fix.read_text(encoding='utf-8'))
            changes = manifest['files']
            if not any(row.get('destination_relative') == 'backend/app/project_analysis.py'
                       and row.get('after_sha256') != row.get('baseline_sha256') for row in changes):
                raise RuntimeError('No material analysis implementation fix in manifest')
            for row in changes:
                target = (ROOT / row['destination_relative']).resolve()
                if not target.is_relative_to(ROOT) or sha(target) != row['after_sha256']:
                    raise RuntimeError('Concrete fix is not installed in this runtime')
            value = read_view(client, record, output)
            if (value['version']['status'] != 'analysis_failed'
                    or value['current_version'] != record.get('expected_version')
                    or value['version']['version'] != record.get('expected_version')):
                raise RuntimeError('Observe/reconcile a known terminal failure before a regression')
            dump(output / record['case_id'] / f"pre-fix-failure-v{record['expected_version']}.json", value)
            trial = {'fix_manifest_sha256': sha(fix), 'intent_at': now(),
                     'previous_version': record['expected_version'],
                     'previous_prompt_version': value['version']['prompt_version'],
                     'new_prompt_version': ANALYSIS_PROMPT_VERSION,
                     'reason': 'Explicit regression after reproduced generic validator defect and concrete prompt/diagnostic fixes; not an automatic retry or proof of prior draft cause'}
            record['post_fix_analysis_trial'] = trial
            record.setdefault('prior_analysis_trials', []).append({key: record.get(key) for key in
                ('expected_version', 'analysis_intent_at', 'analysis_http_status', 'status', 'observed_status')})
            record.pop('analysis_intent_at', None)
            checkpoint()
            args.action = 'analyze'
        if args.action == 'retry-known-analysis':
            # One explicit regression trial after a known terminal failure;
            # never reconcile an uncertain write by submitting it again.
            value = read_view(client, record, output)
            if (record.get('prior_analysis_trials') or record.get('retry_analysis_intent_at')
                    or value['version']['status'] != 'analysis_failed'
                    or value['current_version'] != record.get('expected_version')
                    or value['version']['version'] != record.get('expected_version')):
                raise RuntimeError('Only one explicit retry of a known failed analysis is allowed')
            dump(output / record['case_id'] / f"first-analysis-v{record['expected_version']}.json", value)
            record['prior_analysis_trials'] = [{key: record.get(key) for key in
                ('expected_version', 'analysis_intent_at', 'analysis_http_status', 'status', 'observed_status')}]
            record['retry_analysis_intent_at'] = now()
            record.pop('analysis_intent_at', None)
            checkpoint()
            args.action = 'analyze'
        if args.action in {'repeat-known-search', 'regress-known-search'}:
            post_fix = args.action == 'regress-known-search'
            if post_fix:
                if not args.fix_manifest or record.get('post_fix_search_trial'):
                    raise RuntimeError('Only one explicit source-fix regression per case is allowed')
                fix = args.fix_manifest.resolve(strict=True)
                changes = json.loads(fix.read_text(encoding='utf-8'))['files']
                if not any(row.get('destination_relative') == 'backend/app/teaching_match.py'
                           and row.get('after_sha256') != row.get('baseline_sha256') for row in changes):
                    raise RuntimeError('No concrete teaching source fix in manifest')
                for row in changes:
                    target = (ROOT / row['destination_relative']).resolve()
                    if not target.is_relative_to(ROOT) or sha(target) != row['after_sha256']:
                        raise RuntimeError('Source fix is not installed')
            value = read_view(client, record, output)
            if ((not post_fix and (record.get('prior_search_trials') or record.get('repeat_search_intent_at')))
                    or value['version']['status'] not in {'completed', 'partial', 'failed', 'interrupted'}
                    or value['current_version'] != record.get('expected_version')
                    or value['version']['version'] != record.get('expected_version')
                    or not value['version'].get('search_started_at')):
                raise RuntimeError('Only one explicit new-version search of a known terminal trial is allowed')
            result = client.get(f"/api/projects/{record['project_id']}/results", params={'version': record['expected_version']})
            result.raise_for_status()
            dump(output / record['case_id'] / f"previous-search-v{record['expected_version']}.json", result.json())
            record.setdefault('prior_search_trials', []).append({key: record.get(key) for key in
                ('expected_version', 'confirm_intent_at', 'confirm_http_status', 'search_intent_at', 'search_http_status', 'status')})
            if post_fix:
                record['post_fix_search_trial'] = {'fix_manifest_sha256':sha(fix),'intent_at':now(),
                    'previous_version':record['expected_version'],
                    'reason':'Explicit regression after source-bound same-video chapter and bounded observation-selection fix; identical reviewed analysis'}
            record['repeat_search_intent_at'] = now()
            checkpoint()
            response = client.post(f"/api/projects/{record['project_id']}/edit", json={
                'expected_version': record['expected_version'], 'analysis': value['version']['analysis']})
            record['repeat_search_edit_http_status'] = response.status_code
            checkpoint()
            response.raise_for_status()
            record['expected_version'] = response.json()['current_version']
            record['status'] = 'analyzed'
            record['repeat_search_reason'] = 'Explicit post-fix regression using identical reviewed analysis; no analysis model call'
            for key in ('search_intent_at', 'confirm_intent_at'):
                record.pop(key, None)
            checkpoint()
            args.action = 'search'
        if args.action.startswith('observe-'):
            if not record.get('project_id') or not record.get('expected_version'):
                raise RuntimeError('No known submission to observe')
            poll(client, record, output, checkpoint, analysis=args.action == 'observe-analysis')
        elif args.action == 'analyze':
            if record.get('analysis_intent_at'):
                raise RuntimeError('Analysis was already attempted; observe it instead')
            if not record.get('project_id'):
                if record.get('create_intent_at'):
                    raise RuntimeError('Uncertain project creation must be reconciled manually; no retry')
                record['create_intent_at'] = now()
                checkpoint()
                response = client.post('/api/projects', json=record['input'])
                record['create_http_status'] = response.status_code
                checkpoint()
                response.raise_for_status()
                record['project_id'] = response.json()['project_id']
                checkpoint()
            prior = client.get(f"/api/projects/{record['project_id']}")
            prior.raise_for_status()
            prior = prior.json()
            dump(output / record['case_id'] / 'before-analysis.json', prior)
            record['source_version'] = prior['current_version']
            record['expected_version'] = prior['current_version'] + 1
            record['analysis_intent_at'] = now()
            checkpoint()
            response = client.post(f"/api/projects/{record['project_id']}/analyze", json={
                'expected_version': prior['current_version'], 'input': record['input']})
            record['analysis_http_status'] = response.status_code
            checkpoint()
            response.raise_for_status()
            poll(client, record, output, checkpoint, analysis=True)
        elif args.action == 'search':
            if record.get('search_intent_at') or record.get('confirm_intent_at'):
                raise RuntimeError('Confirmation/search already attempted; inspect or observe, never blindly retry')
            value = read_view(client, record, output)
            version = value['version']
            if version['version'] != record.get('expected_version') or version['status'] != 'analyzed':
                raise RuntimeError('Expected successfully analyzed version is unavailable')
            document = AnalysisDocument.model_validate(version['analysis'])
            if not all(point.learning_skills for point in document.knowledge_points):
                raise RuntimeError('Fresh analysis missing explicit teaching goals; do not search a fabricated migration')
            record['confirm_intent_at'] = now()
            checkpoint()
            response = client.post(f"/api/projects/{record['project_id']}/confirm", json={
                'version': record['expected_version'], 'acknowledged_skipped_prerequisites': []})
            record['confirm_http_status'] = response.status_code
            checkpoint()
            response.raise_for_status()
            record['search_intent_at'] = now()
            checkpoint()
            response = client.post(f"/api/projects/{record['project_id']}/search", json={'version': record['expected_version']})
            record['search_http_status'] = response.status_code
            checkpoint()
            response.raise_for_status()
            poll(client, record, output, checkpoint)
    print(json.dumps({'case_id': record['case_id'], 'status': record.get('status'), 'project_id': record.get('project_id'),
                      'version': record.get('expected_version'), 'output': str(output / record['case_id'])}))


if __name__ == '__main__':
    main()
