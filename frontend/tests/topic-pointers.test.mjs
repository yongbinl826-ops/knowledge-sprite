import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { relatedTopicPointers, topicPointerEvidenceTexts } from '../src/topicPointers.ts';
import { skillLearningRows } from '../src/learningEvidence.ts';
import { visibleGroupItems } from '../src/topicEvidence.ts';

// Retained actual r3 catalog, projected offline by backend producer. No new
// search or instructional semantic support is created by these tests.
const original = JSON.parse(readFileSync(new URL('./fixtures/topic-pointer-actual-p26.json', import.meta.url), 'utf8'));
const sha = text => createHash('sha256').update(text).digest('hex');
function fixture() {
  const entry = structuredClone(original);
  const planned = { learning_skills: [entry.pointer.skill], concepts: ['analogWrite 0–255'], project_task: '实现自己的调光器', practice_check: '检查两端与中间值' };
  const group = { knowledge_point_id: entry.pointer.knowledge_point_id, text: 'Arduino analogWrite PWM 调光', items: [], partial_items: [], review_items: [], total_matches: 0,
    learning_coverage: { mode: 'transferable_skills', skills: [{ id: entry.pointer.skill_id, text: entry.pointer.skill, content_resource_ids: [], title_resource_ids: [], evidence_ids: [] }], disclaimer: '教学未确认，实践待完成' }, related_topic_pointers: [entry] };
  return { entry, planned, group, digests: new Map(topicPointerEvidenceTexts(group).map(text => [text, sha(text)])) };
}
const display = (f, platform = 'all') => relatedTopicPointers(f.planned, f.group, platform, f.digests);
test('actual original chapter p26 is a zero-coverage topic pointer, never a supported skill or recommendation', () => {
  const f = fixture(), before = structuredClone(f), rows = display(f);
  assert.equal(rows.length, 1); assert.equal(rows[0].pointer.quote, '1-25 模拟输出1 - analogWrite');
  assert.equal(rows[0].targetUrl, 'https://www.bilibili.com/video/BV164411J7GE/?p=26');
  assert.deepEqual(rows[0].pointer.missing_components, ['占空比控制输出']);
  const learning = skillLearningRows(f.planned, f.group, [], f.digests);
  assert.equal(learning.length, 1); assert.deepEqual(learning[0].content, []); assert.deepEqual(learning[0].titles, []);
  assert.equal(visibleGroupItems(f.group, 'all', 'learning', 5).length, 0); assert.deepEqual(f, before);
});
const bad = {
  'wrong point ID': f => { f.entry.pointer.knowledge_point_id = 'foreign'; },
  'wrong resource ID': f => { f.entry.pointer.resource_id = 'foreign'; },
  'wrong skill ID': f => { f.entry.pointer.skill_id = 'skill_2'; },
  'borrowed skill text': f => { f.entry.pointer.skill += '及PWM引脚识别'; },
  'historical absent skills': f => { delete f.planned.learning_skills; },
  'search/source snippet': f => { f.entry.evidence.find(row=>row.evidence_id===f.entry.pointer.evidence_id).source = 'search.snippet'; },
  'wrong source URL': f => { f.entry.pointer.source_url = 'https://www.bilibili.com/video/BV1YW411x7rp/'; },
  'wrong BV destination': f => { f.entry.pointer.target_url = 'https://www.bilibili.com/video/BV1YW411x7rp/?p=26'; },
  'unobserved part from title': f => { f.entry.pointer.target_url = 'https://www.bilibili.com/video/BV164411J7GE/?p=25'; },
  'foreign same-site destination': f => { f.entry.pointer.target_url = 'https://www.bilibili.com/'; },
  'redirect extra query': f => { f.entry.pointer.target_url += '&redirect=https://example.org'; },
  'unobserved target fragment': f => { f.entry.pointer.target_url += '#unobserved'; },
  'different resource BV borrowing canonical': f => { f.entry.resource.url='https://www.bilibili.com/video/BV1YW411x7rp/'; },
  'private destination': f => { f.entry.pointer.target_url = 'http://127.0.0.1/'; },
  'hash of only quote': f => { f.entry.pointer.source_text_sha256 = sha(f.entry.pointer.quote); },
  'no digest': f => { f.digests = new Map(); },
  'changed quote': f => { f.entry.pointer.quote += '占空比控制输出'; },
  'substring instead of original title': f => { f.entry.pointer.quote = 'analogWrite'; },
  'description basis': f => { f.entry.pointer.basis = 'description'; },
  'support scope': f => { f.entry.pointer.scope = 'supported'; },
  'no unknown components': f => { f.entry.pointer.missing_components = []; },
  'duplicate evidence ID': f => { f.entry.evidence.push(structuredClone(f.entry.evidence[0])); },
  'lost own title proof': f => { const id=f.entry.resource.field_provenance.title.evidence_id; f.entry.evidence=f.entry.evidence.filter(row=>row.evidence_id!==id); },
  'search-only media identity': f => { f.entry.resource.video_evidence_status = 'search_discovered'; },
  'course type without video identity': f => { f.entry.resource.resource_type='course'; f.entry.resource.video_evidence_status='none'; },
  'lost own media proof': f => { const id=f.entry.resource.field_provenance.video_evidence_status.evidence_id; f.entry.evidence=f.entry.evidence.filter(row=>row.evidence_id!==id); },
  'native source removed': f => { const index=Number(f.entry.evidence.find(row=>row.evidence_id===f.entry.pointer.evidence_id).field.split('.')[1]); delete f.entry.resource.chapters[index].source; },
  'native part number altered': f => { const index=Number(f.entry.evidence.find(row=>row.evidence_id===f.entry.pointer.evidence_id).field.split('.')[1]); f.entry.resource.chapters[index].page_number=25; },
  'native raw proof altered even after rehash': f => { const record=f.entry.evidence.find(row=>row.evidence_id===f.entry.pointer.evidence_id); const facts=JSON.parse(record.text); facts.page_number=25; record.text=JSON.stringify(facts); f.entry.pointer.source_text_sha256=sha(record.text); f.digests.set(record.text,sha(record.text)); },
  'scope-mismatched historical result': f => { f.group.scope_status='mismatch'; },
};
for(const [name, mutate] of Object.entries(bad)) test(`rejects ${name} without lending any coverage`,()=>{ const f=fixture(); mutate(f); assert.deepEqual(display(f),[]); });
test('platform filtering and duplicate pointers never expose a hidden source or inflate pointers/cards',()=>{
  const f=fixture(); assert.equal(display(f,'bilibili').length,1); assert.deepEqual(display(f,'other'),[]);
  f.group.related_topic_pointers.push(structuredClone(f.entry)); assert.equal(display(f).length,1);
  assert.equal(visibleGroupItems(f.group,'all','learning',5).length,0);
});
test('empty/missing pointer lane leaves the original skills and project practice untouched',()=>{
  const f=fixture(), planned=structuredClone(f.planned); delete f.group.related_topic_pointers;
  assert.deepEqual(display(f),[]); assert.deepEqual(topicPointerEvidenceTexts(f.group),[]); assert.deepEqual(f.planned,planned);
});
test('native Bili catalog source cannot use a fully rewritten foreign canonical/same-page destination even after rehash',()=>{
  const f=fixture(),foreign='https://example.org/foreign-lesson';
  f.entry.resource.url=foreign;f.entry.resource.canonical_url=foreign;f.entry.resource.resolved_url=foreign;
  for(const origin of Object.values(f.entry.resource.field_provenance))if(origin&&typeof origin==='object'&&'url'in origin)origin.url=foreign;
  for(const record of f.entry.evidence)record.url=foreign;
  const record=f.entry.evidence.find(row=>row.evidence_id===f.entry.pointer.evidence_id),index=Number(record.field.split('.')[1]);
  const chapter=f.entry.resource.chapters[index],facts=JSON.parse(record.text);
  chapter.url=foreign;chapter.source_url=foreign;facts.url=foreign;facts.source_url=foreign;
  record.text=JSON.stringify(facts);f.entry.pointer.source_url=foreign;f.entry.pointer.target_url=foreign;f.entry.pointer.source_text_sha256=sha(record.text);f.digests.set(record.text,sha(record.text));
  assert.deepEqual(display(f),[]);
});
