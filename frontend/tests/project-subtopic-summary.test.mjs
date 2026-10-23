import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { projectSubtopicSummary } from '../src/projectSubtopicSummary.ts';

// Retained source/ranking replay, not live HTTP or a synthetic teaching claim.
const views = JSON.parse(readFileSync(new URL('./fixtures/retained-r9-ui-projects.json', import.meta.url), 'utf8')).cases;
const original = views.browser_flashcards_intermediate.points.find(point => point.result).result;
const group = () => structuredClone(original);
const summary = value => Object.fromEntries(projectSubtopicSummary(value).map(row => [row.text, row.supported]));
const copies = value => [...value.partial_items, ...Object.values(value.partial_platform_items || {}).flat()];

test('retained native P24 supports JSON while read/write stays unknown; input is not mutated', () => {
  const value = group(), before = JSON.stringify(value);
  assert.deepEqual(summary(value), { '读写': false, 'JSON 序列化': true });
  assert.equal(JSON.stringify(value), before);
});
test('collection aggregate cannot supply a missing card or missing supporting ID', () => {
  const value = group();
  for (const item of copies(value)) item.match.supporting_evidence_ids = [];
  assert.deepEqual(projectSubtopicSummary(value), []);
});
test('same subtopic ID with different text cannot donate support', () => {
  const value = group();
  for (const item of copies(value)) item.match.subtopic_coverage.find(row => row.status === 'supported').text = 'other skill';
  assert.deepEqual(summary(value), { '读写': false, 'JSON 序列化': false });
});
test('an unknown aggregate target stays unknown even if another item field claims support', () => {
  const value = group();
  value.collection_coverage.subtopics.find(row => row.text === 'JSON 序列化').status = 'unknown';
  assert.deepEqual(summary(value), { '读写': false, 'JSON 序列化': false });
});
test('foreign resource or evidence IDs cannot supply displayed support', () => {
  for (const field of ['resource_ids', 'evidence_ids']) {
    const value = group(); value.collection_coverage.subtopics.find(row => row.text === 'JSON 序列化')[field] = ['unrelated'];
    assert.deepEqual(summary(value), { '读写': false, 'JSON 序列化': false });
  }
});
test('needs-review, foreign point and unsafe URL cannot count as a visible learning card', () => {
  for (const mutate of [item => { item.match.topic_evidence_status = 'needs_review'; }, item => { item.match.knowledge_point_id = 'foreign-point'; }, item => { item.resource.url = 'javascript:alert(1)'; }]) {
    const value = group(); for (const item of copies(value)) mutate(item);
    assert.deepEqual(projectSubtopicSummary(value), []);
  }
});
test('unparsed whole-topic and duplicate target IDs do not invent a displayed decomposition', () => {
  const ar = views.arduino_pot_button_beginner.points.find(point => point.result).result;
  assert.deepEqual(projectSubtopicSummary(ar), []);
  const value = group();value.collection_coverage.subtopics.push(structuredClone(value.collection_coverage.subtopics[0]));
  assert.deepEqual(projectSubtopicSummary(value), []);
});
