"""One bounded real manual-search job for selected points of a prior request.

The prior request is input only. No courses, responses or caches are imported.
This diagnostic job never replaces or merges into the completed project result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-job', type=Path, action='append', required=True)
    parser.add_argument('--point-index', type=int, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.base)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Use the explicit localhost acceptance server only')
    sources = [json.loads(path.read_text(encoding='utf-8'))['request'] for path in args.source_job]
    request = dict(sources[0])
    context = {key: value for key, value in request.items() if key != 'knowledge_points'}
    if any({key: value for key, value in source.items() if key != 'knowledge_points'} != context for source in sources):
        raise ValueError('Source request contexts differ; choose compatible requests')
    points = [point for source in sources for point in source['knowledge_points']]
    if not 1 <= len(args.point_index) <= 5 or len(set(args.point_index)) != len(args.point_index):
        raise ValueError('Select one to five distinct input points')
    if any(index < 0 or index >= len(points) for index in args.point_index):
        raise ValueError('Point index outside source request')
    request['knowledge_points'] = [points[index] for index in args.point_index]
    database = (args.output / 'live/live.sqlite3').resolve()
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as conn:
        before = {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in ('projects', 'jobs', 'resources', 'evidence', 'search_attempts', 'cache')}
    if any(before.values()):
        raise ValueError('Diagnostic search requires an empty initialized database')

    def save(name, data):
        with (args.output / name).open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')

    def api(path, data=None, key=None):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        req = Request(args.base + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        with urlopen(req, timeout=30) as response:
            return json.load(response)

    key = 'query-guard-' + uuid4().hex
    save('submission-plan.json', {'source_jobs': [str(path) for path in args.source_job], 'request': request,
         'before_counts': before, 'idempotency_key': key, 'course_imported': False,
         'scope': 'Additional real query-guard validation, separate from project results'})
    job = api('/api/search-jobs', request, key)
    save('submitted.json', job)
    job_id = job['job_id']
    last = None
    deadline = time.monotonic() + 600
    while True:
        job = api('/api/search-jobs/' + job_id)
        state = {'job_id': job_id, 'status': job['status'], 'progress': job['progress']}
        if state != last:
            print(json.dumps(state), flush=True)
            last = state
        if job['status'] not in ('queued', 'running'):
            break
        if time.monotonic() > deadline:
            raise TimeoutError('Diagnostic observer deadline reached; no silent retry')
        time.sleep(3)
    save('job.json', job)
    save('results.json', api('/api/search-jobs/' + job_id + '/results'))
    save('audit-status.json', api('/api/live-audit'))
    print(json.dumps({'finished': True, 'job_id': job_id, 'status': job['status']}), flush=True)


if __name__ == '__main__':
    main()
