# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project.spec.ts >> 离线 Mock：历史结果保留版本，新版本不混入旧课程；手机布局无溢出
- Location: tests\project.spec.ts:307:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '确认知识点 · v2' })
Expected: visible
Timeout: 7000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('heading', { name: '确认知识点 · v2' }) with timeout 7000ms
  - waiting for getByRole('heading', { name: '确认知识点 · v2' })

```

```yaml
- link "跳转到主要内容":
  - /url: "#stage-title"
- banner:
  - text: 项目制知识引导小精灵
  - navigation "项目学习流程":
    - button "01 项目描述"
    - button "02 选择知识点"
    - button "03 推荐视频" [disabled]
  - button "我的项目"
- main:
  - complementary:
    - paragraph: 02 / LEARNING SCOPE
    - heading "选择此刻， 想学的知识。" [level=1]
    - paragraph: 围绕 Mock：Excel 成绩分析工具， 选择适合你的学习单元。
    - button "查看或修改项目描述"
    - paragraph:
      - text: 已选择
      - strong: "3"
      - text: 个学习单元 建议按先修顺序学习，可自由调整。
  - status: 修改已保存为新版本，需要重新确认。
  - paragraph: Mock：Excel 成绩分析工具 · v3 · 待确认
  - region "确认知识点 · v3":
    - heading "确认知识点 · v3" [level=2]: 你的项目，需要这些知识
    - paragraph: 按先修顺序排列；展开学习单元，了解目标与实践任务。
    - text: 等待确认
    - group: 分析建议与默认假设
    - group "学习单元排列方式":
      - button "按学习顺序" [pressed]
      - button "按项目任务"
    - region "学习顺序":
      - article:
        - text: 知识点名称：pandas 读取 Excel
        - textbox "知识点名称：pandas 读取 Excel":
          - /placeholder: 填写具体、适合检索的知识点
          - text: pandas 读取 Excel
        - text: 必需
        - button "删除知识点：pandas 读取 Excel": 删除
        - group "pandas 读取 Excel的学习选择":
          - checkbox "想学习" [checked]
          - text: 想学习
        - paragraph: 用于 读取与统计、图表与导出
        - paragraph: 离线 Mock 知识点说明
        - paragraph: 能够在本地工具中应用
        - paragraph:
          - strong: 先学技能：
          - text: 此版本尚未单独整理，可展开后补充。
        - group: 学习目标与前置关系 · 建议顺序 1 · 共享于 2 个功能
      - article:
        - text: 知识点名称：新版本统计方法
        - textbox "知识点名称：新版本统计方法":
          - /placeholder: 填写具体、适合检索的知识点
          - text: 新版本统计方法
        - text: 必需
        - button "删除知识点：新版本统计方法": 删除
        - group "新版本统计方法的学习选择":
          - checkbox "想学习" [checked]
          - text: 想学习
        - paragraph: 用于 读取与统计
        - paragraph: 离线 Mock 知识点说明
        - paragraph: 能够在本地工具中应用
        - paragraph:
          - strong: 先学技能：
          - text: 此版本尚未单独整理，可展开后补充。
        - group: 学习目标与前置关系 · 建议顺序 2
      - article:
        - text: 知识点名称：Matplotlib 柱状图绘制
        - textbox "知识点名称：Matplotlib 柱状图绘制":
          - /placeholder: 填写具体、适合检索的知识点
          - text: Matplotlib 柱状图绘制
        - text: 必需
        - button "删除知识点：Matplotlib 柱状图绘制": 删除
        - group "Matplotlib 柱状图绘制的学习选择":
          - checkbox "想学习" [checked]
          - text: 想学习
        - paragraph: 用于 图表与导出
        - paragraph: 离线 Mock 知识点说明
        - paragraph: 能够在本地工具中应用
        - paragraph:
          - strong: 先学技能：
          - text: 此版本尚未单独整理，可展开后补充。
        - group: 学习目标与前置关系 · 建议顺序 3
      - paragraph: 需要新增单元或查看功能覆盖？切换到“按项目任务”。
    - paragraph: 已勾选 3 项 · 未勾选 0 项 · 最多每批 5 项，预计 1 批
    - button "保存修改，稍后确认" [disabled]
    - button "查找推荐视频"
    - paragraph: 分析模型：mock-test-only · 提示词：test-v1 · 2026/10/17 16:00:00
- contentinfo: 让学习，发生在项目里。 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  215 |   expect(mock.calls.edit[0].knowledge_points.map(point => point.name)).toContain('pandas 处理空值');
  216 |   expect(mock.calls.edit[0].knowledge_points.map(point => point.id)).not.toContain('kp2');
  217 |   expect(mock.calls.edit[0].technical_plan).toBe('使用 Python 和 pandas，暂不绘图。');
  218 |   expect(mock.calls.confirm).toEqual([]); expect(mock.calls.search).toEqual([]);
  219 | });
  220 | 
  221 | test('离线 Mock：保存编辑后确认失败仍恢复新版本，重试不重复编辑', async ({ page }) => {
  222 |   const mock = await mockProject(page, { initial: true, failConfirmOnce: true });
  223 |   await enterProject(page, true);
  224 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('pandas 均值与缺失值');
  225 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  226 |   await expect(page.getByRole('alert')).toContainText('修改已保存');
  227 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  228 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  229 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v2' })).toBeVisible();
  230 |   expect(mock.calls.edit).toHaveLength(1); expect(mock.calls.confirm.map(call => call.version)).toEqual([2, 2]);
  231 | });
  232 | 
  233 | test('离线 Mock：单元技术默认显示并随完整分析保存，历史空值兼容且只读', async ({ page }, testInfo) => {
  234 |   const mock = await mockProject(page, { initial: true });
  235 |   const initial = mock.versions.get(1)!.analysis!;
  236 |   initial.knowledge_points[0].technology = 'pandas';
  237 |   const original = structuredClone(initial);
  238 |   const changedTechnology = 'Python 3 / pandas（本地 Excel）';
  239 |   await enterProject(page, true);
  240 |   await firstPoint(page, 'kp1').locator('summary').click();
  241 |   const technology = firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true });
  242 |   await expect(technology).toBeVisible();
  243 |   await expect(technology).toHaveValue('pandas');
  244 |   await expect(technology).toHaveAttribute('maxlength', '80');
  245 |   await expect(technology).toBeEditable();
  246 |   // A legacy unit can omit the optional field without a render or draft mutation.
  247 |   await firstPoint(page, 'kp2').locator('summary').click();
  248 |   await expect(firstPoint(page, 'kp2').getByLabel('本单元使用的工具或技术', { exact: true })).toHaveValue('');
  249 |   await technology.fill(changedTechnology);
  250 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  251 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  252 |   expect(mock.calls.edit).toEqual([{ ...original, knowledge_points: original.knowledge_points.map(point => point.id === 'kp1' ? { ...point, technology: changedTechnology } : point) }]);
  253 |   await firstPoint(page, 'kp1').locator('summary').click();
  254 |   const savedTechnology = firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true });
  255 |   await expect(savedTechnology).toHaveValue(changedTechnology);
  256 |   await savedTechnology.scrollIntoViewIfNeeded();
  257 |   await page.screenshot({ path: testInfo.outputPath('unit-technology-saved.png'), fullPage: false, animations: 'disabled' });
  258 |   const technologyLayout = await savedTechnology.evaluate(element => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
  259 |   expect(technologyLayout.scrollWidth).toBeLessThanOrEqual(technologyLayout.clientWidth + 1);
  260 |   await page.getByRole('button', { name: '我的项目' }).click();
  261 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  262 |   await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  263 |   await firstPoint(page, 'kp1').locator('summary').click();
  264 |   await expect(firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true })).toHaveValue('pandas');
  265 |   await expect(firstPoint(page, 'kp1').getByLabel('本单元使用的工具或技术', { exact: true })).toBeDisabled();
  266 |   await firstPoint(page, 'kp2').locator('summary').click();
  267 |   const historicalEmpty = firstPoint(page, 'kp2').getByLabel('本单元使用的工具或技术', { exact: true });
  268 |   await expect(historicalEmpty).toHaveValue('');
  269 |   await expect(historicalEmpty).toBeDisabled();
  270 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].technology).toBe('pandas');
  271 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[1].technology).toBeUndefined();
  272 |   expect(mock.calls.edit).toHaveLength(1); expect(mock.calls.confirm).toHaveLength(0); expect(mock.calls.search).toHaveLength(0);
  273 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.console).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  274 |   await writeFile(resolve(process.cwd(), process.env.QA_EVIDENCE_ROOT || '../evidence/browser', 'unit-technology-browser-observations.json'), JSON.stringify({ kind: 'isolated browser transport fixture, not live model evidence', defaultTechnology: 'pandas', submittedTechnology: mock.calls.edit[0].knowledge_points[0].technology,
  275 |     entireAnalysisPreserved: true, inputMaxLength: 80, technologyLayout, historicalDefaultUnchanged: true, historicalMissingTechnology: '', historicalFieldsDisabled: true, mutationRequests: mock.calls.edit.length }, null, 2));
  276 | });
  277 | 
  278 | test('离线 Mock：预算超限保留全部知识点，需求修改后阻止旧分析确认', async ({ page }) => {
  279 |   const mock = await mockProject(page, { initial: true, count: 7, maxBatches: 1 });
  280 |   await enterProject(page, true);
  281 |   await expect(page.getByText(/超过项目 1 批上限/)).toBeVisible();
  282 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  283 |   expect(new Set(await page.locator('[data-point-id]').evaluateAll(elements => elements.map(element => element.getAttribute('data-point-id')))).size).toBe(7);
  284 |   await page.getByRole('button', { name: '查看或修改项目描述' }).click();
  285 |   await page.getByLabel('功能需求', { exact: true }).fill('功能需求有实质变化，需要重新分析。');
  286 |   await page.getByRole('navigation', { name: '项目学习流程' }).getByRole('button', { name: /选择知识点/ }).click();
  287 |   await expect(page.getByText(/需求已有未保存修改/)).toBeVisible();
  288 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  289 |   expect(mock.calls.search).toEqual([]);
  290 | });
  291 | 
  292 | test('离线 Mock：模型未配置仍保存原始输入，保留直接搜索入口', async ({ page }) => {
  293 |   const mock = await mockProject(page, { unconfigured: true });
  294 |   await enterProject(page);
  295 |   await expect(page.getByText(/项目分析不可用/)).toBeVisible();
  296 |   await page.getByLabel('项目名称', { exact: true }).fill('不能丢失的需求');
  297 |   await page.getByLabel('功能需求', { exact: true }).fill('读取表格并导出统计图');
  298 |   await page.getByRole('button', { name: '保存项目并检查分析配置' }).click();
  299 |   await expect(page.getByRole('alert')).toContainText('未配置可用模型');
  300 |   await expect(page.getByLabel('功能需求', { exact: true })).toHaveValue('读取表格并导出统计图');
  301 |   expect(mock.calls.create[0].requirements).toBe('读取表格并导出统计图');
  302 |   expect(mock.calls.search).toEqual([]);
  303 |   await page.getByRole('button', { name: '直接搜索知识点', exact: true }).click();
  304 |   await expect(page.getByLabel('知识点', { exact: true })).toBeVisible();
  305 | });
  306 | 
  307 | test('离线 Mock：历史结果保留版本，新版本不混入旧课程；手机布局无溢出', async ({ page }, testInfo) => {
  308 |   const mock = await mockProject(page, { initial: true });
  309 |   await enterProject(page, true);
  310 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  311 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  312 |   await page.getByRole('button', { name: '← 调整知识点', exact: true }).click();
  313 |   await firstPoint(page, 'kp2').locator('.point-title-line input').fill('新版本统计方法');
  314 |   await page.getByRole('button', { name: '保存修改，稍后确认' }).click();
> 315 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
      |                                                                   ^ Error: expect(locator).toBeVisible() failed
  316 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  317 |   await page.getByRole('button', { name: '我的项目' }).click();
  318 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  319 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  320 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  321 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toHaveCount(0);
  322 |   const historyRetry = page.getByRole('button', { name: '重新检索这些知识点' });
  323 |   expect(await historyRetry.count() === 0 || await historyRetry.isDisabled()).toBe(true);
  324 |   await page.setViewportSize({ width: 390, height: 844 });
  325 |   await page.screenshot({ path: testInfo.outputPath('project-mobile-history.png'), fullPage: true });
  326 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  327 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  328 | });
  329 | 
  330 | test('离线 Mock：部分完成仅有文字资源时显示明确空态，不假示仍在检索', async ({ page }, testInfo) => {
  331 |   const mock = await mockProject(page, { initial: true });
  332 |   const current = mock.versions.get(1)!;
  333 |   current.status = 'partial'; current.confirmation = { version: 1, confirmed_at: time };
  334 |   current.batches = [{ batch_id: 'partial-batch', status: 'partial', project_knowledge_point_ids: ['kp1', 'kp2', 'kp3'], job_id: 'partial-job' }];
  335 |   await page.route('**/api/projects/mock-project/results*', route => {
  336 |     const snapshot = mock.view();
  337 |     snapshot.points = snapshot.points!.map(point => ({ ...point, status: 'partial', result: {
  338 |       knowledge_point_id: point.project_knowledge_point_id, text: point.name, total_matches: 0, items: [],
  339 |       partial_items: [{ ...resource(point.project_knowledge_point_id), resource: { ...resource(point.project_knowledge_point_id).resource, resource_type: 'article' } }],
  340 |     } }));
  341 |     return route.fulfill({ json: snapshot });
  342 |   });
  343 |   await enterProject(page, true);
  344 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
  345 |   await expect(page.getByText('本次检索部分完成，未找到可展示的课程。', { exact: true })).toHaveCount(3);
  346 |   await expect(page.getByText('正在读取或查找课程…', { exact: true })).toHaveCount(0);
  347 |   await expect(page.locator('.resource-card')).toHaveCount(0);
  348 |   await page.locator('.project-results').scrollIntoViewIfNeeded();
  349 |   await page.screenshot({ path: testInfo.outputPath('partial-terminal-empty.png'), fullPage: false });
  350 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  351 | });
  352 | 
  353 | test('离线 Mock：平台筛选无匹配区别于本次无结果，切回全部恢复课程', async ({ page }) => {
  354 |   const mock = await mockProject(page, { initial: true });
  355 |   const current = mock.versions.get(1)!;
  356 |   current.status = 'completed'; current.confirmation = { version: 1, confirmed_at: time };
  357 |   current.batches = [{ batch_id: 'completed-batch', status: 'completed', project_knowledge_point_ids: ['kp1', 'kp2', 'kp3'], job_id: 'completed-job' }];
  358 |   await page.route('**/api/projects/mock-project/results*', route => {
  359 |     const snapshot = mock.view();
  360 |     snapshot.points = snapshot.points!.map(point => {
  361 |       const item = resource(point.project_knowledge_point_id);
  362 |       if (point.project_knowledge_point_id === 'kp2') item.resource.platform = 'bilibili';
  363 |       return { ...point, status: point.project_knowledge_point_id === 'kp3' ? 'no_results' : 'completed', result: {
  364 |         knowledge_point_id: point.project_knowledge_point_id, text: point.name,
  365 |         total_matches: point.project_knowledge_point_id === 'kp3' ? 0 : 1, items: point.project_knowledge_point_id === 'kp3' ? [] : [item],
  366 |       } };
  367 |     });
  368 |     return route.fulfill({ json: snapshot });
  369 |   });
  370 |   await enterProject(page, true);
  371 |   await expect(page.locator('.resource-card')).toHaveCount(2);
  372 |   await expect(page.getByText('本次没有找到可展示的相关课程。', { exact: true })).toHaveCount(1);
  373 |   await page.getByLabel('项目课程来源', { exact: true }).selectOption('bilibili');
  374 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  375 |   await expect(page.locator('.platform-search-fallback')).toHaveCount(0);
  376 |   await expect(page.getByText('当前平台下暂无可展示课程，可切换到全部平台。', { exact: true })).toHaveCount(2);
  377 |   await expect(page.getByText('正在读取或查找课程…', { exact: true })).toHaveCount(0);
  378 |   await page.getByLabel('项目课程来源', { exact: true }).selectOption('all');
  379 |   await expect(page.locator('.resource-card')).toHaveCount(2);
  380 |   await expect(page.getByText('本次没有找到可展示的相关课程。', { exact: true })).toHaveCount(1);
  381 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  382 | });
  383 | 
  384 | test('离线 Mock：轮询自动恢复清除读取错误，同时保留确认预算失败', async ({ page }) => {
  385 |   const mock = await mockProject(page, { initial: true, failConfirmOnce: true });
  386 |   let reads = 0;
  387 |   let failNextRead = false;
  388 |   await page.route('**/api/projects/mock-project/results*', route => {
  389 |     reads += 1;
  390 |     if (failNextRead) { failNextRead = false; return route.fulfill({ status: 503, json: { detail: 'Mock：一次暂时读取失败' } }); }
  391 |     return route.fulfill({ json: mock.view() });
  392 |   });
  393 |   await enterProject(page, true);
  394 |   await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  395 |   failNextRead = true;
  396 |   await page.getByRole('button', { name: '我的项目' }).click();
  397 |   await page.getByRole('button', { name: '重新读取', exact: true }).click();
  398 |   await expect(page.getByRole('alert')).toContainText('一次暂时读取失败');
  399 |   await expect(page.getByRole('alert')).toHaveCount(0);
  400 |   const readsBeforeConfirm = reads;
  401 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  402 |   await expect.poll(() => reads).toBeGreaterThan(readsBeforeConfirm);
  403 |   await expect(page.getByRole('alert')).toContainText('Mock：暂时超出项目预算，修改已保存。');
  404 |   expect(mock.calls.confirm).toHaveLength(1); expect(mock.calls.search).toHaveLength(0);
  405 |   expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  406 | });
  407 | 
  408 | const screenshotRoot = resolve(process.cwd(), process.env.QA_EVIDENCE_ROOT || '../evidence/browser', 'screenshots');
  409 | const responsiveViewports = [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }];
  410 | async function capture(page: Page, name: string) {
  411 |   await mkdir(screenshotRoot, { recursive: true });
  412 |   await page.screenshot({ path: resolve(screenshotRoot, name), fullPage: false, animations: 'disabled' });
  413 | }
  414 | async function assertNoOverflow(page: Page) {
  415 |   const measurement = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
```