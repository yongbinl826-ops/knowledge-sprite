import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { relatedRecommendations, verifiedReferenceChapterTarget } from '../src/relatedRecommendations.ts';

const actual = JSON.parse(readFileSync(new URL('./fixtures/streamlit-chapters-actual.json', import.meta.url), 'utf8'));
const root = actual.resource.url;
// Exact captured chapter facts; reference selection is an isolated policy wrapper.
function group(parts = [7, 8, 9]) {
  const row = { resource: structuredClone(actual.resource), evidence: structuredClone(actual.evidence), reference: {
    policy: 'related-reference-v1', kind: 'related_reference', knowledge_point_id: 'form', ranking_score: 60,
    reason: 'Catalog-reference UI control; exact teaching not asserted.', exact_teaching_verified: false,
    basis: ['catalog'], technical_context: 'observed',
    evidence_ids: actual.evidence.filter(e => parts.includes(JSON.parse(e.text).page_number)).map(e => e.evidence_id),
  } };
  return { knowledge_point_id: 'form', text: '表单输入', related_recommendations: [row] };
}
const target = value => relatedRecommendations(value)[0]?.href;

test('actual individually cited Streamlit chapters choose P7 for form and P6 for download, never uncited Flet P3', () => {
  assert.equal(target(group()), root + '?p=7');
  assert.equal(target(group([6])), root + '?p=6');
  const reversed = group(); reversed.related_recommendations[0].evidence.reverse();
  assert.equal(target(reversed), root + '?p=7');
});
test('an existing explicit part is preserved and choosing a target does not mutate source facts or canonical dedupe', () => {
  const value = group(); value.related_recommendations[0].resource.url = root + '?p=9';
  const before = structuredClone(value), rows = relatedRecommendations(value);
  assert.equal(rows[0].href, root + '?p=9'); assert.equal(rows[0].urlKey, root); assert.deepEqual(value, before);
});
test('only cited individual catalog evidence can change a root target', () => {
  for (const mutate of [row => { row.reference.basis = ['search']; }, row => { row.evidence.forEach(e => { e.kind = 'search'; }); },
    row => { row.evidence.forEach(e => { e.field = 'chapters'; }); }, row => { row.evidence.forEach(e => { e.text = 'model recommends ' + root + '?p=7'; }); },
    row => { row.evidence.forEach(e => { e.cache = { stale: true }; }); },
    row => { row.reference.evidence_ids = [row.evidence.find(e => JSON.parse(e.text).page_number === 1).evidence_id]; row.evidence.find(e => JSON.parse(e.text).page_number === 1).kind = 'page'; }]) {
    const value = group(); mutate(value.related_recommendations[0]); assert.equal(target(value), root);
  }
});
test('foreign BV, owner URL, unsafe/query targets and contradictory part metadata never redirect to a chapter', () => {
  const bad = ['https://www.bilibili.com/video/BV1hs4y137K7/?p=7', root + '?p=0', root + '?p=7&p=8', root + '?p=7&from=search',
    root + '?p=1000000', root + '?p=7#fragment', 'https://user:secret@www.bilibili.com/video/BV12T4m1S7a7/?p=7', 'javascript:alert(1)', 'https://www.bilibili.com/video/BV12T4m1S7a7/?p=2'];
  for (const url of bad) {
    const value = group([7]), row = value.related_recommendations[0], e = row.evidence.find(e => row.reference.evidence_ids.includes(e.evidence_id));
    e.text = JSON.stringify({ ...JSON.parse(e.text), url }); assert.equal(target(value), root);
  }
  for (const field of ['url', 'source_url']) {
    const value = group([7]), row = value.related_recommendations[0], e = row.evidence.find(e => row.reference.evidence_ids.includes(e.evidence_id));
    if (field === 'url') e.url = 'https://www.bilibili.com/video/BV1hs4y137K7/';
    else e.text = JSON.stringify({ ...JSON.parse(e.text), source_url: 'https://www.bilibili.com/video/BV1hs4y137K7/' });
    assert.equal(target(value), root);
  }
});
test('unverified, stale or paid resource facts cannot select a chapter, and foreign evidence IDs still fail closed', () => {
  for (const override of [{ fetch_status: 'not_fetched' }, { video_evidence_status: 'search_discovered' }, { cache: { stale: true } }, { requires_payment: true }]) {
    const value = group(); Object.assign(value.related_recommendations[0].resource, override); assert.equal(target(value), root);
  }
  const value = group(); value.related_recommendations[0].evidence[0].resource_id = 'foreign';
  value.related_recommendations[0].reference.evidence_ids.push(value.related_recommendations[0].evidence[0].evidence_id);
  assert.equal(target(value), undefined);
});
test('chapter evidence requires a named source and exact root-page ownership, never another part of the same BV', () => {
  for (const mutate of [e => { e.source = ''; }, e => { e.source = '  '; }, e => { delete e.source; },
    e => { e.url = root + '?p=2'; }, e => { e.url = root.replace('www.', ''); },
    e => { e.text = JSON.stringify({ ...JSON.parse(e.text), source_url: root + '?p=2' }); },
    e => { e.text = JSON.stringify({ ...JSON.parse(e.text), source_url: root.replace('www.', '') }); },
    e => { const chapter = JSON.parse(e.text); delete chapter.source_url; e.text = JSON.stringify(chapter); }]) {
    const value = group([7]), row = value.related_recommendations[0];
    mutate(row.evidence.find(e => row.reference.evidence_ids.includes(e.evidence_id)));
    assert.equal(target(value), root);
  }
});
test('either declared raw or canonical root is allowed, with no part or query borrowing', () => {
  const value = group([7]), row = value.related_recommendations[0];
  row.resource.url = root.replace('www.', '').replace(/\/$/, '');
  assert.equal(target(value), root + '?p=7');
  row.resource.canonical_url = root + '?p=2';
  assert.equal(target(value), row.resource.url);
});
test('a verified same-point primary duplicate reuses the cited part while explicit primary parts remain unchanged', () => {
  const value = group(), row = relatedRecommendations(value)[0], primary = { ...row.resource, url: root + '?uid=tracking' };
  assert.equal(verifiedReferenceChapterTarget(primary, row, value.knowledge_point_id), root + '?p=7');
  assert.equal(verifiedReferenceChapterTarget({ ...primary, url: root + '?p=9&uid=tracking' }, row, value.knowledge_point_id), undefined);
  assert.equal(verifiedReferenceChapterTarget(primary, row, 'another-point'), undefined);
  assert.equal(verifiedReferenceChapterTarget({ ...primary, url: 'https://www.bilibili.com/video/BV1hs4y137K7/' }, row, value.knowledge_point_id), undefined);
  for (const change of [{ requires_payment: true }, { cache: { stale: true } }, { video_evidence_status: 'search_discovered' }]) {
    assert.equal(verifiedReferenceChapterTarget({ ...primary, ...change }, row, value.knowledge_point_id), undefined);
  }
});
test('primary overrides cannot rely on a bare root reference or an uncited explicit part', () => {
  const value = group(), primary = structuredClone(value.related_recommendations[0].resource);
  value.related_recommendations[0].resource.url = root + '?p=6';
  assert.equal(verifiedReferenceChapterTarget(primary, relatedRecommendations(value)[0], value.knowledge_point_id), undefined);
  value.related_recommendations[0].resource.url = root;
  value.related_recommendations[0].reference.basis = ['page'];
  assert.equal(verifiedReferenceChapterTarget(primary, relatedRecommendations(value)[0], value.knowledge_point_id), undefined);
});
