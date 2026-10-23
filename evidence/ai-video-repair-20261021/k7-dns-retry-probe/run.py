"""Read three previously discovered candidates without writing production state."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from bs4 import BeautifulSoup
from backend.app.config import Settings
from backend.app.ai_video_fallback import direct_video_url
from backend.app.fetcher import Fetcher, FetcherConfig, FETCH_DEADLINE_AT, NETWORK_OBSERVER
from backend.app.models import SearchRequest
from backend.app.related_recommendations import related_recommendation
from backend.app.source_adapters.bilibili import _page_initial_state

OUT = Path(__file__).resolve().parent
TARGETS = tuple(x['canonical_url'].rstrip('/').rsplit('/', 1)[-1] for x in json.loads((ROOT / 'evidence/ai-video-repair-20261021/final-gap-diagnostic.json').read_text(encoding='utf-8'))['bilibili_sources'] if x['fetch_status'] == 'dns_error')


def own_payment(html, expected_bvid):
    state = _page_initial_state(BeautifulSoup(html, 'html.parser'))
    video = state.get('videoData', {}) if isinstance(state, dict) else {}
    bound = bool(state and state.get('bvid') == expected_bvid and video.get('bvid') == expected_bvid)
    return {'identity_bound': bound, 'state_bvid': state.get('bvid') if state else None,
            'video_bvid': video.get('bvid'), 'title': video.get('title'),
            'own_flags': {k: v for k, v in video.items() if re.search(r'pay|vip|power|charge|elec|rights|access|preview|trial', k, re.I)} if bound else {},
            'free_playback_verified': False}


def observed_candidates():
    path = ROOT / 'evidence/ai-video-repair-20261021/final-gap-diagnostic.json'
    diagnostic = json.loads(path.read_text(encoding='utf-8'))
    sources = [x for x in diagnostic['bilibili_sources'] if x['fetch_status'] == 'dns_error']
    assert len(sources) == 3
    return [{'candidate': {'url': x['canonical_url'], 'title': x['title'], 'source': 'previously_discovered_dns_error',
        'snippet': ''}, 'bvid': x['canonical_url'].rstrip('/').rsplit('/', 1)[-1],
        'original_resource_id': x['resource_id'],
        'source_evidence': {'diagnostic': str(path), 'job_id': diagnostic['job']['job_id'], 'prior_status': 'dns_error', 'resource': x}} for x in sources]

async def main():
    settings = Settings.from_env()
    candidates = observed_candidates()
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'production_db_writes': 0,
              'configuration_changes': 0, 'search_queries': 0, 'injected_urls': False,
              'candidate_limit': 3, 'detail_http_requests': 0, 'candidates': candidates, 'results': []}
    source_html = ROOT / 'evidence/ai-video-repair-20261021/bilibili-size-probe/page.html'
    paid = own_payment(source_html.read_text(encoding='utf-8'), 'BV1nxCXBtEy5')
    paid.update(source_path=str(source_html), source_sha256=hashlib.sha256(source_html.read_bytes()).hexdigest())
    (OUT / 'known-paid-own-flags.json').write_text(json.dumps(paid, ensure_ascii=False, indent=2), encoding='utf-8')
    fetcher = Fetcher(FetcherConfig(enabled=settings.fetch_enabled, timeout_seconds=settings.fetch_timeout_seconds, max_retries=0,
        global_concurrency=settings.global_concurrency, min_interval_seconds=settings.fetch_min_interval_seconds,
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
        bvid = url.rstrip('/').rsplit('/', 1)[-1]
        if bvid in TARGETS:
            captured[bvid] = html
            (OUT / (bvid + '.html')).write_text(html, encoding='utf-8')
        return original_extract(html, url, fetched_at)
    fetcher.extractor.extract = capture
    async def before_detail():
        if report['detail_http_requests'] >= 4:
            raise TimeoutError('diagnostic_detail_http_budget')
        report['detail_http_requests'] += 1
    observer = NETWORK_OBSERVER.set({'before_target_http': before_detail})
    deadline = FETCH_DEADLINE_AT.set(asyncio.get_running_loop().time() + 150)
    request = SearchRequest(knowledge_points=['文件下载'], topic_technologies={'文件下载': 'Streamlit'}, preferred_platforms=['bilibili'], language='zh')
    point = {'knowledge_point_id': 'K7', 'text': '文件下载', 'technology': 'Streamlit'}
    try:
        for observed in candidates:
            resource = await fetcher.enrich(observed['candidate'])
            resource['resource_id'] = observed['original_resource_id']
            own = [x for x in resource.get('evidence', []) if x.get('kind') in {'page', 'catalog'}]
            html = captured.get(observed['bvid'])
            result = {'bvid': observed['bvid'], 'resource': resource,
                'own_related': related_recommendation(point, resource, own, request),
                'download_chapters': [x for x in resource.get('chapters', []) if re.search(r'下载|download|导出|export', x.get('title', ''), re.I)],
                'own_payment': own_payment(html, observed['bvid']) if html else None,
                'playback_verified': False, 'known_audio_quality_notice': re.findall(r'[^。！；\n]*(?:音频坏|声音坏|没有声音|无声音|音频损坏|audio broken)[^。！；\n]*', resource.get('description') or '', re.I)}
            report['results'].append(result)
            (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'bvid': observed['bvid'], 'title': resource.get('title'), 'fetch_status': resource.get('fetch_status'),
                'page_verified': resource.get('video_evidence_status'), 'chapters': len(resource.get('chapters', [])),
                'download_chapters': result['download_chapters'], 'own_related': result['own_related'] is not None,
                'requires_payment': resource.get('requires_payment'), 'own_payment': result['own_payment']}, ensure_ascii=False), flush=True)
    finally:
        NETWORK_OBSERVER.reset(observer)
        FETCH_DEADLINE_AT.reset(deadline)
        report.update(finished_at=datetime.now(timezone.utc).isoformat(), request_trace=list(fetcher.request_trace))
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


asyncio.run(main())

