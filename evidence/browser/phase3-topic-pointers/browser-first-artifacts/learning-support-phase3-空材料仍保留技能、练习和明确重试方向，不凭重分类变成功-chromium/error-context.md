# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: learning-support.spec.ts >> phase3 空材料仍保留技能、练习和明确重试方向，不凭重分类变成功
- Location: tests\learning-support.spec.ts:141:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('complementary', { name: 'pandas 时间解析与筛选的学习路线', exact: true }).locator('.learning-route-next')
Expected substring: "尚未找到可用材料"
Received string:    "下一步尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。"
Timeout: 7000ms

Call log:
  - Expect "toContainText" getByRole('complementary', { name: 'pandas 时间解析与筛选的学习路线', exact: true }).locator('.learning-route-next') with timeout 7000ms
  - waiting for getByRole('complementary', { name: 'pandas 时间解析与筛选的学习路线', exact: true }).locator('.learning-route-next')
    17 × locator resolved to <div class="learning-route-next">…</div>
       - unexpected value "下一步尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。"

```

```yaml
- strong: 下一步
- paragraph: 尚无已确认技能教学范围的主要推荐。请保留学习目标，继续核对资料，或调整后重新检索。
```

# Test source

```ts
  45  |       versions: Array.from({ length: edited ? 2 : fixture.current }, (_, i) => ({ version: i + 1, status: 'partial', created_at: time })),
  46  |       version: { version, status: edited ? 'analyzed' : 'partial', input, analysis, confirmation: edited ? null : { confirmed_at: time }, batches: edited ? [] : [{ batch_id: 'batch-1', job_id: 'job-1', status: 'completed', project_knowledge_point_ids: [point.id] }], error: null, created_at: time },
  47  |       points: edited ? [] : [{ project_knowledge_point_id: point.id, name: point.name, selection: 'learn', status: 'partial', batch_id: 'batch-1', job_id: 'job-1', knowledge_point_id: result?.knowledge_point_id || null, result }] };
  48  |   };
  49  |   await page.route('**/*', async route => {
  50  |     const request = route.request(), url = new URL(request.url()), origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5177').origin;
  51  |     if (url.origin === origin && !url.pathname.startsWith('/api/')) return route.continue();
  52  |     if (request.method() === 'GET' && url.pathname === '/api/capabilities') return route.fulfill({ json: caps });
  53  |     if (request.method() === 'GET' && url.pathname === '/api/projects') return route.fulfill({ json: { projects: [{ project_id: 'skills-project', name: input.name, current_version: view().current_version, created_at: time, updated_at: time }] } });
  54  |     if (request.method() === 'GET' && url.pathname === '/api/projects/skills-project/results') return route.fulfill({ json: view() });
  55  |     if (request.method() === 'POST' && url.pathname === '/api/projects/skills-project/edit') { const body = request.postDataJSON() as { analysis: ProjectAnalysis }; log.writes.push({ path: url.pathname, body }); edited = body.analysis; return route.fulfill({ json: view() }); }
  56  |     if (request.resourceType() === 'image' && /^https:\/\/i\d+\.hdslb\.com\//.test(url.href)) return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jrZkAAAAASUVORK5CYII=', 'base64') });
  57  |     log.unexpected.push(`${request.method()} ${url.href}`); return route.abort('blockedbyclient');
  58  |   });
  59  |   await page.emulateMedia({ reducedMotion: 'reduce' });
  60  |   await page.goto(`/?project=skills-project&version=${fixture.selected}`);
  61  |   await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
  62  |   await expect(page.getByRole('heading', { name: `项目课程结果 · v${fixture.selected}` })).toBeVisible();
  63  |   await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  64  |   return { fixture, log };
  65  | }
  66  | const route = (page: Page) => page.getByRole('complementary', { name: 'pandas 时间解析与筛选的学习路线', exact: true });
  67  | 
  68  | test('phase3 两轴：内容、标题线索和项目实践分别表达，项目参数不进入技能行', async ({ page }) => {
  69  |   const { log } = await setup(page), panel = route(page), learning = panel.getByRole('region', { name: '先学这些技能' });
  70  |   await expect(panel.locator('[data-skill-id="skill_1"]')).toHaveAttribute('data-skill-state', 'content');
  71  |   await expect(panel.locator('[data-skill-id="skill_2"]')).toHaveAttribute('data-skill-state', 'title');
  72  |   await expect(panel.locator('.transferable-skills>li')).toHaveCount(2);
  73  |   await expect(learning).not.toContainText('end < start');
  74  |   const practice = panel.getByRole('region', { name: '带回项目练习' });
  75  |   await expect(practice).toContainText('待自己实践'); await expect(practice).toContainText('end < start'); await expect(practice).toContainText('end==start仍有效');
  76  |   await expect(practice).toContainText('构造一条相等时间记录');
  77  |   const legacy = panel.locator('.legacy-requirements'); await expect(legacy).not.toHaveAttribute('open', '');
  78  |   await panel.locator('[data-skill-id="skill_2"] summary').click();
  79  |   await expect(panel.locator('[data-skill-id="skill_2"]')).toContainText('尚未确认具体教学、参数和项目应用');
  80  |   await expect(panel.locator('[data-skill-id="skill_2"] .basis-title')).toHaveText('本课标题明确');
  81  |   await expect(panel.locator('.learning-route-next')).toContainText('再按项目要求试做');
  82  |   await mkdir(out, { recursive: true });
  83  |   await panel.screenshot({ path: resolve(out, 'source-title-expanded.png'), animations: 'disabled' });
  84  |   expect(log.writes).toEqual([]);
  85  | });
  86  | test('phase3 平台筛选只统计可见来源；同一项目练习不被隐去或自动完成', async ({ page }) => {
  87  |   await setup(page); const panel = route(page);
  88  |   await expect(panel.locator('[data-skill-id="skill_1"]')).toHaveAttribute('data-skill-state', 'content');
  89  |   await page.getByLabel('项目课程来源').selectOption('other');
  90  |   await expect(panel.locator('[data-skill-id="skill_1"]')).toHaveAttribute('data-skill-state', 'unknown');
  91  |   await expect(panel.locator('[data-skill-id="skill_2"]')).toHaveAttribute('data-skill-state', 'title');
  92  |   await expect(panel.locator('.project-practice-axis')).toContainText('待自己实践');
  93  |   await page.getByLabel('项目课程来源').selectOption('bilibili');
  94  |   await expect(panel.locator('[data-skill-id="skill_2"]')).toHaveAttribute('data-skill-state', 'unknown');
  95  | });
  96  | test('phase3 损坏哈希或跨技能借用引文不能展示为内容依据', async ({ page }) => {
  97  |   const fixture = { analysis: document(), result: group(), current: 1, selected: 1 };
  98  |   fixture.result.partial_items![0].match.teaching_support![0].source_text_sha256 = '0'.repeat(64);
  99  |   await setup(page, fixture);
  100 |   await expect(route(page).locator('[data-skill-id="skill_1"]')).toHaveAttribute('data-skill-state', 'unknown');
  101 |   fixture.result.partial_items![0].match.teaching_support![0].skill = '识别缺失值';
  102 |   await page.reload(); await expect(route(page).locator('[data-skill-id="skill_1"]')).toHaveAttribute('data-skill-state', 'unknown');
  103 |   await expect(route(page).locator('.project-practice-axis')).toContainText('end==start仍有效');
  104 | });
  105 | test('phase3 历史实际APIcore只显示局部标题线索，不造新技能；旧明细折叠且不可编辑', async ({ page }) => {
  106 |   const old = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/api-operation-core-coverage.json'), 'utf8')) as { planned: ProjectAnalysis['knowledge_points'][number]; result_group: ResultGroup };
  107 |   const analysis = document(); analysis.knowledge_points = [old.planned]; analysis.functions[0].id = old.planned.function_ids[0];
  108 |   await setup(page, { analysis, result: old.result_group, current: 2, selected: 1 });
  109 |   const panel = page.getByRole('complementary', { name: `${old.planned.name}的学习路线`, exact: true });
  110 |   await expect(panel.locator('.transferable-skills')).toHaveCount(0);
  111 |   await expect(panel.locator('.legacy-learning-clues')).toContainText('pandas.to_datetime API 使用核心（参数未确认）');
  112 |   await expect(panel.locator('.legacy-requirements')).not.toHaveAttribute('open', '');
  113 |   await mkdir(out, { recursive: true });
  114 |   await panel.screenshot({ path: resolve(out, 'historical-api-core-clue.png'), animations: 'disabled' });
  115 |   await panel.locator('.legacy-requirements>summary').click(); await expect(panel.locator('.unit-coverage')).toContainText('0 / 8 项有内容依据');
  116 |   await page.locator('.stage-navigation').getByRole('button', { name: /02.*选择知识点/ }).click();
  117 |   await page.locator('.point-details>summary').click();
  118 |   await expect(page.getByLabel('准备学习的可迁移技能')).toBeDisabled();
  119 |   await expect(page.getByRole('button', { name: '保存修改，稍后确认' })).toHaveCount(0);
  120 | });
  121 | test('phase3 新技能可编辑保存，原concepts/任务/检查原样保留；6条上限明确失败可恢复', async ({ page }) => {
  122 |   const { log, fixture } = await setup(page);
  123 |   await page.locator('.stage-navigation').getByRole('button', { name: /02.*选择知识点/ }).click();
  124 |   await page.locator('.point-details>summary').click();
  125 |   const field = page.getByLabel('准备学习的可迁移技能'); await expect(field).toHaveValue(skills.join('\n'));
  126 |   await mkdir(out, { recursive: true });
  127 |   await page.screenshot({ path: resolve(out, 'editable-learning-skills.png'), fullPage: true, animations: 'disabled' });
  128 |   await field.fill(Array.from({ length: 7 }, (_, index) => `技能${index + 1}`).join('\n'));
  129 |   await page.getByRole('button', { name: '保存修改，稍后确认' }).click();
  130 |   await expect(page.getByRole('alert')).toContainText('最多填写 6 条'); expect(log.writes).toHaveLength(0);
  131 |   await field.fill('  日期解析方法  \n缺失识别\n');
  132 |   await page.getByRole('button', { name: '保存修改，稍后确认' }).click();
  133 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  134 |   expect(log.writes).toHaveLength(1);
  135 |   const saved = (log.writes[0].body as { analysis: ProjectAnalysis }).analysis.knowledge_points[0];
  136 |   expect(saved.learning_skills).toEqual(['日期解析方法', '缺失识别']);
  137 |   expect(saved.concepts).toEqual(fixture.analysis.knowledge_points[0].concepts);
  138 |   expect(saved.project_task).toEqual(fixture.analysis.knowledge_points[0].project_task);
  139 |   expect(saved.practice_check).toEqual(fixture.analysis.knowledge_points[0].practice_check);
  140 | });
  141 | test('phase3 空材料仍保留技能、练习和明确重试方向，不凭重分类变成功', async ({ page }) => {
  142 |   await setup(page, { analysis: document(), result: null, current: 1, selected: 1 });
  143 |   const panel = route(page);
  144 |   await expect(panel.locator('.transferable-skills>li')).toHaveCount(2);
> 145 |   await expect(panel.locator('.learning-route-next')).toContainText('尚未找到可用材料');
      |                                                       ^ Error: expect(locator).toContainText(expected) failed
  146 |   await expect(panel.locator('.project-practice-axis')).toContainText('待自己实践');
  147 |   await expect(panel.locator('.learning-route-next')).not.toContainText('等待材料');
  148 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  149 |   await mkdir(out, { recursive: true });
  150 |   await panel.screenshot({ path: resolve(out, 'empty-materials-practice-retained.png'), animations: 'disabled' });
  151 | });
  152 | test('phase3 三尺寸、键盘与减少动态：技能依据可展开、练习不被标成已完成', async ({ page }) => {
  153 |   await setup(page); const panel = route(page);
  154 |   await expect(panel.locator('[data-skill-id="skill_1"]')).toHaveAttribute('data-skill-state', 'content');
  155 |   await mkdir(out, { recursive: true }); const observations = [];
  156 |   for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
  157 |     await page.setViewportSize({ width: viewport.width, height: viewport.height });
  158 |     expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
  159 |     const motion = await panel.evaluate(node => ({ animation: getComputedStyle(node).animationName, scroll: getComputedStyle(globalThis.document.documentElement).scrollBehavior }));
  160 |     expect(motion.animation).toBe('none'); expect(motion.scroll).not.toBe('smooth');
  161 |     expect(await page.evaluate(() => globalThis.document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  162 |     const colors = await panel.evaluate(node => {
  163 |       const channels = (value: string) => value.match(/[\d.]+/g)!.map(Number);
  164 |       const lum = (rgb: number[]) => rgb.slice(0, 3).map(n => n / 255 <= .04045 ? n / 255 / 12.92 : ((n / 255 + .055) / 1.055) ** 2.4).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
  165 |       const bg = (e: Element): number[] => { const color = channels(getComputedStyle(e).backgroundColor); return color.length < 4 || color[3] > 0 ? color : bg(e.parentElement!); };
  166 |       return [...node.querySelectorAll('h5,h6,p,strong,.skill-support-state,.practice-state')].filter(e => e.checkVisibility()).map(e => { const a = lum(channels(getComputedStyle(e).color)), b = lum(bg(e)); return { text: e.textContent?.trim(), ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) }; });
  167 |     });
  168 |     expect(colors.every(row => row.ratio >= 4.5), JSON.stringify(colors)).toBe(true);
  169 |     await page.screenshot({ path: resolve(out, `two-axes-${viewport.name}.png`), fullPage: true, animations: 'disabled' });
  170 |     observations.push({ viewport, overflow: false, reducedMotion: motion, colors });
  171 |   }
  172 |   const summary = panel.locator('[data-skill-id="skill_1"] summary'); await summary.focus(); await page.keyboard.press('Enter');
  173 |   await expect(panel.locator('[data-skill-id="skill_1"] details')).toHaveAttribute('open', '');
  174 |   await expect(panel.locator('[data-skill-id="skill_1"] blockquote')).toContainText('解析日期时间');
  175 |   await page.keyboard.press('Tab'); await expect(panel.locator('[data-skill-id="skill_1"] a')).toBeFocused();
  176 |   await expect(panel.locator('.practice-state')).toHaveText('待自己实践');
  177 |   await writeFile(resolve(out, 'responsive-observations.json'), JSON.stringify({ mock: true, viewports: observations, keyboardEvidenceDetailsOpened: true, sourcePlaybackOrTeachingQualityAccepted: false }, null, 2));
  178 | });
  179 | 
```