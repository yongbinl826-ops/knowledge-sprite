# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project-coverage.spec.ts >> phase2 单元状态：项目仍运行时已结束空单元不再等待，排队单元等待，已有部分依据仍可学习
- Location: tests\project-coverage.spec.ts:278:1

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
  184 |     if(request.method()==='GET'&&url.pathname===`/api/projects/${view.project_id}/results`)return route.fulfill({json:view});
  185 |     if(request.resourceType()==='image')return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jrZkAAAAASUVORK5CYII=','base64')});
  186 |     log.unexpected.push(`${request.method()} ${url.href}`);return route.abort('blockedbyclient');
  187 |   });
  188 |   await page.emulateMedia({reducedMotion:'reduce'});
  189 |   await page.goto(`/?project=${view.project_id}&version=1`);
  190 |   const select=page.getByRole('button',{name:mismatch.name,exact:true});
  191 |   await select.focus();await page.keyboard.press('Enter');
  192 |   const point=page.locator('.project-result-point'),notice=page.getByRole('status',{name:'检索范围需重试',exact:true});
  193 |   await expect(point).toHaveCount(1);await expect(notice).toContainText(mismatch.result!.scope_notice!);
  194 |   await expect(notice).toContainText(mismatch.result!.expected_search_text!);
  195 |   await expect(notice).toContainText('创建新版本');
  196 |   await expect(point).toContainText('检索范围需重试 · 0 条推荐');
  197 |   await expect(point.locator('.resource-card,.unit-coverage')).toHaveCount(0);
  198 |   await expect(page.locator('.search-progress,.skeleton-card')).toHaveCount(0);
  199 |   await expect(point).not.toContainText('本次没有找到');await expect(point).not.toContainText('正在读取');
  200 |   await expect(page.getByRole('button',{name:'重新检索这些知识点'})).toBeEnabled();
  201 |   await mkdir(resolve(root,'screenshots'),{recursive:true});const observations=[];
  202 |   for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
  203 |     await page.setViewportSize({width:viewport.width,height:viewport.height});
  204 |     const overflow=await page.evaluate(()=>globalThis.document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);
  205 |     const colors=await notice.evaluate(element=>{
  206 |       const rgb=(s:string)=>s.match(/[\d.]+/g)!.map(Number);
  207 |       const lum=(c:number[])=>c.slice(0,3).map(n=>n/255<=.04045?n/255/12.92:((n/255+.055)/1.055)**2.4).reduce((sum,n,i)=>sum+n*[.2126,.7152,.0722][i],0);
  208 |       const bg=(e:Element):number[]=>{const c=rgb(getComputedStyle(e).backgroundColor);return c.length<4||c[3]>0?c:bg(e.parentElement!);};
  209 |       return [...element.querySelectorAll('p')].map(node=>{const s=getComputedStyle(node),a=lum(rgb(s.color)),b=lum(bg(node));return {text:node.textContent,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};});
  210 |     });
  211 |     expect(colors.length).toBe(3);expect(colors.every(row=>row.ratio>=4.5)).toBe(true);
  212 |     await notice.scrollIntoViewIfNeeded();
  213 |     await page.screenshot({path:resolve(root,`screenshots/scope-mismatch-${viewport.name}.png`),animations:'disabled'});
  214 |     observations.push({viewport,overflow,colors});
  215 |   }
  216 |   await writeFile(resolve(root,'scope-mismatch-observations.json'),JSON.stringify({mock:true,source:'actual retained Dashboard v1 -> staged backend pure read projection, not a new network search',fixtureSha256:'09ad8aecf65917409956edda81bba62b409f792756ef9e85193df928b76e8a01',observations},null,2));
  217 |   const stale=structuredClone(view.points!.find(row=>row.result?.partial_items?.length)!.result!.partial_items![0]);
  218 |   stale.resource.title='Excel GROUPBY 旧范围课程';
  219 |   mismatch.status='partial';mismatch.result!.items=[stale];mismatch.result!.partial_items=[stale];mismatch.result!.review_items=[stale];
  220 |   mismatch.result!.platform_items={excel:[stale]};mismatch.result!.partial_platform_items={excel:[stale]};mismatch.result!.review_platform_items={excel:[stale]};
  221 |   mismatch.result!.collection_coverage!.status='all_subtopics_supported';
  222 |   await page.reload();await openLegacy(page);await page.getByRole('button',{name:mismatch.name,exact:true}).click();
  223 |   await expect(notice).toBeVisible();await expect(point.locator('.resource-card,.unit-coverage')).toHaveCount(0);
  224 |   await expect(page.locator('#project-platform-filter option[value="excel"]')).toHaveCount(0);
  225 |   delete mismatch.result!.scope_status;mismatch.status='scope_mismatch';
  226 |   mismatch.result!.scope_notice='<img src=x onerror="window.__scopeInjected=1"> 范围需重试';
  227 |   await page.reload();await openLegacy(page);await page.getByRole('button',{name:mismatch.name,exact:true}).click();
  228 |   await expect(notice).toContainText('<img src=x');await expect(notice.locator('img,script')).toHaveCount(0);
  229 |   await expect(point.locator('.resource-card,.unit-coverage')).toHaveCount(0);
  230 |   expect(await page.evaluate(()=>(window as Window & {__scopeInjected?:number}).__scopeInjected)).toBeUndefined();
  231 | });
  232 | 
  233 | test('phase2 精确同文：拆分与确认目标只显示一次，未知成员和隐藏来源不借用已有支持',async({page})=>{
  234 |   const group=fixtureGroup();const document=structuredClone(analysis);
  235 |   document.knowledge_points[0].concepts=[skills[0].text,skills[1].text];
  236 |   const original=course('exact-title-video','read');
  237 |   const target=structuredClone(original);target.resource.resource_id='exact-target-video';target.resource.platform='other';
  238 |   target.match.resource_id=target.resource.resource_id;
  239 |   target.match.subtopic_coverage=[{id:'learning_target_1',text:skills[0].text,status:'supported',evidence_ids:[original.evidence[0].evidence_id],reason:'隔离已绑定正文'}];
  240 |   const extra:CollectionCoverage['subtopics'][number]={id:'learning_target_1',text:skills[0].text,status:'supported',resource_ids:[target.resource.resource_id],evidence_ids:[original.evidence[0].evidence_id]};
  241 |   group.collection_coverage!.subtopics=[...group.collection_coverage!.subtopics,extra,
  242 |     {id:'learning_target_2',text:skills[1].text,status:'unknown',resource_ids:[],evidence_ids:[]}];
  243 |   group.partial_items=[original,target];group.partial_platform_items={bilibili:[original],other:[target]};group.review_items=[];group.review_platform_items=undefined;
  244 |   await page.emulateMedia({reducedMotion:'reduce'});
  245 |   await setup(page,new Map([[1,group]]),'completed',document);
  246 |   const summary=routeSummary(page);
  247 |   await expect(summary).toContainText('1 / 3 项有内容依据');
  248 |   await expect(summary.locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  249 |   await expect(summary.locator('.unit-coverage-supported small')).toHaveText('2 个当前视频有正文或目录依据');
  250 |   await expect(summary.locator('.unit-coverage-supported li')).toHaveAttribute('data-requirement-ids',JSON.stringify(['read','learning_target_1']));
  251 |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText([skills[1].text,skills[2].text]);
  252 |   await expect(summary.locator('.unit-coverage-missing li').first()).toHaveAttribute('data-requirement-ids',JSON.stringify(['mean','learning_target_2']));
  253 |   await expect(summary.locator('.unit-coverage-next')).toContainText('项目应用则需要自己实践');
  254 |   await mkdir(resolve(root,'screenshots'),{recursive:true});const observations=[];
  255 |   for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
  256 |     await page.setViewportSize({width:viewport.width,height:viewport.height});
  257 |     const overflow=await page.evaluate(()=>globalThis.document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);
  258 |     const colors=await contrast(page);expect(colors.every(row=>row.ratio>=4.5),JSON.stringify(colors)).toBe(true);
  259 |     await page.screenshot({path:resolve(root,`screenshots/coverage-exact-text-${viewport.name}.png`),fullPage:true,animations:'disabled'});
  260 |     observations.push({viewport,overflow,colors});
  261 |   }
  262 |   await writeFile(resolve(root,'exact-text-observations.json'),JSON.stringify({mock:true,observations,scope:'Display grouping after own-source validation; no live source or learning completion claim'},null,2));
  263 |   await page.getByLabel('项目课程来源').selectOption('bilibili');
  264 |   await expect(summary).toContainText('0 / 3 项有内容依据');
  265 |   await expect(summary.locator('.unit-coverage-supported li')).toHaveCount(0);
  266 |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  267 |   await expect(summary.getByRole('link')).toHaveCount(0);
  268 |   await expect(primaryNext(page)).toContainText('切换到全部平台');
  269 |   await page.getByLabel('项目课程来源').selectOption('all');
  270 |   extra.status='unknown';extra.resource_ids=[];extra.evidence_ids=[];
  271 |   await page.reload();await openLegacy(page);
  272 |   await expect(summary).toContainText('0 / 3 项有内容依据');
  273 |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText(skills.map(skill=>skill.text));
  274 |   await expect(summary.getByRole('link')).toHaveCount(0);
  275 |   await expect(summary).toContainText('不代表整单元教学完整');
  276 | });
  277 | 
  278 | test('phase2 单元状态：项目仍运行时已结束空单元不再等待，排队单元等待，已有部分依据仍可学习',async({page})=>{
  279 |   const group=fixtureGroup();group.items=[];group.partial_items=[];group.partial_platform_items=undefined;group.review_items=[];group.review_platform_items=undefined;
  280 |   const state={current:'partial'};
  281 |   await setup(page,new Map([[1,group]]),'running',analysis,input,state);
  282 |   await expect(page.locator('.search-progress')).toContainText('正在执行项目检索');
  283 |   await expect(page.locator('.group-empty')).toContainText('本次检索部分完成，暂无达到技能教学推荐标准的课程');
> 284 |   await expect(primaryNext(page)).toContainText('调整或重新检索');
      |                                   ^ Error: expect(locator).toContainText(expected) failed
  285 |   await expect(primaryNext(page)).not.toContainText('等待材料');
  286 |   for(const status of ['pending','queued','submitted','running']){
  287 |     state.current=status;await page.reload();await openLegacy(page);
  288 |     await expect(primaryNext(page),status).toContainText('检索仍在进行');
  289 |     await expect(primaryNext(page),status).toContainText('等待材料返回');
  290 |   }
  291 |   state.current='partial';group.partial_items=[course('terminal-partial-video','read')];await page.reload();await openLegacy(page);
  292 |   await expect(routeSummary(page)).toContainText('1 / 3 项有内容依据');
  293 |   await expect(primaryNext(page)).toContainText('已有相关材料');
  294 |   await expect(primaryNext(page)).not.toContainText('等待材料');
  295 |   await expect(routeSummary(page).getByRole('link')).toHaveAttribute('href',group.partial_items[0].resource.url);
  296 | });
  297 | 
  298 | function actualFccFixture(file = 'freecodecamp-course-coverage.json', pandas = false) {
  299 |   const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures', file), 'utf8')) as {
  300 |     source_fixture: string; fixture_sha256: string; original_public_source_sha256: string; point_text: string; item: ResourceItem; collection_coverage: CollectionCoverage;
  301 |   };
  302 |   expect(createHash('sha256').update(readFileSync(resolve(sourceRoot, fixture.source_fixture))).digest('hex')).toBe(fixture.fixture_sha256);
  303 |   const partial = fixture.item.match.topic_evidence_status === 'partial';
  304 |   const group: ResultGroup = { knowledge_point_id: 'job-point-1', text: fixture.point_text, total_matches: partial ? 0 : 1, items: partial ? [] : [fixture.item], partial_items: partial ? [fixture.item] : [], collection_coverage: fixture.collection_coverage };
  305 |   const document = structuredClone(analysis); document.knowledge_points[0].name = fixture.point_text;
  306 |   document.knowledge_points[0].concepts = fixture.collection_coverage.subtopics.map(part => part.text);
  307 |   document.knowledge_points[0].learning_goal = '在 Python 程序中接收用户输入并保存到变量';
  308 |   document.knowledge_points[0].practice_check = '独立编写一个询问姓名并回应用户的 Python 程序。';
  309 |   document.knowledge_points[0].technology = 'Python';
  310 |   document.scope='Python 交互练习'; document.technical_plan='Python'; document.functions[0].name='用户输入与回应';
  311 |   const projectInput=pandas ? {...input,name:'Pandas 数据分析工具',requirements:'读取数据并完成选定的数据分析步骤。',technical_version:'Python / pandas'}
  312 |     : {...input,name:'Python 交互小游戏',requirements:'询问姓名并回应用户。',technical_version:'Python'};
  313 |   if(pandas){ document.scope='本地Pandas数据分析';document.technical_plan='Python / pandas';document.functions[0].name='数据分析';document.knowledge_points[0].technology='Python / pandas';
  314 |     document.knowledge_points[0].learning_goal='将本单元的数据分析步骤用在自己的数据表中';document.knowledge_points[0].practice_check='换一份数据表，独立完成所选分析步骤并检查结果。'; }
  315 |   return { fixture, group, document, projectInput };
  316 | }
  317 | 
  318 | function actualTwtFixture(file = 'techwithtim-lesson-coverage.json') {
  319 |   const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures', file), 'utf8')) as {
  320 |     source_fixture: string; fixture_sha256: string; original_public_source_sha256: string; point_text: string; item: ResourceItem; collection_coverage: CollectionCoverage;
  321 |   };
  322 |   expect(createHash('sha256').update(readFileSync(resolve(sourceRoot, fixture.source_fixture))).digest('hex')).toBe(fixture.fixture_sha256);
  323 |   const partial = fixture.item.match.topic_evidence_status === 'partial';
  324 |   const group: ResultGroup = { knowledge_point_id:'job-point-1', text:fixture.point_text, total_matches:partial ? 0 : 1,
  325 |     items:partial ? [] : [fixture.item], partial_items:partial ? [fixture.item] : [], collection_coverage:fixture.collection_coverage };
  326 |   const document = structuredClone(analysis); document.knowledge_points[0].name=fixture.point_text;
  327 |   const targets=fixture.collection_coverage.subtopics.filter(part=>part.id.startsWith('learning_target_'));
  328 |   document.knowledge_points[0].concepts=(targets.length ? targets : fixture.collection_coverage.subtopics.filter(part=>part.id!=='whole_topic')).map(part=>part.text);
  329 |   document.knowledge_points[0].learning_goal='在小游戏中显示本单元对应的界面反馈';
  330 |   document.knowledge_points[0].practice_check='换一组游戏数据，独立实现本单元已选的界面反馈。';
  331 |   document.knowledge_points[0].technology='Python / pygame';
  332 |   document.scope='Python 小游戏'; document.technical_plan='Python / pygame'; document.functions[0].name='游戏文字与碰撞反馈';
  333 |   const projectInput={...input,name:'Python 小游戏',requirements:'显示提示文字并检测矩形碰撞。',technical_version:'Python / pygame'};
  334 |   if(file==='techwithtim-movement-coverage.json'){
  335 |     document.functions[0].name='游戏主循环';projectInput.requirements='为小游戏建立主循环并处理窗口退出事件。';
  336 |     document.knowledge_points[0].learning_goal='在游戏主循环中处理本课展示的事件与画面更新';
  337 |     document.knowledge_points[0].practice_check='独立建立可关闭窗口的游戏主循环。';
  338 |   }else if(file==='techwithtim-snake-coverage.json'){
  339 |     document.functions[0].name='网格线绘制';projectInput.requirements='为小游戏绘制等距网格线。';
  340 |     document.knowledge_points[0].learning_goal='根据本课说明绘制等距网格线';
  341 |     document.knowledge_points[0].practice_check='独立绘制网格线并检查行列是否等距。';
  342 |   }
  343 |   return { fixture,group,document,projectInput };
  344 | }
  345 | 
  346 | for(const lesson of [{key:'movement',title:'Basic Movement & Key Presses'},{key:'snake',title:'Tutorial #1'}]){
  347 |   test(`phase2 TWT DOM v2：真实${lesson.key}自身正文与视频绑定保留实际标题及窄目标`,async({page})=>{
  348 |     const {fixture,group,document,projectInput}=actualTwtFixture(`techwithtim-${lesson.key}-coverage.json`);
  349 |     const proof=JSON.parse(fixture.item.evidence.find(row=>row.field==='video_evidence_status')!.text!);
  350 |     const summary=fixture.item.resource.video_topic_summary!;
  351 |     expect(proof.binding_version).toBe(2);expect(proof.binding_kind).toBe('same_lesson_dom_v2');
  352 |     expect(proof.teaching_binding).not.toMatch(/video above offers/i);
  353 |     expect(fixture.item.resource.title).toBe(lesson.title);expect(fixture.item.match.topic_evidence_status).toBe('supported');
  354 |     expect([...summary].length).toBeLessThanOrEqual(6000);
  355 |     if(lesson.key==='movement')expect([...summary].length).toBeGreaterThan(1800);
  356 |     expect(proof.dom_witness.notes_sha256).toBe(createHash('sha256').update(summary).digest('hex'));
  357 |     expect(proof.dom_witness.notes_characters).toBe([...summary].length);
  358 |     await setup(page,new Map([[1,group]]),'completed',document,projectInput);
  359 |     const route=page.locator('.unit-coverage');
  360 |     await expect(route).toContainText('2 / 2 项有内容依据');
  361 |     await expect(route.locator('.unit-coverage-supported li>span')).toHaveText(fixture.collection_coverage.subtopics.map(row=>row.text));
  362 |     await expect(page.locator('.resource-card h4')).toHaveText(lesson.title);
  363 |     await expect(page.locator('.recommendation-reason')).toHaveText(fixture.item.match.recommendation_reason);
  364 |     await expect(page.locator('iframe,video,.learning-location li')).toHaveCount(0);
  365 |     await expect(route).toContainText('不代表已完成项目实践');
  366 |     await mkdir(resolve(root,'screenshots'),{recursive:true});
  367 |     const widths=[];
  368 |     for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}]){
  369 |       await page.setViewportSize({width:viewport.width,height:viewport.height});
  370 |       const overflow=await page.evaluate(()=>globalThis.document.documentElement.scrollWidth>innerWidth);expect(overflow).toBe(false);
  371 |       const colors=await contrast(page);expect(colors.every(row=>row.ratio>=4.5),JSON.stringify(colors)).toBe(true);
  372 |       await page.screenshot({path:resolve(root,`screenshots/coverage-twt-dom-v2-${lesson.key}-${viewport.name}.png`),fullPage:true,animations:'disabled'});
  373 |       widths.push({viewport,horizontalOverflow:overflow,contrast:colors});
  374 |     }
  375 |     await writeFile(resolve(root,`dom-v2-${lesson.key}-observations.json`),JSON.stringify({kind:'retained actual public HTML replay, not a new fetch or player test',
  376 |       title:lesson.title,sourceFixture:fixture.source_fixture,originalPublicSourceSha256:fixture.original_public_source_sha256,
  377 |       point:fixture.point_text,confirmedConcepts:document.knowledge_points[0].concepts,summaryCharacters:[...summary].length,binding:proof,widths,
  378 |       scope:'Narrow source-binding validation only; no assertion that the actual maze requirements are covered'},null,2));
  379 |   });
  380 | }
  381 | 
  382 | test('phase2 TWT DOM v2：结构旗标、版本降级、标题或摘要破坏不能替代真实自身绑定',async({page})=>{
  383 |   const file='techwithtim-movement-coverage.json';const {group,document,projectInput}=actualTwtFixture(file);
  384 |   await setup(page,new Map([[1,group]]),'completed',document,projectInput);
```