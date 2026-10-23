import { expectGalleryTitlesOnly } from './coverTitleContract';
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ProjectView } from '../src/projectTypes';

// Actual retained r9 metadata/ranking replay, transported in an explicitly
// documented UI wrapper. No live model/search/backend API is exercised.
const fixture = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/retained-r9-ui-projects.json'), 'utf8')) as { cases: Record<string, ProjectView> };
// Conservative UI control: retain the real card/match but make the aggregate range unknown.
// This is an explicit local fixture mutation, not a new real teaching assertion.
const unknownRange = structuredClone(fixture.cases.browser_flashcards_intermediate);
for (const point of unknownRange.points || []) if (point.result?.collection_coverage) {
  for (const row of point.result.collection_coverage.subtopics) { row.status = 'unknown'; row.resource_ids = []; row.evidence_ids = []; }
}
const scenarios: [string, ProjectView][] = [...Object.entries(fixture.cases), ['browser_unknown_range_control', unknownRange]];
for (const [name, view] of scenarios) for (const width of [1440, 390]) {
  test(`${name} ${width}: professional navigation stays unsplit; generic material scope and keyboard cover focus remain`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.emulateMedia({ reducedMotion: width === 390 ? 'reduce' : 'no-preference' });
    const base = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
    const blocked: string[] = [], runtime: string[] = [];
    page.on('pageerror', error => runtime.push(error.message));
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (request.method() !== 'GET') { blocked.push(`${request.method()} ${url.pathname}`); return route.abort(); }
      if (url.origin !== base) return request.resourceType() === 'image' ? route.fulfill({ status: 204, body: '' }) : route.abort();
      if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'live', teaching_match_enabled: true, search: { status: 'configured', providers: [] }, project_analysis: { status: 'configured' }, llm: { status: 'configured' }, fetch: { status: 'available' }, platforms: [], limits: { max_knowledge_points: 15, max_results_per_point: 5 } } });
      if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
      if (url.pathname === `/api/projects/${view.project_id}/results`) return route.fulfill({ json: view });
      if (url.pathname.startsWith('/api/')) { blocked.push(`unknown ${url.pathname}`); return route.abort(); }
      return route.continue();
    });
    await page.goto(`/?project=${view.project_id}&version=${view.version!.version}`);
    const cover = page.locator('.video-cover-card a.course-cover');
    await expect(cover).toHaveCount(1);
    await page.waitForFunction(() => !document.documentElement.dataset.motionKind);
    const details = page.locator('.project-result-details');
    if (name.startsWith('browser')) {
      const summary = details.getByRole('region', { name: 'localStorage读写与JSON序列化的材料范围', exact: true });
      await expect(summary).toBeVisible();
      if (width > 640) await expect(summary).toBeInViewport();
      else {
        await expect(page.locator('.stage-intro .project-result-details')).toHaveCount(0);
        const galleryBox = await page.locator('.project-video-gallery').boundingBox();
        const detailsBox = await details.boundingBox();
        expect(detailsBox!.y).toBeGreaterThanOrEqual(galleryBox!.y + galleryBox!.height);
      }
      if (name.includes('unknown_range')) {
        await expect(summary.locator('[data-support="unknown"]')).toHaveText('当前材料的完整讲授范围尚待核对，请结合课程详情判断。');
        await expect(summary.locator('[data-support="partial"]')).toHaveCount(0);
      } else await expect(summary.locator('[data-support="partial"]')).toHaveText('部分匹配不等于单门课程完整覆盖，请核对课程内容。');
      await expect(summary.locator('[data-support]')).not.toContainText('已有依据');
      await expect(summary.locator('[data-support]')).not.toContainText('待补依据');
      await expect(summary.locator('[data-support]')).not.toContainText('JSON 序列化');
      await expect(summary.locator('[data-support]')).not.toContainText('读写');
    } else await expect(details.locator('.project-support-summary')).toHaveCount(0);
    const expectedPoints = view.version!.analysis!.knowledge_points.filter(point => point.selection === 'learn');
    const buttons = page.locator('.topic-navigation button');
    await expect(buttons).toHaveCount(expectedPoints.length + 1);
    await expect(buttons.first()).toHaveText('全部');
    for (let index = 0; index < expectedPoints.length; index++) {
      const point = expectedPoints[index], button = buttons.nth(index + 1);
      await expect(button).toHaveAttribute('aria-label', point.name);
      await expect(button).toHaveAccessibleName(point.name);
      if (point.technology) await expect(button.locator('small')).toHaveText(`检索语境：${point.technology}`);
      else await expect(button.locator('small')).toHaveCount(0);
    }
    await expectGalleryTitlesOnly(page);
    const selected = page.locator('.topic-navigation button').nth(1);
    await selected.focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(() => !document.documentElement.dataset.motionKind);
    for (let i = 0; i < 8 && !await cover.evaluate(node => node === document.activeElement); i++) await page.keyboard.press('Tab');
    await expect(cover).toBeFocused();
    await expect(cover).toBeInViewport();
    const painted = await cover.evaluate(node => {
      const after = getComputedStyle(node, '::after');
      return { keyboard: node.matches(':focus-visible'), content: after.content, width: after.borderTopWidth, color: after.borderTopColor, z: after.zIndex, inset: after.inset };
    });
    expect(painted.keyboard).toBe(true);
    expect(painted.content).toBe('""'); expect(painted.width).toBe('3px');
    expect(painted.color).toBe('rgb(49, 87, 255)'); expect(Number(painted.z)).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    const focusBox = await cover.boundingBox(); expect(focusBox!.width).toBeGreaterThan(100);
    expect(await cover.getAttribute('rel')).toContain('noopener');
    await info.attach('focus-style', { body: JSON.stringify(painted), contentType: 'application/json' });
    await page.screenshot({ path: info.outputPath('cover-focus-and-partial-scope.png'), fullPage: false });
    expect(blocked).toEqual([]); expect(runtime).toEqual([]);
  });
}
