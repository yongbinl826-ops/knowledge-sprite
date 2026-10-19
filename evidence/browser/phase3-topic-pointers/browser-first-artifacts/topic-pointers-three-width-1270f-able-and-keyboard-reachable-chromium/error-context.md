# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: topic-pointers.spec.ts >> three widths and reduce motion: folded/expanded pointer long source stays readable and keyboard reachable
- Location: tests\topic-pointers.spec.ts:85:1

# Error details

```
Error: expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 3

- Array []
+ Array [
+   "SPAN",
+ ]
```

# Page snapshot

```yaml
- generic [ref=e2]:
  - link "跳转到主要内容" [ref=e3] [cursor=pointer]:
    - /url: "#stage-title"
  - banner [ref=e4]:
    - generic [ref=e5]: 项目制知识引导小精灵
    - navigation "项目学习流程" [ref=e9]:
      - button "01 项目描述" [ref=e10] [cursor=pointer]:
        - generic [aria-hidden] [ref=e11]: ✓
        - generic [ref=e12]: "01"
        - text: 项目描述
      - button "02 选择知识点" [ref=e13] [cursor=pointer]:
        - generic [aria-hidden] [ref=e14]: ✓
        - generic [ref=e15]: "02"
        - text: 选择知识点
      - button "03 推荐视频" [ref=e16] [cursor=pointer]:
        - generic [ref=e18]: "03"
        - text: 推荐视频
    - button "我的项目" [ref=e19] [cursor=pointer]: 我的项目 ↗
  - main [ref=e20]:
    - complementary [ref=e21]:
      - paragraph [ref=e22]: 03 / CURATED LEARNING
      - heading "让知识， 走进你的项目。" [level=1] [ref=e23]: 让知识，走进你的项目。
      - paragraph [ref=e24]: Arduino 调光器从相关的视频与章节开始。
      - button "← 调整知识点" [ref=e26] [cursor=pointer]
      - navigation "已选知识点" [ref=e27]:
        - paragraph [ref=e28]: 已选知识点
        - button "全部" [pressed] [ref=e29] [cursor=pointer]
        - button "Arduino analogWrite PWM 调光" [ref=e30] [cursor=pointer]
      - generic [aria-hidden] [ref=e31]: "03"
    - generic [ref=e32]:
      - paragraph [ref=e33]: Arduino 调光器 · v1 · 部分完成
      - region [ref=e34]:
        - generic [ref=e35]:
          - generic [ref=e36]:
            - heading "项目课程结果 · v1" [level=2] [ref=e37]: 推荐视频
            - paragraph [ref=e38]: 从一个学习单元开始，将学到的内容用在项目里。
          - generic [ref=e39]: 部分完成
        - group [ref=e40]:
          - generic "查看检索进度与预算" [ref=e41] [cursor=pointer]
        - generic [ref=e42]:
          - heading "控制亮度" [level=3] [ref=e43]
          - generic [ref=e44]:
            - generic [ref=e45]:
              - heading "Arduino analogWrite PWM 调光" [level=4] [ref=e46]
              - generic [ref=e47]: 部分完成 · 0 条推荐
            - complementary "Arduino analogWrite PWM 调光的学习路线" [ref=e48]:
              - generic [ref=e49]:
                - heading "从学会技能，到完成项目" [level=5] [ref=e50]
                - status [ref=e51]: 教学范围待核对
              - paragraph [ref=e52]:
                - strong [ref=e53]: 必要先修
                - text: 无额外先修，可从这里开始
              - generic [ref=e54]:
                - region "先学这些技能" [ref=e55]:
                  - generic [ref=e56]:
                    - generic [aria-hidden] [ref=e57]: "01"
                    - heading "先学这些技能" [level=6] [ref=e58]
                  - paragraph [ref=e59]: 学习可迁移的方法；教程不必使用同款项目。
                  - list [ref=e60]:
                    - listitem [ref=e61]:
                      - generic [ref=e62]:
                        - strong [ref=e63]: Arduino analogWrite 占空比控制输出
                        - generic [ref=e64]: 待补充材料
                      - paragraph [ref=e65]: 当前材料还没有可确认的本课教学依据。
                    - listitem [ref=e66]:
                      - generic [ref=e67]:
                        - strong [ref=e68]: 识别并选用支持 PWM 的数字引脚
                        - generic [ref=e69]: 待补充材料
                      - paragraph [ref=e70]: 当前材料还没有可确认的本课教学依据。
                - region "带回项目练习" [ref=e71]:
                  - generic [ref=e72]:
                    - generic [aria-hidden] [ref=e73]: "02"
                    - heading "带回项目练习" [level=6] [ref=e74]
                    - generic [ref=e75]: 待自己实践
                  - paragraph [ref=e76]: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
                  - generic [ref=e77]:
                    - strong [ref=e78]: 项目子任务
                    - paragraph [ref=e79]: 使用analogWrite把自己的电位器读数转换为LED亮度
                  - generic [ref=e80]:
                    - strong [ref=e81]: 参数与应用检查
                    - list [ref=e82]:
                      - listitem [ref=e83]: analogWrite取值0–255
                      - listitem [ref=e84]: 按板卡官方说明确认PWM引脚
                  - generic [ref=e85]:
                    - strong [ref=e86]: 试做后这样检查
                    - paragraph [ref=e87]: 旋转电位器检查两端及中间亮度。
              - generic [ref=e88]:
                - strong [ref=e89]: 下一步
                - paragraph [ref=e90]: 尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。
              - paragraph [ref=e91]: 章节线索不等于技能教学或项目实践完成。
              - group [ref=e92]:
                - generic "原项目要求来源核对 旧口径明细" [ref=e93] [cursor=pointer]
            - group [ref=e94]:
              - generic "相关课题线索 · 尚未证实讲授完整技能 （1）" [active] [ref=e95] [cursor=pointer]:
                - text: 相关课题线索 · 尚未证实讲授完整技能
                - generic [ref=e96]: （1）
              - paragraph [ref=e97]: 目录原题提到了相关课题，可前往核对；这些线索不计入技能支持或推荐数量，也不代表已讲授完整技能。
              - list [ref=e98]:
                - listitem [ref=e99]:
                  - paragraph [ref=e100]:
                    - strong [ref=e101]: 学习目标
                    - text: Arduino analogWrite 占空比控制输出
                  - paragraph [ref=e102]: 实际目录原题
                  - blockquote [ref=e103]: 1-25 模拟输出1 - analogWrite
                  - paragraph [ref=e104]: 【太极创客】零基础入门学用Arduino 第一部分 合辑 · B站
                  - generic [ref=e105]:
                    - strong [ref=e106]: 仍未证实讲授
                    - list [ref=e107]:
                      - listitem [ref=e108]: 占空比控制输出
                  - link "到平台核对这节课 ：1-25 模拟输出1 - analogWrite（在新窗口打开）" [ref=e109] [cursor=pointer]:
                    - /url: https://www.bilibili.com/video/BV164411J7GE/?p=26
                    - text: 到平台核对这节课 ↗
                    - generic [ref=e110]: ：1-25 模拟输出1 - analogWrite（在新窗口打开）
                  - paragraph [ref=e111]: 授课深度、语言与访问条件仍以原平台为准。核对后再决定是否学习，并回到项目中练习。
            - paragraph [ref=e112]: 本次检索部分完成，暂无达到技能教学推荐标准的课程。
            - link "到 B站搜索这个单元 （平台搜索入口，非已推荐视频，在新窗口打开）" [ref=e113] [cursor=pointer]:
              - /url: https://search.bilibili.com/all?keyword=Arduino+analogWrite+PWM+%E8%B0%83%E5%85%89
              - text: 到 B站搜索这个单元
              - generic [aria-hidden] [ref=e114]: ↗
              - generic [ref=e115]: （平台搜索入口，非已推荐视频，在新窗口打开）
        - generic [ref=e116]:
          - paragraph [ref=e117]: 章节信息来自实际检索证据。课程可能需要登录、选课或付费，以原平台为准。
          - button "重新检索这些知识点" [ref=e118] [cursor=pointer]: 重新检索这些知识点 ↗
          - paragraph [ref=e119]: 重新检索会创建新版本，上次结果保留；受相同预算与限流约束。
  - contentinfo [ref=e120]:
    - generic [ref=e121]: 让学习，发生在项目里。
    - generic [ref=e122]: 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  1  | import { test, expect, type Page } from '@playwright/test';
  2  | import { readFileSync } from 'node:fs';
  3  | import { mkdir, writeFile } from 'node:fs/promises';
  4  | import { resolve } from 'node:path';
  5  | import type { RelatedTopicPointer, ResourceItem, ResultGroup } from '../src/types';
  6  | import type { ProjectAnalysis, ProjectInput, ProjectView } from '../src/projectTypes';
  7  | 
  8  | // Offline actual retained catalog projection. All API is mocked; 0 live search,
  9  | // model, platform navigation or source instructional-quality acceptance.
  10 | const source = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/topic-pointer-actual-p26.json'), 'utf8')) as RelatedTopicPointer;
  11 | const out = resolve(process.cwd(), 'tests/evidence/topic-pointers');
  12 | const time = '2026-10-18T23:29:44Z';
  13 | const input: ProjectInput = { name: 'Arduino 调光器', requirements: '安全连接LED，通过电位器调光。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: 'Arduino', preferred_platforms: ['bilibili'] };
  14 | function fixture() {
  15 |   const entry = structuredClone(source);
  16 |   const analysis: ProjectAnalysis = { scope: input.requirements, technical_plan: 'Arduino', assumptions: [], functions: [{ id: 'f1', name: '控制亮度', original_requirement: input.requirements, acceptance_criteria: '两端及中间亮度正确', no_new_learning_reason: null }],
  17 |     knowledge_points: [{ id: 'k1', name: 'Arduino analogWrite PWM 调光', description: '用PWM控制LED', project_task: '使用analogWrite把自己的电位器读数转换为LED亮度', learning_goal: '能够调光', why_needed: '实现项目亮度变化', function_ids: ['f1'], learning_order: 1, prerequisite_ids: [], necessity: 'required', selection: 'learn', learning_skills: [entry.pointer.skill, '识别并选用支持 PWM 的数字引脚'], technology: 'Arduino', concepts: ['analogWrite取值0–255', '按板卡官方说明确认PWM引脚'], practice_check: '旋转电位器检查两端及中间亮度。' }] };
  18 |   const group: ResultGroup = { knowledge_point_id: entry.pointer.knowledge_point_id, text: analysis.knowledge_points[0].name, total_matches: 0, total_partial_matches: 0, items: [], partial_items: [], review_items: [],
  19 |     learning_coverage: { mode: 'transferable_skills', skills: analysis.knowledge_points[0].learning_skills!.map((text,index)=>({id:`skill_${index+1}`,text,content_resource_ids:[],title_resource_ids:[],evidence_ids:[]})), disclaimer: '章节线索不等于技能教学或项目实践完成。' }, related_topic_pointers: [entry] };
  20 |   return { entry, analysis, group };
  21 | }
  22 | type Fixture = ReturnType<typeof fixture>;
  23 | const diagnostics = new WeakMap<Page, { writes: string[]; external: string[]; runtime: string[]; console: string[] }>();
  24 | test.afterEach(async ({ page }, info) => {
  25 |   const log = diagnostics.get(page)!;
  26 |   await info.attach('pointer-isolated-diagnostics', { body: JSON.stringify(log,null,2), contentType: 'application/json' });
  27 |   expect(log.writes).toEqual([]); expect(log.external).toEqual([]); expect(log.runtime).toEqual([]); expect(log.console).toEqual([]);
  28 | });
  29 | async function setup(page: Page, f = fixture()) {
  30 |   const log = { writes: [] as string[], external: [] as string[], runtime: [] as string[], console: [] as string[] }; diagnostics.set(page, log);
  31 |   page.on('pageerror', error => log.runtime.push(error.message)); page.on('console', msg => { if (['error','warning'].includes(msg.type())) log.console.push(msg.text()); });
  32 |   const view: ProjectView = { project_id: 'pointer-project', input, current_version: 1, versions: [{ version: 1, status: 'partial', created_at: time }],
  33 |     version: { version: 1, status: 'partial', input, analysis: f.analysis, confirmation: { confirmed_at: time }, batches: [{ batch_id: 'batch1', job_id: 'job1', status: 'completed', project_knowledge_point_ids: ['k1'] }], error: null, created_at: time },
  34 |     points: [{ project_knowledge_point_id: 'k1', name: f.analysis.knowledge_points[0].name, selection: 'learn', status: 'partial', batch_id: 'batch1', job_id: 'job1', knowledge_point_id: f.group.knowledge_point_id, result: f.group }] };
  35 |   const origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5178').origin;
  36 |   await page.route('**/*', async route => {
  37 |     const request=route.request(), url=new URL(request.url());
  38 |     if(request.method()!=='GET'){log.writes.push(`${request.method()} ${url.href}`);return route.abort('blockedbyclient');}
  39 |     if(url.origin===origin && !url.pathname.startsWith('/api/')) return route.continue();
  40 |     if(url.origin===origin && url.pathname==='/api/projects/pointer-project/results') return route.fulfill({json:view});
  41 |     if(url.origin===origin && url.pathname==='/api/projects') return route.fulfill({json:{projects:[{project_id:'pointer-project',name:input.name,current_version:1,created_at:time,updated_at:time}]}});
  42 |     if(url.origin===origin && url.pathname==='/api/capabilities') return route.fulfill({json:{mode:'live',search:{status:'configured',message:'isolated',selected_provider:'fixture',providers:[]},llm:{status:'configured',message:'isolated'},fetch:{status:'available',message:'isolated',browser_fallback:false},platforms:[],limits:{max_knowledge_points:5,max_results_per_point:5,max_search_requests:30,max_detail_pages:40}}});
  43 |     log.external.push(url.href);return route.abort('blockedbyclient');
  44 |   });
  45 |   await page.emulateMedia({reducedMotion:'reduce'}); await page.goto('/?project=pointer-project&version=1');
  46 |   await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
  47 |   await expect(page.getByRole('heading',{name:'项目课程结果 · v1'})).toBeVisible(); await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  48 |   return {f,log};
  49 | }
  50 | const panel=(page:Page)=>page.locator('.project-result-point');
  51 | const fold=(page:Page)=>page.locator('.related-topic-pointers');
  52 | async function allUnknown(page:Page) {
  53 |   await expect(panel(page).locator('.transferable-skills>li')).toHaveCount(2);
  54 |   await expect(panel(page).locator('.transferable-skills>li[data-skill-state="unknown"]')).toHaveCount(2);
  55 |   await expect(panel(page).locator('.project-practice-axis')).toContainText('待自己实践');
  56 |   await expect(panel(page).locator('.project-practice-axis')).toContainText('analogWrite取值0–255');
  57 | }
  58 | test('zero main recommendations: actual catalog pointer starts open with original p26 link, while0recommendations/2unknownskills stay unchanged',async({page})=>{
  59 |   await setup(page);await expect(fold(page)).toBeVisible();await expect(fold(page)).toHaveAttribute('open','');
  60 |   await expect(panel(page).locator('.group-heading')).toContainText('0 条推荐');await expect(panel(page).locator('.course-card')).toHaveCount(0);await allUnknown(page);
  61 |   await fold(page).locator('summary').focus();await page.keyboard.press('Enter');await expect(fold(page)).not.toHaveAttribute('open','');
  62 |   await page.keyboard.press('Enter');await expect(fold(page)).toHaveAttribute('open','');
  63 |   await expect(fold(page)).toContainText('相关课题线索 · 尚未证实讲授完整技能');await expect(fold(page)).toContainText('Arduino analogWrite 占空比控制输出');
  64 |   await expect(fold(page).locator('blockquote')).toHaveText('1-25 模拟输出1 - analogWrite');await expect(fold(page).locator('.topic-pointer-missing')).toContainText('占空比控制输出');
  65 |   const link=fold(page).getByRole('link',{name:/到平台核对这节课/});await expect(link).toHaveAttribute('href','https://www.bilibili.com/video/BV164411J7GE/?p=26');await expect(link).toHaveAttribute('target','_blank');await expect(link).toHaveAttribute('rel','noopener noreferrer');
  66 |   await page.keyboard.press('Tab');await expect(link).toBeFocused();await allUnknown(page);
  67 |   await expect(panel(page).locator('.learning-route-next')).toContainText('主要推荐');await expect(panel(page).locator('.group-empty')).toContainText('暂无达到技能教学推荐标准');
  68 | });
  69 | test('platform filter hides pointer source without borrowing topic support from other visible materials',async({page})=>{
  70 |   const f=fixture();
  71 |   const item=(id:string,platform:string):ResourceItem=>({resource:{...structuredClone(f.entry.resource),resource_id:id,platform,thumbnail_url:null,chapters:[]},evidence:[],match:{knowledge_point_id:f.group.knowledge_point_id,resource_id:id,ranking_score:1,recommendation_reason:'隔离的部分匹配材料；教学范围待核实。',matched_evidence_ids:[],coverage_basis:[],topic_evidence_status:'partial'}});
  72 |   const a=item('other-main','other'),b=item('bili-main','bilibili');f.group.partial_items=[a,b];f.group.partial_platform_items={other:[a],bilibili:[b]};
  73 |   await setup(page,f);await expect(fold(page)).toBeVisible();await expect(fold(page)).not.toHaveAttribute('open','');await allUnknown(page);
  74 |   await page.getByLabel('项目课程来源').selectOption('other');await expect(fold(page)).toHaveCount(0);await allUnknown(page);
  75 |   await page.getByLabel('项目课程来源').selectOption('bilibili');await expect(fold(page)).toBeVisible();await allUnknown(page);
  76 | });
  77 | test('bad hash or wrong actual part is absent, not an unknown-source clickable lead',async({page})=>{
  78 |   const f=fixture();f.entry.pointer.source_text_sha256='0'.repeat(64);await setup(page,f);await expect(fold(page)).toHaveCount(0);await allUnknown(page);
  79 |   f.entry.pointer.source_text_sha256=source.pointer.source_text_sha256;f.entry.pointer.target_url='https://www.bilibili.com/video/BV164411J7GE/?p=25';await page.reload();await expect(fold(page)).toHaveCount(0);await allUnknown(page);
  80 | });
  81 | test('missing pointer lane and historical absent skills cannot invent goals or display source hints',async({page})=>{
  82 |   const f=fixture();delete f.analysis.knowledge_points[0].learning_skills;await setup(page,f);await expect(fold(page)).toHaveCount(0);
  83 |   await expect(panel(page).locator('.transferable-skills')).toHaveCount(0);await expect(panel(page)).toContainText('此版本尚未区分可迁移技能');
  84 | });
  85 | test('three widths and reduce motion: folded/expanded pointer long source stays readable and keyboard reachable',async({page})=>{
  86 |   await setup(page);await mkdir(out,{recursive:true});const observations=[];
  87 |   for(const size of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
  88 |     await page.setViewportSize(size);await fold(page).evaluate(node=>(node as HTMLDetailsElement).open=false);await fold(page).scrollIntoViewIfNeeded();
  89 |     await page.screenshot({path:resolve(out,`${size.name}-folded.png`),animations:'disabled'});
  90 |     await fold(page).locator('summary').focus();await page.keyboard.press('Enter');await expect(fold(page)).toHaveAttribute('open','');
  91 |     await fold(page).screenshot({path:resolve(out,`${size.name}-expanded.png`),animations:'disabled'});await allUnknown(page);
  92 |     const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);expect(overflow).toBe(false);
> 93 |     const inner=await fold(page).evaluate(node=>[...node.querySelectorAll('*')].filter(el=>el.clientWidth>0&&el.scrollWidth>el.clientWidth+1).map(el=>el.tagName));expect(inner).toEqual([]);
     |                                                                                                                                                                                  ^ Error: expect(received).toEqual(expected) // deep equality
  94 |     const motions=await fold(page).evaluate(node=>({animation:getComputedStyle(node).animationName,transition:getComputedStyle(node).transitionDuration}));expect(motions).toEqual({animation:'none',transition:'0s'});
  95 |     await page.keyboard.press('Tab');await expect(fold(page).getByRole('link')).toBeFocused();observations.push({size,overflow,inner,motions});
  96 |   }
  97 |   await writeFile(resolve(out,'three-width-observations.json'),JSON.stringify({mock:true,actualRetainedCatalog:true,noSourceSemanticAcceptance:true,observations},null,2));
  98 | });
  99 | 
```