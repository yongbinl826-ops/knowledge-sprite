"""Offline only: minimal observed shell + sanitized own fields; fake transport."""
import asyncio
import hashlib
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from backend.app.extractor import MetadataExtractor
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, NETWORK_OBSERVER, FETCH_DEADLINE_AT
from backend.app.source_adapters.bilibili import empty_ssr_locale_url
from backend.app.video_availability import _bound_page_video

FIX = Path(__file__).parent / 'fixtures'
SHELL = (FIX / 'bilibili-empty-ssr-minimal.html').read_bytes()
OWN = (FIX / 'bilibili-locale-own-sanitized.html').read_bytes()
BASE = 'https://www.bilibili.com'
VIDEO = BASE + '/video/BV1eu4y1y7pb/'
LOCALE = BASE + '/zh-Hans/video/BV1eu4y1y7pb/'
ROBOTS = BASE + '/robots.txt'

def facts(body=SHELL, url=VIDEO):
    return MetadataExtractor().extract(body.decode(), url, 'initial-time')

def reply(url, body=SHELL, status=200, **headers):
    return HTTPResult(status, {'content-type':'text/html; charset=utf-8', **headers}, body, url)

class FakeHTTP:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
    async def request(self, url, addresses, max_bytes):
        self.calls.append((url, max_bytes))
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            return await value()
        return value

async def reserve_true():
    return True

async def resolver(url, timeout):
    return ['93.184.216.34']

def make_fetcher(suffix='', locale=None, initial=None, robots=b'User-agent: *\nAllow: /'):
    url, alt = VIDEO + suffix, LOCALE + suffix
    client=FakeHTTP({ROBOTS:reply(ROBOTS,robots),url:initial or reply(url),alt:locale or reply(alt,OWN)})
    f=Fetcher(FetcherConfig(bilibili_public_metadata=True,min_interval_seconds=0,max_retries=1),resolver=resolver,http_client=client)
    return f, client

@pytest.mark.parametrize('suffix', ['', '?p=1', '?p=37'])
def test_observed_shell_retains_part(suffix):
    assert empty_ssr_locale_url(SHELL.decode(),VIDEO+suffix,VIDEO+suffix,facts(url=VIDEO+suffix)) == LOCALE+suffix

@pytest.mark.parametrize('url', [VIDEO+'?p=1&p=2',VIDEO+'?p=0',VIDEO+'?p=01',VIDEO+'?%70=1',VIDEO+'?p=１',VIDEO+'?p=1&x=2',VIDEO+'#p=1',LOCALE,VIDEO.replace('www.','m.'),VIDEO.replace('https:','http:'),VIDEO.replace('BV1eu4y1y7pb','av123'),VIDEO.replace('www.bilibili.com','www.bilibili.com.attacker.example')])
def test_raw_identity_not_cleaned_before_gate(url):
    assert empty_ssr_locale_url(SHELL.decode(),url,url,facts()) is None

@pytest.mark.parametrize('body', [SHELL.replace(b'<title></title>',b'<title>404</title>'),SHELL.replace(b'<div id="video-page-app"></div>',b'<div id="video-page-app"><p>data</p></div>'),SHELL.replace(b'</body>',b'<div id="app"><p>own data</p></div></body>'),SHELL.replace(b'</body>',b'<script>window.__INITIAL_STATE__={broken;</script></body>'),SHELL.replace(b'</body>',b'<script type="application/ld+json">{}</script></body>'),SHELL.replace(b'</body>',b'<form>Sign in</form></body>'),SHELL.replace(b'</body>',b'<p>captcha</p></body>'),SHELL.replace(b's1.hdslb.com',b'unknown.example'),OWN])
def test_not_an_explicit_empty_shell_does_not_trigger(body):
    assert empty_ssr_locale_url(body.decode(),VIDEO,VIDEO,facts(body)) is None

@pytest.mark.asyncio
@pytest.mark.parametrize('suffix', ['', '?p=1'])
async def test_realshape_success_reserves_once_uses_actual_time_and_own_evidence(suffix):
    f,c=make_fetcher(suffix)
    calls=[]
    async def reserve(): calls.append(1);return True
    with patch('backend.app.fetcher.utcnow', side_effect=lambda: 'locale-time' if c.calls and c.calls[-1][0]==LOCALE+suffix else 'shell-time'):
        value=await f.enrich({'url':VIDEO+suffix,'title':'search title','source':'test'},catalog_budget_hook=reserve)
    assert len(calls)==1
    assert [x[0] for x in c.calls]==[ROBOTS,VIDEO+suffix,LOCALE+suffix]
    assert value['fetched_at']=='locale-time' and value['resolved_url']==LOCALE+suffix
    assert value['fetch_status']=='fetched' and value['video_evidence_status']=='page_verified'
    assert value['catalog_pages_completed']==1 and len(value['chapters'])==1
    assert _bound_page_video(value,value['evidence'])
    assert len([e for e in value['evidence'] if e['kind']=='search'])==1
    assert any(e.get('fetched_at')=='shell-time' for e in value['evidence'])
    trace={x['event']:x for x in f.request_trace}
    assert trace['bilibili_empty_ssr']['body_sha256']==hashlib.sha256(SHELL).hexdigest()
    assert trace['bilibili_locale_received']['body_sha256']==hashlib.sha256(OWN).hexdigest()

@pytest.mark.asyncio
async def test_false_detail_hook_stops_before_extra_io():
    f,c=make_fetcher()
    async def reserve():return False
    v=await f.enrich({'url':VIDEO},catalog_budget_hook=reserve)
    assert v['catalog_fetch_status']=='budget_limited' and v['fetch_status']=='javascript_required'
    assert v['catalog_pages_completed']==0
    assert [x[0] for x in c.calls]==[ROBOTS,VIDEO]

@pytest.mark.asyncio
async def test_no_trailing_slash_with_explicit_budget():
    f,c=make_fetcher()
    c.responses[VIDEO.rstrip('/')]=reply(VIDEO.rstrip('/'))
    c.responses[LOCALE.rstrip('/')]=reply(LOCALE.rstrip('/'),OWN)
    v=await f.enrich({'url':VIDEO.rstrip('/')},catalog_budget_hook=reserve_true)
    assert v['fetch_status']=='fetched' and v['resolved_url']==LOCALE.rstrip('/')
    assert len(c.calls)==3

@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected',[(401,'login_required'),(403,'access_denied'),(404,'not_found'),(429,'rate_limited')])
async def test_locale_negative_stays_negative_without_video_proof(status,expected):
    f,c=make_fetcher(locale=reply(LOCALE,OWN,status=status))
    v=await f.enrich({'url':VIDEO,'title':'search title'},catalog_budget_hook=reserve_true)
    assert v['fetch_status']==expected and v['video_evidence_status']=='none' and v['chapters']==[]
    assert len(c.calls)==3
    assert not any(e.get('field')=='video_evidence_status' for e in v['evidence'])

@pytest.mark.asyncio
@pytest.mark.parametrize('target',[VIDEO,LOCALE,LOCALE+'?p=2',LOCALE.replace('BV1eu4y1y7pb','BV16C4y1E78m'),LOCALE.replace('www.','')])
async def test_redirect_does_not_send_second_page(target):
    f,c=make_fetcher(locale=reply(LOCALE,b'',status=301,location=target))
    v=await f.enrich({'url':VIDEO},catalog_budget_hook=reserve_true)
    assert v['fetch_status']=='redirect_limit' and len(c.calls)==3

@pytest.mark.asyncio
async def test_unknown_locale_does_not_become_verified_and_no_renderer():
    f,c=make_fetcher(locale=reply(LOCALE,b'<html><title>unrelated generic</title></html>'))
    class Renderer:
        config=type('Config',(),{'enabled':True,'allowed_hosts':('www.bilibili.com',)})()
        async def render(self,*args):raise AssertionError('static followup may not execute JavaScript')
    f.renderer=Renderer()
    v=await f.enrich({'url':VIDEO},catalog_budget_hook=reserve_true)
    assert v['fetch_status']=='javascript_required' and v['video_evidence_status']=='none'

@pytest.mark.asyncio
async def test_mismatched_response_url_does_not_bind():
    f,c=make_fetcher(locale=reply(LOCALE+'?p=2',OWN))
    v=await f.enrich({'url':VIDEO},catalog_budget_hook=reserve_true)
    assert v['catalog_fetch_status']=='identity_mismatch' and v['video_evidence_status']=='none'

@pytest.mark.asyncio
async def test_timeout_is_single_attempt_and_observer_restored():
    f,c=make_fetcher(locale=httpx.ReadTimeout('synthetic'))
    seen=[]
    async def before(url):seen.append(url)
    original={'before_resolve':before,'max_retries':1}
    token=NETWORK_OBSERVER.set(original)
    try:
        v=await f.enrich({'url':VIDEO},catalog_budget_hook=reserve_true)
        assert NETWORK_OBSERVER.get() is original
    finally:NETWORK_OBSERVER.reset(token)
    assert v['fetch_status']=='timeout' and len(c.calls)==3 and seen==[ROBOTS,VIDEO,LOCALE]

@pytest.mark.asyncio
async def test_cancel_propagates_and_observer_restores():
    f,c=make_fetcher(locale=asyncio.CancelledError())
    original={};token=NETWORK_OBSERVER.set(original)
    try:
        with pytest.raises(asyncio.CancelledError):await f.enrich({'url':VIDEO},catalog_budget_hook=reserve_true)
        assert NETWORK_OBSERVER.get() is original
    finally:NETWORK_OBSERVER.reset(token)

@pytest.mark.asyncio
async def test_deadline_spent_after_shell_does_not_reserve():
    f,c=make_fetcher(); reserved=[]
    async def initial():
        FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time()-1)
        return reply(VIDEO)
    # Set in extractor, because transport runs in its own wait_for child task.
    extract=f.extractor.extract
    def expiry(*args):
        FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time()-1)
        return extract(*args)
    f.extractor.extract=expiry
    async def reserve():reserved.append(1);return True
    token=FETCH_DEADLINE_AT.set(None)
    try:
        with pytest.raises(TimeoutError):await f.enrich({'url':VIDEO},catalog_budget_hook=reserve)
    finally:FETCH_DEADLINE_AT.reset(token)
    assert not reserved and len(c.calls)==2

@pytest.mark.asyncio
async def test_existing_network_byte_and_call_hooks_are_preserved():
    f,c=make_fetcher(); resolutions=[]; responses=[]; calls=[]
    async def resolve(url):resolutions.append(url)
    async def before():calls.append(1)
    original={'before_resolve':resolve,'before_target_http':before,'response_byte_limit':lambda:999999,'response':lambda result,kind:responses.append((result.url,kind))}
    token=NETWORK_OBSERVER.set(original)
    try:
        v=await f.enrich({'url':VIDEO},catalog_budget_hook=reserve_true)
        assert NETWORK_OBSERVER.get() is original
    finally:NETWORK_OBSERVER.reset(token)
    assert v['fetch_status']=='fetched' and len(responses)==len(calls)==len(resolutions)==3
    assert c.calls[-1][1]==999999

@pytest.mark.asyncio
async def test_robots_disallow_locale_without_extra_page():
    f,c=make_fetcher(robots=b'User-agent: *\nAllow: /video/\nDisallow: /zh-Hans/')
    v=await f.enrich({'url':VIDEO},catalog_budget_hook=reserve_true)
    assert v['fetch_status']=='robots_blocked' and len(c.calls)==2


@pytest.mark.asyncio
async def test_missing_hook_does_not_send_locale_request():
    f,c=make_fetcher()
    value=await f.enrich({'url':VIDEO})
    assert value['catalog_fetch_status']=='not_attempted'
    assert value['fetch_status']=='javascript_required' and len(c.calls)==2


@pytest.mark.parametrize('suffix', ['?uid=3546389412382854', '?utm_source=search', '?vd_source=known', '?p=1&uid=3546389412382854', '?uid=123&p=1'])
def test_existing_known_tracking_normalization_is_compatible(suffix):
    canonical=VIDEO+('?p=1' if 'p=1' in suffix else '')
    expected=LOCALE+('?p=1' if 'p=1' in suffix else '')
    assert empty_ssr_locale_url(SHELL.decode(),VIDEO+suffix,canonical,facts(url=canonical))==expected


def test_irrelevant_malformed_script_does_not_escape_shell_parser():
    body=SHELL.replace(b'</body>',b'<script src="http://["></script></body>')
    assert empty_ssr_locale_url(body.decode(),VIDEO,VIDEO,facts(body))==LOCALE
