import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { relatedRecommendations } from '../src/relatedRecommendations.ts';
import { hasEligibleReferenceLink, referenceLinkLabel } from '../src/relatedReferenceLink.ts';
import { hasVerifiedReferencePage } from '../src/verifiedVideoPage.ts';

const actual = JSON.parse(readFileSync(new URL('./fixtures/related-link-eligibility-actual.json', import.meta.url)));
const clone = value => structuredClone(value);
function proposal() {
  const row = clone(actual.search);
  row.reference.link_eligible = true; // Simulated new server projection, not a new semantic verdict.
  return row;
}
function admitted(row) {
  return relatedRecommendations({ knowledge_point_id: row.reference.knowledge_point_id,
    recommendation_policy: 'related-reference-v1', related_recommendations: [row] }).filter(hasEligibleReferenceLink);
}

test('source-linked search reference is visible without changing its status, teaching flag or URL', () => {
  const row = proposal(), before = clone(row), visible = admitted(row);
  assert.equal(visible.length, 1);
  assert.equal(visible[0].href, row.resource.url);
  assert.equal(hasVerifiedReferencePage(row), false);
  assert.equal(visible[0].reference.exact_teaching_verified, false);
  assert.equal(referenceLinkLabel(row), '搜索参考');
  assert.deepEqual(row, before);
});

test('legacy verified references remain visible; old search-only and weak wrong-topic rows do not acquire eligibility', () => {
  assert.equal(admitted(clone(actual.legacy_verified)).length, 1);
  assert.equal(admitted(clone(actual.search)).length, 0);
  assert.equal(admitted(clone(actual.legacy_wrong_topic)).length, 0);
  const rejected = clone(actual.legacy_verified); rejected.reference.link_eligible = false;
  assert.equal(admitted(rejected).length, 0);
});

for (const status of ['unsafe_url', 'not_found', 'error_page', 'unavailable', 'removed', 'deleted', 'access_denied', 'access_blocked', 'robots_blocked']) {
  test(`known ${status} cannot be rescued by an eligibility marker`, () => {
    const row = proposal(); row.resource.fetch_status = status;
    assert.equal(admitted(row).length, 0);
  });
}

for (const mutate of [
  row => row.resource.cache = { stale: true },
  row => row.evidence.forEach(e => e.cache = { stale: true }),
  row => row.reference.evidence_ids = ['absent'],
  row => row.evidence.forEach(e => e.source = ''),
  row => row.evidence.forEach(e => { e.title = ''; e.snippet = ''; e.text = ''; }),
  row => row.evidence.forEach(e => e.url = e.url.replace('BV14TYd6QEe6', 'BV1ypLX6wE5o')),
  row => row.evidence.forEach(e => { const url = new URL(e.url); url.searchParams.set('p', '2'); e.url = url.href; }),
  row => row.resource.canonical_url += '?p=2',
  row => row.resource.url = 'javascript:alert(1)',
  row => row.resource.url = row.resource.canonical_url = 'https://www.bilibili.com.attacker.example/video/BV14TYd6QEe6/',
  row => row.resource.url = row.resource.canonical_url = 'https://www.bilibili.com/read/cv1234',
  row => row.reference.technical_context = 'unconfirmed',
  row => row.reference.exact_teaching_verified = true,
]) {
  test(`malformed or unbound reference fails closed: ${mutate}`, () => {
    const row = proposal(); mutate(row); assert.equal(admitted(row).length, 0);
  });
}

test('known tracking and actually observed locale remain binding aliases, not generated destinations', () => {
  const row = proposal();
  for (const e of row.evidence) { const url = new URL(e.url); url.searchParams.set('uid', '123'); url.searchParams.set('utm_source', 'search'); e.url = url.href; }
  row.resource.resolved_url = row.resource.url.replace('/video/', '/zh-Hans/video/');
  assert.equal(admitted(row)[0].href, row.resource.url);
});

test('search catalog cannot fabricate a part URL even with eligible marker', () => {
  const row = proposal(); row.reference.basis.push('catalog');
  row.evidence.push({ evidence_id: 'synthetic-chapter', kind: 'catalog', field: 'chapters.0', source: 'test', url: row.resource.url,
    text: JSON.stringify({ title: 'Matched lesson', url: row.resource.url + '?p=7', source_url: row.resource.url }) });
  row.reference.evidence_ids.push('synthetic-chapter');
  assert.equal(admitted(row)[0].href, row.resource.url);
});

for (const query of ['?p=01', '?%70=2', '?p=1&p=2', '?x=1', '?p=2']) {
  test(`raw unsupported or different-part evidence cannot bind: ${query}`, () => {
    const row = proposal(); row.evidence.forEach(e => { const u = new URL(e.url); u.search = query; e.url = u.href; });
    assert.equal(admitted(row).length, 0);
  });
}

test('native course own-page reference needs no VideoObject or invented chapter target', () => {
  const row = proposal(), url = 'https://www.icourse163.org/course/PKU-1206307812';
  row.resource = { ...row.resource, url, canonical_url: url, platform: 'icourse163', resource_type: 'course', fetch_status: 'fetched', video_evidence_status: 'none' };
  row.reference.basis = ['catalog']; row.reference.evidence_ids = ['own-course'];
  row.evidence = [{ evidence_id: 'own-course', source: 'html.icourse163.course_structure', kind: 'catalog', url, field: 'chapters.0', text: 'Synthetic course fixture: tree traversal' }];
  assert.equal(admitted(row)[0].href, url); assert.equal(hasVerifiedReferencePage(row), false);
  assert.equal(referenceLinkLabel(row), '课程参考');
});

test('known login, payment and enrollment remain honest short labels without altering eligibility or page status', () => {
  const row = proposal(); Object.assign(row.resource, { requires_login: true, requires_payment: true, requires_enrollment: true, fetch_status: 'login_required' });
  assert.equal(admitted(row).length, 1);
  assert.equal(referenceLinkLabel(row), '搜索参考 · 需登录 · 需付费 · 需报名');
  assert.equal(hasVerifiedReferencePage(row), false);
});

const projectedCatalog = JSON.parse(readFileSync(new URL('./fixtures/related-projected-catalog-actual.json', import.meta.url))).row;
function projectedProposal() {
  const row = clone(projectedCatalog);
  row.reference.link_eligible = true; // New-marker control on actual producer output; no new verdict.
  return row;
}
function citedChapter(row) {
  return row.evidence.find(e => row.reference.evidence_ids.includes(e.evidence_id) && e.kind === 'catalog' && /^chapters\.\d+$/.test(e.field));
}

for (const value of [false, null, undefined, 0, 1, '', 'true', 'false', [], {}]) {
  test(`only an absent marker permits verified legacy fallback: ${JSON.stringify(value)}`, () => {
    const row = clone(actual.legacy_verified);
    assert.equal(hasVerifiedReferencePage(row), true);
    row.reference.link_eligible = value;
    assert.equal(admitted(row).length, 0);
  });
}

test('actual grounded producer chapter target accepts its own parent catalog without rewriting observed values', () => {
  const row = projectedProposal(), before = clone(row), chapter = JSON.parse(citedChapter(row).text);
  assert.equal(row.resource.url, 'https://www.bilibili.com/video/BV1HUKj6KE1i/?p=127');
  assert.equal(chapter.url, row.resource.url);
  assert.equal(chapter.source_url, 'https://www.bilibili.com/video/BV1HUKj6KE1i/');
  const visible = admitted(row);
  assert.equal(visible.length, 1);
  assert.equal(visible[0].href, chapter.url);
  assert.equal(visible[0].reference.exact_teaching_verified, false);
  assert.deepEqual(row, before);
});

test('actual projected target may retain only the exact catalog parent as resolved alias', () => {
  const row = projectedProposal(), parent = JSON.parse(citedChapter(row).text).source_url;
  row.resource.resolved_url = parent.replace('/video/', '/zh-Hans/video/');
  assert.equal(admitted(row)[0].href, row.resource.url);
});

for (const [name, mutate] of [
  ['other chapter target', (row,e,c) => { c.url = c.url.replace('p=127','p=126'); }],
  ['other BV target', (row,e,c) => { c.url = c.url.replace('BV1HUKj6KE1i','BV1BfpieUE3K'); }],
  ['unknown query', (row,e,c) => { c.url += '&chapter=1'; }],
  ['encoded part', (row,e,c) => { c.url = c.url.replace('?p=','?%70='); }],
  ['duplicate part', (row,e,c) => { c.url += '&p=127'; }],
  ['mismatched parent URL', (row,e,c) => { c.source_url += '?p=2'; }],
  ['borrow another part as parent', (row,e,c) => { e.url += '?p=2'; c.source_url = e.url; }],
  ['mismatched evidence URL', (row,e,c) => { e.url += '?p=3'; }],
  ['foreign host parent', (row,e,c) => { e.url=e.url.replace('www.bilibili.com','foreign.example.org'); c.source_url=e.url; }],
  ['mismatched page_number', (row,e,c) => { c.page_number=128; }],
  ['empty title', (row,e,c) => { c.title=' '; }],
  ['aggregate catalog', (row,e,c) => { e.field='chapters'; }],
  ['stale source', (row,e,c) => { e.cache={stale:true}; }],
  ['missing source', (row,e,c) => { e.source=''; }],
  ['uncited source', (row,e,c) => { row.reference.evidence_ids=row.reference.evidence_ids.filter(id=>id!==e.evidence_id); }],
  ['other resolved part', (row,e,c) => { row.resource.resolved_url=c.source_url+'?p=3'; }],
]) test(`projected chapter cannot borrow or fabricate identity: ${name}`, () => {
  const row=projectedProposal(), e=citedChapter(row), c=JSON.parse(e.text);
  mutate(row,e,c);e.text=JSON.stringify(c);
  assert.equal(admitted(row).length,0);
});
