"""Eight bounded configured-provider searches; no production writes."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.providers import SerperProvider, SearchError, SearchBudgetReached, QueryBudgetReached

OUT = Path(__file__).resolve().parent
QUERIES = [
    'site:bilibili.com/video/ Streamlit text_input',
    'site:bilibili.com/video/ Streamlit input widgets',
    'site:bilibili.com/video/ Streamlit form',
    'site:bilibili.com/video/ Streamlit 输入控件',
    'site:bilibili.com/video/ Streamlit st.download_button',
    'site:bilibili.com/video/ Streamlit "download button"',
    'site:bilibili.com/video/ Streamlit 文件 导出',
    'site:bilibili.com/video/ Streamlit 上传下载',
]

async def main():
    provider = SerperProvider(Settings.from_env())
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'production_writes': 0,
              'logical_query_limit': 8, 'physical_search_limit': 8, 'search_requests': 0, 'queries': []}
    for query in QUERIES:
        used = 0
        async def count():
            nonlocal used
            if used >= 1 or report['search_requests'] >= 8:
                raise QueryBudgetReached()
            used += 1
            report['search_requests'] += 1
        row = {'query': query, 'status': 'completed'}
        with provider.query_scope(count):
            try:
                candidates = await provider.search(query, 'zh', 10, ['bilibili.com'])
            except SearchBudgetReached as error:
                candidates = error.partial_candidates
                row.update(status='partial', error_code='query_budget_exhausted')
            except SearchError as error:
                candidates = []
                row.update(status='failed', error_code=error.code)
        row['candidates'] = [c.model_dump() for c in candidates]
        row['provider_requests'] = deepcopy(provider.last_requests)
        report['queries'].append(row)
        denied = any(type(x.get('http_status')) is int and 400 <= x['http_status'] < 500 for x in row['provider_requests'])
        denied = denied or row.get('error_code') in {'captcha', 'access_denied', 'rate_limited', 'source_stopped'}
        report['aborted_on_source_stop'] = denied
        (OUT / 'searches.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'query': query, 'status': row['status'], 'physical_requests': used,
                         'source_stop': denied, 'candidates': [{'title': c.title, 'url': c.url, 'snippet': c.snippet} for c in candidates]}, ensure_ascii=False), flush=True)
        if denied:
            break
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    (OUT / 'searches.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


asyncio.run(main())

