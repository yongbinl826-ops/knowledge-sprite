// Captured actual page facts plus explicitly synthetic boundary mutations.
// Unit tests perform no network, model calls, or playback.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { relatedRecommendations, verifiedReferenceChapterTarget } from '../src/relatedRecommendations.ts';

const data = JSON.parse(readFileSync(new URL('./fixtures/related-explicit-part-actual.json', import.meta.url), 'utf8'));
const retained = data.group;
const original = retained.related_recommendations[0].resource.url;
const exact = 'https://www.bilibili.com/video/BV1fpgV6cEZw/?p=15';
const clone = () => structuredClone(retained);
const row = g => g.related_recommendations[0];
const target = g => relatedRecommendations(g).find(r => r.resource.resource_id === retained.related_recommendations[0].resource.resource_id)?.href;
const catalog = r => r.evidence.filter(e => e.kind === 'catalog');

test('an incidental discovery part uses its cited ChatPromptTemplate chapter from retained own-page evidence', () => {
  assert.equal(new URL(original).searchParams.get('p'), '2');
  assert.equal(target(clone()), exact);
});
test('a selected original part with its own matching catalog support remains exact', () => {
  const g = clone(), r = row(g), oldSource = r.resource.url;
  r.resource.url = r.resource.canonical_url = oldSource.replace('p=2', 'p=40');
  for (const e of catalog(r)) {
    e.url = r.resource.url;
    e.text = JSON.stringify({ ...JSON.parse(e.text), source_url: r.resource.url });
  }
  assert.equal(target(g), r.resource.url); // p15 exists, but p40 is already cited.
});
test('existing explicit primary cards retain their target independently of related references', () => {
  const g = clone(), r = row(g), ref = relatedRecommendations(g)[0];
  assert.equal(verifiedReferenceChapterTarget(r.resource, ref, g.knowledge_point_id), undefined);
});
for (const kind of ['page', 'search']) test(`${kind} support does not let a sibling catalog override an explicit link`, () => {
  const g = clone(); row(g).reference.basis.push(kind);
  assert.equal(target(g), original);
});
test('selection is independent of evidence order and does not mutate retained facts', () => {
  const g = clone(), saved = structuredClone(g); target(g); assert.deepEqual(g, saved);
  row(g).evidence.reverse(); assert.equal(target(g), exact);
});
for (const [name, mutate] of [
  ['aggregate catalog', e => { e.field = 'chapters'; }],
  ['uncited records', e => { e.evidence_id = 'not-cited-' + e.evidence_id; }],
  ['search text masquerading as chapter', e => { e.kind = 'search'; }],
  ['stale evidence', e => { e.cache = { stale: true }; }],
  ['missing provenance', e => { e.source = ''; }],
  ['unbound other source part', e => { e.url = e.url.replace('p=2', 'p=3'); }],
  ['unbound inner source part', e => { e.text = JSON.stringify({ ...JSON.parse(e.text), source_url: e.url.replace('p=2', 'p=3') }); }],
  ['foreign BV target', e => { e.text = JSON.stringify({ ...JSON.parse(e.text), url: 'https://www.bilibili.com/video/BV1M9ah6JEwZ/?p=15' }); }],
  ['paid chapter', e => { e.text = JSON.stringify({ ...JSON.parse(e.text), requires_payment: true }); }],
  ['mismatched part metadata', e => { e.text = JSON.stringify({ ...JSON.parse(e.text), page_number: 999 }); }],
  ['unsafe target', e => { e.text = JSON.stringify({ ...JSON.parse(e.text), url: 'javascript:alert(1)' }); }],
  ['ambiguous target query', e => { e.text = JSON.stringify({ ...JSON.parse(e.text), url: JSON.parse(e.text).url + '&p=90' }); }],
]) test(`${name} cannot supply a replacement target`, () => {
  const g = clone(); catalog(row(g)).forEach(mutate);
  assert.ok([original, undefined].includes(target(g)));
});
for (const [name, change] of [
  ['paid resource', { requires_payment: true }],
  ['unfetched resource', { fetch_status: 'not_fetched' }],
  ['stale resource', { cache: { stale: true } }],
]) test(`${name} cannot select a chapter`, () => {
  const g = clone(); Object.assign(row(g).resource, change); assert.equal(target(g), original);
});
