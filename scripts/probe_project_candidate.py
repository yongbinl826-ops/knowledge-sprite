"""Fetch one explicitly selected real search candidate; never insert it into jobs."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.db import Store
from backend.app.fetcher import NETWORK_OBSERVER, FETCH_DEADLINE_AT
from backend.app.service import JobService


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--point-id', required=True)
    parser.add_argument('--resource-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding='utf8'))
    point = next(p for p in source['points'] if p['project_knowledge_point_id'] == args.point_id)
    group = point['result']
    items = [item for name in ('items', 'partial_items', 'review_items') for item in group.get(name, [])]
    item = next(item for item in items if item['resource']['resource_id'] == args.resource_id)
    resource = item['resource']
    observations = [e for e in item['evidence'] if e.get('kind') == 'search']
    if not observations:
        raise ValueError('A real saved search observation is required')
    args.output.mkdir(parents=True, exist_ok=False)
    settings = Settings.from_env()
    service = JobService(settings, Store(':memory:'))
    request_limit = min(4, settings.max_detail_pages)
    seconds = min(60, settings.deadline_seconds)
    plan = {'started_at': datetime.now(timezone.utc).isoformat(),
            'source_file': str(args.source), 'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
            'source_project_id': source['project_id'], 'source_job_id': point['job_id'],
            'point_id': args.point_id, 'resource_id': args.resource_id,
            'url': resource['canonical_url'], 'title': resource['title'],
            'source_evidence_ids': [e['evidence_id'] for e in observations],
            'max_target_requests': request_limit, 'max_seconds': seconds,
            'new_search_performed': False, 'injected_into_search_results': False,
            'settings_changed': False, 'note': 'Independent detail verification explicitly requested by the user.'}
    (args.output / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf8')
    requests, responses = 0, []

    async def before():
        nonlocal requests
        if requests >= request_limit:
            raise TimeoutError('diagnostic_request_budget')
        requests += 1

    def response(result, kind):
        responses.append({'url': result.url, 'kind': kind, 'http_status': result.status_code,
                          'body_bytes': len(result.body), 'body_sha256': hashlib.sha256(result.body).hexdigest()})

    observer = NETWORK_OBSERVER.set({'before_target_http': before, 'response': response, 'max_retries': 0})
    deadline = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + seconds)
    try:
        result = await service.fetcher.enrich({'url': resource['canonical_url'], 'title': resource['title'],
                                              'source': 'explicit_saved_candidate_detail_probe'})
    finally:
        NETWORK_OBSERVER.reset(observer)
        FETCH_DEADLINE_AT.reset(deadline)
        service.store.close()
    report = {'finished_at': datetime.now(timezone.utc).isoformat(), 'plan': plan, 'result': result,
              'physical_requests': requests, 'responses': responses,
              'trace': list(service.fetcher.request_trace), 'end_to_end_acceptance': False}
    (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'fetch_status': result.get('fetch_status'), 'error': result.get('fetch_error'),
                      'title': result.get('title'), 'chapters': len(result.get('chapters', [])),
                      'physical_requests': requests, 'response_count': len(responses)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
