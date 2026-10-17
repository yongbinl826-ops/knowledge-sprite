# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: search.spec.ts >> 平台采集政策不冒充浏览器访问结论或全平台完成
- Location: tests\search.spec.ts:584:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: locator('.access-line').first()
Expected substring: "浏览器访问：未逐页实测"
Received string:    "登录：未知付费：未知选课：未知"
Timeout: 7000ms

Call log:
  - Expect "toContainText" locator('.access-line').first() with timeout 7000ms
  - waiting for locator('.access-line').first()
    18 × locator resolved to <div class="access-line">…</div>
       - unexpected value "登录：未知付费：未知选课：未知"

```

```yaml
- text: 登录：未知 付费：未知 选课：未知
```

# Test source

```ts
  492 |   await page.waitForTimeout(100);
  493 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  494 |   await expect(page.getByRole('heading', { name: '新任务的唯一结果' })).toBeVisible();
  495 |   await expect(page).toHaveURL(/job=new-job/);
  496 | });
  497 | 
  498 | test('轮询任一请求失败会及时取消同轮兄弟请求', async ({ page }) => {
  499 |   await page.addInitScript(() => {
  500 |     const target = window as typeof window & { __fetchAudit: { url: string; aborted: boolean }[] };
  501 |     target.__fetchAudit = [];
  502 |     const nativeFetch = window.fetch.bind(window);
  503 |     window.fetch = (input, init) => {
  504 |       const entry = { url: String(input), aborted: false };
  505 |       target.__fetchAudit.push(entry);
  506 |       init?.signal?.addEventListener('abort', () => { entry.aborted = true; }, { once: true });
  507 |       return nativeFetch(input, init);
  508 |     };
  509 |   });
  510 |   await setup(page);
  511 |   let recovered = false;
  512 |   let release!: () => void;
  513 |   const gate = new Promise<void>(resolve => { release = resolve; });
  514 |   await page.route('**/api/search-jobs/test-job', route => {
  515 |     return route.fulfill(!recovered ? { status: 503, json: { detail: '隔离轮询故障' } } : { json: baseJob });
  516 |   });
  517 |   await page.route('**/api/search-jobs/test-job/results', async route => {
  518 |     if (!recovered) await gate;
  519 |     await route.fulfill({ json: results }).catch(() => {});
  520 |   });
  521 |   await page.goto('/?job=test-job');
  522 |   await expect(page.getByRole('alert')).toContainText('隔离轮询故障');
  523 |   await expect.poll(() => page.evaluate(() => {
  524 |     const entries = (window as typeof window & { __fetchAudit: { url: string; aborted: boolean }[] }).__fetchAudit.filter(entry => entry.url.endsWith('/results'));
  525 |     return entries.length >= 2 && entries.every(entry => entry.aborted);
  526 |   })).toBe(true);
  527 |   recovered = true; release();
  528 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  529 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  530 | });
  531 | 
  532 | test('取消请求失败保持未确认状态，不假装取消成功', async ({ page }) => {
  533 |   await setup(page, caps, { ...baseJob, status: 'running', phase: 'searching' }, { ...results, status: 'running' });
  534 |   await page.route('**/api/search-jobs/test-job/cancel', route => route.abort('connectionreset'));
  535 |   await page.goto('/?job=test-job');
  536 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  537 |   await page.getByRole('button', { name: '取消任务', exact: true }).click();
  538 |   await expect(page.getByRole('alert')).toContainText('取消状态尚未确认');
  539 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  540 |   await expect(page.getByText('已按你的操作取消')).toHaveCount(0);
  541 |   await expect(page.getByRole('button', { name: '取消任务', exact: true })).toBeEnabled();
  542 | });
  543 | 
  544 | test('任务已自然结束时取消返回原终态，不覆盖为cancelled', async ({ page }) => {
  545 |   await setup(page);
  546 |   let completed = false;
  547 |   await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: completed ? 'completed' : 'running' } }));
  548 |   await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: { ...results, status: completed ? 'completed' : 'running' } }));
  549 |   await page.route('**/api/search-jobs/test-job/cancel', route => { completed = true; return route.fulfill({ json: { job_id: 'test-job', status: 'completed', cancelled: false } }); });
  550 |   await page.goto('/?job=test-job');
  551 |   await expect(page.locator('.job-status')).toHaveText('正在查找');
  552 |   await page.getByRole('button', { name: '取消任务', exact: true }).click();
  553 |   await expect(page.locator('.job-status')).toHaveText('检索完成');
  554 |   await expect(page.getByText('任务已结束，已保留原任务状态。')).toBeVisible();
  555 |   await expect(page.getByText('已按你的操作取消')).toHaveCount(0);
  556 | });
  557 | 
  558 | test('课程归属和讲次按证据显示，身份未知与统计范围如实标注', async ({ page }, testInfo) => {
  559 |   const url = 'https://www.icourse163.org/course/TEST-123456';
  560 |   const identity = { status: 'partial', family_id: 'source-course-1', offering_id: null, lesson_id: null, family_url: url, offering_url: null, role: 'course', basis: 'recognized_url', source_url: url, evidence_ids: ['identity-search'], unknown_reason: '开课学期尚未确认。' } as const;
  561 |   const identified: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, title: '同来源课程身份 fixture', url, course_identity: { ...identity, evidence_ids: [...identity.evidence_ids] } }, evidence: [{ evidence_id: 'identity-search', kind: 'search', source: 'fixture', url: url + '?utm_source=fixture' }] };
  562 |   const unbacked: ResourceItem = { ...identified, resource: { ...identified.resource, resource_id: 'missing-identity', title: '缺少身份依据 fixture', course_identity: { ...identity, family_id: 'fabricated', lesson_id: 'fabricated-lesson', evidence_ids: ['missing'] } } };
  563 |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [identified, unbacked, item] }], identity_summary: { resource_records: 3, identified_course_families: 1, identified_course_offerings: 0, identified_lessons: 0, unknown_course_family_resources: 2, unknown_offering_resources: 3, unknown_identity_resources: 2, scope: 'observed_source_scoped_identities_not_global_course_deduplication' } });
  564 |   await page.goto('/?job=test-job');
  565 |   await expect(page.locator('.identity-note').nth(0)).toContainText('课程归属：已识别同来源课程 · 开课版本：未知 · 讲次：未知');
  566 |   await expect(page.locator('.identity-note').nth(1)).toContainText('课程归属：未知 · 开课版本：未知 · 讲次：未知');
  567 |   await expect(page.locator('.identity-note').nth(2)).toContainText('课程归属：未知');
  568 |   await expect(page.locator('.identity-summary')).toContainText('不是跨网站独立课程总数');
  569 |   await page.locator('.evidence-details summary').first().click();
  570 |   await expect(page.getByRole('link', { name: '查看同来源课程入口' })).toHaveAttribute('href', url);
  571 |   await expect(page.locator('.identity-details').first()).toContainText('开课学期尚未确认');
  572 |   await page.screenshot({ path: testInfo.outputPath('identity-evidence-desktop.png'), fullPage: true });
  573 |   await page.setViewportSize({ width: 390, height: 844 });
  574 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  575 |   await page.locator('.identity-note').last().scrollIntoViewIfNeeded();
  576 |   await expect(page.locator('.identity-note').last()).toBeVisible();
  577 |   await page.locator('.identity-note').first().scrollIntoViewIfNeeded();
  578 |   await expect(page.locator('.identity-details').first()).toBeVisible();
  579 |   // Capture the actual visible card; offscreen content-visibility placeholders
  580 |   // in a full-page screenshot do not represent the mobile reading experience.
  581 |   await page.screenshot({ path: testInfo.outputPath('identity-evidence-mobile.png') });
  582 | });
  583 | 
  584 | test('平台采集政策不冒充浏览器访问结论或全平台完成', async ({ page }, testInfo) => {
  585 |   const capability: Capabilities = { ...caps, platforms: [
  586 |     { id: 'bilibili', name: 'B站', discovery: 'search', metadata: 'site_policy_blocked', playback: 'unknown', source_url: 'https://example.org/terms', reviewed_at: time },
  587 |     { id: 'icourse163', name: '中国大学 MOOC', discovery: 'search', metadata: 'policy_unreviewed', playback: 'unknown' },
  588 |   ] };
  589 |   await setup(page, capability);
  590 |   await page.goto('/?job=test-job');
  591 |   await expect(page.locator('.completion-boundary')).toContainText('不代表每个平台均有结果');
> 592 |   await expect(page.locator('.access-line').first()).toContainText('浏览器访问：未逐页实测');
      |                                                      ^ Error: expect(locator).toContainText(expected) failed
  593 |   await page.locator('.capabilities-footer summary').click();
  594 |   await expect(page.locator('.platform-capabilities section').first()).toContainText('当前政策停止自动采集');
  595 |   await expect(page.locator('.platform-capabilities section').nth(1)).toContainText('自动采集许可范围待确认');
  596 |   await expect(page.locator('.capabilities-detail')).toContainText('自动采集停止不表示用户无法浏览');
  597 |   await expect(page.locator('.capabilities-detail')).toContainText('在线浏览器采集回退：已关闭');
  598 |   await expect(page.locator('.capabilities-detail')).toContainText('受控 JS 补全：未知（服务端未返回）');
  599 |   await expect(page.locator('.platform-capabilities')).not.toContainText('浏览器无法访问');
  600 |   await page.screenshot({ path: testInfo.outputPath('platform-policy-boundaries.png'), fullPage: true });
  601 | });
  602 | 
  603 | test('可靠普通课程与显式父课程讲次分别展示，缺失或冲突证据保持未知', async ({ page }) => {
  604 |   const courseUrl = 'https://example.org/course';
  605 |   const lessonUrl = 'https://example.org/lesson/one';
  606 |   const commonIdentity = { status: 'identified', family_id: 'course-fixture', offering_id: null, lesson_id: null, family_url: courseUrl, offering_url: null, role: 'course', basis: 'page_course', source_url: courseUrl, evidence_ids: ['course-type'], unknown_reason: null } as const;
  607 |   const course: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, title: '普通课程结构 fixture', url: courseUrl, resource_type: 'course', video_evidence_status: 'none', course_identity: { ...commonIdentity, evidence_ids: ['course-type'] }, field_provenance: { resource_type: { evidence_id: 'course-type', source: 'jsonld.@type', url: courseUrl } } }, evidence: [{ evidence_id: 'course-type', kind: 'page', field: 'resource_type', source: 'jsonld.@type', url: courseUrl, text: 'course' }] };
  608 |   const parentRecord: Evidence = { evidence_id: 'parent-relation', kind: 'page', field: 'parent_course_url', source: 'jsonld.isPartOf.Course', url: lessonUrl, text: JSON.stringify({ '@type': 'Course', url: courseUrl }) };
  609 |   const lesson: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_id: 'lesson-fixture', title: '显式课程讲次 fixture', url: lessonUrl, parent_course_url: courseUrl, course_identity: { ...commonIdentity, role: 'lesson', basis: 'page_is_part_of', source_url: lessonUrl, lesson_id: 'lesson-one', evidence_ids: ['parent-relation'] }, field_provenance: { parent_course_url: { evidence_id: 'parent-relation', source: 'jsonld.isPartOf.Course', url: lessonUrl } } }, evidence: [parentRecord] };
  610 |   const conflict: ResourceItem = { ...lesson, resource: { ...lesson.resource, resource_id: 'conflict-fixture', title: '父课程关系冲突 fixture', parent_course_url: 'https://different.example.org/course' } };
  611 |   const genericOutline: ResourceItem = { ...course, resource: { ...course.resource, resource_id: 'generic-outline-fixture', title: '普通页面目录不能证明课程 fixture', field_provenance: { resource_type: { evidence_id: 'course-type', source: 'html.visible_course_outline', url: courseUrl } } }, evidence: [{ ...course.evidence[0], source: 'html.visible_course_outline' }] };
  612 |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [course, lesson, conflict, genericOutline] }] });
  613 |   await page.goto('/?job=test-job');
  614 |   await expect(page.locator('.video-evidence-note').first()).toContainText('页面含课程结构证据 · 是否含视频未核验');
  615 |   await expect(page.locator('.video-evidence-note').first()).not.toContainText('页面含视频结构证据');
  616 |   await expect(page.locator('.identity-note').nth(1)).toContainText('课程归属：已识别同来源课程 · 开课版本：未知 · 讲次：已识别');
  617 |   await expect(page.locator('.identity-note').nth(2)).toContainText('课程归属：未知 · 开课版本：未知 · 讲次：未知');
  618 |   await expect(page.locator('.identity-note').nth(3)).toContainText('课程归属：未知');
  619 |   await expect(page.locator('.video-evidence-note').nth(3)).not.toContainText('页面含课程结构证据');
  620 |   await expect(page.locator('.access-line').first()).toContainText('登录：');
  621 | });
  622 | 
  623 | test('受控 JS 状态与真实字段增益分开，课程表证据兼容且 DOM 哈希仅作来源记录', async ({ page }, testInfo) => {
  624 |   const source = 'html.microsoft_ai.curriculum_table';
  625 |   const url = 'https://microsoft.github.io/AI-For-Beginners/';
  626 |   const acquisition = { acquisition: 'offline_rendered_dom', render_id: 'render-fixture', dom_sha256: 'a'.repeat(64) };
  627 |   const chapters: Chapter[] = [{ title: 'Fixture chapter A', url: null, evidence_id: 'render-chapter-0' }, { title: 'Fixture chapter B', url: null, evidence_id: 'render-chapter-1' }];
  628 |   const dynamic: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_id: 'render-gain', title: '动态课程 fixture', url,
  629 |     resource_type: 'course', video_evidence_status: 'none', metadata_evidence_level: 'catalog', chapters,
  630 |     field_provenance: { resource_type: { ...acquisition, evidence_id: 'render-type', source, url }, chapters: { ...acquisition, evidence_id: 'render-catalog', source, url } },
  631 |     render_diagnostics: { ...acquisition, status: 'rendered', source_url: url, static_chapter_count: 0, rendered_chapter_count: 2, added_fields: ['resource_type', 'chapters'] } },
  632 |     evidence: [{ ...acquisition, evidence_id: 'render-type', kind: 'page', field: 'resource_type', source, url, text: 'Observed public curriculum table' },
  633 |       { ...acquisition, evidence_id: 'render-catalog', kind: 'catalog', field: 'chapters', source, url, text: JSON.stringify(chapters) },
  634 |       ...chapters.map((chapter, index) => ({ ...chapterEvidence(chapter, index), ...acquisition, url, source }))] };
  635 |   const noGain: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_id: 'render-no-gain', title: '执行无增益 fixture',
  636 |     render_diagnostics: { ...acquisition, status: 'rendered', static_chapter_count: 0, rendered_chapter_count: 0, added_fields: ['chapters'] } } };
  637 |   const timeout: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_id: 'render-timeout', title: '动态超时 fixture',
  638 |     render_diagnostics: { status: 'render_timeout', static_chapter_count: 0, dom_sha256: '<img src=x onerror=alert(1)>' } } };
  639 |   await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [dynamic, noGain, timeout] }] });
  640 |   await page.goto('/?job=test-job');
  641 |   await expect(page.locator('.resource-card')).toHaveCount(3);
  642 |   for (const card of await page.locator('.resource-card').all()) await card.getByText('查看来源与证据', { exact: true }).click();
  643 |   const cards = page.locator('.resource-card');
  644 |   await expect(cards.nth(0).locator('.video-evidence-note')).toContainText('页面含课程结构证据 · 是否含视频未核验');
  645 |   await expect(cards.nth(0).locator('.render-diagnostics')).toContainText('静态目录项：0 · DOM 提取目录项：2');
  646 |   await expect(cards.nth(0).locator('.render-diagnostics')).toContainText('可对应来源的新增字段：课程类型、目录');
  647 |   await expect(cards.nth(0).locator('.chapter-list li')).toHaveCount(2);
  648 |   await expect(cards.nth(0).locator('.render-diagnostics code')).toHaveText('a'.repeat(64));
  649 |   await expect(cards.nth(1).locator('.render-diagnostics')).toContainText('离线执行完成（不代表字段有增益）');
  650 |   await expect(cards.nth(1).locator('.render-diagnostics')).toContainText('可对应来源的新增字段：尚未确认');
  651 |   await expect(cards.nth(2).locator('.render-diagnostics')).toContainText('状态：补全超时');
  652 |   await expect(cards.nth(2).locator('.render-diagnostics')).toContainText('DOM 提取目录项：未知');
  653 |   await expect(cards.nth(2).locator('.render-diagnostics code')).toHaveText('未知');
  654 |   await expect(page.locator('.render-diagnostics img')).toHaveCount(0);
  655 |   await expect(cards.nth(0).locator('.access-line')).toContainText('登录：');
  656 |   await page.setViewportSize({ width: 390, height: 844 });
  657 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  658 |   await page.screenshot({ path: testInfo.outputPath('render-diagnostics-mobile.png'), fullPage: true });
  659 | });
  660 | 
  661 | test('受控 JS 配置与在线回退及动态可用性分开', async ({ page }, testInfo) => {
  662 |   const capability: Capabilities = { ...caps, js_render: { enabled: true, status: 'configured', allowed_hosts: ['microsoft.github.io'], asset_hosts: ['cdn.jsdelivr.net'],
  663 |     timeout_seconds: 20, max_resources: 6, max_target_requests: 12, max_doh_requests: 24, max_total_bytes: 2_000_000,
  664 |     max_dom_bytes: 1_000_000, max_observed_data_resources: 2, online_browser_fallback: false,
  665 |     message: '仅显式允许来源；公开资源经安全采集后离线执行', process_network_egress: 'unknown', playback_verified: false } };
  666 |   await setup(page, capability);
  667 |   await page.goto('/');
  668 |   await page.locator('.capabilities-footer summary').click();
  669 |   const detail = page.locator('.capabilities-detail');
  670 |   await expect(detail).toContainText('在线浏览器采集回退：已关闭');
  671 |   await expect(detail).toContainText('受控 JS 补全：已配置，动态增益需逐页核对');
  672 |   await expect(detail).toContainText('允许页面来源：microsoft.github.io · 允许跨源资产：cdn.jsdelivr.net');
  673 |   await expect(detail).toContainText('单次补全上限：6 个资产 · 12 次补充目标请求 · 24 次 DoH · 20 秒');
  674 |   await expect(detail).not.toContainText('已验证动态采集成功');
  675 |   await page.screenshot({ path: testInfo.outputPath('render-capability-configured.png'), fullPage: true });
  676 |   await page.route('**/api/capabilities', route => route.fulfill({ json: { ...capability, js_render: { ...capability.js_render, enabled: false, status: 'disabled' } } }));
  677 |   await page.getByRole('button', { name: '重新检查服务状态' }).click();
  678 |   await expect(detail).toContainText('受控 JS 补全：已关闭');
  679 | });
  680 | 
  681 | test('创建响应丢失后刷新可按原幂等key恢复已结束任务，确认后清除tab存储', async ({ page }, testInfo) => {
  682 |   await setup(page);
  683 |   const requests: { key: string | undefined; body: unknown }[] = [];
  684 |   await page.route('**/api/search-jobs', async route => {
  685 |     requests.push({ key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON() });
  686 |     if (requests.length === 1) return route.abort('connectionreset');
  687 |     return route.fulfill({ status: 202, json: { job_id: 'test-job', status: 'completed', reused: true } });
  688 |   });
  689 |   await page.goto('/');
  690 |   await page.getByLabel('知识点', { exact: true }).fill('响应丢失后的原知识点');
  691 |   await page.getByLabel('学生基础').selectOption('intermediate');
  692 |   await page.getByLabel('学习语言').selectOption('en');
```