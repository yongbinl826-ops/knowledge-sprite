import test from 'node:test';
import assert from 'node:assert/strict';
import { recommendChapters } from '../src/chapterRecommendations.ts';

// Explicit offline fixtures. These are not real course acceptance results.
function fixture(titles) {
  const chapters = titles.map((title, index) => ({ title, evidence_id: `chapter-${index}`, url: null, start_seconds: null, end_seconds: null, duration_seconds: null }));
  return { resource: { title: 'Python 课程', chapters }, match: { topic_evidence_status: 'partial', supporting_evidence_ids: ['chapter-0'], subtopic_coverage: [
    { id: 'core', text: 'Python 基础语法', status: 'supported', evidence_ids: ['chapter-0'] },
    { id: 'run', text: '运行', status: 'unknown', evidence_ids: [] },
  ] }, evidence: chapters.map((chapter, index) => ({ evidence_id: chapter.evidence_id, kind: 'catalog', field: `chapters.${index}`, source: 'offline_fixture', url: 'https://example.org/course', text: JSON.stringify(chapter) })) };
}

test('partial core grammar cannot recommend an unproved generic run chapter', () => {
  const row = fixture(['Python 基础语法', '【爬虫篇】http与https的区别创建与运行']);
  assert.deepEqual(recommendChapters(row, ['Python 脚本基础语法与运行']).map(c => c.title), ['Python 基础语法']);
});

test('page-only partial support cannot nominate a matching but unsupported chapter', () => {
  const row = fixture(['Python 基础语法', 'Python 脚本运行']);
  row.match.supporting_evidence_ids = ['page'];
  row.match.subtopic_coverage[0].evidence_ids = ['page'];
  row.evidence.push({ evidence_id: 'page', kind: 'page', field: 'description', text: 'Python 基础语法' });
  assert.deepEqual(recommendChapters(row, ['Python 脚本基础语法与运行']), []);
});

test('partial chapter support must be shared by the supported part and overall match', () => {
  const row = fixture(['Python 基础语法', 'Python 脚本运行']);
  row.match.supporting_evidence_ids = ['chapter-1'];
  assert.deepEqual(recommendChapters(row, ['Python 脚本基础语法与运行']), []);
});

test('backend partial support never bypasses source field validation', () => {
  const row = fixture(['Python 基础语法']);
  row.evidence[0].text = JSON.stringify({ title: 'A different lesson' });
  assert.deepEqual(recommendChapters(row, ['Python 脚本基础语法与运行']), []);
});

test('a supported API lesson retains its real title instead of fabricating a semantic title', () => {
  const row = fixture(['Pandas DataFrame.isna 检测缺失值']);
  row.resource.title = 'Pandas 教程';
  row.match.subtopic_coverage = [{ id: 'missing', text: '缺失值检查', status: 'supported', evidence_ids: ['chapter-0'] }];
  assert.deepEqual(recommendChapters(row, ['pandas 数值类型转换与缺失值检查']).map(c => c.title), ['Pandas DataFrame.isna 检测缺失值']);
});

test('partial API fallback does not recommend assessment or prerequisite chapters', () => {
  for (const title of ['Python 列表测验', 'Python 列表作业', 'Python 列表前置要求']) {
    const row = fixture([title]);
    row.match.subtopic_coverage[0].text = 'Python 列表';
    assert.deepEqual(recommendChapters(row, ['Python 列表与元组']), []);
  }
});

test('partial API fallback cannot override an explicit programming language conflict', () => {
  const row = fixture(['Java 列表']);
  row.match.subtopic_coverage[0].text = '列表';
  assert.deepEqual(recommendChapters(row, ['Python 列表与元组']), []);
});
