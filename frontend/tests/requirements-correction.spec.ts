import { test, expect, type Page, type TestInfo } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Only local intercepted API responses. Actual retained groups come from the
// frozen create_app GET producer; ProjectView and action responses are synthetic.
const ROOT = resolve(import.meta.dirname, 'fixtures/requirements-correction');
const read = (path: string) => JSON.parse(readFileSync(resolve(ROOT, path), 'utf8'));
const producer = read('manifest.json');
const parts = producer.four_get_payloads.filter((p: any) => p.label === 'pygame').map((p: any) => ({ ...p, body: read(p.path) }));
const retained = JSON.parse(readFileSync(resolve(import.meta.dirname, '../../tests/fixtures/related-policy-20261020/pygame-analysis.json'), 'utf8'));
const stamp = '2026-10-20T11:50:00Z';
const caps = { teaching_match_enabled: true, mode: 'offline-requirements-QA', search: { status: 'configured', message: 'mock', providers: [], selected_provider: 'mock' }, llm: { status: 'configured', message: 'mock' }, fetch: { status: 'available', message: 'mock', browser_fallback: false }, platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 10, max_detail_pages: 10 }, project_analysis: { status: 'configured', message: 'mock', max_knowledge_points: 24, max_functions: 12 }, project_search: { max_batches: 6, batch_size: 5, max_search_requests: 20, max_detail_pages: 20, deadline_seconds: 180 } };
async function setup(page: Page, options: { initial?: 'results' | 'analysis'; failAnalysis?: boolean; historical?: boolean } = {}) {
  const requests: { method: string; path: string; body?: any; key?: string }[] = [], unexpected: string[] = [], errors: string[] = [];
  const guard = { image_fallbacks: 0, external_blocked: [] as string[], real_api_requests: 0, external_requests_sent: 0, models: 0, searches: 0 };
  const origin = new URL(process.env.PLAYWRIGHT_BASE_URL!).origin;
  const history = new Map<number, any>(); let version = 0, created = false, failures = options.failAnalysis ? 1 : 0;
  let input = structuredClone(retained.input);
  if (options.historical) input = { ...input, student_level: 'advanced', preferred_platforms: ['xuetangx'], technical_version: 'retained v1', project_context: 'historical input must survive' };
  const makeVersion = (status: string) => ({ version, status, input: structuredClone(input), analysis: structuredClone(retained.analysis), confirmation: status === 'completed' ? { version, confirmed_at: stamp } : null, batches: [], error: null, created_at: stamp });
  if (options.initial) { version = 1; created = true; history.set(1, makeVersion(options.initial === 'results' ? 'completed' : 'analyzed')); }
  function view(chosen = version) {
    const current = history.get(chosen) || null;
    const originals = parts.flatMap((p: any) => p.original_points), groups = parts.flatMap((p: any) => p.body.groups);
    return { project_id: 'requirements-project', input, current_version: version, versions: [...history.values()].map(v => ({ version: v.version, status: v.status, created_at: stamp })), version: current,
      points: current?.confirmation ? groups.map((group: any, i: number) => ({ project_knowledge_point_id: originals[i].id, name: originals[i].name, selection: 'learn', status: group.related_recommendations.length ? 'completed' : 'no_results', batch_id: null, job_id: parts[Math.floor(i / 5)].body.job_id, knowledge_point_id: group.knowledge_point_id, result: group })) : [],
      ...(current?.confirmation ? { pipeline: { ...parts[0].body.pipeline, displayed: new Set(groups.flatMap((g: any) => g.related_recommendations).map((r: any) => r.resource.canonical_url || r.resource.url)).size } } : {}) };
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== origin) { if (req.resourceType() === 'image') { guard.image_fallbacks++; return route.fulfill({ status: 204, body: '' }); } guard.external_blocked.push(req.url()); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const method = req.method(), body = method === 'POST' ? req.postDataJSON() : undefined;
    requests.push({ method, path: url.pathname, body, key: req.headers()['idempotency-key'] });
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: caps });
    if (url.pathname === '/api/projects' && method === 'GET') return route.fulfill({ json: { projects: created ? [{ project_id: 'requirements-project', name: input.name, current_version: version, created_at: stamp, updated_at: stamp }] : [] } });
    if (url.pathname === '/api/projects' && method === 'POST') { input = body; created = true; return route.fulfill({ json: view() }); }
    if (url.pathname === '/api/projects/requirements-project/results') return route.fulfill({ json: view(Number(url.searchParams.get('version')) || version) });
    if (url.pathname === '/api/projects/requirements-project/analyze') {
      input = body.input;
      if (failures) { failures--; return route.fulfill({ status: 503, json: { detail: '本机模拟：分析暂时不可用' } }); }
      version++; history.set(version, makeVersion('analyzed')); return route.fulfill({ json: view() });
    }
    if (url.pathname === '/api/search-jobs' && method === 'POST') return route.fulfill({ json: { job_id: parts[0].body.job_id, status: 'completed' } });
    if (url.pathname === '/api/search-jobs/' + parts[0].body.job_id) return route.fulfill({ json: parts[0].body.job });
    if (url.pathname === '/api/search-jobs/' + parts[0].body.job_id + '/results') return route.fulfill({ json: parts[0].body });
    unexpected.push(method + ' ' + url.pathname); return route.abort();
  });
  return { requests, history, guard, clean: () => { expect(unexpected).toEqual([]); expect(errors).toEqual([]); expect(guard.external_blocked).toEqual([]); }, groups: parts.flatMap((p: any) => p.body.groups) };
}
async function evidence(info: TestInfo, s: Awaited<ReturnType<typeof setup>>) { await info.attach('local-request-guard', { contentType: 'application/json', body: Buffer.from(JSON.stringify({ scope: 'all API locally fulfilled; no real model/search/API/supplier calls', guard: s.guard, requests: s.requests.map(r => ({ method: r.method, path: r.path, payload_keys: r.body ? Object.keys(r.body) : [], student_level: r.body?.student_level, language: r.body?.language, preferred_platforms: r.body?.preferred_platforms, idempotency_present: !!r.key })) }, null, 2)) }); }
async function noExtraPreferences(page: Page, project: boolean) {
  await expect(page.locator(project ? '#project-level, #project-background, .platform-choices, .default-assumption' : '#level, #version, #context, .platform-choices')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '共享课程库', exact: true })).toHaveCount(0);
  await expect(page.locator('.device-learned-toggle, .device-progress')).toHaveCount(0);
  await expect(page.locator(project ? '#project-language' : '#language')).toBeVisible();
}
async function layout(page: Page) { await page.waitForFunction(() => !document.documentElement.dataset.motionKind); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true); await expect(page.locator('vite-error-overlay')).toHaveCount(0); }

test('new inputs offer only language; unknown starting level and automatic dual platforms; analysis failure is recoverable', async ({ page }, info) => {
  const s = await setup(page, { failAnalysis: true }); await page.goto('/'); await noExtraPreferences(page, true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel('项目名称', { exact: true }).fill('公开合成：接金币小游戏');
  await page.getByLabel('功能需求', { exact: true }).fill('键盘控制，接金币，记录得分。');
  await page.getByLabel('视频语言', { exact: true }).selectOption('en');
  await page.screenshot({ path: info.outputPath('desktop-language-only-input.png'), fullPage: false });
  await page.setViewportSize({ width: 390, height: 844 }); await layout(page); await page.screenshot({ path: info.outputPath('mobile-project-language-only.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '分析项目', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('分析暂时不可用');
  await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue('公开合成：接金币小游戏');
  await page.getByRole('button', { name: '分析项目', exact: true }).click();
  await expect(page.locator('.simple-knowledge-list')).toBeVisible();
  const creates = s.requests.filter(r => r.path === '/api/projects' && r.method === 'POST'); expect(creates).toHaveLength(1);
  expect(creates[0].body).toMatchObject({ student_level: 'any', language: 'en', preferred_platforms: ['bilibili', 'icourse163'], technical_version: '', project_context: '' });
  expect(s.requests.filter(r => r.path.endsWith('/analyze'))).toHaveLength(2);
  await page.goto('/?mode=manual'); await noExtraPreferences(page, false);
  await page.getByLabel('知识点', { exact: true }).fill('线性表'); await page.getByLabel('学习语言', { exact: true }).selectOption('any');
  await page.setViewportSize({ width: 390, height: 844 }); await page.locator('.form-panel').scrollIntoViewIfNeeded(); await layout(page); await page.screenshot({ path: info.outputPath('mobile-direct-form-language-only.png'), fullPage: false });
  await page.getByRole('button', { name: '开始查找', exact: true }).click();
  await expect(page.locator('.resource-card').first()).toBeVisible();
  const manual = s.requests.find(r => r.path === '/api/search-jobs' && r.method === 'POST')!;
  expect(manual.body).toEqual({ knowledge_points: ['线性表'], student_level: 'any', language: 'any', technical_version: '', project_context: '', preferred_platforms: ['bilibili', 'icourse163'] });
  await page.setViewportSize({ width: 390, height: 844 }); await layout(page); await page.screenshot({ path: info.outputPath('mobile-direct-language-only.png'), fullPage: false });
  s.clean(); await evidence(info, s);
});

test('project titles are visible with covers at three widths; dedupe, keyboard, topic changes and empty state remain safe', async ({ page }, info) => {
  const s = await setup(page, { initial: 'results' }); await page.goto('/?project=requirements-project&version=1');
  const unique = [...new Map(s.groups.flatMap((g: any) => g.related_recommendations).map((r: any) => [r.resource.canonical_url || r.resource.url, r])).values()] as any[];
  await expect(page.locator('.video-cover-title')).toHaveCount(unique.length);
  for (const size of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
    await page.setViewportSize(size); await layout(page);
    for (const card of await page.locator('.video-cover-card').all()) {
      const title = card.locator('.video-cover-title a'), cover = card.locator('.course-cover');
      await expect(title).toBeVisible(); await expect(title).toHaveAttribute('href', (await cover.getAttribute('href'))!); await expect(title).toHaveAttribute('rel', 'noopener noreferrer');
      expect(await card.innerText()).toBe((await title.innerText()));
    }
    await expect(page.locator('.project-video-gallery .recommendation-reason, .project-video-gallery .course-info')).toHaveCount(0);
    const cover = page.locator('.course-cover').first(), title = page.locator('.video-cover-title a').first();
    await cover.focus(); await page.keyboard.press('Tab'); await expect(title).toBeFocused();
    await page.screenshot({ path: info.outputPath(size.name + '-cover-and-title.png'), fullPage: false });
  }
  const nav = page.getByRole('navigation', { name: '已选知识点' });
  const empty = retained.analysis.knowledge_points[4]; await nav.getByRole('button', { name: empty.name, exact: true }).click();
  await expect(page.locator('.video-cover-title')).toHaveCount(0); await expect(page.locator('.video-cover-skeleton')).toHaveCount(0); await expect(page.locator('.project-empty-message')).toBeVisible();
  await nav.getByRole('button', { name: '全部', exact: true }).click(); await expect(page.locator('.video-cover-title')).toHaveCount(unique.length);
  expect(s.requests.every(r => r.method === 'GET')).toBe(true); s.clean(); await evidence(info, s);
});

test('old project and uncertain direct request retain original fields without preference controls or implicit resubmission', async ({ page }, info) => {
  const s = await setup(page, { initial: 'analysis', historical: true });
  const original = structuredClone(s.history.get(1));
  await page.goto('/?project=requirements-project&version=1'); await expect(page.locator('.simple-knowledge-list')).toBeVisible();
  await page.getByRole('button', { name: /01 项目描述/ }).click(); await noExtraPreferences(page, true);
  await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue(original.input.name);
  await page.getByLabel('视频语言', { exact: true }).selectOption('en');
  await page.getByRole('button', { name: '保存需求并重新分析', exact: true }).click();
  await expect(page.locator('.simple-knowledge-list')).toBeVisible();
  const submitted = s.requests.find(r => r.path.endsWith('/analyze'))!.body.input;
  expect(submitted).toEqual({ ...original.input, language: 'en' }); expect(s.history.get(1)).toEqual(original); expect([...s.history.keys()]).toEqual([1, 2]);
  const oldRequest = { knowledge_points: ['历史术语'], student_level: 'intermediate', language: 'en', technical_version: 'old v2', project_context: 'saved historic context', preferred_platforms: ['xuetangx'] };
  await page.evaluate(request => sessionStorage.setItem('knowledge-guide.pending-creation.v1', JSON.stringify({ key: 'qa-pending-old-request', body: JSON.stringify(request) })), oldRequest);
  await page.goto('/?mode=manual'); await noExtraPreferences(page, false); await expect(page.getByRole('button', { name: '继续上次未确认提交', exact: true })).toBeVisible();
  const before = s.requests.filter(r => r.path === '/api/search-jobs' && r.method === 'POST').length; expect(before).toBe(0);
  await page.getByRole('button', { name: '继续上次未确认提交', exact: true }).click(); await expect(page.locator('.resource-card').first()).toBeVisible();
  const resumed = s.requests.filter(r => r.path === '/api/search-jobs' && r.method === 'POST'); expect(resumed).toHaveLength(1); expect(resumed[0].body).toEqual(oldRequest); expect(resumed[0].key).toBe('qa-pending-old-request');
  await page.setViewportSize({ width: 768, height: 1024 }); await layout(page); await page.screenshot({ path: info.outputPath('tablet-legacy-request-resumed.png'), fullPage: false });
  s.clean(); await evidence(info, s);
});
