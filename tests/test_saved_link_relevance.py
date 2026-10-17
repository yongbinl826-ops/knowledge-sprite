"""Regression evidence copied from the frozen live run; never makes HTTP calls.

These cases have now been used for development, not independent holdout scoring.
"""
import json
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.db import Store
from backend.app.models import SearchRequest
from backend.app.ranking import compound_english_match, rank_resource
from backend.app.service import JobService

ROWS=json.loads((Path(__file__).parent/'fixtures/link_relevance_saved_20261014.json').read_text(encoding='utf-8'))
WRONG={'res_4a5c8ba7ca1fd4bc531450d3','res_2a5b07262e65a3ef79f7e779','res_2c2d83de03dcd1df0f6e3d3f'}
NEAR={'res_5091435142e799ae427ba482','res_6b124ff45a37b184875ee36e'}
POSITIVE={'res_237b5f11b40a27a4e7893078','res_357cd724128c99855b7f7a83','res_3b4db78a241702697f29b865',
          'res_48a094d37c2af3b6ee6b064f','res_69fe33aba122bd7e2ac0035b','res_85913b0630a9396514eedce4',
          'res_1ff59f584387a5d9d59f27b1','res_87e5e47b6f0ae598d6c3eecf','res_47b624b6e3e0881cf1ae1e16','res_9790ac9d98a6c273ccdde7df',
          'res_7273464738a20d7d5a3292b8','res_fa78a19d2b6e64ad63fee816','res_d2a2a2ee5b10905b6aa3bc7d','res_1adfa84aece04ff59027aa48'}

@pytest.mark.parametrize('row',[r for r in ROWS if r['item']['resource']['resource_id'] in WRONG|NEAR|POSITIVE],ids=lambda r:r['item']['resource']['resource_id'])
def test_real_saved_topic_evidence(row):
    item=row['item']
    match=rank_resource(row['point'],item['resource'],item['evidence'],SearchRequest(**row['request']))
    assert bool(match)==(item['resource']['resource_id'] in POSITIVE)

def test_plural_equivalence_and_no_cross_observation_word_borrowing():
    assert compound_english_match('Python context managers',['Python context manager tutorial'])
    assert not compound_english_match('Python context managers',['Python distributed managers','Context for Java'])

def test_bounded_term_equivalence_keeps_context_and_specific_subtopic():
    audit=[]
    assert compound_english_match('SQL window functions ROW_NUMBER',['SQL窗口函数 row number 练习'],audit)
    assert audit==['sql_row_number_is_window_function']
    assert not compound_english_match('SQL window functions ROW_NUMBER',['ROW_NUMBER variable in Python'])
    assert not compound_english_match('SQL window functions RANK',['SQL ROW_NUMBER tutorial'])
    assert not compound_english_match('CSS Grid explicit tracks',['CSS Grid grid-template-columns tutorial'])
    assert not compound_english_match('CSS Grid explicit tracks',['CSS Grid explicit tutorial'])

def test_saved_wrong_matches_filtered_from_default_and_platform_views():
    row=next(r for r in ROWS if r['item']['resource']['resource_id'] in WRONG)
    store=Store(':memory:')
    svc=JobService(Settings(fetch_enabled=False),store)
    created=svc.create(SearchRequest(**row['request']))
    job=store.get_job(created['job_id']);point=job['knowledge_points'][0]
    item=row['item'];rid=item['resource']['resource_id']
    store.save_resource(job['job_id'],item['resource'])
    for e in item['evidence']:
        copied=dict(e,knowledge_point_id=point['knowledge_point_id'])
        store.add_evidence(job['job_id'],rid,point['knowledge_point_id'],copied)
    store.save_match(job['job_id'],dict(item['match'],knowledge_point_id=point['knowledge_point_id']))
    result=svc.results(job['job_id'])['groups'][0]
    assert result['items']==[] and result['platform_items']=={} and result['total_matches']==0
    assert store.matches(job['job_id']) # Read-time guard retains original history.
    store.close()
