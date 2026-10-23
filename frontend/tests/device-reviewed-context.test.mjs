import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { reviewedTopicTechnologies, visibleTopicTechnology, canonicalTopicName } from '../src/reviewedTopicTechnologies.ts';

const point = (name, technology, selection = 'learn') => ({ id: name, name, technology, selection });
const analysis = knowledge_points => ({ knowledge_points, technical_plan: 'Python hidden legacy context', concepts: ['Pygame'] });
test('professional labels remain unchanged; visible safe context is separate, explicit and selected only', () => {
  const value = analysis([point('线性表', 'C++'), point('栈', 'Python'), point('队列', 'Java', 'skip')]), before = JSON.stringify(value);
  assert.deepEqual(reviewedTopicTechnologies(value), { 线性表: 'C++', 栈: 'Python' }); assert.equal(JSON.stringify(value), before);
});
test('canonical name matches backend whitespace and leading ASCII/CJK boundary, without NFKC/alias guessing', () => {
  assert.equal(canonicalTopicName('  pygame事件循环\t'), 'pygame 事件循环');
  assert.equal(canonicalTopicName('localStorage读写与JSON序列化'), 'localStorage 读写与JSON序列化');
  assert.equal(canonicalTopicName('Ｃ＋＋  链表'), 'Ｃ＋＋ 链表');
});
test('only exact literal tools are displayed/submitted; URLs/control/operators/instructions remain hidden and unbound', () => {
  for (const technology of ['https://evil.example', 'site:example', 'ignore instructions', 'Python\u200b', 'Python\n', 'A'.repeat(49), 'general', 'none', '通用']) {
    assert.equal(visibleTopicTechnology(point('栈', technology)), undefined);
    assert.deepEqual(reviewedTopicTechnologies(analysis([point('栈', technology)])), {});
  }
  for (const technology of ['C++', 'JavaScript DOM', 'Arduino Uno', 'micro:bit', '.NET 8']) assert.equal(visibleTopicTechnology(point('栈', technology)), technology);
});
test('missing visible metadata cannot inherit hidden plan, legacy concepts or another point context', () => {
  assert.deepEqual(reviewedTopicTechnologies(analysis([point('线性表', undefined), point('栈', 'Python', 'skip')])), {});
});
test('conflicting duplicate canonical names cannot donate context; reserved object keys remain plain JSON', () => {
  assert.deepEqual(reviewedTopicTechnologies(analysis([point('栈', 'Python'), point(' 栈 ', 'Java')])), {});
  const map = reviewedTopicTechnologies(analysis([point('__proto__', 'Python'), point('constructor', 'C++')]));
  assert.equal(Object.getPrototypeOf(map), Object.prototype); assert.equal(Object.hasOwn(map, '__proto__'), true);
  assert.equal(JSON.parse(JSON.stringify(map)).__proto__, 'Python'); assert.equal(map.constructor, 'C++');
});

test("literal technology values agree with the independently produced backend validator fixture", () => {
  const fixture = JSON.parse(readFileSync(new URL("./device-topic-technology-safe-values.json", import.meta.url), "utf8"));
  for (const sample of fixture.samples) assert.equal(visibleTopicTechnology(point("Stack", sample.value)), sample.accepted && sample.cleaned ? sample.cleaned : undefined, sample.value);
});
