"""Single bounded entry inspection; not the production JS acceptance run."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.fetcher import Fetcher, FetcherConfig, FetchStopped, NETWORK_OBSERVER
from bs4 import BeautifulSoup

OUT = ROOT / 'reports/runtime-revision-20261013'
ENTRY = 'https://microsoft.github.io/AI-For-Beginners/'

async def main():
    path = OUT / 'dynamic-entry-probe.json'
    if path.exists():
        raise SystemExit('Refusing to overwrite entry probe')
    scope = {'entry': ENTRY, 'target_http_max': 4, 'doh_http_max': 8,
             'per_response_max_bytes': 200000, 'deadline_seconds': 40,
             'concurrency': 1, 'retries': 0, 'scripts_executed': False,
             'basis': 'Official Microsoft curriculum repository links this public course; MIT license confirmed in repository LICENSE'}
    (OUT / 'dynamic-entry-scope.json').write_text(json.dumps(scope, indent=2), encoding='utf-8')
    report = {'scope': scope, 'started_at': datetime.now(timezone.utc).isoformat(), 'target_count': 0, 'dns': [], 'responses': []}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    async def target():
        if report['target_count'] >= 4:
            raise FetchStopped('probe_budget', 'Target limit reached')
        report['target_count'] += 1
    async def resolve(url):
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname != 'microsoft.github.io' or p.port not in (None, 443):
            raise FetchStopped('probe_scope', 'Only declared entry origin allowed')
    async def dns():
        if len(report['dns']) >= 8:
            raise FetchStopped('probe_budget', 'DNS limit reached')
    def response(result, kind):
        name = f'dynamic-entry-source-{len(report["responses"])+1}.txt'
        (OUT / name).write_bytes(result.body)
        report['responses'].append({'url': result.url, 'kind': kind, 'status': result.status_code,
          'bytes': len(result.body), 'sha256': hashlib.sha256(result.body).hexdigest(), 'file': name})
        save()
    fetcher = Fetcher(FetcherConfig(global_concurrency=1, max_retries=0, max_bytes=200000,
                      timeout_seconds=10, dns_resolver='cloudflare_doh'))
    token = NETWORK_OBSERVER.set({'before_resolve': resolve, 'before_target_http': target,
        'before_dns_http': dns, 'dns_trace': report['dns'].append, 'response': response, 'max_retries': 0})
    save()
    try:
        result = await asyncio.wait_for(fetcher.fetch(ENTRY), 40)
        report['status'] = result.status_code
        if result.status_code == 200:
            soup = BeautifulSoup(result.body, 'html.parser')
            report['scripts'] = [{'src': x.get('src'), 'type': x.get('type'),
                'inline': x.get_text() if not x.get('src') else None} for x in soup.find_all('script')]
            report['stylesheets'] = [x.get('href') for x in soup.select('link[rel="stylesheet"]')]
            report['static_extraction'] = fetcher.extractor.extract(result.body.decode('utf-8'), result.url, datetime.now(timezone.utc).isoformat())
    except BaseException as exc:
        report['error'] = {'type': type(exc).__name__, 'status': getattr(exc, 'status', None)}
    finally:
        NETWORK_OBSERVER.reset(token)
        report['trace'] = list(fetcher.request_trace)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({k:report.get(k) for k in ['status','error','target_count','scripts','stylesheets','static_extraction']}, ensure_ascii=False))

if __name__ == '__main__':
    asyncio.run(main())
