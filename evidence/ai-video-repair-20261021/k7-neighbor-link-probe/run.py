"""At most two observed public HTML pages; no API/search or production writes."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from bs4 import BeautifulSoup
from backend.app.ai_video_fallback import direct_video_url
from backend.app.config import Settings
from backend.app.fetcher import Fetcher, FetcherConfig, FETCH_DEADLINE_AT, NETWORK_OBSERVER
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation
from backend.app.source_adapters.bilibili import _page_initial_state

OUT = Path(__file__).resolve().parent
OBSERVED_TITLE = '[streamlit]多媒体提供上传下载大文件'


def title_matches(value):
    value = re.sub(r'\s+', '', str(value)).lower()
    return 'streamlit' in value and '上传下载大文件' in value


def own_payment(html, url):
    state = _page_initial_state(BeautifulSoup(html, 'html.parser'))
    video = state.get('videoData', {}) if isinstance(state, dict) else {}
    bvid = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
    bound = bool(state and state.get('bvid') == bvid and video.get('bvid') == bvid)
    return {'identity_bound': bound, 'state_bvid': state.get('bvid') if state else None,
        'video_bvid': video.get('bvid'), 'title': video.get('title'),
        'own_flags': {k: v for k, v in video.items() if re.search(r'pay|vip|power|charge|elec|rights|access|preview|trial', k, re.I)} if bound else {}}


def related_leads(html, source_url):
    soup = BeautifulSoup(html, 'html.parser')
    result = []
    for index, anchor in enumerate(soup.select('a[href]')):
        text = anchor.get_text(' ', strip=True)
        if not title_matches(text):
            continue
        url = direct_video_url(urljoin(source_url, anchor['href']), ['bilibili'])
        if url and url != source_url:
            result.append({'url': url, 'title': text, 'evidence_kind': 'actual_dom_anchor',
                'source_url': source_url, 'anchor_index': index, 'href': anchor['href']})
    state = _page_initial_state(soup)
    def visit(value, path):
        if isinstance(value, dict):
            title, bvid = value.get('title'), value.get('bvid')
            if title_matches(title) and isinstance(bvid, str) and re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid):
                url = direct_video_url('https://www.bilibili.com/video/' + bvid + '/', ['bilibili'])
                if url and url != source_url:
                    result.append({'url': url, 'title': title, 'observed_bvid': bvid,
                        'evidence_kind': 'actual_structured_item', 'state_path': path, 'source_url': source_url})
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    visit(child, path + '.' + str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + '[' + str(index) + ']')
    if state:
        visit(state, '__INITIAL_STATE__')
    return result


async def main():
    previous_path = ROOT / 'evidence/ai-video-repair-20261021/k7-source-probe/report.json'
    previous = json.loads(previous_path.read_text(encoding='utf-8'))
    candidate = next(x['candidate'] for x in previous['details'] if '/BV1Gx4y1r7ZS/' in x['candidate']['url'])
    settings = Settings.from_env()
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'production_writes': 0,
        'search_queries': 0, 'api_requests': 0, 'source_page_limit': 2, 'source_page_fetches': 0,
        'detail_http_requests': 0, 'source_candidate_from': str(previous_path),
        'observed_neighbor_title': OBSERVED_TITLE, 'source_candidate': candidate, 'leads': []}
    fetcher = Fetcher(FetcherConfig(enabled=settings.fetch_enabled, timeout_seconds=settings.fetch_timeout_seconds,
        max_retries=0, global_concurrency=settings.global_concurrency, min_interval_seconds=settings.fetch_min_interval_seconds,
        allowed_restricted_hosts=settings.allowed_restricted_hosts, denied_hosts=settings.denied_fetch_hosts,
        bilibili_public_metadata=settings.bilibili_public_metadata,
        bilibili_public_metadata_max_bytes=settings.bilibili_public_metadata_max_bytes,
        dns_resolver=settings.dns_resolver, phased_timeouts=settings.fetch_phased_timeouts,
        body_idle_timeout_seconds=settings.fetch_body_idle_timeout_seconds,
        body_min_bytes_per_second=settings.fetch_body_min_bytes_per_second,
        body_timeout_cap_seconds=settings.fetch_body_timeout_cap_seconds))
    captured = {}
    original_extract = fetcher.extractor.extract
    def capture(html, url, fetched_at):
        normalized = direct_video_url(url, ['bilibili'])
        if normalized:
            captured[normalized] = html
            bvid = urlsplit(normalized).path.rstrip('/').rsplit('/', 1)[-1]
            (OUT / (bvid + '.html')).write_text(html, encoding='utf-8')
        return original_extract(html, url, fetched_at)
    fetcher.extractor.extract = capture
    async def before_detail():
        if report['detail_http_requests'] >= 10:
            raise TimeoutError('diagnostic_http_budget')
        report['detail_http_requests'] += 1
    observer = NETWORK_OBSERVER.set({'before_target_http': before_detail})
    deadline = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + 120)
    try:
        report['source_page_fetches'] += 1
        first = await fetcher.enrich(candidate)
        report['source_resource'] = first
        first_url = direct_video_url(candidate['url'], ['bilibili'])
        html = captured.get(first_url)
        if html and first.get('fetch_status') == 'fetched':
            report['leads'] = related_leads(html, first_url)
        print(json.dumps({'source_status': first.get('fetch_status'), 'observed_leads': report['leads']}, ensure_ascii=False), flush=True)
        if report['leads']:
            lead = report['leads'][0]
            report['source_page_fetches'] += 1
            second = await fetcher.enrich({'url': lead['url'], 'title': lead['title'], 'source': 'fetched_page_link', 'source_url': first_url})
            second['resource_id'] = 'res_' + hashlib.sha256(second['canonical_url'].encode()).hexdigest()[:24]
            own = [x for x in second.get('evidence', []) if x.get('kind') in {'page', 'catalog'}]
            request = SearchRequest(knowledge_points=['文件下载'], topic_technologies={'文件下载': 'Streamlit'}, preferred_platforms=['bilibili'], language='zh')
            point = {'knowledge_point_id': 'K7', 'text': '文件下载', 'technology': 'Streamlit'}
            html = captured.get(lead['url'])
            report['target'] = {'lead': lead, 'resource': second,
                'own_related': related_recommendation(point, second, own, request),
                'download_chapters': [x for x in second.get('chapters', []) if re.search(r'下载|download|导出|export', x.get('title', ''), re.I)],
                'own_payment': own_payment(html, lead['url']) if html else None, 'playback_verified': False}
            print(json.dumps({'url': lead['url'], 'fetch_status': second.get('fetch_status'), 'video_evidence_status': second.get('video_evidence_status'),
                'requires_payment': second.get('requires_payment'), 'own_related': report['target']['own_related'] is not None,
                'own_payment': report['target']['own_payment']}, ensure_ascii=False), flush=True)
    finally:
        NETWORK_OBSERVER.reset(observer)
        FETCH_DEADLINE_AT.reset(deadline)
        report.update(finished_at=datetime.now(timezone.utc).isoformat(), request_trace=list(fetcher.request_trace))
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


asyncio.run(main())
