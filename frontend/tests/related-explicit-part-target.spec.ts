import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { expectGalleryTitlesOnly } from './coverTitleContract';

const actual = JSON.parse(readFileSync(new URL('./fixtures/related-explicit-part-actual.json', import.meta.url), 'utf8'));
const exact = 'https://www.bilibili.com/video/BV1fpgV6cEZw/?p=15';
const original = actual.group.related_recommendations[0].resource.url;
type Variant = 'catalog' | 'mixed-page' | 'already-cited' | 'explicit-primary';

// Retained source facts; the project wrapper and boundary variants are synthetic.
function fixture(variant: Variant) {
  const group = structuredClone(actual.group), row = group.related_recommendations[0];
  if (variant === 'mixed-page') row.reference.basis.push('page');
  if (variant === 'already-cited') {
    row.resource.url = row.resource.canonical_url = original.replace('p=2', 'p=40');
    for (const e of row.evidence.filter((e: any) => e.kind === 'catalog')) {
      e.url = row.resource.url;
      e.text = JSON.stringify({ ...JSON.parse(e.text), source_url: row.resource.url });
    }
  }
  const input = { name: '实际目录分集链接回归', requirements: '离线验证已引用章节的链接。', student_level: 'any', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili'] };
  const point = { id: group.knowledge_point_id, name: group.text, technology: group.technology, description: '', selection: 'learn' };
  const items = variant === 'explicit-primary' ? [{ resource: { ...row.resource, title: '已有精确主推荐' }, evidence: row.evidence,
    match: { knowledge_point_id: point.id, resource_id: row.resource.resource_id, ranking_score: 99, recommendation_reason: 'Synthetic explicit-primary navigation control', topic_evidence_status: 'supported', matched_evidence_ids: row.reference.evidence_ids, supporting_evidence_ids: row.reference.evidence_ids, coverage_basis: ['synthetic'] } }] : [];
  return { project_id: 'explicit-part-target', input, current_version: 1, versions: [{ version: 1, status: 'partial', created_at: '2026-10-21T06:38:44Z' }],
    version: { version: 1, status: 'partial', input, created_at: '2026-10-21T06:38:44Z', analysis: { analysis_format: 'concept_list_v1', scope: 'Offline target control', technical_plan: '', assumptions: [], knowledge_points: [point] }, confirmation: { confirmed_at: '2026-10-21T06:38:44Z' }, batches: [], error: null },
    points: [{ project_knowledge_point_id: point.id, name: point.name, selection: 'learn', status: 'partial', batch_id: null, job_id: null, knowledge_point_id: point.id, result: { ...group, items, total_matches: items.length } }] };
}

for (const size of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  for (const variant of ['catalog', 'mixed-page', 'already-cited', 'explicit-primary'] as const) {
    test(`${variant} links retain their proven target at ${size.name} width`, async ({ page, context }, info) => {
      const data = fixture(variant), unexpected: string[] = [], errors: string[] = [], opened: string[] = [], media: string[] = [];
      const expected = variant === 'catalog' ? exact : variant === 'already-cited' ? original.replace('p=2', 'p=40') : original;
      const title = variant === 'explicit-primary' ? '已有精确主推荐' : actual.group.related_recommendations[0].resource.title;
      const base = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
      await page.setViewportSize(size); await page.emulateMedia({ reducedMotion: 'reduce' });
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (['warning', 'error'].includes(message.type())) errors.push(message.text()); });
      await context.route('**/*', route => {
        const request = route.request(), url = new URL(request.url());
        if (request.method() !== 'GET') { unexpected.push(request.method()); return route.abort(); }
        if (request.resourceType() === 'media') { media.push(url.href); return route.abort(); }
        if (url.origin !== base) {
          if (request.resourceType() === 'image') return route.fulfill({ status: 204, body: '' });
          if (request.isNavigationRequest() && url.href === expected) {
            opened.push(url.href); return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Isolated link target</title><p>No source video request or playback.</p>' });
          }
          unexpected.push(url.href); return route.abort();
        }
        if (!url.pathname.startsWith('/api/')) return route.continue();
        if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'offline-ui-control', teaching_match_enabled: true, search: { status: 'configured', providers: [] }, llm: { status: 'unconfigured' }, fetch: { status: 'available' }, platforms: [], limits: { max_knowledge_points: 15, max_results_per_point: 5 } } });
        if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
        if (url.pathname === '/api/projects/explicit-part-target/results') return route.fulfill({ json: data });
        unexpected.push(url.pathname); return route.abort();
      });
      await page.goto('/?project=explicit-part-target&version=1');
      await expect(page).toHaveURL(/project=explicit-part-target/);
      await page.getByRole('navigation', { name: '已选知识点' }).getByRole('button', { name: actual.group.text, exact: true }).click();
      await expect(page.locator('.video-cover-card')).toHaveCount(1);
      await expectGalleryTitlesOnly(page, [title]);
      await expect(page.locator('.video-cover-card')).toHaveAttribute('data-source-kind', variant === 'explicit-primary' ? 'recommendation' : 'related-reference');
      for (const selector of ['a.course-cover', '.video-cover-title a']) {
        const link = page.locator('.stage-content').locator(selector);
        await expect(link).toHaveAttribute('href', expected);
        const pending = page.waitForEvent('popup'); await link.click(); const popup = await pending;
        await popup.waitForLoadState('domcontentloaded'); await expect(popup).toHaveURL(expected); await popup.close();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      expect(await page.locator('vite-error-overlay').count()).toBe(0);
      expect(opened).toEqual([expected, expected]); expect(unexpected).toEqual([]); expect(media).toEqual([]); expect(errors).toEqual([]);
      await info.attach('link-safety', { body: JSON.stringify({ source: 'retained-page fixture with isolated navigation', expected, opened, unexpected, media, errors }), contentType: 'application/json' });
      await page.screenshot({ path: info.outputPath(`${size.name}-${variant}.png`), fullPage: true });
    });
  }
}
