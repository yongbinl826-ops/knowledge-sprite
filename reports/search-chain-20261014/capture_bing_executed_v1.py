"""One installed-engine diagnostic; default prepare mode has no send permit.

Runs only as an isolated process inside the existing SearXNG container. Does not
alter service files, Flask workers, query terms, parser, or security settings.
Never serializes request/response headers, cookies, config, or exception text.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

QUERY = '(site:microsoft.github.io) Artificial Intelligence for Beginners course lesson'
LIVE = '--live' in sys.argv
OUT = Path('/tmp/knowledge-sprite-search-chain-live.json' if LIVE else '/tmp/knowledge-sprite-search-chain-prepare.json')
MAX_BYTES = 2_000_000
START = time.monotonic()
BODY = bytearray()
R = {'schema': 'search-chain/1', 'mode': 'live' if LIVE else 'prepare-no-network',
     'started_at': datetime.now(timezone.utc).isoformat(), 'query': QUERY,
     'method': 'isolated installed Bing engine + OnlineProcessor + original searx.network/curl_cffi',
     'budgets': {'client_calls': 1, 'concurrency': 1, 'extra_retries': 0,
                 'followed_redirects': 0, 'decoded_body_bytes': MAX_BYTES,
                 'client_timeout_seconds': 20, 'process_alarm_seconds': 40},
     'counts': {'engine_request': 0, 'network_client_attempts': 0, 'client_delegations': 0,
                'blocked_client_attempts': 0, 'curl_url_assignments': 0,
                'engine_response': 0, 'patch_response': 0},
     'physical_http_requests': 'unknown: no packet capture; internal curl transport retries are not directly observed',
     'hooks_restored': False, 'clients_closed': False, 'process_complete': False,
     'source_sha256_before': {}, 'source_sha256_after': {}}
PERMIT = False
ORIGINALS = []


class BudgetStop(RuntimeError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def safe_url(value):
    """Only the fixed search q/adlt/setlang and public YouTube v can be retained."""
    value = str(value)
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        return {'url': '[redacted nonpublic/credential URL]', 'sha256': hashlib.sha256(value.encode()).hexdigest()}
    qs = parse_qs(p.query, keep_blank_values=True)
    keep = {}
    if p.hostname == 'www.bing.com' and p.path == '/search':
        if qs.get('q') == [QUERY]:
            keep['q'] = QUERY
        if qs.get('adlt', [''])[0] in ('off', 'moderate', 'strict'):
            keep['adlt'] = qs['adlt'][0]
        if qs.get('setlang', [''])[0] in ('en', 'en-US', 'en-us'):
            keep['setlang'] = qs['setlang'][0]
    if p.hostname in ('www.youtube.com', 'youtube.com') and p.path == '/watch':
        v = qs.get('v', [''])[0]
        if len(v) == 11 and all(c.isalnum() or c in '_-' for c in v):
            keep['v'] = v
    safe = urlunsplit((p.scheme, p.hostname, p.path[:1500], urlencode(keep), ''))
    return {'url': safe, 'sha256': hashlib.sha256(value.encode()).hexdigest(),
            'query_or_fragment_redacted': bool(p.fragment or set(qs) - set(keep))}


def fixed_url(value):
    p = urlsplit(str(value))
    q = parse_qs(p.query)
    if p.scheme != 'https' or p.hostname != 'www.bing.com' or p.port not in (None, 443) or p.path != '/search' or p.username or p.password or q.get('q') != [QUERY]:
        raise BudgetStop('fixed_url_gate')


def hook(obj, name, fn):
    ORIGINALS.append((obj, name, getattr(obj, name)))
    setattr(obj, name, fn)


def save():
    R['finished_at'] = utc()
    R['elapsed_seconds'] = round(time.monotonic() - START, 3)
    OUT.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')


def on_alarm(*_):
    raise BudgetStop('process_deadline')


def body_chunk(chunk):
    if len(BODY) + len(chunk) > MAX_BYTES:
        R['body_limit_hit'] = True
        return 0
    BODY.extend(chunk)
    return len(chunk)


def summarize_html(resp):
    from lxml import html
    tree = html.fromstring(bytes(BODY))
    title = ' '.join(tree.xpath('//title/text()'))[:400]
    inputs = tree.xpath('//input[@name="q" or @id="sb_form_q"]/@value')
    rows = []
    for li in tree.xpath('//ol[@id="b_results"]/li[contains(@class,"b_algo")]')[:20]:
        anchors = li.xpath('.//h2/a')
        if anchors:
            a = anchors[0]
            rows.append({'title': ' '.join(a.itertext())[:400], **safe_url(a.get('href', ''))})
    # Only visible text is inspected for an explicit denial, never script tokens.
    visible = ' '.join(tree.xpath('//body//text()[not(ancestor::script or ancestor::style)]'))
    lower = visible.lower()
    markers = [phrase for phrase in ('verify you are human', 'unusual traffic', 'access denied',
                'complete the captcha', 'solve the challenge', 'please sign in to continue',
                'please log in to continue', '请输入验证码', '请完成验证') if phrase in lower]
    html_summary = {'title': title, 'query_input_values': [v[:1000] for v in inputs[:3]], 'result_rows': rows,
                    'result_row_count': len(tree.xpath('//ol[@id="b_results"]/li[contains(@class,"b_algo")]')),
                    'explicit_stop_markers': markers,
                    'target_host_hrefs_count': sum(1 for v in tree.xpath('//a/@href')
                         if urlsplit(v).hostname == 'microsoft.github.io'),
                    'target_host_occurrences_in_html': bytes(BODY).lower().count(b'microsoft.github.io')}
    R['html_before_engine_parse'] = html_summary
    if markers:
        raise BudgetStop('explicit_denial_or_challenge')


def main():
    global PERMIT
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, '/usr/local/searxng')
    # Curl-level URL gate exists before any SearXNG initialization.
    from curl_cffi import Curl, CurlOpt
    original_setopt = Curl.setopt
    def observed_setopt(self, option, value):
        if option == CurlOpt.URL:
            if not PERMIT or R['counts']['client_delegations'] != 1:
                raise BudgetStop('curl_send_not_permitted')
            url = value.decode() if isinstance(value, bytes) else str(value)
            fixed_url(url)
            R['counts']['curl_url_assignments'] += 1
            if R['counts']['curl_url_assignments'] > 1:
                raise BudgetStop('second_curl_url_blocked')
            R['actual_libcurl_url'] = url
            R['actual_libcurl_q'] = parse_qs(urlsplit(url).query)['q'][0]
        return original_setopt(self, option, value)
    hook(Curl, 'setopt', observed_setopt)

    # Reading settings is necessary for faithful public transport parameters.
    # They remain in memory; only the explicit non-secret projection below is saved.
    from searx import settings
    from searx.engines import engines, load_engines
    from searx.network import get_network
    from searx.network import network as network_module
    from searx.network.client import AsyncClient, DEFAULT_IMPERSONATE
    from searx.search.models import SearchQuery, EngineRef
    from searx.search.processors.online import OnlineProcessor
    from searx.results import ResultContainer
    import searx.metrics
    searx.metrics.initialize(['bing'], enabled=False)

    specs = [copy.deepcopy(e) for e in settings['engines'] if e.get('name') == 'bing' and e.get('engine') == 'bing']
    if len(specs) != 1:
        raise BudgetStop('bing_config_not_unique')
    load_engines(specs)
    network_module.initialize(settings_engines=specs, settings_outgoing=copy.deepcopy(settings['outgoing']))
    engine = engines['bing']
    net = get_network('bing')
    proxy_env_present = any(os.environ.get(k) for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'))
    R['runtime_public_config'] = {
        'settings_source': 'current installed instance settings read in isolated process; never serialized',
        'safesearch': settings['search']['safe_search'], 'language': 'en', 'page': 1,
        'network_verify': bool(net.verify), 'enable_http': net.enable_http,
        'http2': net.enable_http2, 'http3': net.enable_http3,
        'proxy_configured': bool(net.proxies), 'proxy_environment_present': proxy_env_present,
        'tor_configured': net.using_tor_proxy, 'original_retries': net.retries,
        'original_max_redirects': net.max_redirects, 'installed_default_impersonate': DEFAULT_IMPERSONATE}
    if not net.verify or net.proxies or net.using_tor_proxy or proxy_env_present:
        raise BudgetStop('unsupported_transport_configuration')
    net.retries = 0
    processor = OnlineProcessor(engine)
    search = SearchQuery(QUERY, [EngineRef('bing', 'general')], lang='en',
                         safesearch=settings['search']['safe_search'], timeout_limit=22)
    params = processor.get_params(search, 'general')
    if params.get('allow_redirects') or params.get('max_redirects') or params.get('auth') or params.get('cookies'):
        raise BudgetStop('non_default_redirect_or_auth')
    if any(str(k).lower() in ('authorization', 'proxy-authorization', 'cookie') for k in params.get('headers', {})):
        raise BudgetStop('credential_header_present')
    R['request_public_params'] = {'allow_redirects': params['allow_redirects'], 'max_redirects': params['max_redirects'],
                                  'locale': params['searxng_locale'], 'safesearch': params['safesearch']}

    source_paths = [Path(engine.__file__), Path(sys.modules[OnlineProcessor.__module__].__file__),
                    Path(network_module.__file__), Path(sys.modules[AsyncClient.__module__].__file__)]
    R['source_sha256_before'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    R['_source_paths'] = [str(p) for p in source_paths]

    original_client = AsyncClient.request
    async def observed_client(self, method, url, **kwargs):
        R['counts']['network_client_attempts'] += 1
        if not PERMIT or R['counts']['client_delegations'] >= 1:
            R['counts']['blocked_client_attempts'] += 1
            raise BudgetStop('client_call_budget')
        fixed_url(url)
        if method.upper() != 'GET' or kwargs.get('allow_redirects') is not False or kwargs.get('auth') or kwargs.get('cookies'):
            raise BudgetStop('unexpected_request_options')
        R['counts']['client_delegations'] += 1
        R['client_url'] = url
        R['client_started_at'] = utc()
        kwargs['content_callback'] = body_chunk
        kwargs['timeout'] = min(float(kwargs.get('timeout', 20)), 20.0)
        try:
            async with asyncio.timeout(21):
                response = await original_client(self, method, url, **kwargs)
            response.content = bytes(BODY)
            R['transport_before_patch'] = {
                'final_url': safe_url(response.url), 'status': response.status_code,
                'redirect_count': response.redirect_count, 'history': [
                    {'url': safe_url(x.url), 'status': x.status_code} for x in response.history],
                'location': safe_url(response.headers['location']) if response.headers.get('location') else None,
                'http_version': response.http_version, 'body_complete': True,
                'decoded_raw_html_bytes': len(BODY), 'decoded_raw_html_sha256': hashlib.sha256(BODY).hexdigest(),
                'hash_scope': 'client-decoded raw HTML bytes before DOM or engine parsing; not compressed wire bytes'}
            R['client_finished_at'] = utc()
            if response.status_code != 200:
                raise BudgetStop('non_200_stop')
            summarize_html(response)
            return response
        finally:
            R['received_body_bytes'] = len(BODY)
            R['received_body_sha256'] = hashlib.sha256(BODY).hexdigest()
    hook(AsyncClient, 'request', observed_client)

    original_patch = network_module.Network.patch_response
    def observed_patch(self, response, do_raise_for_httperror):
        R['counts']['patch_response'] += 1
        result = original_patch(self, response, do_raise_for_httperror)
        R['after_patch'] = {'status': result.status_code, 'body_sha256': hashlib.sha256(result.content).hexdigest()}
        return result
    hook(network_module.Network, 'patch_response', observed_patch)
    original_request = engine.request
    def observed_request(query, p):
        R['counts']['engine_request'] += 1
        result = original_request(query, p)
        fixed_url(p['url'])
        R['prepared_engine_url'] = p['url']
        R['prepared_engine_q'] = parse_qs(urlsplit(p['url']).query)['q'][0]
        return result
    hook(engine, 'request', observed_request)
    original_response = engine.response
    def observed_response(response):
        R['counts']['engine_response'] += 1
        rows = original_response(response)
        R['engine_results'] = [{'title': x.get('title', '')[:400], **safe_url(x.get('url', ''))} for x in rows]
        R['engine_result_count'] = len(rows)
        R['target_engine_result_count'] = sum(urlsplit(x.get('url', '')).hostname == 'microsoft.github.io' for x in rows)
        return rows
    hook(engine, 'response', observed_response)

    if not LIVE:
        engine.request(QUERY, params)
        # Meaningful local guard checks, without delegating to any network client.
        async def check():
            try:
                await observed_client(None, 'GET', params['url'], allow_redirects=False)
            except BudgetStop:
                R['prepare_guard_blocked'] = True
            else:
                raise AssertionError('network permit failed')
        asyncio.run(check())
        # A used permit is rejected before delegation (including hidden retries).
        PERMIT = True
        R['counts']['client_delegations'] = 1
        asyncio.run(check())
        R['prepare_second_call_blocked'] = R['counts']['blocked_client_attempts'] == 2
        R['counts']['client_delegations'] = 0  # synthetic consumed permit, never sent
        PERMIT = False
        from lxml import html
        from types import SimpleNamespace
        fixture = SimpleNamespace(html=lambda: html.fromstring(
            '<html><ol id="b_results"><li class="b_algo"><h2><a href="https://example.com/">Offline fixture</a></h2><p>Fixture only</p></li></ol></html>'))
        fixture_rows = original_response(fixture)
        fixture_container = ResultContainer()
        fixture_container.extend('bing', fixture_rows)
        assert len(fixture_container.get_ordered_results()) == 1
        R['prepare_parser_aggregation_fixture_passed'] = True
        R['outcome'] = 'prepared_no_network'
        return
    PERMIT = True
    processor.init_network_in_thread(start_time=time.monotonic(), timeout_limit=22)
    rows = processor._search_basic(QUERY, params)
    PERMIT = False
    container = ResultContainer()
    container.extend('bing', copy.deepcopy(rows))
    aggregated = container.get_ordered_results()
    R['isolated_aggregation'] = {'count': len(aggregated), 'results': [
        {'title': x.get('title', '')[:400], **safe_url(x.get('url', ''))} for x in aggregated],
        'scope': 'original ResultContainer only; no Flask/plugin stages observed'}
    R['outcome'] = 'completed_one_query'


def hard_deadline():
    time.sleep(45)
    R['outcome'] = 'hard_process_deadline'
    R['process_complete'] = False
    R['hard_exit_terminates_process_and_sockets'] = True
    try:
        save()
    finally:
        os._exit(124)


threading.Thread(target=hard_deadline, daemon=True).start()
signal.signal(signal.SIGALRM, on_alarm)
signal.alarm(40)
try:
    main()
except BaseException as exc:
    R['outcome'] = 'stopped'
    R['error_type'] = type(exc).__name__
    R['error_locations'] = [{'file': Path(x.filename).name, 'line': x.lineno, 'function': x.name}
                            for x in traceback.extract_tb(exc.__traceback__)]
    if isinstance(exc, BudgetStop):
        R['stop_reason'] = str(exc)
finally:
    PERMIT = False
    try:
        if 'searx.network.network' in sys.modules:
            sys.modules['searx.network.network'].done()
        R['clients_closed'] = True
    except BaseException as exc:
        R['cleanup_error_type'] = type(exc).__name__
    for obj, name, original in reversed(ORIGINALS):
        setattr(obj, name, original)
    R['hooks_restored'] = all(getattr(obj, name) is original for obj, name, original in ORIGINALS)
    for value in R.pop('_source_paths', []):
        p = Path(value)
        R['source_sha256_after'][value] = hashlib.sha256(p.read_bytes()).hexdigest()
    R['process_complete'] = True
    signal.alarm(0)
    save()
    print(json.dumps({'mode': R['mode'], 'outcome': R.get('outcome'), 'error_type': R.get('error_type'),
                      'stop_reason': R.get('stop_reason'), 'counts': R['counts'], 'hooks_restored': R['hooks_restored']}))
