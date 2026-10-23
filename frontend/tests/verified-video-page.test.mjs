import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { isVerifiedVideoPage, hasVerifiedReferencePage } from '../src/verifiedVideoPage.ts';

test('page eligibility rejects discovery-only, stale and paid entries without claiming playback', () => {
  const page = { fetch_status: 'fetched', video_evidence_status: 'page_verified', playback_verified: false };
  assert.equal(isVerifiedVideoPage(page), true);
  for (const override of [{ fetch_status: 'not_fetched' }, { fetch_status: 'dns_error' },
    { video_evidence_status: 'search_discovered' }, { cache: { stale: true } }, { requires_payment: true }]) {
    assert.equal(isVerifiedVideoPage({ ...page, ...override }), false);
  }
  assert.equal(isVerifiedVideoPage({}), false);
});

test('reference cards require their selected evidence to include a fresh own-page observation', () => {
  const row = { resource: { fetch_status: 'fetched', video_evidence_status: 'page_verified' },
    reference: { basis: ['page'], evidence_ids: ['own'] },
    evidence: [{ evidence_id: 'own', kind: 'page', cache: { stale: false } }] };
  assert.equal(hasVerifiedReferencePage(row), true);
  assert.equal(hasVerifiedReferencePage({ ...row, reference: { ...row.reference, basis: ['search'] } }), false);
  assert.equal(hasVerifiedReferencePage({ ...row, reference: { ...row.reference, evidence_ids: ['missing'] } }), false);
  assert.equal(hasVerifiedReferencePage({ ...row, evidence: [{ ...row.evidence[0], cache: { stale: true } }] }), false);
});

test('actual final project replay excludes unverified download cards and preserves five evidenced points', () => {
  const result = JSON.parse(readFileSync(new URL('./fixtures/verified-video-actual.json', import.meta.url), 'utf8'));
  const groups = result.points.filter(point => point.result).map(point => point.result);
  const download = groups.find(group => group.text === '文件下载');
  assert.ok(download.related_recommendations.some(row => row.resource.title.includes('DLSS')));
  assert.equal(download.related_recommendations.filter(hasVerifiedReferencePage).length, 0);
  assert.equal(groups.filter(group => (group.related_recommendations || []).some(hasVerifiedReferencePage)).length, 5);
});
