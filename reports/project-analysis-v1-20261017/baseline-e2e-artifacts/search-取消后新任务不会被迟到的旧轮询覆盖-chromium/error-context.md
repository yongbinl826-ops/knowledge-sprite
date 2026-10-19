# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: search.spec.ts >> 取消后新任务不会被迟到的旧轮询覆盖
- Location: tests\search.spec.ts:433:1

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: '取消', exact: true })

```

# Page snapshot

```yaml
- generic [ref=e2]:
  - link "跳转到知识点输入" [ref=e3] [cursor=pointer]:
    - /url: "#knowledge"
  - banner [ref=e4]:
    - generic [ref=e5]: 项目制知识引导小精灵
    - generic [ref=e9]: 课程与视频发现
  - main [ref=e10]:
    - generic [ref=e11]:
      - heading "想学的知识，去哪里学？" [level=1] [ref=e12]
      - paragraph [ref=e13]: 输入知识点，找到课程与对应章节。
    - generic [ref=e14]:
      - complementary [ref=e15]:
        - heading "学习需求" [level=2] [ref=e16]
        - generic [ref=e17]:
          - generic [ref=e18]:
            - generic [ref=e19]:
              - generic [ref=e20]: 知识点
              - generic [ref=e21]: 0 / 5
            - textbox "知识点" [ref=e22]:
              - /placeholder: 每行一个知识点，最多 5 个
            - generic [ref=e23]: 每行输入一个知识点，重复行会自动合并。
          - generic [ref=e24]:
            - generic [ref=e25]:
              - generic [ref=e26]: 学生基础
              - combobox "学生基础" [ref=e27]:
                - option "初学者" [selected]
                - option "有一定基础"
                - option "进阶学习"
                - option "不限"
            - generic [ref=e28]:
              - generic [ref=e29]: 学习语言
              - combobox "学习语言" [ref=e30]:
                - option "中文" [selected]
                - option "英语"
                - option "不限"
          - group [ref=e31]:
            - generic "更多筛选" [ref=e32] [cursor=pointer]
          - button "开始查找" [ref=e33] [cursor=pointer]
      - region [ref=e34]:
        - generic [ref=e36]:
          - heading "推荐课程" [level=2] [ref=e37]
          - paragraph [ref=e38]: 找到对应章节，去原平台学习
        - alert [ref=e39]:
          - strong [ref=e40]: 请求未完成
          - paragraph [ref=e41]: 进度暂时无法读取：请求超过 15 秒未返回，请检查连接后重试。 正在重试。
          - button "重新读取结果" [ref=e42] [cursor=pointer]
        - generic [ref=e43]:
          - heading "正在寻找学习资源" [level=3] [ref=e47]
          - paragraph [ref=e48]: 输入知识点，找到课程和对应章节
    - group [ref=e50]:
      - generic "来源与访问说明 ＋" [ref=e51] [cursor=pointer]
```

# Test source

```ts
  351 |   await setup(page);
  352 |   let cancelled = false, cancels = 0, polls = 0;
  353 |   let release!: () => void;
  354 |   const gate = new Promise<void>(resolve => { release = resolve; });
  355 |   await page.route('**/api/search-jobs/test-job', route => { polls += 1; return route.fulfill({ json: { ...baseJob, status: cancelled ? 'cancelled' : 'running', phase: cancelled ? 'done' : 'searching' } }); });
  356 |   await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: { ...results, status: cancelled ? 'cancelled' : 'running' } }));
  357 |   await page.route('**/api/search-jobs/test-job/cancel', async route => {
  358 |     cancels += 1; expect(route.request().method()).toBe('POST');
  359 |     await gate; cancelled = true;
  360 |     await route.fulfill({ json: { job_id: 'test-job', status: 'cancelled', cancelled: true } });
  361 |   });
  362 |   await page.goto('/?job=test-job');
  363 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  364 |   await page.getByRole('button', { name: '取消', exact: true }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  365 |   await expect(page.getByRole('button', { name: '正在取消…' })).toBeDisabled();
  366 |   await expect.poll(() => cancels).toBe(1);
  367 |   release();
  368 |   await expect(page.locator('.job-status')).toHaveText('任务已取消');
  369 |   await expect(page.getByText('已取消查找，保留已找到的课程。')).toBeVisible();
  370 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  371 |   await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
  372 |   await expect.poll(() => polls).toBeGreaterThan(1);
  373 |   const endedPolls = polls;
  374 |   await page.waitForTimeout(1700);
  375 |   expect(polls).toBe(endedPolls);
  376 |   await page.screenshot({ path: testInfo.outputPath('cancelled-preserved-results.png'), fullPage: true });
  377 | });
  378 | 
  379 | test('重复提交锁与后端复用原任务提示', async ({ page }) => {
  380 |   await setup(page);
  381 |   let submissions = 0;
  382 |   let release!: () => void;
  383 |   const gate = new Promise<void>(resolve => { release = resolve; });
  384 |   await page.route('**/api/search-jobs', async route => {
  385 |     submissions += 1; await gate;
  386 |     await route.fulfill({ status: 202, json: { job_id: 'test-job', status: 'running', reused: true } });
  387 |   });
  388 |   await page.goto('/');
  389 |   await page.getByLabel('知识点', { exact: true }).fill('隔离重复提交测试');
  390 |   await page.locator('form').evaluate(form => {
  391 |     form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  392 |     form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  393 |   });
  394 |   await expect.poll(() => submissions).toBe(1);
  395 |   await expect(page.getByRole('button', { name: '正在查找…' })).toBeDisabled();
  396 |   release();
  397 |   await expect(page.getByText('已返回相同需求的原任务，未重复发起搜索。')).toBeVisible();
  398 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  399 | });
  400 | 
  401 | test('创建超时重试沿用幂等key，明确重新检索使用新key', async ({ page }) => {
  402 |   await page.clock.install();
  403 |   await setup(page);
  404 |   const keys: string[] = [];
  405 |   let release!: () => void;
  406 |   const gate = new Promise<void>(resolve => { release = resolve; });
  407 |   await page.route('**/api/search-jobs', async route => {
  408 |     keys.push(route.request().headers()['idempotency-key']);
  409 |     if (keys.length === 1) { await gate; await route.abort().catch(() => {}); return; }
  410 |     await route.fulfill({ status: 202, json: { job_id: keys.length === 2 ? 'test-job' : 'new-job', status: 'completed', reused: keys.length === 2 } });
  411 |   });
  412 |   await page.route('**/api/search-jobs/new-job', route => route.fulfill({ json: { ...baseJob, job_id: 'new-job' } }));
  413 |   await page.route('**/api/search-jobs/new-job/results', route => route.fulfill({ json: { ...results, job_id: 'new-job' } }));
  414 |   await page.goto('/');
  415 |   await page.getByLabel('知识点', { exact: true }).fill('隔离创建超时测试');
  416 |   await page.getByRole('button', { name: '开始查找' }).click();
  417 |   await expect.poll(() => keys.length).toBe(1);
  418 |   await page.clock.fastForward(15_001);
  419 |   await expect(page.getByRole('alert')).toContainText('创建状态尚未确认');
  420 |   await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
  421 |   release();
  422 |   await page.getByRole('button', { name: '开始查找' }).click();
  423 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  424 |   expect(keys[0]).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
  425 |   expect(keys[1]).toBe(keys[0]);
  426 |   await expect(page.getByText('已返回相同需求的原任务，未重复发起搜索。')).toBeVisible();
  427 |   await page.getByRole('button', { name: '开始查找' }).click();
  428 |   await expect(page).toHaveURL(/job=new-job/);
  429 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  430 |   expect(keys[2]).not.toBe(keys[1]);
  431 | });
  432 | 
  433 | test('取消后新任务不会被迟到的旧轮询覆盖', async ({ page }) => {
  434 |   await setup(page);
  435 |   let cancelled = false, resultCalls = 0;
  436 |   let releaseOld!: () => void;
  437 |   const oldGate = new Promise<void>(resolve => { releaseOld = resolve; });
  438 |   await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: cancelled ? 'cancelled' : 'running' } }));
  439 |   await page.route('**/api/search-jobs/test-job/results', async route => {
  440 |     resultCalls += 1;
  441 |     if (!cancelled) await oldGate;
  442 |     await route.fulfill({ json: { ...results, status: cancelled ? 'cancelled' : 'running' } }).catch(() => {});
  443 |   });
  444 |   await page.route('**/api/search-jobs/test-job/cancel', route => { cancelled = true; return route.fulfill({ json: { job_id: 'test-job', status: 'cancelled', cancelled: true } }); });
  445 |   await page.route('**/api/search-jobs', route => route.fulfill({ status: 202, json: { job_id: 'new-job', status: 'completed', reused: false } }));
  446 |   await page.route('**/api/search-jobs/new-job', route => route.fulfill({ json: { ...baseJob, job_id: 'new-job' } }));
  447 |   const newResults: SearchResults = { ...results, job_id: 'new-job', groups: [{ ...results.groups[0], items: [{ ...otherItem, resource: { ...otherItem.resource, title: '新任务的唯一结果' } }] }] };
  448 |   await page.route('**/api/search-jobs/new-job/results', route => route.fulfill({ json: newResults }));
  449 |   await page.goto('/?job=test-job');
  450 |   await expect.poll(() => resultCalls).toBeGreaterThanOrEqual(1);
> 451 |   await page.getByRole('button', { name: '取消', exact: true }).click();
      |                                                               ^ Error: locator.click: Test timeout of 30000ms exceeded.
  452 |   await expect(page.locator('.job-status')).toHaveText('任务已取消');
  453 |   await page.getByLabel('知识点', { exact: true }).fill('新任务');
  454 |   await page.getByRole('button', { name: '开始查找' }).click();
  455 |   await expect(page.getByRole('heading', { name: '新任务的唯一结果' })).toBeVisible();
  456 |   releaseOld();
  457 |   await page.waitForTimeout(100);
  458 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  459 |   await expect(page.getByRole('heading', { name: '新任务的唯一结果' })).toBeVisible();
  460 |   await expect(page).toHaveURL(/job=new-job/);
  461 | });
  462 | 
  463 | test('轮询任一请求失败会及时取消同轮兄弟请求', async ({ page }) => {
  464 |   await page.addInitScript(() => {
  465 |     const target = window as typeof window & { __fetchAudit: { url: string; aborted: boolean }[] };
  466 |     target.__fetchAudit = [];
  467 |     const nativeFetch = window.fetch.bind(window);
  468 |     window.fetch = (input, init) => {
  469 |       const entry = { url: String(input), aborted: false };
  470 |       target.__fetchAudit.push(entry);
  471 |       init?.signal?.addEventListener('abort', () => { entry.aborted = true; }, { once: true });
  472 |       return nativeFetch(input, init);
  473 |     };
  474 |   });
  475 |   await setup(page);
  476 |   let recovered = false;
  477 |   let release!: () => void;
  478 |   const gate = new Promise<void>(resolve => { release = resolve; });
  479 |   await page.route('**/api/search-jobs/test-job', route => {
  480 |     return route.fulfill(!recovered ? { status: 503, json: { detail: '隔离轮询故障' } } : { json: baseJob });
  481 |   });
  482 |   await page.route('**/api/search-jobs/test-job/results', async route => {
  483 |     if (!recovered) await gate;
  484 |     await route.fulfill({ json: results }).catch(() => {});
  485 |   });
  486 |   await page.goto('/?job=test-job');
  487 |   await expect(page.getByRole('alert')).toContainText('隔离轮询故障');
  488 |   await expect.poll(() => page.evaluate(() => {
  489 |     const entries = (window as typeof window & { __fetchAudit: { url: string; aborted: boolean }[] }).__fetchAudit.filter(entry => entry.url.endsWith('/results'));
  490 |     return entries.length >= 2 && entries.every(entry => entry.aborted);
  491 |   })).toBe(true);
  492 |   recovered = true; release();
  493 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  494 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  495 | });
  496 | 
  497 | test('取消请求失败保持未确认状态，不假装取消成功', async ({ page }) => {
  498 |   await setup(page, caps, { ...baseJob, status: 'running', phase: 'searching' }, { ...results, status: 'running' });
  499 |   await page.route('**/api/search-jobs/test-job/cancel', route => route.abort('connectionreset'));
  500 |   await page.goto('/?job=test-job');
  501 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  502 |   await page.getByRole('button', { name: '取消', exact: true }).click();
  503 |   await expect(page.getByRole('alert')).toContainText('取消状态尚未确认');
  504 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  505 |   await expect(page.getByText('已取消查找，保留已找到的课程。')).toHaveCount(0);
  506 |   await expect(page.getByRole('button', { name: '取消', exact: true })).toBeEnabled();
  507 | });
  508 | 
  509 | test('任务已自然结束时取消返回原终态，不覆盖为cancelled', async ({ page }) => {
  510 |   await setup(page);
  511 |   let completed = false;
  512 |   await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: completed ? 'completed' : 'running' } }));
  513 |   await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: { ...results, status: completed ? 'completed' : 'running' } }));
  514 |   await page.route('**/api/search-jobs/test-job/cancel', route => { completed = true; return route.fulfill({ json: { job_id: 'test-job', status: 'completed', cancelled: false } }); });
  515 |   await page.goto('/?job=test-job');
  516 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  517 |   await page.getByRole('button', { name: '取消', exact: true }).click();
  518 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  519 |   await expect(page.getByText('任务已结束，已保留原任务状态。')).toBeVisible();
  520 |   await expect(page.getByText('已取消查找，保留已找到的课程。')).toHaveCount(0);
  521 | });
  522 | 
  523 | test('来源说明折叠保留平台条款，不展示内部采集配置或宣称播放已验证', async ({ page }, testInfo) => {
  524 |   const capability: Capabilities = { ...caps, platforms: [
  525 |     { id: 'bilibili', name: 'B站', discovery: 'search', metadata: 'site_policy_blocked', playback: 'unknown', source_url: 'https://example.org/terms', reviewed_at: time,
  526 |       policy_basis: '隔离条款 fixture：自动工具读取范围受限。', policy_section: '5.6(3)' },
  527 |     { id: 'icourse163', name: '中国大学 MOOC', discovery: 'search', metadata: 'public_course_metadata_only', playback: 'unknown',
  528 |       policy_basis: '隔离范围 fixture：仅匿名读取公开课程页。' },
  529 |   ] };
  530 |   await setup(page, capability);
  531 |   await page.goto('/?job=test-job');
  532 |   await expect(page.locator('.capabilities-footer details')).not.toHaveAttribute('open', '');
  533 |   await page.getByText('来源与访问说明', { exact: true }).click();
  534 |   await expect(page.locator('.platform-capabilities section').first()).toContainText('隔离条款 fixture：自动工具读取范围受限。');
  535 |   await expect(page.locator('.platform-capabilities section').nth(1)).toContainText('隔离范围 fixture：仅匿名读取公开课程页。');
  536 |   const terms = page.getByRole('link', { name: '查看平台条款（5.6(3)）' });
  537 |   await expect(terms).toHaveAttribute('href', 'https://example.org/terms');
  538 |   await expect(terms).toHaveAttribute('target', '_blank');
  539 |   await expect(terms).toHaveAttribute('rel', 'noopener noreferrer');
  540 |   await expect(page.locator('.capabilities-detail')).toContainText('点击封面前往原平台');
  541 |   await expect(page.locator('.capabilities-detail')).not.toContainText('浏览器无法访问');
  542 |   await expect(page.locator('.capabilities-detail')).not.toContainText('已验证播放');
  543 |   await expect(page.locator('.capabilities-detail')).not.toContainText('DoH');
  544 |   await page.screenshot({ path: testInfo.outputPath('compact-source-notice.png'), fullPage: true });
  545 | });
  546 | 
  547 | test('取得的目录证据可参与章节定位，内部渲染诊断不进入课程卡片', async ({ page }) => {
  548 |   const source = 'html.microsoft_ai.curriculum_table';
  549 |   const url = 'https://microsoft.github.io/AI-For-Beginners/';
  550 |   const acquisition = { acquisition: 'offline_rendered_dom', render_id: 'render-fixture', dom_sha256: 'a'.repeat(64) };
  551 |   const chapters: Chapter[] = [{ title: 'Fixture chapter A', evidence_id: 'render-chapter-0' }, { title: 'Fixture chapter B', evidence_id: 'render-chapter-1' }];
```