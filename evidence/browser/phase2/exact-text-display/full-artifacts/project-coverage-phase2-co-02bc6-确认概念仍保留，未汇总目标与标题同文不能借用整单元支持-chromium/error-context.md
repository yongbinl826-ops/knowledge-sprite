# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project-coverage.spec.ts >> phase2 concepts：旧结果只有whole_topic时确认概念仍保留，未汇总目标与标题同文不能借用整单元支持
- Location: tests\project-coverage.spec.ts:590:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('complementary', { name: 'pandas 读取成绩、统计并导出的学习路线' })
Expected substring: "1 / 4 项有内容依据"
Received string:    "本单元学习路线0 / 3 项有内容依据视频可支持当前视频尚无足够的正文或目录依据。仍需补充读取 Excel 成绩表按班级统计均值导出统计结果下一步先到原平台核对简介或目录；待核实线索和搜索摘要不计入已支持的子技能。项目练习换一份成绩表，独立生成按班级汇总的 Excel 文件。仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。"
Timeout: 7000ms

Call log:
  - Expect "toContainText" getByRole('complementary', { name: 'pandas 读取成绩、统计并导出的学习路线' }) with timeout 7000ms
  - waiting for getByRole('complementary', { name: 'pandas 读取成绩、统计并导出的学习路线' })
    18 × locator resolved to <aside class="unit-coverage" aria-label="pandas 读取成绩、统计并导出的学习路线">…</aside>
       - unexpected value "本单元学习路线0 / 3 项有内容依据视频可支持当前视频尚无足够的正文或目录依据。仍需补充读取 Excel 成绩表按班级统计均值导出统计结果下一步先到原平台核对简介或目录；待核实线索和搜索摘要不计入已支持的子技能。项目练习换一份成绩表，独立生成按班级汇总的 Excel 文件。仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。"

```

```yaml
- complementary "pandas 读取成绩、统计并导出的学习路线":
  - heading "本单元学习路线" [level=5]
  - status: 0 / 3 项有内容依据
  - heading "视频可支持" [level=6]
  - paragraph: 当前视频尚无足够的正文或目录依据。
  - heading "仍需补充" [level=6]
  - list:
    - listitem: 读取 Excel 成绩表
    - listitem: 按班级统计均值
    - listitem: 导出统计结果
  - strong: 下一步
  - paragraph: 先到原平台核对简介或目录；待核实线索和搜索摘要不计入已支持的子技能。
  - paragraph:
    - strong: 项目练习
    - text: 换一份成绩表，独立生成按班级汇总的 Excel 文件。
  - paragraph: 仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。
```

# Test source

```ts
  499 | 
  500 | test('phase2：只有待核实视频时所有子项仍需补充', async ({ page }) => {
  501 |   const group = fixtureGroup(); group.partial_items = []; group.partial_platform_items = undefined;
  502 |   await setup(page, new Map([[1, group]]));
  503 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  504 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  505 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(row => row.text));
  506 |   await expect(routeSummary(page).getByRole('link')).toHaveCount(0);
  507 | });
  508 | 
  509 | test('phase2：每栏展示上限以外的视频不能计入当前覆盖', async ({ page }) => {
  510 |   const group = fixtureGroup(); group.section_limit = 1;
  511 |   await setup(page, new Map([[1, group]]));
  512 |   await expect(page.locator('[data-resource-id="mean-video"]')).toHaveCount(0);
  513 |   await expect(routeSummary(page)).toContainText('1 / 3 项有内容依据');
  514 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.slice(1).map(row => row.text));
  515 | });
  516 | 
  517 | test('phase2：未拆分单元的合法whole_topic行显示自身依据，错文本不能伪造新子技能', async ({page})=>{
  518 |   const text='pandas 读取Excel成绩表';const item=course('whole-unit-video','read');
  519 |   item.match.topic_evidence_status='supported';
  520 |   item.match.subtopic_coverage=[{id:'whole_topic',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'本资源自身说明支持原单元'}];
  521 |   const group:ResultGroup={knowledge_point_id:'job-point-1',text,total_matches:1,items:[item],collection_coverage:{
  522 |     decomposition_status:'not_applicable',shared_context:[],status:'all_subtopics_supported',single_resource_full_coverage:true,disclaimer:'整单元主题匹配不表示实践已完成',
  523 |     subtopics:[{id:'whole_topic',text,status:'supported',resource_ids:[item.resource.resource_id],evidence_ids:item.match.supporting_evidence_ids!}],
  524 |   }};
  525 |   const document=structuredClone(analysis);document.knowledge_points[0].name=text;document.knowledge_points[0].concepts=[];
  526 |   await setup(page,new Map([[1,group]]),'completed',document);
  527 |   await expect(page.locator('.unit-coverage')).toContainText('1 / 1 项有内容依据');
  528 |   await expect(page.locator('.unit-coverage-supported li>span')).toHaveText([text]);
  529 |   await expect(page.locator('.unit-coverage')).toContainText('不代表已完成项目实践');
  530 |   group.collection_coverage!.subtopics[0].text='另一个学习单元';item.match.subtopic_coverage[0].text='另一个学习单元';
  531 |   await page.reload();await expect(page.locator('.unit-coverage')).toContainText('子技能覆盖待确认');
  532 |   await expect(page.locator('.unit-coverage').getByRole('link')).toHaveCount(0);
  533 | });
  534 | 
  535 | test('phase2 concepts：整单元已支持不能隐藏确认概念，三种分解状态都保留目标缺项', async ({page})=>{
  536 |   const text='pandas 成绩表分析'; const item=course('title-only-unit','read');
  537 |   item.match.topic_evidence_status='supported';
  538 |   item.match.subtopic_coverage=[{id:'whole_topic',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'只支持原单元标题'}];
  539 |   const targets=skills.map((skill,index)=>({id:`learning_target_${index+1}`,text:skill.text,status:'unknown' as const,resource_ids:[],evidence_ids:[]}));
  540 |   const group:ResultGroup={knowledge_point_id:'job-point-1',text,total_matches:1,items:[item],collection_coverage:{
  541 |     decomposition_status:'not_applicable',shared_context:[],status:'all_subtopics_supported',single_resource_full_coverage:true,disclaimer:'故意过度宣称',
  542 |     subtopics:[{id:'whole_topic',text,status:'supported',resource_ids:[item.resource.resource_id],evidence_ids:item.match.supporting_evidence_ids!},...targets],
  543 |   }};
  544 |   await setup(page,new Map([[1,group]]));
  545 |   for(const status of ['not_applicable','unknown','applied'] as const){
  546 |     group.collection_coverage!.decomposition_status=status;await page.reload();
  547 |     await expect(routeSummary(page)).toContainText('1 / 4 项有内容依据');
  548 |     await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([text]);
  549 |     await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  550 |     await expect(routeSummary(page)).toContainText('再为仍需补充的子技能寻找视频或资料');
  551 |   }
  552 |   await mkdir(resolve(root,'screenshots'),{recursive:true});
  553 |   const widths=[];
  554 |   for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
  555 |     await page.setViewportSize({width:viewport.width,height:viewport.height});
  556 |     const overflow=await page.evaluate(()=>globalThis.document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);
  557 |     const colors=await contrast(page);expect(colors.every(row=>row.ratio>=4.5),JSON.stringify(colors)).toBe(true);
  558 |     await routeSummary(page).scrollIntoViewIfNeeded();
  559 |     await page.screenshot({path:resolve(root,`screenshots/coverage-confirmed-concepts-${viewport.name}.png`),animations:'disabled'});
  560 |     widths.push({viewport,horizontalOverflow:overflow,contrast:colors});
  561 |   }
  562 |   await writeFile(resolve(root,'confirmed-concepts-widths.json'),JSON.stringify({kind:'isolated UI contract fixtures, not a new service request',widths},null,2));
  563 | });
  564 | 
  565 | test('phase2 concepts：目标只接收同ID同原文的自身证据，隐藏平台与错配目标不能补齐', async ({page})=>{
  566 |   const group=fixtureGroup();const target=course('confirmed-read-target','read','page','other');
  567 |   const first={id:'learning_target_1',text:skills[0].text};
  568 |   target.match.subtopic_coverage=[{...first,status:'supported',evidence_ids:target.match.supporting_evidence_ids!,reason:'当前视频自己的内容支持目标原文'}];
  569 |   group.collection_coverage!.decomposition_status='unknown';
  570 |   group.collection_coverage!.subtopics=skills.map((skill,index)=>({id:`learning_target_${index+1}`,text:skill.text,status:'supported',resource_ids:[target.resource.resource_id],evidence_ids:target.match.supporting_evidence_ids!}));
  571 |   const review=course('review-target','export');review.match.topic_evidence_status='needs_review';
  572 |   review.match.subtopic_coverage=[{id:'learning_target_3',text:skills[2].text,status:'supported',evidence_ids:review.match.supporting_evidence_ids!,reason:'待核实不能计入'}];
  573 |   group.partial_items=[target];group.partial_platform_items={other:[target]};group.review_items=[review];group.review_platform_items={bilibili:[review]};
  574 |   await setup(page,new Map([[1,group]]));
  575 |   await expect(routeSummary(page)).toContainText('1 / 3 项有内容依据');
  576 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  577 |   await page.getByLabel('项目课程来源').selectOption('bilibili');
  578 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  579 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  580 |   await page.getByLabel('项目课程来源').selectOption('all');
  581 |   target.match.subtopic_coverage[0].text=skills[1].text;await page.reload();
  582 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  583 |   target.match.subtopic_coverage[0].text=skills[0].text;
  584 |   group.collection_coverage!.subtopics[0].text=skills[1].text;await page.reload();
  585 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  586 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText([skills[1].text,skills[2].text,skills[0].text]);
  587 |   await expect(routeSummary(page).getByRole('link')).toHaveCount(0);
  588 | });
  589 | 
  590 | test('phase2 concepts：旧结果只有whole_topic时确认概念仍保留，未汇总目标与标题同文不能借用整单元支持', async ({page})=>{
  591 |   const text=skills[0].text;const item=course('historical-whole-only','read');item.match.topic_evidence_status='supported';
  592 |   item.match.subtopic_coverage=[{id:'whole_topic',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'只评估整单元'},
  593 |     {id:'learning_target_1',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'缺少该目标的当前汇总行，不能借用'}];
  594 |   const group:ResultGroup={knowledge_point_id:'job-point-1',text,total_matches:1,items:[item],collection_coverage:{
  595 |     decomposition_status:'not_applicable',shared_context:[],status:'all_subtopics_supported',single_resource_full_coverage:true,disclaimer:'旧标题结果',
  596 |     subtopics:[{id:'whole_topic',text,status:'supported',resource_ids:[item.resource.resource_id],evidence_ids:item.match.supporting_evidence_ids!}],
  597 |   }};
  598 |   await setup(page,new Map([[1,group]]));
> 599 |   await expect(routeSummary(page)).toContainText('1 / 4 项有内容依据');
      |                                    ^ Error: expect(locator).toContainText(expected) failed
  600 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([text]);
  601 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  602 |   await expect(routeSummary(page)).toContainText('不代表整单元教学完整，也不代表已完成项目实践');
  603 | });
  604 | 
  605 | test('phase2：全部子项有依据仍保留练习与完整性边界，不宣称已掌握', async ({ page }) => {
  606 |   const group = fixtureGroup();
  607 |   const third = course('export-video', 'export', 'catalog');
  608 |   group.partial_items = [...group.partial_items!.slice(0, 2), third]; group.partial_platform_items = undefined;
  609 |   await setup(page, new Map([[1, group]]));
  610 |   const summary = routeSummary(page);
  611 |   await expect(summary).toContainText('3 / 3 项有内容依据');
  612 |   await expect(summary.locator('.unit-coverage-missing')).toContainText('仍需核对深度与完整性');
  613 |   await expect(summary).toContainText('再用下面的项目练习检验');
  614 |   await expect(summary).not.toContainText('已掌握');
  615 |   await expect(summary).toContainText('不代表已完成项目实践');
  616 | });
  617 | 
  618 | test('phase2：错配ID、标题字段、重复记录、目录篡改及跨资源引用不能成为内容依据', async ({ page }) => {
  619 |   const group = fixtureGroup(); group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined;
  620 |   const variants: [string, (item: ResourceItem) => void][] = [
  621 |     ['missing ID', item => { item.match.supporting_evidence_ids = ['missing']; }],
  622 |     ['wrong point', item => { item.match.knowledge_point_id = 'old-point'; }],
  623 |     ['wrong resource', item => { item.match.resource_id = 'different-resource'; }],
  624 |     ['title only', item => { item.evidence[0].field = 'title'; }],
  625 |     ['duplicate evidence', item => { item.evidence.push(structuredClone(item.evidence[0])); }],
  626 |     ['foreign URL', item => { item.evidence[0].url = 'https://example.org/another-course'; }],
  627 |     ['unbound description', item => { item.resource.description = '另一份描述'; }],
  628 |     ['wrong subtopic text', item => { item.match.subtopic_coverage![0].text = '无关的标题命中'; }],
  629 |     ['tampered catalog', item => { item.resource.chapters[0].title = '篡改的目录标题'; }],
  630 |   ];
  631 |   group.partial_items = [course('invalid', 'read')];
  632 |   await setup(page, new Map([[1, group]]));
  633 |   for (const [label, mutate] of variants) {
  634 |     const candidate = course('invalid', 'read', label === 'tampered catalog' ? 'catalog' : 'page'); mutate(candidate);
  635 |     group.partial_items = [candidate]; await page.reload();
  636 |     await expect(routeSummary(page), label).toContainText('0 / 3 项有内容依据');
  637 |     await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(row => row.text));
  638 |     await expect(routeSummary(page).getByRole('link', { name: /打开首个有依据的视频/ })).toHaveCount(0);
  639 |   }
  640 | });
  641 | 
  642 | for (const state of ['missing', 'empty'] as const) test(`phase2：${state} 覆盖信息给出待核对内容与下一步`, async ({ page }) => {
  643 |   const group = fixtureGroup(); delete group.collection_coverage; delete group.platform_collection_coverage;
  644 |   if (state === 'empty') { group.partial_items = []; group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  645 |   await setup(page, new Map([[1, group]]));
  646 |   const summary = routeSummary(page);
  647 |   await expect(summary).toContainText('子技能覆盖待确认');
  648 |   await expect(summary).toContainText(`学习时请核对：${skills.map(row => row.text).join('、')}`);
  649 |   await expect(summary.getByRole('link')).toHaveCount(0);
  650 |   if (state === 'empty') {
  651 |     await expect(summary).toContainText('返回调整知识点');
  652 |     await expect(page.locator('.group-empty')).toContainText('本次没有找到');
  653 |   } else await expect(summary).toContainText('先到原平台核对简介或目录');
  654 | });
  655 | 
  656 | test('phase2：切换版本只显示该版本可见资源的依据', async ({ page }) => {
  657 |   const old = fixtureGroup(); const latest = fixtureGroup();
  658 |   old.partial_items = [old.partial_items![0]]; latest.partial_items = [latest.partial_items![1]];
  659 |   for (const group of [old, latest]) { group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  660 |   await setup(page, new Map([[1, old], [2, latest]]));
  661 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[1].text]);
  662 |   await page.goto('/?project=coverage-project&version=1');
  663 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  664 |   await expect(page.locator('[data-resource-id="mean-video"]')).toHaveCount(0);
  665 |   await expect(page.getByRole('button', { name: /重新检索这些知识点/ })).toHaveCount(0);
  666 | });
  667 | 
  668 | async function contrast(page: Page) {
  669 |   return page.locator('.unit-coverage').evaluate(container => {
  670 |     const channels = (value: string) => value.match(/[\d.]+/g)!.map(Number);
  671 |     const luminance = (rgb: number[]) => rgb.slice(0, 3).map(n => n / 255 <= .04045 ? n / 255 / 12.92 : ((n / 255 + .055) / 1.055) ** 2.4).reduce((sum, n, i) => sum + n * [.2126,.7152,.0722][i], 0);
  672 |     const background = (element: Element): number[] => { const c = channels(getComputedStyle(element).backgroundColor); return c.length < 4 || c[3] > 0 ? c : background(element.parentElement!); };
  673 |     return [...container.querySelectorAll('h5,h6,li>span,li>small,.unit-coverage-missing li,.unit-coverage-next p,.unit-coverage-next a,.unit-coverage-practice span,.unit-coverage-note,.unit-coverage-heading>span')].filter(e => e.checkVisibility()).map(element => {
  674 |       const style = getComputedStyle(element); const a = luminance(channels(style.color)); const b = luminance(background(element));
  675 |       return { text: element.textContent?.trim(), ratio: (Math.max(a,b)+.05)/(Math.min(a,b)+.05), fontSize: style.fontSize };
  676 |     });
  677 |   });
  678 | }
  679 | for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
  680 |   test(`phase2：${viewport.name} 学习路线可读、无横溢并保留三步设计`, async ({ page }) => {
  681 |     await page.setViewportSize({ width: viewport.width, height: viewport.height });
  682 |     await setup(page, new Map([[1, fixtureGroup()]]));
  683 |     await expect(page.locator('.stage-navigation [aria-current="step"]')).toContainText('推荐视频');
  684 |     await expect(page.locator('h1')).toContainText('让知识，走进你的项目。');
  685 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  686 |     const observations = await contrast(page); expect(observations.length).toBeGreaterThan(10);
  687 |     expect(observations.every(row => row.ratio >= 4.5), JSON.stringify(observations)).toBe(true);
  688 |     await mkdir(resolve(root,'screenshots'), { recursive: true });
  689 |     await writeFile(resolve(root,`coverage-${viewport.name}.json`), JSON.stringify({ kind: 'isolated fixture UI observations', viewport, contrast: observations, horizontalOverflow: false },null,2));
  690 |     await page.screenshot({ path: resolve(root,`screenshots/coverage-${viewport.name}-entry.png`), animations: 'disabled' });
  691 |     await routeSummary(page).scrollIntoViewIfNeeded();
  692 |     await page.screenshot({ path: resolve(root,`screenshots/coverage-${viewport.name}-detail.png`), animations: 'disabled' });
  693 |   });
  694 | }
  695 | 
  696 | test('phase2：键盘可从平台筛选到视频入口，减少动态偏好保持静态路线', async ({ page }) => {
  697 |   await page.emulateMedia({ reducedMotion: 'reduce' });
  698 |   await setup(page, new Map([[1, fixtureGroup()]]));
  699 |   await page.getByLabel('项目课程来源').focus(); await page.keyboard.press('Tab');
```