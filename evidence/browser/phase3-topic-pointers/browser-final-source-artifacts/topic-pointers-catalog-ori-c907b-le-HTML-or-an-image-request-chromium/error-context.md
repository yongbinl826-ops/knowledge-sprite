# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: topic-pointers.spec.ts >> catalog original text is React-escaped, never executable HTML or an image request
- Location: tests\topic-pointers.spec.ts:86:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('.related-topic-pointers')
Expected: visible
Timeout: 7000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" locator('.related-topic-pointers') with timeout 7000ms
  - waiting for locator('.related-topic-pointers')

```

```yaml
- link "跳转到主要内容":
  - /url: "#stage-title"
- banner:
  - text: 项目制知识引导小精灵
  - navigation "项目学习流程":
    - button "01 项目描述"
    - button "02 选择知识点"
    - button "03 推荐视频"
  - button "我的项目"
- main:
  - complementary:
    - paragraph: 03 / CURATED LEARNING
    - heading "让知识， 走进你的项目。" [level=1]
    - paragraph: Arduino 调光器 从相关的视频与章节开始。
    - button "← 调整知识点"
    - navigation "已选知识点":
      - paragraph: 已选知识点
      - button "全部" [pressed]
      - button "Arduino analogWrite PWM 调光"
  - paragraph: Arduino 调光器 · v1 · 部分完成
  - region "项目课程结果 · v1":
    - heading "项目课程结果 · v1" [level=2]: 推荐视频
    - paragraph: 从一个学习单元开始，将学到的内容用在项目里。
    - text: 部分完成
    - group: 查看检索进度与预算
    - heading "控制亮度" [level=3]
    - heading "Arduino analogWrite PWM 调光" [level=4]
    - text: 部分完成 · 0 条推荐
    - complementary "Arduino analogWrite PWM 调光的学习路线":
      - heading "从学会技能，到完成项目" [level=5]
      - status: 教学范围待核对
      - paragraph:
        - strong: 必要先修
        - text: 无额外先修，可从这里开始
      - region "先学这些技能":
        - heading "先学这些技能" [level=6]
        - paragraph: 学习可迁移的方法；教程不必使用同款项目。
        - list:
          - listitem:
            - strong: Arduino analogWrite 占空比控制输出
            - text: 待补充材料
            - paragraph: 当前材料还没有可确认的本课教学依据。
          - listitem:
            - strong: 识别并选用支持 PWM 的数字引脚
            - text: 待补充材料
            - paragraph: 当前材料还没有可确认的本课教学依据。
      - region "带回项目练习":
        - heading "带回项目练习" [level=6]
        - text: 待自己实践
        - paragraph: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
        - strong: 项目子任务
        - paragraph: 使用analogWrite把自己的电位器读数转换为LED亮度
        - strong: 参数与应用检查
        - list:
          - listitem: analogWrite取值0–255
          - listitem: 按板卡官方说明确认PWM引脚
        - strong: 试做后这样检查
        - paragraph: 旋转电位器检查两端及中间亮度。
      - strong: 下一步
      - paragraph: 尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。
      - paragraph: 章节线索不等于技能教学或项目实践完成。
      - group: 原项目要求来源核对 旧口径明细
    - paragraph: 本次检索部分完成，暂无达到技能教学推荐标准的课程。
    - link "到 B站搜索这个单元 （平台搜索入口，非已推荐视频，在新窗口打开）":
      - /url: https://search.bilibili.com/all?keyword=Arduino+analogWrite+PWM+%E8%B0%83%E5%85%89
    - paragraph: 章节信息来自实际检索证据。课程可能需要登录、选课或付费，以原平台为准。
    - button "重新检索这些知识点"
    - paragraph: 重新检索会创建新版本，上次结果保留；受相同预算与限流约束。
- contentinfo: 让学习，发生在项目里。 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  1   | import { test, expect, type Page } from '@playwright/test';
  2   | import { readFileSync } from 'node:fs';
  3   | import { createHash } from 'node:crypto';
  4   | import { mkdir, writeFile } from 'node:fs/promises';
  5   | import { resolve } from 'node:path';
  6   | import type { RelatedTopicPointer, ResourceItem, ResultGroup } from '../src/types';
  7   | import type { ProjectAnalysis, ProjectInput, ProjectView } from '../src/projectTypes';
  8   | 
  9   | // Offline actual retained catalog projection. All API is mocked; 0 live search,
  10  | // model, platform navigation or source instructional-quality acceptance.
  11  | const source = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/topic-pointer-actual-p26.json'), 'utf8')) as RelatedTopicPointer;
  12  | const out = resolve(process.cwd(), 'tests/evidence/topic-pointers');
  13  | const time = '2026-10-18T23:29:44Z';
  14  | const input: ProjectInput = { name: 'Arduino 调光器', requirements: '安全连接LED，通过电位器调光。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: 'Arduino', preferred_platforms: ['bilibili'] };
  15  | function fixture() {
  16  |   const entry = structuredClone(source);
  17  |   const analysis: ProjectAnalysis = { scope: input.requirements, technical_plan: 'Arduino', assumptions: [], functions: [{ id: 'f1', name: '控制亮度', original_requirement: input.requirements, acceptance_criteria: '两端及中间亮度正确', no_new_learning_reason: null }],
  18  |     knowledge_points: [{ id: 'k1', name: 'Arduino analogWrite PWM 调光', description: '用PWM控制LED', project_task: '使用analogWrite把自己的电位器读数转换为LED亮度', learning_goal: '能够调光', why_needed: '实现项目亮度变化', function_ids: ['f1'], learning_order: 1, prerequisite_ids: [], necessity: 'required', selection: 'learn', learning_skills: [entry.pointer.skill, '识别并选用支持 PWM 的数字引脚'], technology: 'Arduino', concepts: ['analogWrite取值0–255', '按板卡官方说明确认PWM引脚'], practice_check: '旋转电位器检查两端及中间亮度。' }] };
  19  |   const group: ResultGroup = { knowledge_point_id: entry.pointer.knowledge_point_id, text: analysis.knowledge_points[0].name, total_matches: 0, total_partial_matches: 0, items: [], partial_items: [], review_items: [],
  20  |     learning_coverage: { mode: 'transferable_skills', skills: analysis.knowledge_points[0].learning_skills!.map((text,index)=>({id:`skill_${index+1}`,text,content_resource_ids:[],title_resource_ids:[],evidence_ids:[]})), disclaimer: '章节线索不等于技能教学或项目实践完成。' }, related_topic_pointers: [entry] };
  21  |   return { entry, analysis, group };
  22  | }
  23  | type Fixture = ReturnType<typeof fixture>;
  24  | const diagnostics = new WeakMap<Page, { writes: string[]; external: string[]; runtime: string[]; console: string[] }>();
  25  | test.afterEach(async ({ page }, info) => {
  26  |   const log = diagnostics.get(page)!;
  27  |   await info.attach('pointer-isolated-diagnostics', { body: JSON.stringify(log,null,2), contentType: 'application/json' });
  28  |   expect(log.writes).toEqual([]); expect(log.external).toEqual([]); expect(log.runtime).toEqual([]); expect(log.console).toEqual([]);
  29  | });
  30  | async function setup(page: Page, f = fixture()) {
  31  |   const log = { writes: [] as string[], external: [] as string[], runtime: [] as string[], console: [] as string[] }; diagnostics.set(page, log);
  32  |   page.on('pageerror', error => log.runtime.push(error.message)); page.on('console', msg => { if (['error','warning'].includes(msg.type())) log.console.push(msg.text()); });
  33  |   const view: ProjectView = { project_id: 'pointer-project', input, current_version: 1, versions: [{ version: 1, status: 'partial', created_at: time }],
  34  |     version: { version: 1, status: 'partial', input, analysis: f.analysis, confirmation: { confirmed_at: time }, batches: [{ batch_id: 'batch1', job_id: 'job1', status: 'completed', project_knowledge_point_ids: ['k1'] }], error: null, created_at: time },
  35  |     points: [{ project_knowledge_point_id: 'k1', name: f.analysis.knowledge_points[0].name, selection: 'learn', status: 'partial', batch_id: 'batch1', job_id: 'job1', knowledge_point_id: f.group.knowledge_point_id, result: f.group }] };
  36  |   const origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5178').origin;
  37  |   await page.route('**/*', async route => {
  38  |     const request=route.request(), url=new URL(request.url());
  39  |     if(request.method()!=='GET'){log.writes.push(`${request.method()} ${url.href}`);return route.abort('blockedbyclient');}
  40  |     if(url.origin===origin && !url.pathname.startsWith('/api/')) return route.continue();
  41  |     if(url.origin===origin && url.pathname==='/api/projects/pointer-project/results') return route.fulfill({json:view});
  42  |     if(url.origin===origin && url.pathname==='/api/projects') return route.fulfill({json:{projects:[{project_id:'pointer-project',name:input.name,current_version:1,created_at:time,updated_at:time}]}});
  43  |     if(url.origin===origin && url.pathname==='/api/capabilities') return route.fulfill({json:{mode:'live',search:{status:'configured',message:'isolated',selected_provider:'fixture',providers:[]},llm:{status:'configured',message:'isolated'},fetch:{status:'available',message:'isolated',browser_fallback:false},platforms:[],limits:{max_knowledge_points:5,max_results_per_point:5,max_search_requests:30,max_detail_pages:40}}});
  44  |     log.external.push(url.href);return route.abort('blockedbyclient');
  45  |   });
  46  |   await page.emulateMedia({reducedMotion:'reduce'}); await page.goto('/?project=pointer-project&version=1');
  47  |   await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
  48  |   await expect(page.getByRole('heading',{name:'项目课程结果 · v1'})).toBeVisible(); await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  49  |   return {f,log};
  50  | }
  51  | const panel=(page:Page)=>page.locator('.project-result-point');
  52  | const fold=(page:Page)=>page.locator('.related-topic-pointers');
  53  | async function allUnknown(page:Page) {
  54  |   await expect(panel(page).locator('.transferable-skills>li')).toHaveCount(2);
  55  |   await expect(panel(page).locator('.transferable-skills>li[data-skill-state="unknown"]')).toHaveCount(2);
  56  |   await expect(panel(page).locator('.project-practice-axis')).toContainText('待自己实践');
  57  |   await expect(panel(page).locator('.project-practice-axis')).toContainText('analogWrite取值0–255');
  58  | }
  59  | test('zero main recommendations: actual catalog pointer starts open with original p26 link, while0recommendations/2unknownskills stay unchanged',async({page})=>{
  60  |   await setup(page);await expect(fold(page)).toBeVisible();await expect(fold(page)).toHaveAttribute('open','');
  61  |   await expect(panel(page).locator('.group-heading')).toContainText('0 条推荐');await expect(panel(page).locator('.course-card')).toHaveCount(0);await allUnknown(page);
  62  |   await fold(page).locator('summary').focus();await page.keyboard.press('Enter');await expect(fold(page)).not.toHaveAttribute('open','');
  63  |   await page.keyboard.press('Enter');await expect(fold(page)).toHaveAttribute('open','');
  64  |   await expect(fold(page)).toContainText('相关课题线索 · 尚未证实讲授完整技能');await expect(fold(page)).toContainText('Arduino analogWrite 占空比控制输出');
  65  |   await expect(fold(page).locator('blockquote')).toHaveText('1-25 模拟输出1 - analogWrite');await expect(fold(page).locator('.topic-pointer-missing')).toContainText('占空比控制输出');
  66  |   const link=fold(page).getByRole('link',{name:/到平台核对这节课/});await expect(link).toHaveAttribute('href','https://www.bilibili.com/video/BV164411J7GE/?p=26');await expect(link).toHaveAttribute('target','_blank');await expect(link).toHaveAttribute('rel','noopener noreferrer');
  67  |   await page.keyboard.press('Tab');await expect(link).toBeFocused();await allUnknown(page);
  68  |   await expect(panel(page).locator('.learning-route-next')).toContainText('主要推荐');await expect(panel(page).locator('.group-empty')).toContainText('暂无达到技能教学推荐标准');
  69  | });
  70  | test('platform filter hides pointer source without borrowing topic support from other visible materials',async({page})=>{
  71  |   const f=fixture();
  72  |   const item=(id:string,platform:string):ResourceItem=>({resource:{...structuredClone(f.entry.resource),resource_id:id,platform,thumbnail_url:null,chapters:[]},evidence:[],match:{knowledge_point_id:f.group.knowledge_point_id,resource_id:id,ranking_score:1,recommendation_reason:'隔离的部分匹配材料；教学范围待核实。',matched_evidence_ids:[],coverage_basis:[],topic_evidence_status:'partial'}});
  73  |   const a=item('other-main','other'),b=item('bili-main','bilibili');f.group.partial_items=[a,b];f.group.partial_platform_items={other:[a],bilibili:[b]};
  74  |   await setup(page,f);await expect(fold(page)).toBeVisible();await expect(fold(page)).not.toHaveAttribute('open','');await allUnknown(page);
  75  |   await page.getByLabel('项目课程来源').selectOption('other');await expect(fold(page)).toHaveCount(0);await allUnknown(page);
  76  |   await page.getByLabel('项目课程来源').selectOption('bilibili');await expect(fold(page)).toBeVisible();await allUnknown(page);
  77  | });
  78  | test('bad hash or wrong actual part is absent, not an unknown-source clickable lead',async({page})=>{
  79  |   const f=fixture();f.entry.pointer.source_text_sha256='0'.repeat(64);await setup(page,f);await expect(fold(page)).toHaveCount(0);await allUnknown(page);
  80  |   f.entry.pointer.source_text_sha256=source.pointer.source_text_sha256;f.entry.pointer.target_url='https://www.bilibili.com/video/BV164411J7GE/?p=25';await page.reload();await expect(fold(page)).toHaveCount(0);await allUnknown(page);
  81  | });
  82  | test('missing pointer lane and historical absent skills cannot invent goals or display source hints',async({page})=>{
  83  |   const f=fixture();delete f.analysis.knowledge_points[0].learning_skills;await setup(page,f);await expect(fold(page)).toHaveCount(0);
  84  |   await expect(panel(page).locator('.transferable-skills')).toHaveCount(0);await expect(panel(page)).toContainText('此版本尚未区分可迁移技能');
  85  | });
  86  | test('catalog original text is React-escaped, never executable HTML or an image request',async({page})=>{
  87  |   const f=fixture(), record=f.entry.evidence.find(row=>row.evidence_id===f.entry.pointer.evidence_id)!;
  88  |   const chapter=f.entry.resource.chapters[Number(record.field!.split('.')[1])];
  89  |   const malicious='<img src="https://example.org/evil" onerror="alert(1)">';
  90  |   const facts=JSON.parse(record.text!);facts.title=malicious;chapter.title=malicious;
  91  |   record.text=JSON.stringify(facts);f.entry.pointer.quote=malicious;f.entry.pointer.source_text_sha256=createHash('sha256').update(record.text!).digest('hex');
> 92  |   await setup(page,f);await expect(fold(page)).toBeVisible();await expect(fold(page).locator('blockquote')).toHaveText(malicious);
      |                                                ^ Error: expect(locator).toBeVisible() failed
  93  |   await expect(fold(page).locator('img,script,iframe')).toHaveCount(0);await allUnknown(page);
  94  | });
  95  | test('three widths and reduce motion: folded/expanded pointer long source stays readable and keyboard reachable',async({page})=>{
  96  |   await setup(page);await mkdir(out,{recursive:true});const observations=[];
  97  |   for(const size of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
  98  |     await page.setViewportSize(size);await fold(page).evaluate(node=>(node as HTMLDetailsElement).open=false);await fold(page).scrollIntoViewIfNeeded();
  99  |     await page.screenshot({path:resolve(out,`${size.name}-folded.png`),animations:'disabled'});
  100 |     await fold(page).locator('summary').focus();await page.keyboard.press('Enter');await expect(fold(page)).toHaveAttribute('open','');
  101 |     await fold(page).screenshot({path:resolve(out,`${size.name}-expanded.png`),animations:'disabled'});await allUnknown(page);
  102 |     const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);expect(overflow).toBe(false);
  103 |     // Screen-reader text is intentionally clipped to1px; visible text remains
  104 |     // subject to the full interior-overflow check.
  105 |     const inner=await fold(page).evaluate(node=>[...node.querySelectorAll('*')].filter(el=>!el.classList.contains('sr-only')&&el.clientWidth>0&&el.scrollWidth>el.clientWidth+1).map(el=>el.tagName));expect(inner).toEqual([]);
  106 |     const motions=await fold(page).evaluate(node=>({animation:getComputedStyle(node).animationName,transition:getComputedStyle(node).transitionDuration}));expect(motions).toEqual({animation:'none',transition:'0s'});
  107 |     await page.keyboard.press('Tab');await expect(fold(page).getByRole('link')).toBeFocused();observations.push({size,overflow,inner,motions});
  108 |   }
  109 |   await writeFile(resolve(out,'three-width-observations.json'),JSON.stringify({mock:true,actualRetainedCatalog:true,noSourceSemanticAcceptance:true,observations},null,2));
  110 | });
  111 | 
```