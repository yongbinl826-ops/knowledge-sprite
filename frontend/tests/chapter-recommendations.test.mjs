import test from 'node:test';
import assert from 'node:assert/strict';
import { recommendChapters } from '../src/chapterRecommendations.ts';

// Local evidence fixtures test matching/binding, not live source or teaching claims.
function item(titles, courseTitle = 'Python语言基础与应用') {
  const chapters = titles.map((title, index) => ({ title, evidence_id: `chapter-${index}`, url: null, start_seconds: null, end_seconds: null, duration_seconds: null }));
  return { resource: { title: courseTitle, chapters }, match: { supporting_evidence_ids: [] }, evidence: chapters.map((chapter, index) => ({ evidence_id: chapter.evidence_id, kind: 'catalog', field: `chapters.${index}`, source: 'fixture', url: 'https://www.icourse163.org/course/PKU-1003479006', text: JSON.stringify(chapter) })) };
}

test('specific Python list point selects real list chapters, not any Python title', () => {
  const row = item(['Python简介', '2.1 Python列表的基本操作', '2.2 Python字典', '2.3 Python list slicing']);
  assert.deepEqual(recommendChapters(row, ['Python 列表']).map(chapter => chapter.title), ['2.1 Python列表的基本操作', '2.3 Python list slicing']);
  assert.equal(recommendChapters(row, ['Python 列表'])[0].ordinal, 2);
  assert.equal(recommendChapters(row, ['Python 列表'])[0].sourceUrl, row.evidence[1].url);
  assert.equal(recommendChapters(row, ['Python 列表'])[0].chapterUrl, undefined);
});

test('compound topic can point to separate list and dictionary locations', () => {
  assert.deepEqual(recommendChapters(item(['Python基础', 'Python列表', 'Python字典']), ['Python 列表与字典']).map(chapter => chapter.ordinal), [2, 3]);
  assert.deepEqual(recommendChapters(item(['Python基础', 'Python列表', 'Python字典']), ['Python 列表和字典']).map(chapter => chapter.ordinal), [2, 3]);
});

test('limited recommendations cover list and tuple before repeating list chapters', () => {
  // Titles observed in BV1S85VzgEwn; this isolated fixture tests selection only.
  const row = item(['序章', '01 Python基础数据类型 列表的简单介绍.mp4', '02 列表的索引与切片', '03 列表的增加', '04 列表的删除', '05 列表的修改', '06 列表的查询', '07 列表进阶操作 列表的嵌套', '08 Python基础数据类型 元组', '09 内置函数range的使用', '10 进阶提升篇 本节作业思路讲解']);
  assert.deepEqual(recommendChapters(row, ['Python 列表和元组']).map(chapter => chapter.ordinal), [2, 9]);
  assert.deepEqual(recommendChapters(row, ['Python 列表和元组'], 3).map(chapter => chapter.ordinal), [2, 9, 3]);
});

test('new subtopic coverage precedes repeated supporting IDs but does not invent absent coverage', () => {
  const row = item(['Python列表第一讲', 'Python列表第二讲', 'Python元组']);
  row.match.supporting_evidence_ids = ['chapter-0', 'chapter-1'];
  assert.deepEqual(recommendChapters(row, ['Python 列表和元组']).map(chapter => chapter.ordinal), [1, 3]);
  row.evidence[2].text = JSON.stringify({ title: 'forged tuple evidence' });
  assert.deepEqual(recommendChapters(row, ['Python 列表和元组']).map(chapter => chapter.ordinal), [1, 2]);
});

test('one chapter may cover several explicit title parts and duplicate aliases do not create new parts', () => {
  const row = item(['Python列表', 'Python元组', 'Python列表与元组']);
  assert.deepEqual(recommendChapters(row, ['Python 列表和元组'], 1).map(chapter => chapter.ordinal), [3]);
  assert.deepEqual(recommendChapters(row, ['Python 列表和元组', 'Python lists']).map(chapter => chapter.ordinal), [3, 1]);
});

test('narrow concept needs its modifier and cannot fall back to the generic language', () => {
  const row = item(['Python列表', 'Python列表推导式', '列表排序', 'Python字典']);
  assert.deepEqual(recommendChapters(row, ['Python 列表推导式']).map(chapter => chapter.ordinal), [2]);
  assert.deepEqual(recommendChapters(row, ['Python 列表排序']).map(chapter => chapter.ordinal), [3]);
  assert.deepEqual(recommendChapters(row, ['Python 网络爬虫']), []);
});

test('broad foundation point selects only introductory/foundation chapters', () => {
  assert.deepEqual(recommendChapters(item(['第一周 Python基础', '1.1 初识Python', '2.1 Python列表', '第三周 Python函数']), ['Python 语言基础']).map(chapter => chapter.ordinal), [1, 2]);
  assert.deepEqual(recommendChapters(item(['列表基础', '函数介绍', 'Python概述']), ['Python 语言基础']).map(chapter => chapter.ordinal), [3]);
  assert.deepEqual(recommendChapters(item(['Python基础', 'Python列表']), ['Python']).map(chapter => chapter.ordinal), [1]);
});

test('language foundation cannot borrow course language for another subjects introduction', () => {
  const row = item(['第1单元 人工智能概述 + Python语法基础', '理论课程：第一讲 人工智能概述'], '用Python学人工智能');
  assert.deepEqual(recommendChapters(row, ['Python语言基础']).map(chapter => chapter.ordinal), [1]);
});

test('explicit competing language is excluded and generic title requires course context', () => {
  assert.deepEqual(recommendChapters(item(['JavaScript list basics', '列表'], 'JavaScript基础'), ['Python 列表']), []);
  assert.deepEqual(recommendChapters(item(['JavaScript list basics', '列表']), ['Python 列表']).map(chapter => chapter.ordinal), [2]);
});

test('assessment and prerequisites are not presented as learning locations', () => {
  assert.deepEqual(recommendChapters(item(['Python列表测验', '列表作业', 'Python列表先修要求', 'Python列表']), ['Python 列表']).map(chapter => chapter.ordinal), [4]);
});

test('supporting IDs only break ties and never replace title matching', () => {
  const row = item(['Python函数', 'Python列表第一讲', 'Python列表第二讲']);
  row.match.supporting_evidence_ids = ['chapter-0', 'chapter-2'];
  assert.deepEqual(recommendChapters(row, ['Python列表']).map(chapter => chapter.ordinal), [3, 2]);
});

for (const [name, mutate] of [
  ['missing evidence', row => { row.evidence = []; }],
  ['forged evidence id', row => { row.resource.chapters[0].evidence_id = 'not-present'; }],
  ['wrong row field', row => { row.evidence[0].field = 'chapters.1'; }],
  ['noncatalog evidence', row => { row.evidence[0].kind = 'page'; }],
  ['changed chapter title', row => { row.resource.chapters[0].title = 'Python列表伪造标题'; }],
  ['invalid JSON text', row => { row.evidence[0].text = 'Python列表'; }],
  ['ambiguous duplicate id', row => { row.evidence.push({ ...row.evidence[0] }); }],
  ['unsafe source URL', row => { row.evidence[0].url = 'javascript:alert(1)'; }],
  ['credential-bearing source URL', row => { row.evidence[0].url = 'https://user:pass@example.org/course'; }],
  ['invalid chapter URL', row => { row.resource.chapters[0].url = 'javascript:alert(1)'; row.evidence[0].text = JSON.stringify(row.resource.chapters[0]); }],
  ['invalid time', row => { row.resource.chapters[0].start_seconds = -1; row.evidence[0].text = JSON.stringify(row.resource.chapters[0]); }],
  ['changed duration', row => { row.resource.chapters[0].duration_seconds = 300; }],
]) test(`rejects ${name}`, () => {
  const row = item(['Python列表']);
  mutate(row);
  assert.deepEqual(recommendChapters(row, ['Python 列表']), []);
});

test('a verified direct chapter link is preserved and no deep link is invented', () => {
  const row = item(['Python列表']);
  row.resource.chapters[0].url = 'https://example.org/lesson/list?start=10';
  row.evidence[0].text = JSON.stringify(row.resource.chapters[0]);
  assert.equal(recommendChapters(row, ['Python 列表'])[0].chapterUrl, row.resource.chapters[0].url);
});

test('verified Bilibili part number is preserved instead of being inferred from catalog position', () => {
  const row = item(['Python列表']);
  const chapterUrl = 'https://www.bilibili.com/video/BV_TEST_ONLY?p=35';
  row.resource.chapters[0].url = chapterUrl;
  row.evidence[0].url = 'https://www.bilibili.com/video/BV_TEST_ONLY';
  row.evidence[0].text = JSON.stringify(row.resource.chapters[0]);
  const recommendation = recommendChapters(row, ['Python 列表'])[0];
  assert.equal(recommendation.chapterUrl, chapterUrl);
  assert.equal(recommendation.ordinal, 1);
});

test('rejects a chapter part number changed after its evidence was recorded', () => {
  const row = item(['Python列表']);
  row.resource.chapters[0].url = 'https://www.bilibili.com/video/BV_TEST_ONLY?p=35';
  row.evidence[0].text = JSON.stringify(row.resource.chapters[0]);
  row.resource.chapters[0].url = 'https://www.bilibili.com/video/BV_TEST_ONLY?p=36';
  assert.deepEqual(recommendChapters(row, ['Python 列表']), []);
});

test('result limits are bounded and empty points produce no arbitrary suggestions', () => {
  const row = item(['Python列表1', 'Python列表2', 'Python列表3']);
  assert.equal(recommendChapters(row, ['Python 列表'], 1).length, 1);
  assert.equal(recommendChapters(row, ['Python 列表'], 0).length, 2);
  assert.deepEqual(recommendChapters(row, []), []);
});
