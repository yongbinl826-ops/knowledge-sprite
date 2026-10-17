# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: search.spec.ts >> 轮询任一请求失败会及时取消同轮兄弟请求
- Location: tests\search.spec.ts:483:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('alert')
Expected substring: "隔离轮询故障"
Timeout: 7000ms
Error: element(s) not found

Call log:
  - Expect "toContainText" getByRole('alert') with timeout 7000ms
  - waiting for getByRole('alert')

```

```yaml
- link "跳转到知识点输入":
  - /url: "#knowledge"
- banner: 项目制知识引导小精灵 课程与视频发现
- main:
  - heading "从知识点，找到学习入口" [level=1]
  - paragraph: 输入你想学的知识点，发现公开课程与视频，回到原平台继续学习。
  - complementary:
    - heading "学习需求" [level=2]
    - text: 知识点 0 / 5
    - textbox "知识点":
      - /placeholder: 每行一个知识点，最多 5 个
    - text: 每行输入一个知识点，重复行会自动合并。 学生基础
    - combobox "学生基础":
      - option "初学者" [selected]
      - option "有一定基础"
      - option "进阶学习"
      - option "不限"
    - text: 学习语言
    - combobox "学习语言":
      - option "中文" [selected]
      - option "英语"
      - option "不限"
    - text: 技术版本 （可选）
    - textbox "技术版本 （可选）":
      - /placeholder: 例如：Python 3.11、Vue 3、JDK 17
    - text: 项目背景 （可选）
    - textbox "项目背景 （可选）":
      - /placeholder: 例如：做一个博客系统、课程设计
    - group "优先搜索的平台":
      - text: 优先搜索的平台
      - checkbox "B站" [checked]
      - text: B站
      - checkbox "中国大学 MOOC" [checked]
      - text: 中国大学 MOOC
      - checkbox "学堂在线" [checked]
      - text: 学堂在线
      - paragraph: 也会搜索其他公开课程网站
    - button "开始查找"
  - region "学习资源":
    - heading "学习资源" [level=2]
    - paragraph: 按知识点整理 · 保留来源证据
    - text: 检索完成
    - strong: 已结束
    - text: 更新于 2026/10/13 15:00:00 查询 4 / 4 发现候选 2 详情采集 1 / 2 缓存命中 1
    - paragraph: 实际搜索请求：4 / 30 次；详情与目录页共用 40 页预算，采集计数分别列示。
    - paragraph: 本次任务流程已结束；不代表每个平台均有结果，或每个页面、目录与播放条件都已核验。
    - text: 来源平台
    - combobox "来源平台":
      - option "全部平台" [selected]
      - option "B站"
      - option "其他网站"
    - text: 资源类型
    - combobox "资源类型":
      - option "全部类型" [selected]
      - option "课程与视频"
      - option "文字资料"
      - option "类型未知"
    - text: 每个知识点最多 5 项
    - region "非预设知识点：空间哈希":
      - heading "非预设知识点：空间哈希" [level=3]
      - text: 2 个候选
      - article:
        - text: B站 视频 搜索发现
        - heading "测试响应：空间哈希 <img src=x onerror=alert(1)>" [level=4]:
          - link "测试响应：空间哈希 <img src=x onerror=alert(1)>":
            - /url: https://www.bilibili.com/video/BV_TEST_ONLY?p=2
        - paragraph: 相关知识点：非预设知识点：空间哈希、边界条件
        - paragraph: 课程归属：未知 · 开课版本：未知 · 讲次：未知
        - paragraph: 根据标题与摘要匹配，可能涉及空间哈希。
        - paragraph: 暂无视频结构证据 · 页面元信息与目录不等于观看验证，观看尚未实测。
        - paragraph: 仅搜索发现，页面详情未核验 · robots 禁止采集
        - paragraph: 暂无可获取的目录证据，不代表来源没有目录。
        - text: 登录：未知 付费：未知 选课：未知 浏览器访问：未逐页实测 可播放性：尚未核验
        - paragraph: 使用过期缓存 · 缓存时间：2026/10/13 15:00:00
        - group: 查看来源与证据
        - link "前往原平台":
          - /url: https://www.bilibili.com/video/BV_TEST_ONLY?p=2
      - article:
        - text: 其他网站 视频 页面元信息
        - heading "测试响应：公开教程页面" [level=4]:
          - link "测试响应：公开教程页面":
            - /url: https://example.org/tutorial?chapter=2
        - paragraph: 相关知识点：非预设知识点：空间哈希
        - paragraph: 课程归属：未知 · 开课版本：未知 · 讲次：未知
        - paragraph: 根据标题与摘要匹配，可能涉及空间哈希。
        - paragraph: 暂无视频结构证据 · 页面元信息与目录不等于观看验证，观看尚未实测。
        - paragraph: 暂无可获取的目录证据，不代表来源没有目录。
        - text: 登录：未知 付费：未知 选课：未知 浏览器访问：未逐页实测 可播放性：尚未核验
        - group: 查看来源与证据
        - link "前往原平台":
          - /url: https://example.org/tutorial?chapter=2
      - paragraph: 本次仅找到 2 个符合条件的候选，未补充未经证实的资源。
    - region "边界条件":
      - heading "边界条件" [level=3]
      - text: 1 个候选
      - article:
        - text: B站 视频 搜索发现
        - heading "测试响应：空间哈希 <img src=x onerror=alert(1)>" [level=4]:
          - link "测试响应：空间哈希 <img src=x onerror=alert(1)>":
            - /url: https://www.bilibili.com/video/BV_TEST_ONLY?p=2
        - paragraph: 相关知识点：非预设知识点：空间哈希、边界条件
        - paragraph: 课程归属：未知 · 开课版本：未知 · 讲次：未知
        - paragraph: 根据标题与摘要匹配，可能涉及空间哈希。
        - paragraph: 暂无视频结构证据 · 页面元信息与目录不等于观看验证，观看尚未实测。
        - paragraph: 仅搜索发现，页面详情未核验 · robots 禁止采集
        - paragraph: 暂无可获取的目录证据，不代表来源没有目录。
        - text: 登录：未知 付费：未知 选课：未知 浏览器访问：未逐页实测 可播放性：尚未核验
        - paragraph: 使用过期缓存 · 缓存时间：2026/10/13 15:00:00
        - group: 查看来源与证据
        - link "前往原平台":
          - /url: https://www.bilibili.com/video/BV_TEST_ONLY?p=2
      - paragraph: 本次仅找到 1 个符合条件的候选，未补充未经证实的资源。
    - group: 查看实际查询记录（1）
    - text: 真实来源链接 未知信息如实标注 跳转原平台学习
  - group: 搜索服务 已配置，待验证 查询与排序 规则模式 运行模式 Live 能力详情⌄
```

# Test source

```ts
  400 |   await setup(page);
  401 |   let submissions = 0;
  402 |   let release!: () => void;
  403 |   const gate = new Promise<void>(resolve => { release = resolve; });
  404 |   await page.route('**/api/search-jobs', async route => {
  405 |     submissions += 1; await gate;
  406 |     await route.fulfill({ status: 202, json: { job_id: 'test-job', status: 'running', reused: true } });
  407 |   });
  408 |   await page.goto('/');
  409 |   await page.getByLabel('知识点', { exact: true }).fill('隔离重复提交测试');
  410 |   await page.locator('form').evaluate(form => {
  411 |     form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  412 |     form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  413 |   });
  414 |   await expect.poll(() => submissions).toBe(1);
  415 |   await expect(page.getByRole('button', { name: '正在查找…' })).toBeDisabled();
  416 |   release();
  417 |   await expect(page.getByText('已返回相同需求的原任务，未重复发起搜索。')).toBeVisible();
  418 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  419 | });
  420 | 
  421 | test('创建超时重试沿用幂等key，明确重新检索使用新key', async ({ page }) => {
  422 |   await page.clock.install();
  423 |   await setup(page);
  424 |   const keys: string[] = [];
  425 |   let release!: () => void;
  426 |   const gate = new Promise<void>(resolve => { release = resolve; });
  427 |   await page.route('**/api/search-jobs', async route => {
  428 |     keys.push(route.request().headers()['idempotency-key']);
  429 |     if (keys.length === 1) { await gate; await route.abort().catch(() => {}); return; }
  430 |     await route.fulfill({ status: 202, json: { job_id: keys.length === 2 ? 'test-job' : 'new-job', status: 'completed', reused: keys.length === 2 } });
  431 |   });
  432 |   await page.route('**/api/search-jobs/new-job', route => route.fulfill({ json: { ...baseJob, job_id: 'new-job' } }));
  433 |   await page.route('**/api/search-jobs/new-job/results', route => route.fulfill({ json: { ...results, job_id: 'new-job' } }));
  434 |   await page.goto('/');
  435 |   await page.getByLabel('知识点', { exact: true }).fill('隔离创建超时测试');
  436 |   await page.getByRole('button', { name: '开始查找' }).click();
  437 |   await expect.poll(() => keys.length).toBe(1);
  438 |   await page.clock.fastForward(15_001);
  439 |   await expect(page.getByRole('alert')).toContainText('创建状态尚未确认');
  440 |   await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
  441 |   release();
  442 |   await page.getByRole('button', { name: '开始查找' }).click();
  443 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  444 |   expect(keys[0]).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
  445 |   expect(keys[1]).toBe(keys[0]);
  446 |   await expect(page.getByText('已返回相同需求的原任务，未重复发起搜索。')).toBeVisible();
  447 |   await page.getByRole('button', { name: '开始查找' }).click();
  448 |   await expect(page).toHaveURL(/job=new-job/);
  449 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  450 |   expect(keys[2]).not.toBe(keys[1]);
  451 | });
  452 | 
  453 | test('取消后新任务不会被迟到的旧轮询覆盖', async ({ page }) => {
  454 |   await setup(page);
  455 |   let cancelled = false, resultCalls = 0;
  456 |   let releaseOld!: () => void;
  457 |   const oldGate = new Promise<void>(resolve => { releaseOld = resolve; });
  458 |   await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: cancelled ? 'cancelled' : 'running' } }));
  459 |   await page.route('**/api/search-jobs/test-job/results', async route => {
  460 |     resultCalls += 1;
  461 |     if (resultCalls === 1) await oldGate;
  462 |     await route.fulfill({ json: { ...results, status: cancelled ? 'cancelled' : 'running' } }).catch(() => {});
  463 |   });
  464 |   await page.route('**/api/search-jobs/test-job/cancel', route => { cancelled = true; return route.fulfill({ json: { job_id: 'test-job', status: 'cancelled', cancelled: true } }); });
  465 |   await page.route('**/api/search-jobs', route => route.fulfill({ status: 202, json: { job_id: 'new-job', status: 'completed', reused: false } }));
  466 |   await page.route('**/api/search-jobs/new-job', route => route.fulfill({ json: { ...baseJob, job_id: 'new-job' } }));
  467 |   const newResults: SearchResults = { ...results, job_id: 'new-job', groups: [{ ...results.groups[0], items: [{ ...otherItem, resource: { ...otherItem.resource, title: '新任务的唯一结果' } }] }] };
  468 |   await page.route('**/api/search-jobs/new-job/results', route => route.fulfill({ json: newResults }));
  469 |   await page.goto('/?job=test-job');
  470 |   await expect.poll(() => resultCalls).toBe(1);
  471 |   await page.getByRole('button', { name: '取消任务', exact: true }).click();
  472 |   await expect(page.locator('.job-status')).toHaveText('任务已取消');
  473 |   await page.getByLabel('知识点', { exact: true }).fill('新任务');
  474 |   await page.getByRole('button', { name: '开始查找' }).click();
  475 |   await expect(page.getByRole('heading', { name: '新任务的唯一结果' })).toBeVisible();
  476 |   releaseOld();
  477 |   await page.waitForTimeout(100);
  478 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  479 |   await expect(page.getByRole('heading', { name: '新任务的唯一结果' })).toBeVisible();
  480 |   await expect(page).toHaveURL(/job=new-job/);
  481 | });
  482 | 
  483 | test('轮询任一请求失败会及时取消同轮兄弟请求', async ({ page }) => {
  484 |   await setup(page);
  485 |   let first = true, resultsCount = 0;
  486 |   let release!: () => void;
  487 |   const gate = new Promise<void>(resolve => { release = resolve; });
  488 |   const failed: string[] = [];
  489 |   page.on('requestfailed', request => failed.push(request.url()));
  490 |   await page.route('**/api/search-jobs/test-job', route => {
  491 |     const fail = first; first = false;
  492 |     return route.fulfill(fail ? { status: 503, json: { detail: '隔离轮询故障' } } : { json: baseJob });
  493 |   });
  494 |   await page.route('**/api/search-jobs/test-job/results', async route => {
  495 |     resultsCount += 1;
  496 |     if (resultsCount === 1) await gate;
  497 |     await route.fulfill({ json: results }).catch(() => {});
  498 |   });
  499 |   await page.goto('/?job=test-job');
> 500 |   await expect(page.getByRole('alert')).toContainText('隔离轮询故障');
      |                                         ^ Error: expect(locator).toContainText(expected) failed
  501 |   await expect.poll(() => failed.some(url => url.endsWith('/results'))).toBe(true);
  502 |   release();
  503 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  504 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  505 | });
  506 | 
  507 | test('取消请求失败保持未确认状态，不假装取消成功', async ({ page }) => {
  508 |   await setup(page, caps, { ...baseJob, status: 'running', phase: 'searching' }, { ...results, status: 'running' });
  509 |   await page.route('**/api/search-jobs/test-job/cancel', route => route.abort('connectionreset'));
  510 |   await page.goto('/?job=test-job');
  511 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  512 |   await page.getByRole('button', { name: '取消任务', exact: true }).click();
  513 |   await expect(page.getByRole('alert')).toContainText('取消状态尚未确认');
  514 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  515 |   await expect(page.getByText('已按你的操作取消')).toHaveCount(0);
  516 |   await expect(page.getByRole('button', { name: '取消任务', exact: true })).toBeEnabled();
  517 | });
  518 | 
  519 | test('任务已自然结束时取消返回原终态，不覆盖为cancelled', async ({ page }) => {
  520 |   await setup(page);
  521 |   let completed = false;
  522 |   await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: completed ? 'completed' : 'running' } }));
  523 |   await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: { ...results, status: completed ? 'completed' : 'running' } }));
  524 |   await page.route('**/api/search-jobs/test-job/cancel', route => { completed = true; return route.fulfill({ json: { job_id: 'test-job', status: 'completed', cancelled: false } }); });
  525 |   await page.goto('/?job=test-job');
  526 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  527 |   await page.getByRole('button', { name: '取消任务', exact: true }).click();
  528 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  529 |   await expect(page.getByText('任务已结束，已保留原任务状态。')).toBeVisible();
  530 |   await expect(page.getByText('已按你的操作取消')).toHaveCount(0);
  531 | });
  532 | 
  533 | test('课程归属和讲次按证据显示，身份未知与统计范围如实标注', async ({ page }, testInfo) => {
  534 |   const url = 'https://www.icourse163.org/course/TEST-123456';
  535 |   const identity = { status: 'partial', family_id: 'source-course-1', offering_id: null, lesson_id: null, family_url: url, offering_url: null, role: 'course', basis: 'recognized_url', source_url: url, evidence_ids: ['identity-search'], unknown_reason: '开课学期尚未确认。' } as const;
  536 |   const identified: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, title: '同来源课程身份 fixture', url, course_identity: { ...identity, evidence_ids: [...identity.evidence_ids] } }, evidence: [{ evidence_id: 'identity-search', kind: 'search', source: 'fixture', url }] };
  537 |   const unbacked: ResourceItem = { ...identified, resource: { ...identified.resource, resource_id: 'missing-identity', title: '缺少身份依据 fixture', course_identity: { ...identity, family_id: 'fabricated', lesson_id: 'fabricated-lesson', evidence_ids: ['missing'] } } };
  538 |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [identified, unbacked, item] }], identity_summary: { resource_records: 3, identified_course_families: 1, identified_course_offerings: 0, identified_lessons: 0, unknown_course_family_resources: 2, unknown_offering_resources: 3, unknown_identity_resources: 2, scope: 'observed_source_scoped_identities_not_global_course_deduplication' } });
  539 |   await page.goto('/?job=test-job');
  540 |   await expect(page.locator('.identity-note').nth(0)).toContainText('课程归属：已识别同来源课程 · 开课版本：未知 · 讲次：未知');
  541 |   await expect(page.locator('.identity-note').nth(1)).toContainText('课程归属：未知 · 开课版本：未知 · 讲次：未知');
  542 |   await expect(page.locator('.identity-note').nth(2)).toContainText('课程归属：未知');
  543 |   await expect(page.locator('.identity-summary')).toContainText('不是跨网站独立课程总数');
  544 |   await page.locator('.evidence-details summary').first().click();
  545 |   await expect(page.getByRole('link', { name: '查看同来源课程入口' })).toHaveAttribute('href', url);
  546 |   await expect(page.locator('.identity-details').first()).toContainText('开课学期尚未确认');
  547 |   await page.screenshot({ path: testInfo.outputPath('identity-evidence-desktop.png'), fullPage: true });
  548 |   await page.setViewportSize({ width: 390, height: 844 });
  549 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  550 |   await page.screenshot({ path: testInfo.outputPath('identity-evidence-mobile.png'), fullPage: true });
  551 | });
  552 | 
  553 | test('平台采集政策不冒充浏览器访问结论或全平台完成', async ({ page }, testInfo) => {
  554 |   const capability: Capabilities = { ...caps, platforms: [
  555 |     { id: 'bilibili', name: 'B站', discovery: 'search', metadata: 'site_policy_blocked', playback: 'unknown', source_url: 'https://example.org/terms', reviewed_at: time },
  556 |     { id: 'icourse163', name: '中国大学 MOOC', discovery: 'search', metadata: 'policy_unreviewed', playback: 'unknown' },
  557 |   ] };
  558 |   await setup(page, capability);
  559 |   await page.goto('/?job=test-job');
  560 |   await expect(page.locator('.completion-boundary')).toContainText('不代表每个平台均有结果');
  561 |   await expect(page.locator('.access-line').first()).toContainText('浏览器访问：未逐页实测');
  562 |   await page.locator('.capabilities-footer summary').click();
  563 |   await expect(page.locator('.platform-capabilities section').first()).toContainText('当前政策停止自动采集');
  564 |   await expect(page.locator('.platform-capabilities section').nth(1)).toContainText('自动采集许可范围待确认');
  565 |   await expect(page.locator('.capabilities-detail')).toContainText('自动采集停止不表示用户无法浏览');
  566 |   await expect(page.locator('.capabilities-detail')).toContainText('自动浏览器采集回退：已关闭');
  567 |   await expect(page.locator('.platform-capabilities')).not.toContainText('浏览器无法访问');
  568 |   await page.screenshot({ path: testInfo.outputPath('platform-policy-boundaries.png'), fullPage: true });
  569 | });
  570 | 
```