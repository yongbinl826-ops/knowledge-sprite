import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {contentEvidence} from '../src/contentEvidence.ts';
// Moved from retired coverage-UI checks: pure retained-source validation, no HTTP.
const files=['techwithtim-lesson-coverage.json','techwithtim-movement-coverage.json','techwithtim-snake-coverage.json','freecodecamp-course-coverage.json','freecodecamp-pandas-coverage.json'];
const sha=s=>createHash('sha256').update(s).digest('hex');
const load=f=>JSON.parse(readFileSync(new URL(`./fixtures/${f}`,import.meta.url))).item;
const proof=i=>i.evidence.find(e=>e.field==='video_evidence_status');
const body=i=>i.evidence.find(e=>e.field==='video_topic_summary');
const result=i=>contentEvidence(i,new Map([[i.resource.video_topic_summary,sha(i.resource.video_topic_summary||'')]]));
for(const file of files){
 test(`retained source binding remains valid without restoring coverage UI: ${file}`,()=>{
  const item=load(file);assert(result(item).some(e=>e.evidence_id===body(item).evidence_id));
 });
 test(`bound lesson cannot borrow title/meta/article/foreign proof: ${file}`,()=>{
  const mutations=[
   i=>{i.resource.field_provenance.video_evidence_status.evidence_id='missing';},
   i=>{body(i).url='https://example.org/foreign';},
   i=>{i.resource.title+=' altered';},
   i=>{body(i).text+=' adjacent article';},
   i=>{i.evidence.push(structuredClone(body(i)));},
   i=>{const p=JSON.parse(proof(i).text);p.video_id='aaaaaaaaaaa';proof(i).text=JSON.stringify(p);},
   i=>{i.resource.video_evidence_status='search_discovered';},
  ];
  for(const mutate of mutations){const item=load(file);mutate(item);assert.equal(result(item).length,0);}
 });
}
test('retained TWT DOM-v2 witnesses reject malformed or downgraded proof without legacy phrase fallback',()=>{
 const file='techwithtim-movement-coverage.json';
 for(const mutate of [p=>p.binding_version=3,p=>p.binding_version=true,p=>delete p.binding_version,p=>p.binding_kind='same_page',p=>delete p.dom_witness,p=>p.dom_witness={visible:true},p=>p.dom_witness.heading_text='foreign',p=>p.dom_witness.iframe_title='foreign',p=>p.dom_witness.notes_sha256='0'.repeat(64),p=>p.dom_witness.notes_characters++,p=>p.dom_witness.teaching_prose_count=1,p=>p.dom_witness.content_count=2,p=>p.dom_witness.visible='true',p=>p.teaching_binding='The video above offers more in-depth explanations.']){
  const item=load(file),p=JSON.parse(proof(item).text);mutate(p);proof(item).text=JSON.stringify(p);assert.equal(result(item).length,0);
 }
});
