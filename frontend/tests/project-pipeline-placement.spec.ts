import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ProjectView } from '../src/projectTypes';

const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/project-pipeline-retained.json'), 'utf8')) as { view: ProjectView };
const retainedTeaching = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/retained-r9-ui-projects.json'), 'utf8')) as { cases: Record<string, ProjectView> };
async function setup(page: import('@playwright/test').Page, view: ProjectView) {
  const blocked: string[] = [];
  await page.addInitScript(() => { Object.defineProperty(window, 'EventSource', { value: undefined }); });
  const base = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() !== 'GET') { blocked.push(request.method() + ' ' + url.pathname); return route.abort(); }
    if (url.origin !== base) return route.fulfill({ status: 204, body: '' });
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'live', teaching_match_enabled: true, search: { status: 'configured', providers: [] }, project_analysis: { status: 'unconfigured', message: '项目分析不可用：服务端未配置模型。' }, llm: { status: 'unconfigured' }, fetch: { status: 'available' }, platforms: [], limits: { max_knowledge_points: 15, max_results_per_point: 5 } } });
    if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
    if (url.pathname === `/api/projects/${view.project_id}/results`) return route.fulfill({ json: view });
    if (url.pathname.startsWith('/api/')) { blocked.push(url.pathname); return route.abort(); }
    return route.continue();
  });
  return blocked;
}
async function expectProgressAtTop(page: import('@playwright/test').Page) {
  const progress = page.locator('.project-progress');
  await expect(progress).toHaveCount(1);
  await expect(page.locator('.stage-intro .search-pipeline')).toHaveCount(0);
  const [headerBox, progressBox, mainBox] = await Promise.all([
    page.locator('.site-header').boundingBox(), progress.boundingBox(), page.locator('.stage-main').boundingBox(),
  ]);
  expect(headerBox).not.toBeNull(); expect(progressBox).not.toBeNull(); expect(mainBox).not.toBeNull();
  expect(progressBox!.y).toBeGreaterThanOrEqual(headerBox!.y + headerBox!.height);
  expect(progressBox!.y + progressBox!.height).toBeLessThanOrEqual(mainBox!.y);
  expect(progressBox!.y + progressBox!.height).toBeLessThan(Math.min(240, page.viewportSize()!.height));
}
test('terminal progress and its sticky wrapper are hidden on desktop/mobile; right remains icon-only', async ({ page }, info) => {
  const view = structuredClone(fixture.view), originalPipeline = JSON.stringify(view.pipeline);
  const blocked = await setup(page, view);
  await page.goto(`/?project=${view.project_id}&version=${view.version!.version}`);
  const details = page.locator('.project-result-details'), right = page.locator('.stage-content');
  const progress = page.locator('.project-progress');
  await expect(details.getByRole('button', { name: '重新检索这些知识点', exact: true })).toBeEnabled();
  await expect(progress).toHaveCount(0);
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  await expect(details.locator('.project-empty-message')).toHaveCount(0);
  await expect(right.locator('.gallery-motion')).toHaveText('');
  await expect(right.locator('.video-cover-skeleton')).toHaveCount(0);
  await expect(right.getByRole('status', { name: '这个知识点暂未找到视频', exact: true })).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.emulateMedia({ reducedMotion: width === 390 ? 'reduce' : 'no-preference' });
    await expect(details).toHaveCount(1);
    await expect(page.locator('.stage-intro .project-result-details')).toHaveCount(width <= 640 ? 0 : 1);
    await expect(details.getByRole('button', { name: '重新检索这些知识点', exact: true })).toBeEnabled();
    await expect(progress).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: info.outputPath(`terminal-pipeline-${width}.png`), fullPage: false });
  }
  expect(JSON.stringify(view.pipeline)).toBe(originalPipeline); expect(blocked).toEqual([]);
  await page.locator('.stage-navigation button').first().click();
  await expect(progress).toHaveCount(0);
  const warning = page.locator('.project-description .warning-notice');
  await expect(warning).toContainText('项目分析不可用：服务端未配置模型。');
  expect((await warning.innerText()).match(/项目分析不可用/g)).toHaveLength(1);
});
test('running progress stays at the top at desktop/mobile widths with one description and accessible animation', async ({ page }, info) => {
  // Only lifecycle values below are synthetic controls. Retained source evidence,
  // original analysis and the existing pipeline schema are not reclassified.
  const view = structuredClone(fixture.view);
  view.version!.status = 'running';
  view.version!.batches = view.version!.batches.map(batch => ({ ...batch, status: 'submitted', job_status: 'running' }));
  view.pipeline = { ...view.pipeline!, terminal: false, stage: 'searching', checking: 0, displayed: 0, source_limited: true };
  for (const point of view.points || []) if (point.selection === 'learn') { point.status = 'running'; point.result = null; }
  const blocked = await setup(page, view);
  await page.goto(`/?project=${view.project_id}&version=${view.version!.version}`);
  const details = page.locator('.project-result-details'), right = page.locator('.stage-content');
  const progress = page.locator('.project-progress');
  await expect(progress.getByRole('status', { name: '搜索与匹配进度', exact: true })).toBeVisible();
  await expect(progress.locator('.pipeline-description')).toHaveText('来源受限，继续搜索 · 已显示 0 条');
  await expect(progress.locator('.search-pipeline p')).toHaveCount(1);
  await expect(progress.locator('.pipeline-limit,.search-pipeline-steps')).toHaveCount(0);
  await expect(details.getByRole('button', { name: '取消项目检索', exact: true })).toBeEnabled();
  await expect(details.locator('.project-empty-message')).toHaveCount(0);
  await expect(right.locator('.gallery-motion')).toHaveText('');
  await expect(right.getByRole('status', { name: '正在读取视频封面', exact: true })).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.emulateMedia({ reducedMotion: width === 390 ? 'reduce' : 'no-preference' });
    await expect(details).toHaveCount(1);
    await expect(page.locator('.stage-intro .project-result-details')).toHaveCount(width <= 640 ? 0 : 1);
    await expect(details.getByRole('button', { name: '取消项目检索', exact: true })).toBeEnabled();
    await expectProgressAtTop(page);
    await expect(progress.locator('.pipeline-description')).toBeVisible();
    const fullHeight = (await progress.boundingBox())!.height;
    await expect(progress.locator('.pipeline-bar-fill')).toHaveCSS('animation-name', width === 390 ? 'none' : 'pipeline-travel');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: info.outputPath(`running-pipeline-${width}.png`), fullPage: false });
    await page.setViewportSize({ width, height: 600 });
    const documentHeight = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.evaluate(() => window.scrollTo(0, 1));
    await expect(progress.locator('.pipeline-description')).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(documentHeight);
    expect(await page.evaluate(() => window.scrollY)).toBe(1);
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(progress.locator('.pipeline-description')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await expect.poll(async () => (await progress.boundingBox())?.y).toBe(0);
    await expect(progress.getByRole('progressbar')).toBeInViewport();
    await expect(progress.locator('.pipeline-description')).toBeHidden();
    expect((await progress.boundingBox())!.height).toBeLessThan(fullHeight);
    await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '来源受限，继续搜索 · 已显示 0 条');
    expect(await progress.evaluate(node => {
      const bar = node.querySelector('.pipeline-bar')!.getBoundingClientRect();
      return node.contains(document.elementFromPoint(bar.x + bar.width / 2, bar.y + bar.height / 2));
    })).toBe(true);
    await page.screenshot({ path: info.outputPath(`running-pipeline-sticky-${width}.png`), fullPage: false });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(progress.locator('.pipeline-description')).toBeVisible();
  }
  expect(blocked).toEqual([]);
});

for (const variant of ['partial-one', 'same-URL-main-and-partial', 'review-only'] as const) test(`terminal results preserve accepted unique covers: ${variant}, then empty topic filter`, async ({ page }) => {
  // Retained teaching evidence stays intact. Only lane/lifecycle/filter controls
  // are locally mutated below; these are UI mocks, not new teaching claims.
  const view = structuredClone(retainedTeaching.cases.browser_flashcards_intermediate);
  const selected = view.version!.analysis!.knowledge_points.find(point => point.selection === 'learn')!;
  const empty = view.version!.analysis!.knowledge_points.find(point => point.id !== selected.id)!;
  empty.selection = 'learn';
  const emptyPoint = { project_knowledge_point_id: empty.id, name: empty.name, selection: 'learn' as const, status: 'no_results', batch_id: null, job_id: null, knowledge_point_id: empty.id, result: null };
  const existingEmpty = view.points!.find(point => point.project_knowledge_point_id === empty.id);
  if (existingEmpty) Object.assign(existingEmpty, emptyPoint); else view.points!.push(emptyPoint);
  view.pipeline = { stage: 'complete', terminal: true, search_requests: 1, search_budget: 1, candidates: 2, checking: 0, displayed: variant === 'review-only' ? 9 : 0, filtered: 0, unknown: 0, source_limited: false };
  const group = view.points!.find(point => point.project_knowledge_point_id === selected.id)!.result!;
  if (variant === 'same-URL-main-and-partial') { group.items = structuredClone(group.partial_items || []); group.total_matches = group.items.length; }
  if (variant === 'review-only') {
    group.review_items = structuredClone(group.partial_items || []);
    for (const item of group.review_items) item.match.topic_evidence_status = 'needs_review';
    group.items = []; group.partial_items = []; group.platform_items = {}; group.partial_platform_items = {}; group.review_platform_items = {};
    group.total_matches = 0; group.total_partial_matches = 0; group.total_review_matches = group.review_items.length;
  }
  const original = JSON.stringify(view);
  const blocked = await setup(page, view);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`/?project=${view.project_id}&version=${view.version!.version}`);
  const expectedCount = variant === 'review-only' ? 0 : 1;
  await expect(page.locator('.video-cover-card')).toHaveCount(expectedCount);
  await expect(page.locator('.project-progress')).toHaveCount(0);
  await page.getByRole('navigation', { name: '已选知识点' }).getByRole('button', { name: empty.name, exact: true }).click();
  await expect(page.locator('.video-cover-card')).toHaveCount(0);
  await expect(page.locator('.project-progress')).toHaveCount(0);
  await expect(page.locator('.stage-content .gallery-motion')).toHaveText('');
  expect(JSON.stringify(view)).toBe(original); expect(blocked).toEqual([]);
});
