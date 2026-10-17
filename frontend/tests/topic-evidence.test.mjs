import test from 'node:test';
import assert from 'node:assert/strict';
import { collectionCoverageRows, supportedSubtopicIds, topicEvidenceIds, topicStatus, visibleGroupItems } from '../src/topicEvidence.ts';

// Deliberately small, isolated data. These assertions do not verify live teaching content.
function item(id, status = 'partial', platform = 'bilibili', kind = 'video') {
  return { resource: { resource_id: id, title: `isolated fixture ${id}`, platform, resource_type: kind, playback_verified: false },
    match: { topic_evidence_status: status, supporting_evidence_ids: [`ev-${id}`], subtopic_coverage: [
      { id, text: id, status: 'supported', evidence_ids: [`ev-${id}`], reason: 'isolated fixture' },
    ] }, evidence: [{ evidence_id: `ev-${id}`, kind: 'search', url: `https://example.org/${id}` }] };
}
function group() {
  const a = item('concurrency');
  const b = item('errors', 'partial', 'other', 'documentation');
  return { items: [], partial_items: [a, a, b], partial_platform_items: { bilibili: [a], other: [b] },
    collection_coverage: { decomposition_status: 'applied', shared_context: ['JavaScript', 'Promise'], status: 'all_subtopics_supported', single_resource_full_coverage: true,
      subtopics: [{ id: 'concurrency', text: 'concurrency' }, { id: 'errors', text: 'errors' }] } };
}
function coverageCount(g, platform = 'all', type = 'all', limit = 5) {
  const visible = visibleGroupItems(g, platform, type, limit);
  const rows = collectionCoverageRows(g.collection_coverage, visible);
  return { visible: visible.length, supported: rows.filter(row => row.sources.length).length, total: rows.length };
}

test('unknown status or missing support stays needs_review; playback false does not demote supported', () => {
  const row = item('direct', 'supported');
  assert.equal(topicStatus(row), 'supported');
  row.match.supporting_evidence_ids = ['missing'];
  assert.equal(topicStatus(row), 'needs_review');
  row.match.topic_evidence_status = undefined;
  assert.equal(topicStatus(row), 'needs_review');
  row.match.topic_evidence_status = 'unexpected_server_value';
  row.match.supporting_evidence_ids = ['ev-direct'];
  assert.equal(topicStatus(row), 'needs_review');
});

test('platform copies cannot promote a review item and retain the specific weak reason', () => {
  const weak = item('live-preview', 'needs_review');
  weak.match.topic_evidence_reasons = [{ message: 'appointment only', evidence_ids: ['ev-live-preview'] }];
  const falselyStrong = structuredClone(weak);
  falselyStrong.match.topic_evidence_status = 'supported';
  const g = { items: [falselyStrong], platform_items: { bilibili: [falselyStrong] }, review_items: [weak] };
  for (const platform of ['all', 'bilibili']) {
    const rows = visibleGroupItems(g, platform, 'all', 5);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].status, 'needs_review');
    assert.equal(rows[0].item.match.topic_evidence_reasons[0].message, 'appointment only');
  }
});

test('collection uses deduplicated visible resources after platform, type and per-section limit', () => {
  const g = group();
  assert.deepEqual(coverageCount(g), { visible: 2, supported: 2, total: 2 });
  assert.deepEqual(coverageCount(g, 'bilibili'), { visible: 1, supported: 1, total: 2 });
  assert.deepEqual(coverageCount(g, 'all', 'learning'), { visible: 1, supported: 1, total: 2 });
  assert.deepEqual(coverageCount(g, 'all', 'text'), { visible: 1, supported: 1, total: 2 });
  assert.deepEqual(coverageCount(g, 'all', 'all', 1), { visible: 1, supported: 1, total: 2 });
  assert.deepEqual(coverageCount(g, 'all', 'unknown'), { visible: 0, supported: 0, total: 2 });
});

test('subtopic evidence cannot be borrowed from another item or from a policy record', () => {
  const row = item('errors');
  row.match.subtopic_coverage[0].evidence_ids = ['ev-concurrency'];
  assert.deepEqual(supportedSubtopicIds(row, 'errors'), []);
  row.match.subtopic_coverage[0].evidence_ids = ['ev-errors'];
  row.evidence[0].kind = 'site_policy';
  assert.deepEqual(topicEvidenceIds(row, ['ev-errors']), []);
  assert.deepEqual(supportedSubtopicIds(row, 'errors'), []);
});

test('subtopic IDs also need to belong to this item supporting_evidence_ids', () => {
  const row = item('errors');
  row.evidence.push({ evidence_id: 'ev-other-topic', kind: 'search' });
  row.match.subtopic_coverage[0].evidence_ids = ['ev-other-topic'];
  assert.deepEqual(supportedSubtopicIds(row, 'errors'), []);
});

test('review resources never complete the collection even if their subtopic fields claim support', () => {
  const g = group();
  const b = g.partial_items[2];
  b.match.topic_evidence_status = 'needs_review';
  assert.deepEqual(coverageCount(g), { visible: 2, supported: 1, total: 2 });
});

test('a server aggregate never substitutes for absent per-item evidence or adds hidden resources', () => {
  const g = group();
  g.items = [];
  g.partial_items = [];
  assert.deepEqual(coverageCount(g), { visible: 0, supported: 0, total: 2 });
  const unparsed = { ...g.collection_coverage, decomposition_status: 'unknown' };
  assert.deepEqual(collectionCoverageRows(unparsed, []), []);
});
