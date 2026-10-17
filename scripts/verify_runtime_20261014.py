"""Explicit single-run live API acceptance; never imported to start network.

Scope and output names are frozen before execution. No seed URLs enter discovery,
and the optional UI preview serves the same saved production API/database.
"""
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.fetcher import Fetcher, FetcherConfig, FetchStopped, NETWORK_OBSERVER, PinnedHTTPClient, CloudflareDoHResolver, utcnow
from backend.app.main import create_app
from backend.app.providers import SearXNGProvider, SearchError
from backend.app.ranking import has_course_page, has_video_evidence


def sha(body): return hashlib.sha256(body).hexdigest()


def hashes(scope_path):
    paths = [*sorted((ROOT / 'backend/app').rglob('*.py')), ROOT / 'backend/renderer_worker/worker.mjs', Path(__file__), scope_path]
    return {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in paths}


def settings_for(scope):
    return Settings(database_path=str(ROOT / scope['database']), search_provider=scope['provider'],
        searxng_url=scope.get('searxng_url', ''), searxng_engines=('bing',), searxng_video_engines=('bing',),
        open_course_domains=tuple(scope.get('open_course_domains', [])), global_concurrency=1,
        max_search_requests=scope['search_http_max'], max_detail_pages=scope['detail_attempts_max'],
        search_results_per_query=10, search_max_retries=0, search_timeout_seconds=20,
        deadline_seconds=scope['deadline_seconds'], dns_resolver='cloudflare_doh',
        fetch_phased_timeouts=True, fetch_timeout_seconds=scope['header_seconds'],
        fetch_body_idle_timeout_seconds=scope['idle_seconds'], fetch_body_timeout_cap_seconds=scope['body_cap_seconds'],
        fetch_body_min_bytes_per_second=scope['min_bytes_per_second'],
        js_render_enabled=scope['render'], js_render_allowed_hosts=tuple(scope.get('render_hosts', [])),
        js_render_asset_hosts=tuple(scope.get('asset_hosts', [])), js_render_timeout_seconds=90,
        js_render_max_target_requests=scope['target_http_max'], js_render_max_doh_requests=scope['doh_http_max'],
        js_render_max_resources=6, js_render_max_total_bytes=2_000_000)


async def main(scope_path):
    scope = json.loads(scope_path.read_text(encoding='utf-8'))
    output, database, sources = [ROOT / scope[k] for k in ('output', 'database', 'sources')]
    if output.exists() or database.exists() or sources.exists():
        raise SystemExit('Refusing previous outputs: no automatic retry or overwrite')
    sources.mkdir()
    preserved_paths = [ROOT / p for p in scope['preserve']]
    preserved = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in preserved_paths}
    report = {'scope': scope, 'started_at': utcnow(), 'scope_sha256': sha(scope_path.read_bytes()),
        'source_hashes_before': hashes(scope_path), 'preserved_before': preserved,
        'targets': [], 'dns': [], 'search_http': [], 'static_extractions': {}, 'stop_reason': None,
        'api_transport': 'production FastAPI routes via ASGITransport; UI checked separately over loopback TCP',
        'search_upstream_http': 'SearXNG internal engine HTTP count unknown; one configured engine, no fallback/retry'}
    complete_bytes, active, maximum_active = 0, 0, 0
    def save(): output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def enter():
        nonlocal active, maximum_active
        if active: raise FetchStopped('verification_concurrency', 'Independent serial network guard')
        active += 1
        maximum_active = max(maximum_active, active)
    def leave():
        nonlocal active
        active -= 1
    def guard(url):
        parts = urlsplit(url)
        permitted = parts.scheme == 'https' and parts.port in (None, 443) and parts.hostname in scope['hosts']
        if parts.hostname == 'microsoft.github.io':
            permitted = permitted and (parts.path == '/robots.txt' or parts.path.startswith('/AI-For-Beginners/'))
        if not permitted:
            raise FetchStopped('verification_scope', 'Outside frozen public source scope; search evidence retained')
        if report['stop_reason']: raise FetchStopped('verification_stopped', 'Prior failure stopped network')
        if len(report['targets']) >= scope['target_http_max'] or complete_bytes >= scope['total_bytes_max']:
            raise FetchStopped('verification_budget', 'Independent HTTP/byte cap reached before DNS')
    class DNS(CloudflareDoHResolver):
        async def __call__(self, url, timeout=8):
            guard(url)
            enter()
            parent = NETWORK_OBSERVER.get() or {}
            async def before():
                guard(url)
                if len(report['dns']) >= scope['doh_http_max']: raise FetchStopped('verification_budget', 'DoH cap')
                if parent.get('before_dns_http'): await parent['before_dns_http']()
            def trace(row):
                report['dns'].append(row)
                if parent.get('dns_trace'): parent['dns_trace'](row)
                save()
            token = NETWORK_OBSERVER.set({**parent, 'before_dns_http': before, 'dns_trace': trace})
            try: return await super().__call__(url, timeout)
            except BaseException as exc:
                report['stop_reason'] = getattr(exc, 'status', type(exc).__name__)
                raise
            finally:
                NETWORK_OBSERVER.reset(token)
                leave()
                save()
    class HTTP:
        def __init__(self, transport): self.transport = transport
        async def request(self, url, addresses, max_bytes):
            nonlocal complete_bytes
            guard(url)
            enter()
            limit = min(max_bytes, scope['response_bytes_max'], scope['total_bytes_max'] - complete_bytes)
            if urlsplit(url).path.endswith('.xml'): limit = min(limit, 500000)
            row = {'url': url, 'started_at': utcnow(), 'max_bytes': limit, 'pinned_public_addresses': addresses}
            report['targets'].append(row)
            parent = NETWORK_OBSERVER.get() or {}
            def trace(value):
                row['transport'] = value
                if parent.get('transport_trace'): parent['transport_trace'](value)
            token = NETWORK_OBSERVER.set({**parent, 'transport_trace': trace})
            save()
            try:
                value = await self.transport.request(url, addresses, limit)
                complete_bytes += len(value.body)
                filename = 'source-' + str(len(report['targets'])) + '.txt'
                (sources / filename).write_bytes(value.body)
                row.update(status=value.status_code, bytes=len(value.body), sha256=sha(value.body),
                    headers={k:v for k,v in value.headers.items() if k in {'content-type','content-length','location','content-security-policy','retry-after'}}, file=filename)
                if value.status_code in {401,403,429} or value.status_code >= 500:
                    report['stop_reason'] = 'http_' + str(value.status_code)
                if value.status_code == 200 and 'text/html' in value.headers.get('content-type',''):
                    report['static_extractions'][value.url] = fetcher.extractor.extract(value.body.decode('utf-8'), value.url, utcnow())
                return value
            except BaseException as exc:
                row['error'] = type(exc).__name__
                report['stop_reason'] = getattr(exc, 'status', type(exc).__name__)
                raise
            finally:
                NETWORK_OBSERVER.reset(token)
                leave()
                row['finished_at'] = utcnow()
                save()
    class SearchTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            if len(report['search_http']) >= scope['search_http_max']:
                raise SearchError('verification_budget', 'Independent search HTTP cap')
            enter()
            row = {'url': str(request.url), 'started_at': utcnow()}
            report['search_http'].append(row)
            save()
            try:
                result = await super().handle_async_request(request)
                body = bytearray()
                async for chunk in result.aiter_raw():
                    if len(body) + len(chunk) > 2_000_000: raise SearchError('invalid_response','Search response over cap')
                    body.extend(chunk)
                await result.aclose()
                filename = 'search-' + str(len(report['search_http'])) + '.json'
                (sources / filename).write_bytes(body)
                row.update(status=result.status_code, bytes=len(body), sha256=sha(body), file=filename)
                return httpx.Response(result.status_code, headers=result.headers, content=bytes(body), request=request)
            finally:
                row['finished_at'] = utcnow()
                leave()
                save()
    settings = settings_for(scope)
    config = FetcherConfig(global_concurrency=1, max_retries=0, timeout_seconds=scope['header_seconds'],
        phased_timeouts=True, body_idle_timeout_seconds=scope['idle_seconds'],
        body_timeout_cap_seconds=scope['body_cap_seconds'], body_min_bytes_per_second=scope['min_bytes_per_second'],
        max_bytes=scope['response_bytes_max'], dns_resolver='cloudflare_doh')
    fetcher = Fetcher(config, resolver=DNS(), http_client=HTTP(PinnedHTTPClient(config)))
    search_client = httpx.AsyncClient(transport=SearchTransport(), timeout=20, follow_redirects=False, trust_env=False)
    provider = SearXNGProvider(settings, search_client) if scope['provider'] == 'searxng' else None
    app = create_app(settings, provider=provider, fetcher=fetcher)
    report['effective_settings'] = asdict(settings)
    start = time.monotonic()
    save()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as api:
            report['capabilities'] = (await api.get('/api/capabilities')).json()
            created = await api.post('/api/search-jobs', json=scope['request'], headers={'Idempotency-Key':scope['id']})
            report['create_status'] = created.status_code
            report['create_response'] = created.json()
            jid = report['job_id'] = report['create_response']['job_id']
            save()
            try: await asyncio.wait_for(app.state.service.queue.join(), scope['deadline_seconds'] + 10)
            except TimeoutError:
                report['stop_reason'] = report['stop_reason'] or 'outer_watchdog'
                await app.state.service.cancel(jid)
            report['final_job'] = (await api.get('/api/search-jobs/' + jid)).json()
            report['results'] = (await api.get('/api/search-jobs/' + jid + '/results')).json()
            store = app.state.store
            report['stored_resources'] = list(store.resources(jid).values())
            report['stored_evidence'] = {rid:store.evidence(jid,rid) for rid in store.resources(jid)}
            report['acceptance'] = [{'url':r['url'], 'fetch_status':r['fetch_status'],
                'real_course':has_course_page(r,store.evidence(jid,r['resource_id'])),
                'video_structure':has_video_evidence(r,store.evidence(jid,r['resource_id'])),
                'static_chapters':len(report['static_extractions'].get(r['url'],{}).get('chapters',[])),
                'final_chapters':len(r.get('chapters',[])), 'render_status':(r.get('render_diagnostics') or {}).get('status')}
                for r in report['stored_resources']]
            if fetcher.renderer and fetcher.renderer.last_result and fetcher.renderer.last_result.html:
                (sources / 'rendered-dom.html').write_text(fetcher.renderer.last_result.html,encoding='utf-8')
    await search_client.aclose()
    report.update(finished_at=utcnow(), elapsed_seconds=round(time.monotonic()-start,3),
        target_http_count=len(report['targets']), doh_http_count=len(report['dns']), search_http_count=len(report['search_http']),
        complete_response_bytes=complete_bytes, maximum_network_concurrency=maximum_active,
        source_hashes_after=hashes(scope_path), playback_verified=False)
    report['source_unchanged'] = report['source_hashes_before'] == report['source_hashes_after']
    report['preserved_reports_unchanged'] = all(sha((ROOT/p).read_bytes()) == v for p,v in preserved.items())
    save()
    print(json.dumps({k:report[k] for k in ('job_id','acceptance','stop_reason','target_http_count','doh_http_count','search_http_count','elapsed_seconds')},ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1]).resolve()))
