"""Run normal confirmation/search APIs once for an imported real analysis draft.

No provider mocks, course seeds or saved-response playback. Original analysis is
retained only as the fixed input for comparison; all course results are new.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', default='http://127.0.0.1:18120')
    args = parser.parse_args()
    base = args.base.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path or parsed.query:
        raise ValueError('Use the explicit localhost acceptance server only')
    args.output.mkdir(parents=True, exist_ok=True)

    def api(path, data=None):
        request = Request(base + path, data=None if data is None else json.dumps(data).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def save(name, data):
        with (args.output / name).open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')

    path = '/api/projects/' + args.project_id
    project = api(path)
    version = project['version']['version']
    if project['version']['status'] != 'analyzed' or project['version']['confirmation'] or project['version']['batches']:
        raise ValueError('Expected a new unconfirmed draft with no search batches')
    save('before-confirmation.json', project)
    save('capabilities.json', api('/api/capabilities'))
    confirmed = api(path + '/confirm', {'version': version, 'acknowledged_skipped_prerequisites': []})
    save('confirmed.json', confirmed)
    started = api(path + '/search', {'version': version})
    save('submitted.json', started)
    last = None
    deadline = time.monotonic() + 1200
    while True:
        project = api(path + f'?version={version}')
        data = project['version']
        status = {'project_id': args.project_id, 'status': data['status'],
                  'batches': [{'id': b['batch_id'], 'status': b['status'], 'job_id': b['job_id'],
                               'progress': b.get('progress', {})} for b in data['batches']]}
        if status != last:
            print(json.dumps(status), flush=True)
            last = status
        if data['status'] not in {'running', 'confirmed'}:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Acceptance observer deadline exceeded; service tasks are not silently retried')
        time.sleep(3)
    save('project-final.json', project)
    save('project-results.json', api(path + f'/results?version={version}'))
    for batch in data['batches']:
        if batch.get('job_id'):
            job_id = batch['job_id']
            save(job_id + '-job.json', api('/api/search-jobs/' + job_id))
            save(job_id + '-results.json', api('/api/search-jobs/' + job_id + '/results'))
    save('audit-status.json', api('/api/live-audit'))
    print(json.dumps({'finished': True, 'project_id': args.project_id, 'version': version, 'status': data['status']}), flush=True)


if __name__ == '__main__':
    main()
