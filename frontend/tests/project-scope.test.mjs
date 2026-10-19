import test from 'node:test';
import assert from 'node:assert/strict';
import { hasProjectScopeMismatch, projectStatusNames } from '../src/projectTypes.ts';

test('explicit point scope mismatch is terminal and has a user-readable retry label', () => {
  assert.equal(hasProjectScopeMismatch({ status: 'scope_mismatch', result: null }), true);
  assert.equal(projectStatusNames.scope_mismatch, '检索范围需重试');
});
test('group mismatch marker also blocks stale results if the outer status is old', () => {
  assert.equal(hasProjectScopeMismatch({ status: 'partial', result: { scope_status: 'mismatch', items: [{ resource: { title: 'old Excel GROUPBY' } }] } }), true);
});
test('unmarked course titles or plain scope wording cannot invent a mismatch', () => {
  assert.equal(hasProjectScopeMismatch({ status: 'partial', result: { scope_notice: 'scope mismatch', expected_search_text: 'Streamlit', items: [{ resource: { title: 'Excel GROUPBY' } }] } }), false);
  assert.equal(hasProjectScopeMismatch({ status: 'partial', result: { scope_status: 'matched' } }), false);
});
test('missing results and unrelated lifecycle states keep existing handling', () => {
  assert.equal(hasProjectScopeMismatch(undefined), false);
  for (const status of ['pending', 'queued', 'submitted', 'running', 'partial', 'completed', 'failed', 'no_results']) assert.equal(hasProjectScopeMismatch({ status, result: null }), false);
});
test('scope display guard does not mutate stored identities, rows or coverage', () => {
  const point = { status: 'partial', result: { scope_status: 'mismatch', text: 'old raw scope', knowledge_point_id: 'same-job-point', items: [{ resource: { resource_id: 'old-resource' } }], collection_coverage: { status: 'all_subtopics_supported' } } };
  const before = structuredClone(point);
  assert.equal(hasProjectScopeMismatch(point), true);
  assert.deepEqual(point, before);
});
