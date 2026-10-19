"""Offline candidate patch tests; retained-source recall is not model acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from backend.app import teaching_match as candidate
FIXTURE = json.loads(Path(__file__).with_name('fixtures').joinpath('arduino-taiji-own-parts.json').read_text(encoding='utf-8'))


def retained():
    return copy.deepcopy(FIXTURE)


def one_part(f, index=25):
    chapter = f['resource']['chapters'][index]
    row = next(e for e in f['evidence'] if e['evidence_id'] == chapter['evidence_id'])
    return chapter, row


def sync_row(chapter, row):
    raw = json.loads(row['text'])
    for key in ('title', 'url', 'source_url', 'page_number'):
        raw[key] = chapter.get(key)
    row['text'] = json.dumps(raw, ensure_ascii=False, sort_keys=True)


def test_retained_late_api_parts_now_model_visible_without_more_slots():
    f = retained()
    r, ev = f['resource'], f['evidence']
    for point_index, literal in [(1, 'analogRead'), (4, 'analogWrite')]:
        point = f['points'][point_index]
        new = candidate.prepare_pair(point, r, ev, 'beginner')
        assert new
        assert any(o['basis'] == 'catalog' and literal in o['text'] for o in new['observations'])
        assert len(new['observations']) <= candidate.MAX_OBSERVATIONS == 8
        assert sum(len(o['text']) for o in new['observations']) <= candidate.MAX_PAIR_CHARS == 6000
        assert FIXTURE['baseline_pair_fingerprints'][point['knowledge_point_id']] != new['fingerprint']
        assert new['_binding']['version'] != 'source-skill-v1'
        assert r == f['resource'] and ev == f['evidence']


@pytest.mark.parametrize('suffix', [
    '?p=0', '?p=-1', '?p=01', '?p=1.0', '?p=true', '?p=1000000000',
    '?p=26&foo=1', '?p=26&p=27', '?p=26#lesson', '?p=26&url=https://evil.example/',
    '?p=%32%36', '?p=+26', '?P=26', '#p=26', '?p=26;',
])
def test_reject_noncanonical_part_queries(suffix):
    f = retained(); c, e = one_part(f)
    c['url'] = f['resource']['canonical_url'] + suffix; sync_row(c, e)
    assert not candidate._own_catalog_target(f['resource']['canonical_url'], c, e)


@pytest.mark.parametrize('target', [
    'https://www.bilibili.com/video/BV1XK4y1a747/?p=26',
    'https://evil.example/video/BV164411J7GE/?p=26',
    'https://www.bilibili.com.evil.example/video/BV164411J7GE/?p=26',
    'https://www.bilibili.com@evil.example/video/BV164411J7GE/?p=26',
    'http://www.bilibili.com/video/BV164411J7GE/?p=26',
    'https://www.bilibili.com:443/video/BV164411J7GE/?p=26',
    'https://www.bilibili.com:444/video/BV164411J7GE/?p=26',
])
def test_reject_foreign_part_identity(target):
    f = retained(); c, e = one_part(f); c['url'] = target; sync_row(c, e)
    assert not candidate._own_catalog_target(f['resource']['canonical_url'], c, e)


@pytest.mark.parametrize('mutation', ['chapter_source', 'evidence_source', 'chapter_owner', 'evidence_owner', 'part_number', 'bool_number', 'raw_number', 'raw_owner'])
def test_reject_mixed_part_provenance(mutation):
    f = retained(); c, e = one_part(f); canonical = f['resource']['canonical_url']
    if mutation == 'chapter_source': c['source'] = 'search'
    elif mutation == 'evidence_source': e['source'] = 'search'
    elif mutation == 'chapter_owner': c['source_url'] = canonical + '#ignored'
    elif mutation == 'evidence_owner': e['url'] = canonical + '#ignored'
    elif mutation == 'part_number': c['page_number'] = 27
    elif mutation == 'bool_number': c['page_number'] = True
    elif mutation == 'raw_number': e['text'] = e['text'].replace('"page_number": 26', '"page_number": 27')
    elif mutation == 'raw_owner': e['text'] = e['text'].replace('"source_url": "'+canonical+'"', '"source_url": "https://evil.example/"')
    assert not candidate._own_catalog_target(canonical, c, e)


def test_full_prepare_duplicate_evidence_is_rejected():
    f = retained(); f['evidence'].append(copy.deepcopy(f['evidence'][0]))
    assert candidate.prepare_pair(f['points'][4], f['resource'], f['evidence']) is None


def test_full_prepare_corrupt_raw_catalog_is_not_exposed():
    f = retained(); c, e = one_part(f); e['text'] = e['text'].replace('analogWrite', 'analogRead')
    pair = candidate.prepare_pair(f['points'][4], f['resource'], f['evidence'])
    assert pair and not any(o['evidence_id'] == c['evidence_id'] for o in pair['observations'])


def test_other_platform_exact_rule_not_relaxed():
    canonical = 'https://www.example.com/course/'
    assert candidate._own_catalog_target(canonical, {'url': canonical}, {})
    assert not candidate._own_catalog_target(canonical, {'url': canonical+'?p=2'}, {})


def test_literal_catalog_slots_are_fair_and_do_not_select_unrelated_first():
    fixed = [('title', {}, 'Ordinary source title'), ('description', {}, 'Own description')]
    catalog = [('catalog', {'evidence_id': str(i)}, text) for i, text in enumerate(
        ['Unrelated introduction', 'AlphaAPI method one', 'AlphaAPI method two', 'BetaAPI method', 'AlphaAPI method three', 'BetaAPI method two', 'AlphaAPI method four', 'BetaAPI method three'])]
    ordered = candidate._catalog_observation_order(fixed+catalog, ['Tool AlphaAPI', 'Tool BetaAPI'], 'Tool')
    assert ordered[:2] == fixed
    assert 'BetaAPI' in ordered[3][2]
    assert all(item[2] != 'Unrelated introduction' for item in ordered[2:])
    assert len(ordered) == 8
    assert ordered == candidate._catalog_observation_order(fixed+catalog, ['Tool AlphaAPI', 'Tool BetaAPI'], 'Tool')


@pytest.mark.parametrize('heading', ['Prerequisites: analogWrite', 'Next lesson: analogWrite', 'This lesson does not teach analogWrite'])
def test_selected_negative_heading_keeps_context_and_cannot_be_support(heading):
    f = retained(); c, e = one_part(f); c['title'] = heading; sync_row(c, e)
    p = copy.deepcopy(f['points'][4]); p['learning_skills'] = ['Arduino analogWrite']
    pair = candidate.prepare_pair(p, f['resource'], f['evidence'])
    # Whole-scope or quote-local guard may reject; neither may donate support.
    if pair is None:
        return
    obs = next((o for o in pair['observations'] if o['evidence_id'] == c['evidence_id']), None)
    if obs is None:
        return
    assert heading in obs['text']
    decision = {'fingerprint': pair['fingerprint'], 'supports': [{'skill_id': 'skill_1', 'skill': p['learning_skills'][0], 'evidence_id': e['evidence_id'], 'quote': heading, 'basis': 'catalog', 'source_text_sha256': obs['source_text_sha256']}]}
    checked = candidate.validate_decision(p, f['resource'], f['evidence'], decision)
    assert checked is None or not checked['supports']


def test_plain_heading_never_automatically_proves_composite_skill():
    f = retained(); p = f['points'][1]
    pair = candidate.prepare_pair(p, f['resource'], f['evidence'])
    assert pair and any('analogRead' in o['text'] for o in pair['observations'])
    assert candidate.literal_decision(pair)['supports'] == []


def test_old_sealed_empty_is_not_reused_for_new_source_projection():
    f = retained(); p = f['points'][4]
    old_fingerprint = FIXTURE['baseline_pair_fingerprints'][p['knowledge_point_id']]
    assert candidate.validate_decision(p, f['resource'], f['evidence'], {'fingerprint': old_fingerprint, 'supports': []}) is None
