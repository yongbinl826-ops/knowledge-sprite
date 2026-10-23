import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { relatedRecommendations, hasRelatedRecommendationPolicy, recommendationUrlKey } from '../src/relatedRecommendations.ts';

// Actual saved source metadata replay, not a fresh search or teaching verdict.
const replay = JSON.parse(readFileSync(new URL('./related-recommendations-actual.json', import.meta.url), 'utf8'));
function actual(name = 'pygame') {
  const point = structuredClone(replay.cases[name].points.find(point => point.references.length));
  return { knowledge_point_id: point.references[0].reference.knowledge_point_id, text: point.name,
    total_matches: 0, items: [], recommendation_policy: 'related-reference-v1', related_recommendations: point.references };
}
test('actual cached page/catalog and search-only references remain references without lending strict support', () => {
  for (const name of ['pygame', 'dashboard']) {
    const group = actual(name), before = structuredClone(group), rows = relatedRecommendations(group);
    assert.equal(rows.length, 3); assert.deepEqual(group, before); assert.equal(group.items.length, 0);
    assert.ok(rows.every(row => row.reference.exact_teaching_verified === false && row.accessibleReason.includes('精确讲授未验证')));
  }
  assert.ok(relatedRecommendations(actual('dashboard'))[0].reference.basis.includes('search'));
});
test('another point may have found the same source; current reference pid must still match its group', () => {
  const group = actual(); assert.notEqual(group.related_recommendations[0].evidence.at(-1).knowledge_point_id, group.knowledge_point_id);
  assert.equal(relatedRecommendations(group).length, 3);
  group.related_recommendations[0].reference.knowledge_point_id = 'foreign'; assert.equal(relatedRecommendations(group).length, 2);
});
test('missing evidence, conflicting explicit resource IDs and contradictory duplicate IDs are rejected', () => {
  for (const mutate of [row => row.reference.evidence_ids.push('absent'), row => row.evidence[0].resource_id = 'foreign', row => row.evidence.push({ ...row.evidence[0], text: 'foreign' })]) {
    const group = actual(); mutate(group.related_recommendations[0]); assert.equal(relatedRecommendations(group).length, 2);
  }
});
test('a policy reference cannot assert exact teaching or silently change policy/type', () => {
  for (const [key, value] of [['exact_teaching_verified', true], ['kind', 'supported'], ['policy', 'future-version'], ['technical_context', 'guessed']]) {
    const group = actual(); group.related_recommendations[0].reference[key] = value; assert.equal(relatedRecommendations(group).length, 2);
  }
});
test('unsafe links fail closed without changing retained source data', () => {
  for (const url of ['javascript:alert(1)', 'https://user:pass@www.bilibili.com/video/x', 'http://127.0.0.1/private']) {
    const group = actual(); group.related_recommendations[0].resource.url = url; assert.equal(relatedRecommendations(group).length, 2);
  }
});
test('canonical duplicates choose one reference and strict exclusions never hide another platform', () => {
  const group = actual(), duplicate = structuredClone(group.related_recommendations[0]);
  duplicate.resource.resource_id = 'same-url'; duplicate.reference.ranking_score += 1; group.related_recommendations.push(duplicate);
  assert.equal(relatedRecommendations(group).length, 3); assert.equal(relatedRecommendations(group)[0].resource.resource_id, 'same-url');
  const key = recommendationUrlKey(duplicate.resource);
  assert.equal(relatedRecommendations(group, 'all', new Set([key])).length, 2);
  group.related_platform_recommendations = { icourse163: [duplicate] };
  assert.deepEqual(relatedRecommendations(group, 'icourse163'), []);
});
test('parent-course context and missing own page remain explicit uncertainty, not rejected or upgraded', () => {
  const group = actual('dashboard'); group.related_recommendations[0].reference.technical_context = 'parent_course';
  const row = relatedRecommendations(group)[0]; assert.equal(row.reference.technical_context, 'parent_course');
  assert.ok(row.accessibleReason.includes('页面详情尚未读取')); assert.equal(row.reference.exact_teaching_verified, false);
});
test('empty or unknown new policy suppresses raw-discovery fallback; absent legacy policy stays compatible', () => {
  assert.equal(hasRelatedRecommendationPolicy({ recommendation_policy: 'future' }), true);
  assert.equal(hasRelatedRecommendationPolicy({ related_recommendations: [] }), true);
  assert.equal(hasRelatedRecommendationPolicy({ discovery_items: [] }), false);
  assert.deepEqual(relatedRecommendations({ knowledge_point_id: 'empty' }), []);
});
