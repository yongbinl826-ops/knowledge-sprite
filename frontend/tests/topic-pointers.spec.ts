import { expectGalleryTitlesOnly } from './coverTitleContract';
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import type { RelatedTopicPointer, ResourceItem, ResultGroup } from '../src/types';
import type { ProjectAnalysis, ProjectInput, ProjectView } from '../src/projectTypes';
import { courseImageUrl } from '../src/safeUrls';

// Explicit false demo mode retains a verified topic-only pointer; it is not teaching support.
// Offline actual retained catalog projection. All API is mocked; 0 live search,
// model, platform navigation or source instructional-quality acceptance.
const source = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/topic-pointer-actual-p26.json'), 'utf8')) as RelatedTopicPointer;
const out = resolve(process.cwd(), 'tests/evidence/topic-pointers');
const time = '2026-10-18T23:29:44Z';
const input: ProjectInput = { name: 'Arduino 调光器', requirements: '安全连接LED，通过电位器调光。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: 'Arduino', preferred_platforms: ['bilibili'] };
function fixture() {
  const entry = structuredClone(source);
  const analysis: ProjectAnalysis = { scope: input.requirements, technical_plan: 'Arduino', assumptions: [], functions: [{ id: 'f1', name: '控制亮度', original_requirement: input.requirements, acceptance_criteria: '两端及中间亮度正确', no_new_learning_reason: null }],
    knowledge_points: [{ id: 'k1', name: 'Arduino analogWrite PWM 调光', description: '用PWM控制LED', project_task: '使用analogWrite把自己的电位器读数转换为LED亮度', learning_goal: '能够调光', why_needed: '实现项目亮度变化', function_ids: ['f1'], learning_order: 1, prerequisite_ids: [], necessity: 'required', selection: 'learn', learning_skills: [entry.pointer.skill, '识别并选用支持 PWM 的数字引脚'], technology: 'Arduino', concepts: ['analogWrite取值0–255', '按板卡官方说明确认PWM引脚'], practice_check: '旋转电位器检查两端及中间亮度。' }] };
  const group: ResultGroup = { knowledge_point_id: entry.pointer.knowledge_point_id, text: analysis.knowledge_points[0].name, total_matches: 0, total_partial_matches: 0, items: [], partial_items: [], review_items: [],
    learning_coverage: { mode: 'transferable_skills', skills: analysis.knowledge_points[0].learning_skills!.map((text,index)=>({id:`skill_${index+1}`,text,content_resource_ids:[],title_resource_ids:[],evidence_ids:[]})), disclaimer: '章节线索不等于技能教学或项目实践完成。' }, related_topic_pointers: [entry] };
  return { entry, analysis, group };
}
type Fixture = ReturnType<typeof fixture>;
const diagnostics = new WeakMap<Page, { writes: string[]; external: string[]; runtime: string[]; console: string[] }>();
test.afterEach(async ({ page }, info) => {
  const log = diagnostics.get(page)!;
  await info.attach('pointer-isolated-diagnostics', { body: JSON.stringify(log,null,2), contentType: 'application/json' });
  expect(log.writes).toEqual([]); expect(log.external).toEqual([]); expect(log.runtime).toEqual([]); expect(log.console).toEqual([]);
});
async function setup(page: Page, f = fixture()) {
  const log = { writes: [] as string[], external: [] as string[], runtime: [] as string[], console: [] as string[] }; diagnostics.set(page, log);
  page.on('pageerror', error => log.runtime.push(error.message)); page.on('console', msg => { if (['error','warning'].includes(msg.type())) log.console.push(msg.text()); });
  const view: ProjectView = { project_id: 'pointer-project', input, current_version: 1, versions: [{ version: 1, status: 'partial', created_at: time }],
    version: { version: 1, status: 'partial', input, analysis: f.analysis, confirmation: { confirmed_at: time }, batches: [{ batch_id: 'batch1', job_id: 'job1', status: 'completed', project_knowledge_point_ids: ['k1'] }], error: null, created_at: time },
    points: [{ project_knowledge_point_id: 'k1', name: f.analysis.knowledge_points[0].name, selection: 'learn', status: 'partial', batch_id: 'batch1', job_id: 'job1', knowledge_point_id: f.group.knowledge_point_id, result: f.group }] };
  const origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5178').origin;
  await page.route('**/*', async route => {
    const request=route.request(), url=new URL(request.url());
    if(request.method()!=='GET'){log.writes.push(`${request.method()} ${url.href}`);return route.abort('blockedbyclient');}
    // This retained real fixture now renders a cover. Fulfil only its exact
    // recorded HTTPS image locally; never navigate/fetch the external source.
    if(request.resourceType()==='image'&&url.href===courseImageUrl(f.entry.resource.thumbnail_url)&&url.protocol==='https:')return route.fulfill({status:204,body:''});
    if(url.origin===origin && !url.pathname.startsWith('/api/')) return route.continue();
    if(url.origin===origin && url.pathname==='/api/projects/pointer-project/results') return route.fulfill({json:view});
    if(url.origin===origin && url.pathname==='/api/projects') return route.fulfill({json:{projects:[{project_id:'pointer-project',name:input.name,current_version:1,created_at:time,updated_at:time}]}});
    if(url.origin===origin && url.pathname==='/api/capabilities') return route.fulfill({json:{mode:'live',teaching_match_enabled:false,search:{status:'configured',message:'isolated',selected_provider:'fixture',providers:[]},llm:{status:'configured',message:'isolated'},fetch:{status:'available',message:'isolated',browser_fallback:false},platforms:[],limits:{max_knowledge_points:5,max_results_per_point:5,max_search_requests:30,max_detail_pages:40}}});
    log.external.push(url.href);return route.abort('blockedbyclient');
  });
  await page.emulateMedia({reducedMotion:'reduce'}); await page.goto('/?project=pointer-project&version=1');
  await expect(page).toHaveTitle('项目制学习引导小精灵 · 课程与视频发现');
  await expect(page.getByRole('region',{name:'视频封面',exact:true})).toBeVisible(); await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  return {f,log};
}
const gallery=(page:Page)=>page.getByRole('region',{name:'视频封面',exact:true});
async function noVisibleCopy(page:Page){await expectGalleryTitlesOnly(page);await expect(page.locator('.stage-content h1,.stage-content h2:not(.video-cover-title),.stage-content blockquote,.unit-coverage,.transferable-skills,.project-practice-axis')).toHaveCount(0);}
test('实际保存p26仅作为安全封面跳转，章节文案和覆盖结论不显示',async({page})=>{
 await setup(page);await expect(gallery(page).locator('a.course-cover')).toHaveCount(1);const link=gallery(page).locator('a.course-cover');await expect(link).toHaveAttribute('href','https://www.bilibili.com/video/BV164411J7GE/?p=26');await expect(link).toHaveAttribute('target','_blank');await expect(link).toHaveAttribute('rel','noopener noreferrer');await expect(link).toHaveAccessibleName(/在原平台打开/);await noVisibleCopy(page);
});
test('坏hash或错误原生part不能获得可点击封面入口',async({page})=>{
 const f=fixture();f.entry.pointer.source_text_sha256='0'.repeat(64);await setup(page,f);await expect(page.getByRole('status',{name:'这个知识点暂未找到视频'})).toBeVisible();await expect(gallery(page).locator('a.course-cover')).toHaveCount(0);
 f.entry.pointer.source_text_sha256=source.pointer.source_text_sha256;f.entry.pointer.target_url='https://www.bilibili.com/video/BV164411J7GE/?p=25';await page.reload();await expect(page.getByRole('status',{name:'这个知识点暂未找到视频'})).toBeVisible();await expect(gallery(page).locator('a.course-cover')).toHaveCount(0);await noVisibleCopy(page);
});
test('native B站证据整套改外部同页并重算hash，仍不能绕过来源绑定',async({page})=>{
 const f=fixture(),foreign='https://example.org/foreign-lesson';f.entry.resource.url=foreign;f.entry.resource.canonical_url=foreign;f.entry.resource.resolved_url=foreign;
 for(const origin of Object.values(f.entry.resource.field_provenance))if(origin&&typeof origin==='object'&&'url'in origin)origin.url=foreign;
 for(const e of f.entry.evidence)e.url=foreign;
 const record=f.entry.evidence.find(r=>r.evidence_id===f.entry.pointer.evidence_id)!,index=Number(record.field!.split('.')[1]),chapter=f.entry.resource.chapters[index] as any,facts=JSON.parse(record.text!);chapter.url=foreign;chapter.source_url=foreign;facts.url=foreign;facts.source_url=foreign;record.text=JSON.stringify(facts);f.entry.pointer.source_url=foreign;f.entry.pointer.target_url=foreign;f.entry.pointer.source_text_sha256=createHash('sha256').update(record.text!).digest('hex');
 await setup(page,f);await expect(page.getByRole('status',{name:'这个知识点暂未找到视频'})).toBeVisible();await expect(gallery(page).locator('a.course-cover')).toHaveCount(0);await noVisibleCopy(page);
});
for(const mutation of ['missing skills','wrong point','wrong skill','duplicate evidence'] as const)test(`封面线索仍拒绝${mutation}，不借别单元绑定`,async({page})=>{
 const f=fixture();if(mutation==='missing skills')delete f.analysis.knowledge_points[0].learning_skills;if(mutation==='wrong point')f.entry.pointer.knowledge_point_id='foreign-point';if(mutation==='wrong skill')f.entry.pointer.skill_id='skill_2';if(mutation==='duplicate evidence')f.entry.evidence.push(structuredClone(f.entry.evidence.find(e=>e.evidence_id===f.entry.pointer.evidence_id)!));
 await setup(page,f);await expect(page.getByRole('status',{name:'这个知识点暂未找到视频'})).toBeVisible();await expect(gallery(page).locator('a.course-cover')).toHaveCount(0);await noVisibleCopy(page);
});
test('标题与目录中的HTML不执行、不发图片请求；仅保留可访问名称',async({page})=>{
 const f=fixture(),malicious='<img src=https://example.org/evil onerror=alert(1)>';
 f.entry.resource.title=malicious;await setup(page,f);await noVisibleCopy(page);await expect(gallery(page).locator('script,iframe,video')).toHaveCount(0);await expect(gallery(page).locator('[onerror],img[src*="evil"]')).toHaveCount(0);
});
test('WebCrypto失败保守隐藏待核章节封面，不崩溃或伪造链接',async({page})=>{
 await page.addInitScript(()=>{Object.defineProperty(crypto.subtle,'digest',{value:()=>Promise.reject(new Error('offline digest unavailable'))});});await setup(page);await expect(page.getByRole('status',{name:'这个知识点暂未找到视频'})).toBeVisible();await expect(gallery(page).locator('a.course-cover')).toHaveCount(0);await noVisibleCopy(page);
});
