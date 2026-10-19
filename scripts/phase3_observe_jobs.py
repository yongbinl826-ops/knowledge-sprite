"""GET-only, versioned capture of local acceptance jobs. Never starts work."""
from pathlib import Path
import argparse, json, sys
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.phase3_live_acceptance import bind, dump

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8010')
    parser.add_argument('--case', required=True)
    args = parser.parse_args()
    base = ROOT / 'evidence/phase3-live'
    run = json.loads((base / 'run.json').read_text(encoding='utf-8'))
    record = next(row for row in run['records'] if row['case_id'] == args.case)
    runtime = bind(args.base_url)
    version = record['expected_version']
    output = base / record['case_id'] / f'v{version}-jobs'
    observations = []
    with httpx.Client(base_url=args.base_url, trust_env=False, timeout=20) as client:
        response = client.get(f"/api/projects/{record['project_id']}", params={'version': version})
        response.raise_for_status()
        view = response.json()
        assert view['version']['version'] == version
        for batch in view['version']['batches']:
            job = batch.get('job_id')
            if not job:
                continue
            for suffix in ('', '/results'):
                response = client.get(f'/api/search-jobs/{job}{suffix}')
                response.raise_for_status()
                name = f"b{batch['ordinal']}-{'results' if suffix else 'job'}.json"
                dump(output / name, response.json())
                observations.append({'path': name, 'job_id': job, 'http_status': response.status_code})
    dump(output / 'manifest.json', {'runtime': runtime, 'version': version, 'project_id': record['project_id'],
          'api_methods': ['GET'], 'new_external_calls': 0, 'new_model_calls': 0, 'observations': observations})
    print(json.dumps({'case': args.case, 'version': version, 'output': str(output), 'get_count': len(observations)+1}))

if __name__ == '__main__':
    main()
