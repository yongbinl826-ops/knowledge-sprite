import test from 'node:test';
import assert from 'node:assert/strict';
import { groupCoverageRows } from '../src/coverageDisplay.ts';

function row(id, text, supported = true, resource = 'r1', evidence = `ev-${id}`) {
  return { part: { id, text, status: supported ? 'supported' : 'unknown', resource_ids: supported ? [resource] : [], evidence_ids: supported ? [evidence] : [] },
    sources: supported ? [{ item: { resource: { resource_id: resource } }, ids: [evidence] }] : [] };
}
function display(rows) {
  const groups = groupCoverageRows(rows);
  return { groups, supported: groups.filter(group => group.sources.length), missing: groups.filter(group => !group.sources.length) };
}

test('exact title/confirmed duplicate counts once while all original IDs and evidence remain', () => {
  const rows = [row('subtopic_1', '状态对象'), row('subtopic_2', '阶段时长常量', false), row('learning_target_1', '状态对象'), row('learning_target_2', '常量与毫秒换算', false), row('learning_target_3', '渲染函数集中更新 DOM', false)];
  const before = structuredClone(rows);
  const result = display(rows);
  assert.equal(result.groups.length, 4);
  assert.deepEqual(result.supported.map(group => group.text), ['状态对象']);
  assert.deepEqual(result.missing.map(group => group.text), ['阶段时长常量', '常量与毫秒换算', '渲染函数集中更新 DOM']);
  assert.deepEqual(result.supported[0].memberIds, ['subtopic_1', 'learning_target_1']);
  assert.deepEqual(result.supported[0].sources[0].ids, ['ev-subtopic_1', 'ev-learning_target_1']);
  assert.equal(result.supported[0].sources.length, 1);
  assert.deepEqual(rows, before);
});

test('an unknown confirmed duplicate remains missing and cannot borrow a title video', () => {
  const result = display([row('subtopic_1', '状态对象'), row('learning_target_1', '状态对象', false)]);
  assert.equal(result.groups.length, 1);
  assert.equal(result.supported.length, 0);
  assert.deepEqual(result.missing[0].sources, []);
  assert.equal(result.missing[0].members.length, 2);
});

test('a source hidden by current filters keeps a duplicate group unknown despite aggregate status', () => {
  const target = row('learning_target_1', '状态对象'); target.sources = [];
  const result = display([row('subtopic_1', '状态对象'), target]);
  assert.equal(result.supported.length, 0);
  assert.equal(result.missing.length, 1);
});

test('explicit unknown duplicate status prevents a merged display promotion', () => {
  const target = row('learning_target_1', '状态对象'); target.part.status = 'unknown';
  assert.equal(display([row('subtopic_1', '状态对象'), target]).supported.length, 0);
});

test('different phrasing, whitespace, punctuation or case does not merge', () => {
  for (const text of ['状态 对象', ' 状态对象', '状态对象。', 'state object', '状态对象与常量']) {
    const result = display([row('subtopic_1', '状态对象'), row('learning_target_1', text, false)]);
    assert.equal(result.groups.length, 2);
    assert.equal(result.supported.length, 1);
  }
});

test('same-role exact text stays as independently identified requirements', () => {
  assert.equal(groupCoverageRows([row('subtopic_1', '状态对象'), row('subtopic_2', '状态对象')]).length, 2);
  assert.equal(groupCoverageRows([row('learning_target_1', '状态对象'), row('learning_target_2', '状态对象')]).length, 2);
});

test('independent sources are deduplicated without dropping any member or evidence ID', () => {
  const rows = [row('subtopic_1', '状态对象', true, 'r1'), row('learning_target_1', '状态对象', true, 'r2'), row('learning_target_2', '状态对象', true, 'r1')];
  const group = groupCoverageRows(rows)[0];
  assert.deepEqual(group.memberIds, rows.map(item => item.part.id));
  assert.equal(group.members.length, 3);
  assert.equal(group.sources.length, 2);
  assert.equal(group.sources[0].ids.length, 2);
});

test('unmerged rows preserve the existing source-validated decision rather than trust raw aggregate status', () => {
  const sourceValidated = row('subtopic_1', '读取文件'); sourceValidated.part.status = 'unknown';
  const result = display([sourceValidated]);
  assert.equal(result.supported.length, 1);
  assert.equal(result.groups[0].members[0], sourceValidated);
});
