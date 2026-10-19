# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project-coverage.spec.ts >> phase2：empty 覆盖信息给出待核对内容与下一步
- Location: tests\project-coverage.spec.ts:781:52

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: locator('.learning-route-next')
Expected substring: "调整或重新检索"
Received string:    "下一步尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。"
Timeout: 7000ms

Call log:
  - Expect "toContainText" locator('.learning-route-next') with timeout 7000ms
  - waiting for locator('.learning-route-next')
    18 × locator resolved to <div class="learning-route-next">…</div>
       - unexpected value "下一步尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。"

```

```yaml
- strong: 下一步
- paragraph: 尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。
```

# Test source

```ts
  690 |   const widths=[];
  691 |   for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
  692 |     await page.setViewportSize({width:viewport.width,height:viewport.height});
  693 |     const overflow=await page.evaluate(()=>globalThis.document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);
  694 |     const colors=await contrast(page);expect(colors.every(row=>row.ratio>=4.5),JSON.stringify(colors)).toBe(true);
  695 |     await routeSummary(page).scrollIntoViewIfNeeded();
  696 |     await page.screenshot({path:resolve(root,`screenshots/coverage-confirmed-concepts-${viewport.name}.png`),animations:'disabled'});
  697 |     widths.push({viewport,horizontalOverflow:overflow,contrast:colors});
  698 |   }
  699 |   await writeFile(resolve(root,'confirmed-concepts-widths.json'),JSON.stringify({kind:'isolated UI contract fixtures, not a new service request',widths},null,2));
  700 | });
  701 | 
  702 | test('phase2 concepts：目标只接收同ID同原文的自身证据，隐藏平台与错配目标不能补齐', async ({page})=>{
  703 |   const group=fixtureGroup();const target=course('confirmed-read-target','read','page','other');
  704 |   const first={id:'learning_target_1',text:skills[0].text};
  705 |   target.match.subtopic_coverage=[{...first,status:'supported',evidence_ids:target.match.supporting_evidence_ids!,reason:'当前视频自己的内容支持目标原文'}];
  706 |   group.collection_coverage!.decomposition_status='unknown';
  707 |   group.collection_coverage!.subtopics=skills.map((skill,index)=>({id:`learning_target_${index+1}`,text:skill.text,status:'supported',resource_ids:[target.resource.resource_id],evidence_ids:target.match.supporting_evidence_ids!}));
  708 |   const review=course('review-target','export');review.match.topic_evidence_status='needs_review';
  709 |   review.match.subtopic_coverage=[{id:'learning_target_3',text:skills[2].text,status:'supported',evidence_ids:review.match.supporting_evidence_ids!,reason:'待核实不能计入'}];
  710 |   group.partial_items=[target];group.partial_platform_items={other:[target]};group.review_items=[review];group.review_platform_items={bilibili:[review]};
  711 |   await setup(page,new Map([[1,group]]));
  712 |   await expect(routeSummary(page)).toContainText('1 / 3 项有内容依据');
  713 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  714 |   await page.getByLabel('项目课程来源').selectOption('bilibili');
  715 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  716 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  717 |   await page.getByLabel('项目课程来源').selectOption('all');
  718 |   target.match.subtopic_coverage[0].text=skills[1].text;await page.reload();await openLegacy(page);
  719 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  720 |   target.match.subtopic_coverage[0].text=skills[0].text;
  721 |   group.collection_coverage!.subtopics[0].text=skills[1].text;await page.reload();await openLegacy(page);
  722 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  723 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText([skills[1].text,skills[2].text,skills[0].text]);
  724 |   await expect(routeSummary(page).getByRole('link')).toHaveCount(0);
  725 | });
  726 | 
  727 | test('phase2 concepts：旧结果只有whole_topic时确认概念仍保留，未汇总目标与标题同文不能借用整单元支持', async ({page})=>{
  728 |   const text=skills[0].text;const item=course('historical-whole-only','read');item.match.topic_evidence_status='supported';
  729 |   item.match.subtopic_coverage=[{id:'whole_topic',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'只评估整单元'},
  730 |     {id:'learning_target_1',text,status:'supported',evidence_ids:item.match.supporting_evidence_ids!,reason:'缺少该目标的当前汇总行，不能借用'}];
  731 |   const group:ResultGroup={knowledge_point_id:'job-point-1',text,total_matches:1,items:[item],collection_coverage:{
  732 |     decomposition_status:'not_applicable',shared_context:[],status:'all_subtopics_supported',single_resource_full_coverage:true,disclaimer:'旧标题结果',
  733 |     subtopics:[{id:'whole_topic',text,status:'supported',resource_ids:[item.resource.resource_id],evidence_ids:item.match.supporting_evidence_ids!}],
  734 |   }};
  735 |   await setup(page,new Map([[1,group]]));
  736 |   await expect(routeSummary(page)).toContainText('0 / 3 项有内容依据');
  737 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveCount(0);
  738 |   await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  739 |   await expect(routeSummary(page).locator('.unit-coverage-missing li').first()).toHaveAttribute('data-requirement-ids',JSON.stringify(['whole_topic','learning_target_1']));
  740 |   await expect(routeSummary(page).getByRole('link')).toHaveCount(0);
  741 |   await expect(routeSummary(page)).toContainText('不代表整单元教学完整，也不代表已完成项目实践');
  742 | });
  743 | 
  744 | test('phase2：全部子项有依据仍保留练习与完整性边界，不宣称已掌握', async ({ page }) => {
  745 |   const group = fixtureGroup();
  746 |   const third = course('export-video', 'export', 'catalog');
  747 |   group.partial_items = [...group.partial_items!.slice(0, 2), third]; group.partial_platform_items = undefined;
  748 |   await setup(page, new Map([[1, group]]));
  749 |   const summary = routeSummary(page);
  750 |   await expect(summary).toContainText('3 / 3 项有内容依据');
  751 |   await expect(summary.locator('.unit-coverage-missing')).toContainText('仍需核对深度与完整性');
  752 |   await expect(summary).toContainText('项目应用则需要自己实践');
  753 |   await expect(summary).not.toContainText('已掌握');
  754 |   await expect(summary).toContainText('不代表已完成项目实践');
  755 | });
  756 | 
  757 | test('phase2：错配ID、标题字段、重复记录、目录篡改及跨资源引用不能成为内容依据', async ({ page }) => {
  758 |   const group = fixtureGroup(); group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined;
  759 |   const variants: [string, (item: ResourceItem) => void][] = [
  760 |     ['missing ID', item => { item.match.supporting_evidence_ids = ['missing']; }],
  761 |     ['wrong point', item => { item.match.knowledge_point_id = 'old-point'; }],
  762 |     ['wrong resource', item => { item.match.resource_id = 'different-resource'; }],
  763 |     ['title only', item => { item.evidence[0].field = 'title'; }],
  764 |     ['duplicate evidence', item => { item.evidence.push(structuredClone(item.evidence[0])); }],
  765 |     ['foreign URL', item => { item.evidence[0].url = 'https://example.org/another-course'; }],
  766 |     ['unbound description', item => { item.resource.description = '另一份描述'; }],
  767 |     ['wrong subtopic text', item => { item.match.subtopic_coverage![0].text = '无关的标题命中'; }],
  768 |     ['tampered catalog', item => { item.resource.chapters[0].title = '篡改的目录标题'; }],
  769 |   ];
  770 |   group.partial_items = [course('invalid', 'read')];
  771 |   await setup(page, new Map([[1, group]]));
  772 |   for (const [label, mutate] of variants) {
  773 |     const candidate = course('invalid', 'read', label === 'tampered catalog' ? 'catalog' : 'page'); mutate(candidate);
  774 |     group.partial_items = [candidate]; await page.reload();await openLegacy(page);
  775 |     await expect(routeSummary(page), label).toContainText('0 / 3 项有内容依据');
  776 |     await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(row => row.text));
  777 |     await expect(routeSummary(page).getByRole('link', { name: /查看已有要求依据/ })).toHaveCount(0);
  778 |   }
  779 | });
  780 | 
  781 | for (const state of ['missing', 'empty'] as const) test(`phase2：${state} 覆盖信息给出待核对内容与下一步`, async ({ page }) => {
  782 |   const group = fixtureGroup(); delete group.collection_coverage; delete group.platform_collection_coverage;
  783 |   if (state === 'empty') { group.partial_items = []; group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  784 |   await setup(page, new Map([[1, group]]));
  785 |   const summary = routeSummary(page);
  786 |   await expect(summary).toContainText('子技能覆盖待确认');
  787 |   await expect(summary).toContainText(`学习时请核对：${skills.map(row => row.text).join('、')}`);
  788 |   await expect(summary.getByRole('link')).toHaveCount(0);
  789 |   if (state === 'empty') {
> 790 |     await expect(primaryNext(page)).toContainText('调整或重新检索');
      |                                     ^ Error: expect(locator).toContainText(expected) failed
  791 |     await expect(page.locator('.group-empty')).toContainText('本次没有找到');
  792 |   } else await expect(primaryNext(page)).toContainText('已有相关材料');
  793 | });
  794 | 
  795 | test('phase2：切换版本只显示该版本可见资源的依据', async ({ page }) => {
  796 |   const old = fixtureGroup(); const latest = fixtureGroup();
  797 |   old.partial_items = [old.partial_items![0]]; latest.partial_items = [latest.partial_items![1]];
  798 |   for (const group of [old, latest]) { group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  799 |   await setup(page, new Map([[1, old], [2, latest]]));
  800 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[1].text]);
  801 |   await page.goto('/?project=coverage-project&version=1');
  802 |   await openLegacy(page);
  803 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  804 |   await expect(page.locator('[data-resource-id="mean-video"]')).toHaveCount(0);
  805 |   await expect(page.getByRole('button', { name: /重新检索这些知识点/ })).toHaveCount(0);
  806 | });
  807 | 
  808 | async function contrast(page: Page) {
  809 |   return page.locator('.unit-coverage').evaluate(container => {
  810 |     const channels = (value: string) => value.match(/[\d.]+/g)!.map(Number);
  811 |     const luminance = (rgb: number[]) => rgb.slice(0, 3).map(n => n / 255 <= .04045 ? n / 255 / 12.92 : ((n / 255 + .055) / 1.055) ** 2.4).reduce((sum, n, i) => sum + n * [.2126,.7152,.0722][i], 0);
  812 |     const background = (element: Element): number[] => { const c = channels(getComputedStyle(element).backgroundColor); return c.length < 4 || c[3] > 0 ? c : background(element.parentElement!); };
  813 |     return [...container.querySelectorAll('h5,h6,li>span,li>small,.unit-coverage-supported p,.unit-coverage-missing li,.unit-coverage-next p,.unit-coverage-next a,.unit-coverage-practice span,.unit-coverage-note,.unit-coverage-heading>span')].filter(e => e.checkVisibility()).map(element => {
  814 |       const style = getComputedStyle(element); const a = luminance(channels(style.color)); const b = luminance(background(element));
  815 |       return { text: element.textContent?.trim(), ratio: (Math.max(a,b)+.05)/(Math.min(a,b)+.05), fontSize: style.fontSize };
  816 |     });
  817 |   });
  818 | }
  819 | for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
  820 |   test(`phase2：${viewport.name} 学习路线可读、无横溢并保留三步设计`, async ({ page }) => {
  821 |     await page.setViewportSize({ width: viewport.width, height: viewport.height });
  822 |     await setup(page, new Map([[1, fixtureGroup()]]));
  823 |     await expect(page.locator('.stage-navigation [aria-current="step"]')).toContainText('推荐视频');
  824 |     await expect(page.locator('h1')).toContainText('让知识，走进你的项目。');
  825 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  826 |     const observations = await contrast(page); expect(observations.length).toBeGreaterThan(10);
  827 |     expect(observations.every(row => row.ratio >= 4.5), JSON.stringify(observations)).toBe(true);
  828 |     await mkdir(resolve(root,'screenshots'), { recursive: true });
  829 |     await writeFile(resolve(root,`coverage-${viewport.name}.json`), JSON.stringify({ kind: 'isolated fixture UI observations', viewport, contrast: observations, horizontalOverflow: false },null,2));
  830 |     await page.screenshot({ path: resolve(root,`screenshots/coverage-${viewport.name}-entry.png`), animations: 'disabled' });
  831 |     await routeSummary(page).scrollIntoViewIfNeeded();
  832 |     await page.screenshot({ path: resolve(root,`screenshots/coverage-${viewport.name}-detail.png`), animations: 'disabled' });
  833 |   });
  834 | }
  835 | 
  836 | test('phase2：键盘可从平台筛选到视频入口，减少动态偏好保持静态路线', async ({ page }) => {
  837 |   await page.emulateMedia({ reducedMotion: 'reduce' });
  838 |   await setup(page, new Map([[1, fixtureGroup()]]));
  839 |   await page.locator('.legacy-requirements>summary').click();
  840 |   await page.getByLabel('项目课程来源').focus(); await page.keyboard.press('Tab');
  841 |   await expect(page.locator('.legacy-requirements>summary')).toBeFocused();
  842 |   await page.keyboard.press('Enter'); await page.keyboard.press('Tab');
  843 |   const link = routeSummary(page).getByRole('link', { name: /查看已有要求依据/ });
  844 |   await expect(link).toBeFocused();
  845 |   await expect(link).toHaveAttribute('target','_blank'); await expect(link).toHaveAttribute('rel','noopener noreferrer');
  846 |   const motion = await routeSummary(page).evaluate(element => [...element.querySelectorAll('*'),element].map(node => ({ animation: getComputedStyle(node).animationName, transition: getComputedStyle(node).transitionDuration })));
  847 |   expect(motion.every(row => row.animation === 'none' && row.transition === '0s')).toBe(true);
  848 |   await mkdir(resolve(root,'screenshots'), { recursive: true });
  849 |   await page.screenshot({ path: resolve(root,'screenshots/coverage-keyboard-reduced-motion.png'), animations: 'disabled' });
  850 | });
  851 | 
```