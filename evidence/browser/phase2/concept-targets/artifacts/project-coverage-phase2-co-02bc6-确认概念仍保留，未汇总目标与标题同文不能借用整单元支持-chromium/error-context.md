# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project-coverage.spec.ts >> phase2 concepts：旧结果只有whole_topic时确认概念仍保留，未汇总目标与标题同文不能借用整单元支持
- Location: tests\project-coverage.spec.ts:416:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('complementary', { name: 'pandas 读取成绩、统计并导出的学习路线' })
Expected substring: "不代表整个单元教学完整，也不代表已完成项目实践"
Received string:    "本单元学习路线1 / 4 项有内容依据视频可支持读取 Excel 成绩表1 个当前视频有正文或目录依据仍需补充读取 Excel 成绩表按班级统计均值导出统计结果下一步先学习已有内容依据的部分，再为仍需补充的子技能寻找视频或资料。打开首个有依据的视频 ↗：隔离视频：读取 Excel 成绩表（在新窗口打开）项目练习换一份成绩表，独立生成按班级汇总的 Excel 文件。仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。"
Timeout: 7000ms

Call log:
  - Expect "toContainText" getByRole('complementary', { name: 'pandas 读取成绩、统计并导出的学习路线' }) with timeout 7000ms
  - waiting for getByRole('complementary', { name: 'pandas 读取成绩、统计并导出的学习路线' })
    18 × locator resolved to <aside class="unit-coverage" aria-label="pandas 读取成绩、统计并导出的学习路线">…</aside>
       - unexpected value "本单元学习路线1 / 4 项有内容依据视频可支持读取 Excel 成绩表1 个当前视频有正文或目录依据仍需补充读取 Excel 成绩表按班级统计均值导出统计结果下一步先学习已有内容依据的部分，再为仍需补充的子技能寻找视频或资料。打开首个有依据的视频 ↗：隔离视频：读取 Excel 成绩表（在新窗口打开）项目练习换一份成绩表，独立生成按班级汇总的 Excel 文件。仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。"

```

```yaml
- complementary "pandas 读取成绩、统计并导出的学习路线":
  - heading "本单元学习路线" [level=5]
  - status: 1 / 4 项有内容依据
  - heading "视频可支持" [level=6]
  - list:
    - listitem: 读取 Excel 成绩表 1 个当前视频有正文或目录依据
  - heading "仍需补充" [level=6]
  - list:
    - listitem: 读取 Excel 成绩表
    - listitem: 按班级统计均值
    - listitem: 导出统计结果
  - strong: 下一步
  - paragraph: 先学习已有内容依据的部分，再为仍需补充的子技能寻找视频或资料。
  - link "打开首个有依据的视频 ：隔离视频：读取 Excel 成绩表（在新窗口打开）":
    - /url: https://example.org/fixture/historical-whole-only
  - paragraph:
    - strong: 项目练习
    - text: 换一份成绩表，独立生成按班级汇总的 Excel 文件。
  - paragraph: 仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。
```

# Test source

```ts
  328 |   await page.getByLabel('项目课程来源').selectOption('other');
  329 |   await expect(summary.locator('.unit-coverage-supported li>span')).toHaveText([skills[1].text]);
  330 |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText([skills[0].text, skills[2].text]);
  331 |   await page.getByLabel('项目课程来源').selectOption('all');
  332 |   await expect(summary).toContainText('2 / 3 项有内容依据');
  333 | });
  334 | 
  335 | test('phase2：只有待核实视频时所有子项仍需补充', async ({ page }) => {
  336 |   const group = fixtureGroup(); group.partial_items = []; group.partial_platform_items = undefined;
  337 |   await setup(page, new Map([[1, group]]));
  338 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  339 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  340 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(row => row.text));
  341 |   await expect(routeSummary(page).getByRole('link')).toHaveCount(0);
  342 | });
  343 | 
  344 | test('phase2：每栏展示上限以外的视频不能计入当前覆盖', async ({ page }) => {
  345 |   const group = fixtureGroup(); group.section_limit = 1;
  346 |   await setup(page, new Map([[1, group]]));
  347 |   await expect(page.locator('[data-resource-id="mean-video"]')).toHaveCount(0);
  348 |   await expect(routeSummary(page)).toContainText('1 / 3 项有内容依据');
  349 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.slice(1).map(row => row.text));
  350 | });
  351 | 
  352 | test('phase2：未拆分单元的合法whole_topic行显示自身依据，错文本不能伪造新子技能', async ({page})=>{
  353 |   const text='pandas 读取Excel成绩表';const item=course('whole-unit-video','read');
  354 |   item.match.topic_evidence_status='supported';
  355 |   item.match.subtopic_coverage=[{id:'whole_topic',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'本资源自身说明支持原单元'}];
  356 |   const group:ResultGroup={knowledge_point_id:'job-point-1',text,total_matches:1,items:[item],collection_coverage:{
  357 |     decomposition_status:'not_applicable',shared_context:[],status:'all_subtopics_supported',single_resource_full_coverage:true,disclaimer:'整单元主题匹配不表示实践已完成',
  358 |     subtopics:[{id:'whole_topic',text,status:'supported',resource_ids:[item.resource.resource_id],evidence_ids:item.match.supporting_evidence_ids!}],
  359 |   }};
  360 |   const document=structuredClone(analysis);document.knowledge_points[0].name=text;document.knowledge_points[0].concepts=[];
  361 |   await setup(page,new Map([[1,group]]),'completed',document);
  362 |   await expect(page.locator('.unit-coverage')).toContainText('1 / 1 项有内容依据');
  363 |   await expect(page.locator('.unit-coverage-supported li>span')).toHaveText([text]);
  364 |   await expect(page.locator('.unit-coverage')).toContainText('不代表已完成项目实践');
  365 |   group.collection_coverage!.subtopics[0].text='另一个学习单元';item.match.subtopic_coverage[0].text='另一个学习单元';
  366 |   await page.reload();await expect(page.locator('.unit-coverage')).toContainText('子技能覆盖待确认');
  367 |   await expect(page.locator('.unit-coverage').getByRole('link')).toHaveCount(0);
  368 | });
  369 | 
  370 | test('phase2 concepts：整单元已支持不能隐藏确认概念，三种分解状态都保留目标缺项', async ({page})=>{
  371 |   const text='pandas 成绩表分析'; const item=course('title-only-unit','read');
  372 |   item.match.topic_evidence_status='supported';
  373 |   item.match.subtopic_coverage=[{id:'whole_topic',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'只支持原单元标题'}];
  374 |   const targets=skills.map((skill,index)=>({id:`learning_target_${index+1}`,text:skill.text,status:'unknown' as const,resource_ids:[],evidence_ids:[]}));
  375 |   const group:ResultGroup={knowledge_point_id:'job-point-1',text,total_matches:1,items:[item],collection_coverage:{
  376 |     decomposition_status:'not_applicable',shared_context:[],status:'all_subtopics_supported',single_resource_full_coverage:true,disclaimer:'故意过度宣称',
  377 |     subtopics:[{id:'whole_topic',text,status:'supported',resource_ids:[item.resource.resource_id],evidence_ids:item.match.supporting_evidence_ids!},...targets],
  378 |   }};
  379 |   await setup(page,new Map([[1,group]]));
  380 |   for(const status of ['not_applicable','unknown','applied'] as const){
  381 |     group.collection_coverage!.decomposition_status=status;await page.reload();
  382 |     await expect(routeSummary(page)).toContainText('1 / 4 项有内容依据');
  383 |     await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([text]);
  384 |     await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  385 |     await expect(routeSummary(page)).toContainText('再为仍需补充的子技能寻找视频或资料');
  386 |   }
  387 |   await mkdir(resolve(root,'screenshots'),{recursive:true});
  388 |   await page.screenshot({path:resolve(root,'screenshots/coverage-confirmed-concepts-missing.png'),animations:'disabled'});
  389 | });
  390 | 
  391 | test('phase2 concepts：目标只接收同ID同原文的自身证据，隐藏平台与错配目标不能补齐', async ({page})=>{
  392 |   const group=fixtureGroup();const target=course('confirmed-read-target','read','page','other');
  393 |   const first={id:'learning_target_1',text:skills[0].text};
  394 |   target.match.subtopic_coverage=[{...first,status:'supported',evidence_ids:target.match.supporting_evidence_ids!,reason:'当前视频自己的内容支持目标原文'}];
  395 |   group.collection_coverage!.decomposition_status='unknown';
  396 |   group.collection_coverage!.subtopics=skills.map((skill,index)=>({id:`learning_target_${index+1}`,text:skill.text,status:'supported',resource_ids:[target.resource.resource_id],evidence_ids:target.match.supporting_evidence_ids!}));
  397 |   const review=course('review-target','export');review.match.topic_evidence_status='needs_review';
  398 |   review.match.subtopic_coverage=[{id:'learning_target_3',text:skills[2].text,status:'supported',evidence_ids:review.match.supporting_evidence_ids!,reason:'待核实不能计入'}];
  399 |   group.partial_items=[target];group.partial_platform_items={other:[target]};group.review_items=[review];group.review_platform_items={bilibili:[review]};
  400 |   await setup(page,new Map([[1,group]]));
  401 |   await expect(routeSummary(page)).toContainText('1 / 3 项有内容依据');
  402 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  403 |   await page.getByLabel('项目课程来源').selectOption('bilibili');
  404 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  405 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  406 |   await page.getByLabel('项目课程来源').selectOption('all');
  407 |   target.match.subtopic_coverage[0].text=skills[1].text;await page.reload();
  408 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  409 |   target.match.subtopic_coverage[0].text=skills[0].text;
  410 |   group.collection_coverage!.subtopics[0].text=skills[1].text;await page.reload();
  411 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  412 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText([skills[1].text,skills[2].text,skills[0].text]);
  413 |   await expect(routeSummary(page).getByRole('link')).toHaveCount(0);
  414 | });
  415 | 
  416 | test('phase2 concepts：旧结果只有whole_topic时确认概念仍保留，未汇总目标与标题同文不能借用整单元支持', async ({page})=>{
  417 |   const text=skills[0].text;const item=course('historical-whole-only','read');item.match.topic_evidence_status='supported';
  418 |   item.match.subtopic_coverage=[{id:'whole_topic',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'只评估整单元'},
  419 |     {id:'learning_target_1',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'缺少该目标的当前汇总行，不能借用'}];
  420 |   const group:ResultGroup={knowledge_point_id:'job-point-1',text,total_matches:1,items:[item],collection_coverage:{
  421 |     decomposition_status:'not_applicable',shared_context:[],status:'all_subtopics_supported',single_resource_full_coverage:true,disclaimer:'旧标题结果',
  422 |     subtopics:[{id:'whole_topic',text,status:'supported',resource_ids:[item.resource.resource_id],evidence_ids:item.match.supporting_evidence_ids!}],
  423 |   }};
  424 |   await setup(page,new Map([[1,group]]));
  425 |   await expect(routeSummary(page)).toContainText('1 / 4 项有内容依据');
  426 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([text]);
  427 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
> 428 |   await expect(routeSummary(page)).toContainText('不代表整个单元教学完整，也不代表已完成项目实践');
      |                                    ^ Error: expect(locator).toContainText(expected) failed
  429 | });
  430 | 
  431 | test('phase2：全部子项有依据仍保留练习与完整性边界，不宣称已掌握', async ({ page }) => {
  432 |   const group = fixtureGroup();
  433 |   const third = course('export-video', 'export', 'catalog');
  434 |   group.partial_items = [...group.partial_items!.slice(0, 2), third]; group.partial_platform_items = undefined;
  435 |   await setup(page, new Map([[1, group]]));
  436 |   const summary = routeSummary(page);
  437 |   await expect(summary).toContainText('3 / 3 项有内容依据');
  438 |   await expect(summary.locator('.unit-coverage-missing')).toContainText('仍需核对深度与完整性');
  439 |   await expect(summary).toContainText('再用下面的项目练习检验');
  440 |   await expect(summary).not.toContainText('已掌握');
  441 |   await expect(summary).toContainText('不代表已完成项目实践');
  442 | });
  443 | 
  444 | test('phase2：错配ID、标题字段、重复记录、目录篡改及跨资源引用不能成为内容依据', async ({ page }) => {
  445 |   const group = fixtureGroup(); group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined;
  446 |   const variants: [string, (item: ResourceItem) => void][] = [
  447 |     ['missing ID', item => { item.match.supporting_evidence_ids = ['missing']; }],
  448 |     ['wrong point', item => { item.match.knowledge_point_id = 'old-point'; }],
  449 |     ['wrong resource', item => { item.match.resource_id = 'different-resource'; }],
  450 |     ['title only', item => { item.evidence[0].field = 'title'; }],
  451 |     ['duplicate evidence', item => { item.evidence.push(structuredClone(item.evidence[0])); }],
  452 |     ['foreign URL', item => { item.evidence[0].url = 'https://example.org/another-course'; }],
  453 |     ['unbound description', item => { item.resource.description = '另一份描述'; }],
  454 |     ['wrong subtopic text', item => { item.match.subtopic_coverage![0].text = '无关的标题命中'; }],
  455 |     ['tampered catalog', item => { item.resource.chapters[0].title = '篡改的目录标题'; }],
  456 |   ];
  457 |   group.partial_items = [course('invalid', 'read')];
  458 |   await setup(page, new Map([[1, group]]));
  459 |   for (const [label, mutate] of variants) {
  460 |     const candidate = course('invalid', 'read', label === 'tampered catalog' ? 'catalog' : 'page'); mutate(candidate);
  461 |     group.partial_items = [candidate]; await page.reload();
  462 |     await expect(routeSummary(page), label).toContainText('0 / 3 项有内容依据');
  463 |     await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(row => row.text));
  464 |     await expect(routeSummary(page).getByRole('link', { name: /打开首个有依据的视频/ })).toHaveCount(0);
  465 |   }
  466 | });
  467 | 
  468 | for (const state of ['missing', 'empty'] as const) test(`phase2：${state} 覆盖信息给出待核对内容与下一步`, async ({ page }) => {
  469 |   const group = fixtureGroup(); delete group.collection_coverage; delete group.platform_collection_coverage;
  470 |   if (state === 'empty') { group.partial_items = []; group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  471 |   await setup(page, new Map([[1, group]]));
  472 |   const summary = routeSummary(page);
  473 |   await expect(summary).toContainText('子技能覆盖待确认');
  474 |   await expect(summary).toContainText(`学习时请核对：${skills.map(row => row.text).join('、')}`);
  475 |   await expect(summary.getByRole('link')).toHaveCount(0);
  476 |   if (state === 'empty') {
  477 |     await expect(summary).toContainText('返回调整知识点');
  478 |     await expect(page.locator('.group-empty')).toContainText('本次没有找到');
  479 |   } else await expect(summary).toContainText('先到原平台核对简介或目录');
  480 | });
  481 | 
  482 | test('phase2：切换版本只显示该版本可见资源的依据', async ({ page }) => {
  483 |   const old = fixtureGroup(); const latest = fixtureGroup();
  484 |   old.partial_items = [old.partial_items![0]]; latest.partial_items = [latest.partial_items![1]];
  485 |   for (const group of [old, latest]) { group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  486 |   await setup(page, new Map([[1, old], [2, latest]]));
  487 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[1].text]);
  488 |   await page.goto('/?project=coverage-project&version=1');
  489 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  490 |   await expect(page.locator('[data-resource-id="mean-video"]')).toHaveCount(0);
  491 |   await expect(page.getByRole('button', { name: /重新检索这些知识点/ })).toHaveCount(0);
  492 | });
  493 | 
  494 | async function contrast(page: Page) {
  495 |   return page.locator('.unit-coverage').evaluate(container => {
  496 |     const channels = (value: string) => value.match(/[\d.]+/g)!.map(Number);
  497 |     const luminance = (rgb: number[]) => rgb.slice(0, 3).map(n => n / 255 <= .04045 ? n / 255 / 12.92 : ((n / 255 + .055) / 1.055) ** 2.4).reduce((sum, n, i) => sum + n * [.2126,.7152,.0722][i], 0);
  498 |     const background = (element: Element): number[] => { const c = channels(getComputedStyle(element).backgroundColor); return c.length < 4 || c[3] > 0 ? c : background(element.parentElement!); };
  499 |     return [...container.querySelectorAll('h5,h6,li>span,li>small,.unit-coverage-missing li,.unit-coverage-next p,.unit-coverage-next a,.unit-coverage-practice span,.unit-coverage-note,.unit-coverage-heading>span')].filter(e => e.checkVisibility()).map(element => {
  500 |       const style = getComputedStyle(element); const a = luminance(channels(style.color)); const b = luminance(background(element));
  501 |       return { text: element.textContent?.trim(), ratio: (Math.max(a,b)+.05)/(Math.min(a,b)+.05), fontSize: style.fontSize };
  502 |     });
  503 |   });
  504 | }
  505 | for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
  506 |   test(`phase2：${viewport.name} 学习路线可读、无横溢并保留三步设计`, async ({ page }) => {
  507 |     await page.setViewportSize({ width: viewport.width, height: viewport.height });
  508 |     await setup(page, new Map([[1, fixtureGroup()]]));
  509 |     await expect(page.locator('.stage-navigation [aria-current="step"]')).toContainText('推荐视频');
  510 |     await expect(page.locator('h1')).toContainText('让知识，走进你的项目。');
  511 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  512 |     const observations = await contrast(page); expect(observations.length).toBeGreaterThan(10);
  513 |     expect(observations.every(row => row.ratio >= 4.5), JSON.stringify(observations)).toBe(true);
  514 |     await mkdir(resolve(root,'screenshots'), { recursive: true });
  515 |     await writeFile(resolve(root,`coverage-${viewport.name}.json`), JSON.stringify({ kind: 'isolated fixture UI observations', viewport, contrast: observations, horizontalOverflow: false },null,2));
  516 |     await page.screenshot({ path: resolve(root,`screenshots/coverage-${viewport.name}-entry.png`), animations: 'disabled' });
  517 |     await routeSummary(page).scrollIntoViewIfNeeded();
  518 |     await page.screenshot({ path: resolve(root,`screenshots/coverage-${viewport.name}-detail.png`), animations: 'disabled' });
  519 |   });
  520 | }
  521 | 
  522 | test('phase2：键盘可从平台筛选到视频入口，减少动态偏好保持静态路线', async ({ page }) => {
  523 |   await page.emulateMedia({ reducedMotion: 'reduce' });
  524 |   await setup(page, new Map([[1, fixtureGroup()]]));
  525 |   await page.getByLabel('项目课程来源').focus(); await page.keyboard.press('Tab');
  526 |   const link = routeSummary(page).getByRole('link', { name: /打开首个有依据的视频/ });
  527 |   await expect(link).toBeFocused();
  528 |   await expect(link).toHaveAttribute('target','_blank'); await expect(link).toHaveAttribute('rel','noopener noreferrer');
```