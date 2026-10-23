"""Offline route prototype: observed redirect URLs, synthetic transport, saved HTML."""
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from backend.app.url_utils import normalize_url, UnsafeURL
from backend.app.ai_video_fallback import direct_video_url
from backend.app.extractor import MetadataExtractor
from backend.app.fetcher import Fetcher, FetcherConfig, HTTPResult, public_bilibili_metadata_url
from backend.app.models import SearchRequest
from backend.app import grounded_related
from backend.app.teaching_match import _own_catalog_target
from backend.app.video_availability import _bili_part_identity, _bound_page_video
from backend.app.source_adapters.video_leads import observed_bilibili_video_leads
from bs4 import BeautifulSoup

REDIRECTS = json.loads((Path(__file__).parent/'fixtures/bilibili_locale_redirects.json').read_text(encoding='utf-8'))['observations']
ORIGIN = 'https://www.bilibili.com'
VIDEO = ORIGIN + '/video/BV1VZ4y1G7YB/'
LOCALE = ORIGIN + '/zh-Hans/video/BV1VZ4y1G7YB/'
ROBOTS = ORIGIN + '/robots.txt'
REAL_CLIENT = httpx.AsyncClient

def html(bvid='BV1VZ4y1G7YB'):
    state = {'videoData': {'bvid': bvid, 'title': 'Python 列表与字典课程', 'desc': 'Python 列表添加元素，字典查询。',
             'pages': [{'page': 3, 'part': 'Python 列表添加元素', 'duration': 155}, {'page': 7, 'part': 'Python 字典查询', 'duration': 320}]}}
    return '<html><script>window.__INITIAL_STATE__=' + json.dumps(state, ensure_ascii=False) + ';</script></html>'

@pytest.mark.parametrize('number', [1, 2, 3])
def test_actual_observed_redirect_same_bv_and_exact_part(number):
    row = REDIRECTS[number - 1]
    assert '/zh-Hans/video/' in row['actualUrl']
    assert normalize_url(row['actualUrl']) == row['url']
    assert normalize_url(row['actualUrl'], preserve_bilibili_locale=True) == row['actualUrl']
    assert direct_video_url(row['actualUrl'], ['bilibili']) == row['url']
    assert public_bilibili_metadata_url(row['actualUrl'])

@pytest.mark.parametrize('suffix', ['', '?p=1', '?p=32', '?p=999999'])
def test_exact_part_is_retained(suffix):
    assert normalize_url(LOCALE + suffix) == VIDEO + suffix
    assert direct_video_url(LOCALE + suffix, ['bilibili']) == VIDEO + suffix
    assert normalize_url(LOCALE + '?p=32') != normalize_url(LOCALE + '?p=33')

@pytest.mark.parametrize('url', [
    ORIGIN + '/en/video/BV1VZ4y1G7YB/', ORIGIN + '/zh-hans/video/BV1VZ4y1G7YB/',
    ORIGIN + '/zh-Hans/video/BV123/', ORIGIN + '/zh-Hans/video/av123/',
    ORIGIN + '/zh-Hans/video/BV1VZ4y1G7YB/extra', ORIGIN + '/x/zh-Hans/video/BV1VZ4y1G7YB/',
    ORIGIN + '/zh-Hans/video/%42V1VZ4y1G7YB/', ORIGIN + '/zh-Hans/video/BV1VZ4y1G7YB//',
    ORIGIN + '/zh-Hans/video/BV1VZ4y1G7YB/../', ORIGIN + '/zh-Hans/video/BV1VZ4y1G7YB%2F',
    'https://m.bilibili.com/zh-Hans/video/BV1VZ4y1G7YB/',
    'https://api.bilibili.com/zh-Hans/video/BV1VZ4y1G7YB/',
    'https://www.bilibili.com.attacker.example/zh-Hans/video/BV1VZ4y1G7YB/',
    'https://user:secret@www.bilibili.com/zh-Hans/video/BV1VZ4y1G7YB/',
    'http://www.bilibili.com/zh-Hans/video/BV1VZ4y1G7YB/',
    'https://www.bilibili.com:444/zh-Hans/video/BV1VZ4y1G7YB/',
    LOCALE + '?p=0', LOCALE + '?p=1&p=2', LOCALE + '?p=-1', LOCALE + '?p=１',
    LOCALE + '?token=x', LOCALE + '?p=32&chapter=33', LOCALE + '#p=33',
])
def test_locale_does_not_expand_unsafe_or_unknown_shapes(url):
    assert direct_video_url(url, ['bilibili']) is None
    assert not public_bilibili_metadata_url(url)

def test_unknown_query_never_disappears_into_an_allowed_identity():
    assert 'chapter=33' in normalize_url(LOCALE + '?p=32&chapter=33')
    assert normalize_url(LOCALE + '?p=32&uid=old&vd_source=x') == VIDEO + '?p=32'
    assert normalize_url(LOCALE + '?p=32&uid=old', preserve_bilibili_locale=True) == LOCALE + '?p=32'
    assert normalize_url(LOCALE + '?p=32') != normalize_url(LOCALE + '?p=33')

def test_saved_complete_body_canonical_and_locale_evidence_seals_equal():
    path = Path('tests/fixtures/public_catalog_replays/bilibili-local-use-20261017/probe-after-decompression/page.html')
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '163d94189805bfe6c25bc2e2b8bca301c30860cbb83870336757093e377fb388'
    a = MetadataExtractor().extract(raw.decode('utf-8'), VIDEO, 'offline')
    b = MetadataExtractor().extract(raw.decode('utf-8'), LOCALE, 'offline')
    assert a == b and len(b['chapters']) == 15
    assert all(e['url'] == VIDEO for e in b['evidence'])
    assert all(v['url'] == VIDEO for v in b['field_provenance'].values())
    rows = {e['evidence_id']: e for e in b['evidence']}
    assert all(_own_catalog_target(VIDEO, c, rows[c['evidence_id']]) for c in b['chapters'])

def test_native_catalog_chain_keeps_page_identity_and_rejects_tampering():
    out = MetadataExtractor().extract(html(), LOCALE, 'offline')
    c = out['chapters'][0]; row = next(e for e in out['evidence'] if e['evidence_id'] == c['evidence_id'])
    assert c['url'] == VIDEO + '?p=3' and c['source_url'] == VIDEO
    assert _own_catalog_target(VIDEO, c, row)
    bad = dict(c, url=VIDEO + '?p=7')
    assert not _own_catalog_target(VIDEO, bad, row)
    assert not _own_catalog_target(VIDEO, dict(c, source_url=VIDEO + '?p=3'), row)
    assert not _own_catalog_target(VIDEO, c, dict(row, url=VIDEO + '?p=7'))
    assert not _own_catalog_target(VIDEO.replace('BV1VZ4y1G7YB','BV1BfpieUE3K'), c, row)

def test_wrong_bv_cannot_become_own_metadata():
    out = MetadataExtractor().extract(html('BV1BfpieUE3K'), LOCALE, 'offline')
    assert out['video_evidence_status'] != 'page_verified'
    assert not out['chapters']

def response(url, status=200, body=None, **headers):
    return HTTPResult(status, {'content-type':'text/html', **headers}, html().encode() if body is None else body, url)

def fetcher(responses):
    calls = []
    class MemoryHTTP:
        async def request(self, url, addresses, max_bytes):
            calls.append(url)
            assert url in responses, 'No real source requests allowed'
            return responses[url]
    async def dns(url, timeout):
        assert url in responses, 'Unreviewed target cannot resolve'
        return ['93.184.216.34']
    return Fetcher(FetcherConfig(bilibili_public_metadata=True, min_interval_seconds=0, max_retries=0),
                   resolver=dns, http_client=MemoryHTTP()), calls

def prepare(resource):
    r = copy.deepcopy(resource); r['resource_id'] = 'locale-offline'
    point = {'knowledge_point_id':'point-offline', 'text':'Python 列表', 'technology':'Python'}
    return grounded_related.prepare_pair(point, r, r['evidence'], SearchRequest(knowledge_points=[point['text']], topic_technologies={point['text']:'Python'}))

@pytest.mark.asyncio
@pytest.mark.parametrize('entry', [VIDEO, LOCALE])
async def test_redirect_wire_route_is_preserved_without_loop_and_evidence_rebinds(entry):
    f, calls = fetcher({ROBOTS:response(ROBOTS,404,b''), VIDEO:response(VIDEO,302,b'',location=LOCALE), LOCALE:response(LOCALE)})
    out = await f.enrich({'url':entry})
    assert out['fetch_status'] == 'fetched' and out['video_evidence_status'] == 'page_verified'
    assert calls == [ROBOTS] + ([VIDEO,LOCALE] if entry == VIDEO else [LOCALE])
    assert out['canonical_url'] == VIDEO and out['resolved_url'] == LOCALE
    assert all(e['url'] == VIDEO for e in out['evidence'] if e['kind'] in ('page','catalog'))
    assert prepare(out) is not None

@pytest.mark.asyncio
@pytest.mark.parametrize('barrier,expected', [('robots','robots_blocked'),('403','access_denied'),('429','rate_limited'),('captcha','captcha')])
async def test_real_locale_path_access_stops_preserved(barrier, expected):
    robots = response(ROBOTS,404,b'')
    page = response(LOCALE)
    if barrier == 'robots': robots = response(ROBOTS,200,b'User-agent: *\nDisallow: /zh-Hans/video/',**{'content-type':'text/plain'})
    if barrier == '403': page = response(LOCALE,403,b'Forbidden')
    if barrier == '429': page = response(LOCALE,429,b'',**{'retry-after':'120'})
    if barrier == 'captcha': page = response(LOCALE,200,b'<title>Verify you are human</title>')
    f,calls = fetcher({ROBOTS:robots, VIDEO:response(VIDEO,302,b'',location=LOCALE), LOCALE:page})
    out = await f.enrich({'url':VIDEO})
    assert out['fetch_status'] == expected
    assert calls == [ROBOTS,VIDEO] + ([] if barrier=='robots' else [LOCALE])

@pytest.mark.asyncio
async def test_cross_part_redirect_never_passes_bound_grounded_identity():
    f,calls = fetcher({ROBOTS:response(ROBOTS,404,b''), VIDEO+'?p=3':response(VIDEO+'?p=3',302,b'',location=LOCALE+'?p=7'), LOCALE+'?p=7':response(LOCALE+'?p=7')})
    out = await f.enrich({'url':VIDEO+'?p=3'})
    assert out['canonical_url'] == VIDEO+'?p=3' and out['resolved_url'] == LOCALE+'?p=7'
    assert prepare(out) is None

@pytest.mark.asyncio
async def test_pinned_transport_does_not_rewrite_locale_request_path(monkeypatch):
    import backend.app.fetcher as module
    requests=[]
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'<html>ok</html>'
    async def respond(req):
        requests.append((str(req.url),req.headers.get('host')))
        return httpx.Response(200,headers={'content-type':'text/html'},stream=Body())
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:REAL_CLIENT(transport=httpx.MockTransport(respond),**kw))
    out=await module.PinnedHTTPClient(FetcherConfig()).request(LOCALE+'?p=3',['93.184.216.34'],1000)
    assert urlsplit(requests[0][0]).path == '/zh-Hans/video/BV1VZ4y1G7YB/'
    assert urlsplit(requests[0][0]).query == 'p=3' and requests[0][1] == 'www.bilibili.com'
    assert out.url == LOCALE+'?p=3'

def test_observed_native_locale_anchor_is_only_a_lead_not_own_evidence():
    soup=BeautifulSoup('<a href="/zh-Hans/video/BV1BfpieUE3K/?p=2">Canvas</a>','html.parser')
    leads=observed_bilibili_video_leads(soup,LOCALE)
    assert leads == [{'url':ORIGIN+'/video/BV1BfpieUE3K/?p=2','title':'Canvas','source_url':VIDEO}]
    assert 'evidence' not in leads[0]

def test_actual_archived_multipart_dom_locale_canonical_and_own_seal_chain():
    path=Path('tests/fixtures/public_catalog_replays/platform-catalog-20261017/browser/bilibili-dom.html')
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='bb146089cf493d9691223e436a9088b8f01b425e45a761af51c00696b303d58f'
    out=MetadataExtractor().extract(raw.decode(),LOCALE,'offline')
    assert out==MetadataExtractor().extract(raw.decode(),VIDEO,'offline')
    assert out['field_provenance']['video_evidence_status']['source']=='html.bilibili.video_pod.multip'
    r={**out,'resource_id':'actual-multip-offline','url':VIDEO,'canonical_url':VIDEO,'resolved_url':LOCALE}
    assert _bound_page_video(r,out['evidence'])
    point={'knowledge_point_id':'point-multip','text':'Python 列表','technology':'Python'}
    request=SearchRequest(knowledge_points=[point['text']],topic_technologies={point['text']:'Python'})
    chapter=out['chapters'][0]
    pair=grounded_related.prepare_pair(point,r,out['evidence'],request,source_ids=[chapter['evidence_id']])
    assert pair is not None
    source=next(s for s in pair['sources'] if s['evidence_id']==chapter['evidence_id'])
    assert source['_projected']==chapter['title']
    # Synthetic seal only tests local binding, never model relevance/accuracy.
    decision={'pair_id':pair['pair_id'],'fingerprint':pair['fingerprint'],'support':{
        'evidence_id':source['evidence_id'],'source_text_sha256':source['source_text_sha256'],
        'basis':'catalog','quote':chapter['title']}}
    assert grounded_related.validate_support(pair,decision)
    decision.update(version=grounded_related.VERSION,source_ids=[s['evidence_id'] for s in pair['sources']])
    decision['review_seal']=grounded_related._hash(decision)
    assert grounded_related.project_reference(point,r,out['evidence'],request,decision)
    damaged=copy.deepcopy(out['evidence'])
    next(e for e in damaged if e['evidence_id']==chapter['evidence_id'])['text']+=' changed'
    assert grounded_related.project_reference(point,r,damaged,request,decision) is None

@pytest.mark.parametrize('name',['pydantic','set_difference'])
def test_retained_actual_multipart_records_accept_only_same_bv_part_locale(name):
    data=json.loads(Path('tests/fixtures/multip_identity/retained.json').read_text(encoding='utf-8'))['cases'][name]
    r,e=copy.deepcopy(data['resource']),copy.deepcopy(data['evidence'])
    r['resolved_url']=(r.get('resolved_url') or r['url']).replace('/video/','/zh-Hans/video/')
    assert _bound_page_video(r,e)
    request=SearchRequest.model_validate(data['request'])
    c=r['chapters'][data['target_chapter_index']]
    assert grounded_related.prepare_pair(data['point'],r,e,request,source_ids=[c['evidence_id']])

@pytest.mark.parametrize('suffix',['?unknown_source=x','?unknown_uid=x','?unknown_vd=x','?token=x','?p=1&p=1','?p=1&x=2','?%70=1','?p=0','?p=-1','?p=１','#part'])
def test_multipart_identity_raw_query_remains_strict(suffix):
    assert _bili_part_identity(LOCALE+suffix) is None
    data=json.loads(Path('tests/fixtures/multip_identity/retained.json').read_text(encoding='utf-8'))['cases']['pydantic']
    r,e=copy.deepcopy(data['resource']),copy.deepcopy(data['evidence'])
    r['resolved_url']=r['canonical_url'].replace('/video/','/zh-Hans/video/')+suffix
    assert not _bound_page_video(r,e)

@pytest.mark.parametrize('url',[
    LOCALE+'?p=7',LOCALE.replace('BV1VZ4y1G7YB','BV1BfpieUE3K'),
    LOCALE.replace('www.bilibili.com','m.bilibili.com'),LOCALE.replace('www.bilibili.com','evil.bilibili.com'),
    LOCALE.replace('/zh-Hans/','/zh-Hans/zh-Hans/'),LOCALE.replace('/zh-Hans/','/en/'),
])
def test_multipart_locale_does_not_borrow_another_part_bv_host_or_route(url):
    raw=Path('tests/fixtures/public_catalog_replays/platform-catalog-20261017/browser/bilibili-dom.html').read_text(encoding='utf-8')
    out=MetadataExtractor().extract(raw,LOCALE,'offline')
    r={**out,'resource_id':'negative-multip','url':VIDEO,'canonical_url':VIDEO,'resolved_url':url}
    assert not _bound_page_video(r,out['evidence'])

@pytest.mark.asyncio
async def test_real_multipart_replay_survives_fetcher_redirect_as_bound_own_video():
    raw=Path('tests/fixtures/public_catalog_replays/platform-catalog-20261017/browser/bilibili-dom.html').read_bytes()
    f,calls=fetcher({ROBOTS:response(ROBOTS,404,b''),VIDEO:response(VIDEO,302,b'',location=LOCALE),LOCALE:response(LOCALE,body=raw)})
    out=await f.enrich({'url':VIDEO})
    assert calls==[ROBOTS,VIDEO,LOCALE]
    assert out['canonical_url']==VIDEO and out['resolved_url']==LOCALE
    assert _bound_page_video(out,out['evidence']) and prepare(out)

def test_locale_cache_version_changes_only_bilibili_and_retains_old_records():
    from backend.app.config import Settings
    from backend.app.db import Store
    from backend.app.service import JobService
    baseline=json.loads((Path(__file__).parent/'fixtures/bilibili_locale_cache_before.json').read_text(encoding='utf-8'))
    store=Store(':memory:')
    try:
        service=JobService(Settings(bilibili_public_metadata=True),store)
        value={'fetch_status':'javascript_required','chapters':[],'prior_metadata_version':17}
        for row in baseline['rows']:
            store.cache_set(row['old_key'],'page',value,86400)
            key,cached=service._page_cache({'canonical_url':row['url']})
            if urlsplit(row['url']).hostname in {'www.bilibili.com','bilibili.com'}:
                assert key!=row['old_key'] and cached is None
            else:
                assert key==row['old_key'] and cached['data']==value
            assert store.cache_get(row['old_key'])['data']==value
    finally:
        store.close()
