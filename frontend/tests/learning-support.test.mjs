import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { learningEvidenceTexts, legacyLearningClues, parseLearningSkills, skillLearningRows, transferableSkills } from '../src/learningEvidence.ts';

// Isolated source-binding tests, not live course discovery or teaching-quality acceptance.
const sha = text => createHash('sha256').update(text).digest('hex');
function setup(basis = 'description') {
  const url = 'https://example.org/lesson/dates', title = '解析日期时间的方法';
  const description = '本课讲解解析日期时间的方法，也演示识别缺失值。';
  const chapter = { title: '解析日期时间', url, start_seconds: 0, end_seconds: 180, duration_seconds: 180, evidence_id: 'ev-source' };
  const text = basis === 'title' ? title : basis === 'catalog' ? JSON.stringify({ title: chapter.title, url, start_seconds: 0, end_seconds: 180, duration_seconds: 180 }) : description;
  const field = basis === 'title' ? 'title' : basis === 'catalog' ? 'chapters.0' : 'description';
  const source = `fixture.${basis}`;
  const record = { evidence_id: 'ev-source', kind: basis === 'catalog' ? 'catalog' : 'page', field, source, url, text };
  const titleId = basis === 'title' ? 'ev-source' : 'ev-title';
  const item = { resource: { resource_id: 'r1', title, url, canonical_url: url, resource_type: 'video', video_evidence_status: 'page_verified',
    fetch_status: 'fetched', metadata_evidence_level: basis === 'catalog' ? 'catalog' : 'page', description, chapters: basis === 'catalog' ? [chapter] : [], field_provenance: {
      title: { evidence_id: titleId, source: basis === 'title' ? source : 'fixture.title', url },
      description: { evidence_id: 'ev-source', source, url }, video_evidence_status: { evidence_id: 'ev-video', source: 'fixture.video', url },
    } },
    match: { resource_id: 'r1', knowledge_point_id: 'point-1', supporting_evidence_ids: ['ev-source'], topic_evidence_status: 'partial',
      teaching_support: [{ skill_id: 'skill_1', skill: '解析日期时间', evidence_id: 'ev-source', quote: '解析日期时间', basis, source_text_sha256: sha(text) }] },
    evidence: [record, { evidence_id: 'ev-video', kind: 'page', field: 'video_evidence_status', source: 'fixture.video', url, text: 'Same-page observed video identity, no playback verification' },
      ...(basis === 'title' ? [] : [{ evidence_id: 'ev-title', kind: 'page', field: 'title', source: 'fixture.title', url, text: title }])] };
  const planned = { learning_skills: ['解析日期时间', '识别缺失值'], concepts: ['errors参数', 'end < start', '相等时间边界'], project_task: '清洗自己的CSV', practice_check: '相等时间仍有效' };
  const group = { knowledge_point_id: 'point-1', learning_coverage: { mode: 'transferable_skills', skills: [
    { id: 'skill_1', text: '解析日期时间', content_resource_ids: basis === 'title' ? [] : ['r1'], title_resource_ids: basis === 'title' ? ['r1'] : [], evidence_ids: ['ev-source'] },
    { id: 'skill_2', text: '识别缺失值', content_resource_ids: [], title_resource_ids: [], evidence_ids: [] }], disclaimer: '隔离测试，练习未完成' } };
  const rows = [{ status: 'partial', item }], digests = new Map(learningEvidenceTexts(rows).map(text => [text, sha(text)]));
  return { planned, group, item, rows, digests, text };
}
const display = fixture => skillLearningRows(fixture.planned, fixture.group, fixture.rows, fixture.digests);

test('transferable skills have their own rows; project parameters/checks are unchanged and never enter the skill denominator', () => {
  const f = setup(), before = structuredClone(f.planned), rows = display(f);
  assert.equal(rows.length, 2); assert.equal(rows[0].content.length, 1); assert.equal(rows[1].content.length, 0);
  assert.equal(rows.some(row => row.text.includes('end < start')), false); assert.deepEqual(f.planned, before);
});
test('own title is visibly distinct from body support and cannot fill exact project parameters', () => {
  const f = setup('title'), rows = display(f);
  assert.equal(rows[0].content.length, 0); assert.equal(rows[0].titles.length, 1); assert.equal(rows[1].titles.length, 0);
  assert.equal(rows[0].titles[0].basis, 'title'); assert.deepEqual(f.planned.concepts, ['errors参数', 'end < start', '相等时间边界']);
});
test('catalog uses the entire original JSON hash and must match its own retained chapter fields', () => {
  const f = setup('catalog'); assert.equal(display(f)[0].content.length, 1);
  f.item.resource.chapters[0].title = '其他课程章节'; assert.equal(display(f)[0].content.length, 0);
});
test('hash must cover full evidence text, not just the quote', () => {
  const f = setup(); f.item.match.teaching_support[0].source_text_sha256 = sha('解析日期时间');
  assert.equal(display(f)[0].content.length, 0);
});
test('a quote not present verbatim is rejected even with a matching record hash', () => {
  const f = setup(); f.item.match.teaching_support[0].quote = '会讲errors参数与本项目';
  assert.equal(display(f)[0].content.length, 0);
});
test('skill ID, planned text, aggregate text, match resource and point IDs must all agree', () => {
  for (const mutate of [f => f.item.match.teaching_support[0].skill = '其他技能', f => f.item.match.teaching_support[0].skill_id = 'skill_2',
    f => f.group.learning_coverage.skills[0].text = '其他技能', f => f.item.match.resource_id = 'foreign', f => f.item.match.knowledge_point_id = 'foreign']) {
    const f = setup(); mutate(f); assert.equal(display(f)[0].content.length, 0);
  }
});
test('duplicate aggregate IDs or evidence IDs do not lend support', () => {
  const f = setup(); f.group.learning_coverage.skills.push(structuredClone(f.group.learning_coverage.skills[0]));
  assert.equal(display(f)[0].content.length, 0);
  const g = setup(); g.item.evidence.push(structuredClone(g.item.evidence[0])); assert.equal(display(g)[0].content.length, 0);
});
test('wrong aggregate resource lane or absent evidence reference cannot promote a title to content', () => {
  const f = setup('title'); f.group.learning_coverage.skills[0].content_resource_ids = ['r1']; f.group.learning_coverage.skills[0].title_resource_ids = [];
  assert.equal(display(f)[0].content.length, 0); assert.equal(display(f)[0].titles.length, 0);
  const g = setup(); g.group.learning_coverage.skills[0].evidence_ids = []; assert.equal(display(g)[0].content.length, 0);
});
test('search titles, snippets and a foreign page cannot become teaching evidence', () => {
  for (const mutate of [f => f.item.evidence[0].kind = 'search', f => f.item.evidence[0].source = 'search.title',
    f => f.item.evidence[0].url = 'https://example.org/other-course', f => f.item.resource.field_provenance.description.url = 'https://example.org/other-course']) {
    const f = setup(); mutate(f); assert.equal(display(f)[0].content.length, 0);
  }
});
test('visible current resources only: hidden platform rows and review-only material never count', () => {
  const f = setup(); f.rows = []; assert.equal(display(f)[0].content.length, 0);
  const g = setup(); g.rows[0].status = 'needs_review'; assert.equal(display(g)[0].content.length, 0);
});
test('page-verified flag alone without own retained video identity is insufficient', () => {
  const f = setup(); f.item.evidence = f.item.evidence.filter(row => row.evidence_id !== 'ev-video'); assert.equal(display(f)[0].content.length, 0);
  const g = setup(); g.item.resource.video_evidence_status = 'search_discovered'; assert.equal(display(g)[0].content.length, 0);
});
test('no WebCrypto digest or a changed source text stays unknown without throwing', () => {
  const f = setup(); f.digests = new Map(); assert.equal(display(f)[0].content.length, 0);
  const g = setup(); g.item.evidence[0].text += ' altered'; assert.equal(display(g)[0].content.length, 0);
});
test('historical missing/empty skill lists never invent skills from concepts or aggregate claims', () => {
  const f = setup(); delete f.planned.learning_skills; assert.deepEqual(display(f), []);
  assert.deepEqual(transferableSkills({ learning_skills: [] }), []);
});
test('legacy API core is an own-title clue only; search-level CSV clues cannot be silently upgraded', () => {
  const f = setup('title'); f.item.match.subtopic_coverage = [{ id: 'api_operation_core_1', text: 'API 使用核心（参数未确认）', status: 'supported', evidence_ids: ['ev-source'] }];
  assert.equal(legacyLearningClues(f.group, f.rows).length, 1);
  f.item.evidence[0].kind = 'search'; assert.equal(legacyLearningClues(f.group, f.rows).length, 0);
});
test('skill editing trims blank lines and enforces6items/120Unicode code points/unique text', () => {
  assert.deepEqual(parseLearningSkills(' 解析日期时间 \n\n识别缺失值\n'), { skills: ['解析日期时间', '识别缺失值'], error: null });
  assert(parseLearningSkills(Array.from({ length: 7 }, (_, i) => `技能${i}`).join('\n')).error);
  assert(parseLearningSkills('字'.repeat(121)).error); assert(parseLearningSkills('技能\n技能').error);
  assert.equal(parseLearningSkills('😀'.repeat(120)).error, null);
});
for (const file of ['techwithtim-lesson-coverage.json', 'freecodecamp-course-coverage.json']) {
  test(`lesson_notes reuses strict real retained source binding: ${file}`, () => {
    // Annotation is isolated API-shape data. It tests proof compatibility, not
    // a new ranking or live instructional-quality assertion.
    const fixture = JSON.parse(readFileSync(new URL(`./fixtures/${file}`, import.meta.url))), item = fixture.item;
    const record = item.evidence.find(row => row.field === 'video_topic_summary');
    const skill = fixture.point_text;
    item.match.knowledge_point_id = 'point-1'; item.match.resource_id = item.resource.resource_id;
    item.match.teaching_support = [{ skill_id: 'skill_1', skill, evidence_id: record.evidence_id, quote: record.text.slice(0, 100), basis: 'lesson_notes', source_text_sha256: sha(record.text) }];
    const planned = { learning_skills: [skill] }, group = { knowledge_point_id: 'point-1', learning_coverage: { mode: 'transferable_skills', skills: [{ id: 'skill_1', text: skill, content_resource_ids: [item.resource.resource_id], title_resource_ids: [], evidence_ids: [record.evidence_id] }] } };
    const rows = [{ status: 'partial', item }], digests = new Map(learningEvidenceTexts(rows).map(text => [text, sha(text)]));
    assert.equal(skillLearningRows(planned, group, rows, digests)[0].content.length, 1);
    item.resource.field_provenance.video_evidence_status.evidence_id = 'missing-proof';
    assert.equal(skillLearningRows(planned, group, rows, digests)[0].content.length, 0);
  });
}
