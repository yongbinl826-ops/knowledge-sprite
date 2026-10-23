import { expectGalleryTitlesOnly } from './coverTitleContract';
import { test, expect, type BrowserContext, type Page, type TestInfo } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Explicit local API mocks. No models, source search, personal DB, or real images.
const retained = JSON.parse(readFileSync(resolve(import.meta.dirname, 'fixtures/retained-r9-ui-projects.json'), 'utf8')).cases.browser_flashcards_intermediate;
const apiFixture = JSON.parse(readFileSync(resolve(import.meta.dirname, 'device-api-fixture.json'), 'utf8')).responses;
const caps = { mode: 'mock-device-QA', teaching_match_enabled: true,
  project_analysis: { status: 'available', message: 'mock', max_functions: 12, max_knowledge_points: 24 },
  project_search: { max_batches: 6, batch_size: 5, max_search_requests: 10, max_detail_pages: 10, deadline_seconds: 180 },
  limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 10, max_detail_pages: 10 } };
const publicCourse = { course_id: 'public-1', title: '公开 Python 课程', url: 'https://www.bilibili.com/video/BV183411B7nJ/', platform: 'bilibili', resource_type: 'video', observed_at: '2026-10-20T00:00:00Z', expires_at: '2026-10-21T00:00:00Z', access_notice: '平台访问条件请自行核对' };
type Call = { method: string; path: string; time: number; body?: any; token?: string };
async function mockAPI(context: BrowserContext, options: { delayedPost?: boolean; uncertain?: boolean } = {}) {
  const calls: Call[] = [], tasks = new Map<string, any>(); let postSettled = false, earlyGets = 0, offline = false;
  await context.addInitScript(() => Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => localStorage.getItem('__qa.offline') !== '1' }));
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5195').origin) {
      if (request.resourceType() === 'image') return route.fulfill({ status: 204, body: '' });
      return route.abort();
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    expect(url.search).not.toContain('Bearer'); expect(url.search).not.toContain('capability');
    if (offline) return route.abort('internetdisconnected');
    const call: Call = { method: request.method(), path: url.pathname, time: Date.now(), body: request.postDataJSON() };
    calls.push(call);
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: caps });
    if (url.pathname === '/api/mobile/courses') {
      expect(request.method()).toBe('GET'); expect(request.headers().authorization).toBeUndefined();
      expect([...url.searchParams.keys()].sort()).toEqual(['limit', 'offset', 'query', ...(url.searchParams.has('platform') ? ['platform'] : [])].sort());
      return route.fulfill({ json: { items: [publicCourse], total: 1, has_more: false } });
    }
    expect(url.pathname).toMatch(/^\/api\/mobile\/tasks\/[a-f0-9-]{36}(?:\/cancel)?$/);
    const token = request.headers().authorization; expect(token).toMatch(/^Bearer [A-Za-z0-9_-]{43}$/); call.token = token;
    const id = url.pathname.split('/')[4];
    if (request.method() === 'POST' && !url.pathname.endsWith('/cancel')) {
      expect(tasks.has(id)).toBe(false); const body = call.body;
      expect(['analysis', 'search', 'direct_search']).toContain(body.kind); expect(JSON.stringify(body)).not.toContain('learned');
      const task = { task_id: id, kind: body.kind, expires_at: new Date(Date.now() + 7200000).toISOString(), status: 'queued', error: null, result: null, input: body.input, analysis: body.analysis, token, polls: 0 };
      tasks.set(id, task);
      if (options.delayedPost) { await new Promise(resolve => setTimeout(resolve, 2300)); postSettled = true; }
      if (options.uncertain) return route.abort('failed');
      return route.fulfill({ status: 202, json: { ...task, token: undefined, input: undefined, analysis: undefined, polls: undefined } });
    }
    const task = tasks.get(id); expect(task?.token).toBe(token);
    if (request.method() === 'POST') return route.fulfill({ json: { ...task, status: 'cancelled', result: null, token: undefined } });
    if (options.delayedPost && !postSettled) { earlyGets++; return route.fulfill({ status: 404, json: { detail: 'too early' } }); }
    task.polls++;
    if (options.uncertain) {
      if (task.polls === 1) return route.fulfill({ status: 429, headers: { 'Retry-After': '2' }, json: { detail: 'mock rate limit' } });
      return route.fulfill({ status: 404, json: { detail: '任务不存在或已失效' } });
    }
    if (task.kind === 'direct_search') return route.fulfill({ json: { task_id: id, kind: task.kind, expires_at: task.expires_at, status: 'completed', error: null, result: apiFixture.direct_completed.result } });
    const result = structuredClone(retained); result.project_id = 'temporary-server-project'; result.current_version = 8;
    result.input = task.input || result.input; result.version.input = result.input; result.version.version = 8;
    result.version.analysis = task.analysis || result.version.analysis;
    if (task.kind === 'analysis') { result.version.status = 'analyzed'; result.version.confirmation = null; result.points = []; delete result.pipeline; }
    return route.fulfill({ json: { task_id: id, kind: task.kind, expires_at: task.expires_at, status: task.kind === 'analysis' ? 'completed' : 'partial', error: null, result } });
  });
  return { calls, tasks, earlyGets: () => earlyGets, offline: (value: boolean) => { offline = value; } };
}
async function readState(page: Page) {
  return page.evaluate(() => {
    const active = localStorage.getItem('knowledge-sprite.device.v1.head');
    const raw = localStorage.getItem(`knowledge-sprite.device.v1.slot${active}`);
    return raw ? JSON.parse(JSON.parse(raw).payload) : null;
  });
}
async function create(page: Page) {
  await page.goto("/");
  await expect(page.locator("#project-background")).toHaveCount(0);
  await expect(page.locator("#project-level")).toHaveCount(0);
  await expect(page.locator("#project-language")).toBeVisible();
  await page.getByLabel('项目名称', { exact: true }).fill('设备 A 的合成项目');
  await page.getByLabel('功能需求', { exact: true }).fill('公开合成测试：离线单词卡与本机存储。');
  await page.getByRole('button', { name: '分析项目', exact: true }).click();
}
async function noOverflow(page: Page) {
  await page.waitForFunction(() => !document.documentElement.dataset.motionKind);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
}
async function requestEvidence(info: TestInfo, ...groups: { calls: Call[] }[]) {
  await info.attach('sanitized-request-observations', { contentType: 'application/json', body: Buffer.from(JSON.stringify(groups.map((group, context) => ({ context,
    calls: group.calls.map(call => ({ method: call.method, path: call.path.replace(/[a-f0-9-]{36}/g, ':task-id'), time: call.time,
      authorization_present: !!call.token, kind: call.body?.kind, payload_keys: call.body ? Object.keys(call.body) : [] })),
    real_model_or_search_requests: 0, mode: 'Playwright synthetic API; all external blocked',
  })), null, 2)) });
}

test('two isolated devices: drafts/history offline, old progress retained without controls; shared library hidden; delayed POST has no early GET', async ({ browser }, info) => {
  test.setTimeout(60000);
  const a = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  const b = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const am = await mockAPI(a, { delayedPost: true }), bm = await mockAPI(b);
  const ap = await a.newPage(), bp = await b.newPage(); const errors: string[] = []; ap.on('pageerror', e => errors.push(e.message)); bp.on('pageerror', e => errors.push(e.message));
  await create(ap); await expect(ap.getByText('正在梳理项目知识点', { exact: true })).toBeVisible();
  await expect(ap.locator('.simple-knowledge-list')).toBeVisible(); expect(am.earlyGets()).toBe(0); await expect(ap.getByRole('spinbutton')).toHaveCount(0);
  const local = await readState(ap), id = local.selected.id; expect(id).not.toBe('temporary-server-project');
  expect(local.projects[id].ticket.capability).toBe(''); expect(await ap.title()).toContain('项目制学习引导小精灵'); expect(am.calls.filter(c => c.method === 'POST')).toHaveLength(1);
  // Seed a pre-existing schema1 record; removing the product control must not
  // erase history or silently pre-filter the student's own learning selection.
  const oldProgress = { learned: true, at: '2026-10-19T00:00:00Z' };
  await ap.evaluate(async ({ id, oldProgress }) => {
    const slot = localStorage.getItem('knowledge-sprite.device.v1.head')!;
    const key = `knowledge-sprite.device.v1.slot${slot}`, envelope = JSON.parse(localStorage.getItem(key)!);
    const state = JSON.parse(envelope.payload); state.projects[id].learned['1:K5'] = oldProgress; state.revision++;
    envelope.payload = JSON.stringify(state);
    envelope.sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(envelope.payload)))].map(n => n.toString(16).padStart(2, '0')).join('');
    localStorage.setItem(key, JSON.stringify(envelope));
  }, { id, oldProgress });
  await ap.reload(); await expect(ap.locator('.simple-knowledge-list')).toBeVisible();
  const point = ap.locator('[data-point-id="K5"]');
  await expect(ap.locator('.device-learned-toggle, .device-progress')).toHaveCount(0);
  expect((await readState(ap)).projects[id].learned['1:K5']).toEqual(oldProgress);
  await expect(point.locator('.simple-point-selection input')).toBeChecked();
  await point.locator('.simple-point-selection input').uncheck();
  await expect(ap.getByText('专业名称和勾选已保存在本机草稿。')).toBeVisible();
  expect((await readState(ap)).projects[id].drafts[1].knowledge_points.map((p: any) => p.learning_order)).toEqual(retained.version.analysis.knowledge_points.map((p: any) => p.learning_order));
  am.offline(true); await ap.evaluate(() => localStorage.setItem('__qa.offline', '1')); await ap.reload();
  await expect(ap.locator('[data-point-id="K5"] .simple-point-selection input')).not.toBeChecked();
  await expect(ap.locator('.device-learned-toggle, .device-progress')).toHaveCount(0);
  expect((await readState(ap)).projects[id].learned['1:K5']).toEqual(oldProgress);
  await noOverflow(ap); await ap.screenshot({ path: info.outputPath('mobile-offline-review.png') });
  expect(am.calls.filter(c => c.method === 'POST')).toHaveLength(1);
  // Saving selections is local and versioned, independent of internet availability.
  await ap.getByRole('button', { name: '保存修改', exact: true }).click();
  await expect(ap.getByRole('heading', { name: /确认知识点 · v2/ })).toBeVisible();
  await ap.locator('[data-point-id="K5"] .simple-point-selection input').check();
  await ap.getByRole('button', { name: '查找视频', exact: true }).click();
  await expect(ap.locator('.project-result-details')).toContainText('选择已在本机确认');
  await expect(ap.locator('.project-search-controls')).toContainText('仅本机确认，未开始课程检索');
  await expect(ap.locator('.video-cover-skeleton')).toHaveCount(0);
  expect((await readState(ap)).projects[id].views.at(-1).version.confirmation.local_only).toBe(true);
  await expect(ap.locator('.device-learned-toggle, .device-progress')).toHaveCount(0);
  expect((await readState(ap)).projects[id].learned['1:K5']).toEqual(oldProgress);
  expect(am.calls.filter(c => c.method === 'POST')).toHaveLength(1);
  await ap.getByRole('button', { name: /我的项目/ }).click();
  await ap.getByLabel('查看版本').selectOption('1');
  await expect(ap.locator('[data-point-id="K5"] .simple-point-selection input')).not.toBeEditable();
  await expect(ap.locator('[data-point-id="K5"] .simple-point-selection input')).toBeChecked();
  await ap.getByLabel('查看版本').selectOption('2'); await ap.getByRole('button', { name: /我的项目/ }).click();
  await bp.goto('/'); await bp.getByRole('button', { name: /我的项目/ }).click();
  expect(await bp.getByLabel('已保存项目').locator('option').count()).toBe(1); expect(await readState(bp)).toBeNull();
  await bp.getByRole('button', { name: /我的项目/ }).click();
  am.offline(false); await ap.evaluate(() => localStorage.removeItem('__qa.offline'));
  for (const page of [ap, bp]) {
    await expect(page.getByRole('button', { name: '共享课程库', exact: true })).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(/共享(?:课程)?库/);
    await noOverflow(page); await page.screenshot({ path: info.outputPath(page === ap ? 'mobile-project-without-library.png' : 'desktop-project-without-library.png') });
  }
  expect(am.calls.some(c => c.path === '/api/mobile/courses')).toBe(false); expect(bm.calls.some(c => c.path === '/api/mobile/courses')).toBe(false);
  expect(bm.calls.some(c => c.path === '/api/projects')).toBe(false); expect(am.calls.some(c => c.path === '/api/projects')).toBe(false);
  expect(errors).toEqual([]); await requestEvidence(info, am, bm); await a.close(); await b.close();
});

test('search projection remains cover-only and locally mapped; quota failure keeps old state and blocks new POST; deletion is explicit', async ({ browser }, info) => {
  test.setTimeout(45000); const context = await browser.newContext({ viewport: { width: 768, height: 1024 } });
  const mock = await mockAPI(context), page = await context.newPage(); await create(page);
  await expect(page.locator('.simple-knowledge-list')).toBeVisible();
  await page.getByRole('button', { name: '查找视频', exact: true }).click();
  await expect(page.locator('.video-cover-card')).toHaveCount(1); await expectGalleryTitlesOnly(page);
  expect((await readState(page)).selected.version).toBe(1); expect(mock.calls.filter(c => c.method === 'POST')).toHaveLength(2);
  expect(mock.calls.filter(c => c.method === 'POST')[1].body.acknowledged_skipped_prerequisites).toBeUndefined();
  expect(mock.calls.filter(c => c.method === 'POST')[1].body.reviewed_topic_technologies).toEqual({ 'localStorage 读写与JSON序列化': 'JavaScript Web Storage' });
  await expect(page.getByRole('navigation', { name: '已选知识点' })).toContainText('检索语境：JavaScript Web Storage');
  await page.locator('.course-cover').focus(); await expect(page.locator('.course-cover')).toBeFocused();
  await noOverflow(page); await page.screenshot({ path: info.outputPath('tablet-results-cover-only.png') });
  const before = JSON.stringify(await readState(page)); const oldPOSTs = mock.calls.filter(c => c.method === 'POST').length;
  await page.getByRole('button', { name: /01 项目描述/ }).click();
  await page.evaluate(() => { const original = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) { if (key.startsWith('knowledge-sprite.device.v1.')) throw new DOMException('QA quota full', 'QuotaExceededError'); return original.call(this, key, value); }; });
  await page.getByLabel('项目名称', { exact: true }).fill('不能覆盖旧项目');
  await page.getByRole('button', { name: '保存需求并重新分析', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '未能可靠保存到本机' })).toBeVisible();
  expect(JSON.stringify(await readState(page))).toBe(before); expect(mock.calls.filter(c => c.method === 'POST')).toHaveLength(oldPOSTs);
  await page.reload(); await expect(page.locator('.video-cover-card')).toHaveCount(1);
  await page.getByRole('button', { name: /我的项目/ }).click(); await page.getByRole('button', { name: '删除本机项目', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('无法恢复');
  await expect(page.getByRole('alert')).not.toContainText(/共享(?:课程)?库/);
  await page.getByRole('button', { name: '确认删除本机项目', exact: true }).click();
  await expect(page.getByLabel('已保存项目').locator('option')).toHaveCount(1); expect(Object.keys((await readState(page)).projects)).toHaveLength(0);
  expect(mock.calls.filter(c => c.method === 'POST')).toHaveLength(oldPOSTs); await requestEvidence(info, mock); await context.close();
});

test('uncertain POST is not repeated across reload; 429 respects delay; expired task keeps local input and enables explicit recovery', async ({ browser }, info) => {
  test.setTimeout(40000); const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mock = await mockAPI(context, { uncertain: true }), page = await context.newPage(); await create(page);
  await expect(page.getByRole('alert').filter({ hasText: '提交结果尚未确认' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('alert').filter({ hasText: '临时任务已过期或服务已重启' })).toBeVisible();
  expect(mock.calls.filter(c => c.method === 'POST')).toHaveLength(1);
  const gets = mock.calls.filter(c => c.path.startsWith('/api/mobile/tasks/') && c.method === 'GET'); expect(gets).toHaveLength(2);
  expect(gets[1].time - gets[0].time).toBeGreaterThanOrEqual(1900); expect(gets.every(c => c.token === gets[0].token)).toBe(true);
  const stored = await readState(page), project = stored.projects[stored.selected.id]; expect(project.ticket.capability).toBe('');
  await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue('设备 A 的合成项目');
  await expect(page.getByRole('button', { name: '保存需求并重新分析', exact: true })).toBeEnabled();
  await noOverflow(page); await page.screenshot({ path: info.outputPath('mobile-expired-recovery.png') }); await requestEvidence(info, mock); await context.close();
});

test('direct search is a local project, explicit cancel and retry retain direct task contract and fresh capability', async ({ browser }, info) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } }); const mock = await mockAPI(context), page = await context.newPage();
  await page.goto('/'); await page.getByRole('button', { name: /直接搜索知识点/ }).click();
  await page.getByLabel('知识点', { exact: true }).fill('Python list indexing');
  await page.getByRole('button', { name: '开始查找', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: '取消项目检索', exact: true }).click();
  await expect(page.locator('.project-search-controls')).toContainText('已取消');
  const id = (await readState(page)).selected.id;
  await page.getByRole('button', { name: '重新检索这些知识点', exact: true }).click();
  await expect(page.locator('.project-search-controls')).toContainText('检索完成');
  const state = await readState(page); expect(state.selected.id).toBe(id); expect(state.selected.version).toBe(2);
  const posts = mock.calls.filter(call => call.method === 'POST'); expect(posts).toHaveLength(3);
  expect(posts[0].body.kind).toBe('direct_search'); expect(posts[1].path.endsWith('/cancel')).toBe(true); expect(posts[2].body.kind).toBe('direct_search');
  expect(posts[0].token).toBe(posts[1].token); expect(posts[0].token).not.toBe(posts[2].token);
  expect(posts[0].body.request.preferred_platforms).toEqual(['bilibili', 'icourse163']);
  expect(state.projects[id].views[0].version.status).toBe('cancelled'); expect(await page.locator('.stage-content .gallery-motion').innerText()).toBe('');
  await noOverflow(page); await requestEvidence(info, mock); await context.close();
});
