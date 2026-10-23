import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { expectGalleryTitlesOnly } from './coverTitleContract';

const retained = JSON.parse(readFileSync(new URL('./fixtures/gallery-verified-page-actual.json', import.meta.url), 'utf8'));
const stamp = '2026-10-21T02:20:00Z';

// Public producer rows are retained unchanged. Lifecycle and negative variants
// below are isolated UI controls, not a fresh search or playback verdict.
function fixture() {
  const good = structuredClone(retained.cases.verified), bad = structuredClone(retained.cases.searchOnly);
  const variant = (id: string, changes: Record<string, unknown>) => {
    const row = structuredClone(good.row);
    row.resource = { ...row.resource, resource_id: id, url: `https://example.org/${id}`, canonical_url: `https://example.org/${id}`, title: id, thumbnail_url: null, ...changes };
    return row;
  };
  const stale = variant('stale-page', { cache: { hit: true, stale: true, cached_at: stamp } });
  const paid = variant('paid-preview', { requires_payment: true });
  const missing = variant('missing-status', { fetch_status: undefined, video_evidence_status: undefined });
  const searchBasis = variant('page-status-search-basis', {});
  searchBasis.reference.basis = ['search'];
  searchBasis.reference.evidence_ids = searchBasis.evidence.filter((item: any) => item.kind === 'search').map((item: any) => item.evidence_id);
  const uncitedPage = variant('uncited-page-evidence', {});
  uncitedPage.reference.evidence_ids = uncitedPage.evidence.filter((item: any) => item.kind === 'search').map((item: any) => item.evidence_id);
  const staleProof = variant('stale-page-evidence', {});
  staleProof.evidence = staleProof.evidence.map((item: any) => ({ ...item, cache: { hit: true, cached_at: stamp, stale: true } }));
  const input = { name: '已验证页面展示回归', requirements: '离线展示控制，不执行分析或检索。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili'] };
  const rows = [good, bad].map((entry, index) => {
    const references = index === 0 ? [entry.row, stale, paid, missing, searchBasis, uncitedPage, staleProof] : [entry.row];
    return { project_knowledge_point_id: entry.planned.id, name: entry.planned.name, selection: 'learn', status: 'partial', batch_id: null, job_id: null, knowledge_point_id: entry.knowledge_point_id,
      result: { knowledge_point_id: entry.knowledge_point_id, text: entry.planned.name, total_matches: 0, items: [], recommendation_policy: 'related-reference-v1', related_recommendations: references, related_platform_recommendations: { bilibili: references } } };
  });
  const complete = { project_id: 'verified-gallery', input, current_version: 1, versions: [{ version: 1, status: 'partial', created_at: stamp }],
    version: { version: 1, status: 'partial', input, analysis: { scope: 'isolated UI regression', technical_plan: '', assumptions: [], functions: [{ id: 'F3', name: '导出', original_requirement: '', acceptance_criteria: '' }], knowledge_points: [good.planned, bad.planned] }, confirmation: { confirmed_at: stamp }, batches: [], error: null, created_at: stamp }, points: rows,
    pipeline: { stage: 'complete', terminal: true, search_requests: 1, search_budget: 3, candidates: 2, checking: 0, displayed: 1, filtered: 1, unknown: 0, source_limited: false } };
  const running = structuredClone(complete);
  running.version.status = 'running';
  running.pipeline = { ...complete.pipeline, stage: 'ai_video_fallback', terminal: false, displayed: 0 };
  running.points = rows.map(row => ({ ...row, status: 'running', result: null as any }));
  return { complete, running, good, bad };
}

for (const size of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(`gallery admits retained verified pages and hides actual DLSS search-only, stale and paid rows at ${size.name} width`, async ({ page }, info) => {
    const data = fixture(), errors: string[] = [], unexpected: string[] = [];
    const origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
    let complete = false;
    await page.setViewportSize(size);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.addInitScript(() => { Object.defineProperty(window, 'EventSource', { value: undefined }); });
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (['warning', 'error'].includes(message.type())) errors.push(message.text()); });
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (request.method() !== 'GET') { unexpected.push(request.method()); return route.abort(); }
      if (url.origin !== origin) {
        if (request.resourceType() === 'image') return route.fulfill({ status: 204, body: '' });
        unexpected.push(url.href); return route.abort();
      }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'offline-ui-control', teaching_match_enabled: true, search: { status: 'configured', providers: [] }, llm: { status: 'unconfigured' }, fetch: { status: 'available' }, platforms: [], limits: { max_knowledge_points: 15, max_results_per_point: 20 } } });
      if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
      if (url.pathname === '/api/projects/verified-gallery/results') return route.fulfill({ json: complete ? data.complete : data.running });
      unexpected.push(url.pathname); return route.abort();
    });
    await page.goto('/?project=verified-gallery&version=1');
    await expect(page.locator('.project-progress .pipeline-description')).toHaveText('正在搜索相关视频 · 已显示 0 条');
    await expect(page.locator('.video-cover-card')).toHaveCount(0);
    expect(await page.locator('body').ariaSnapshot()).not.toMatch(/ai_video_fallback|AI.*补链|候选链接/);
    complete = true;
    await expect(page.locator('.video-cover-card')).toHaveCount(1);
    await expectGalleryTitlesOnly(page, [data.good.row.resource.title]);
    await expect(page.locator('.video-cover-title a')).toHaveAttribute('href', data.good.row.resource.url + '?p=1');
    await expect(page.locator('.stage-content a[href*="BV14ctF6SEqX"]')).toHaveCount(0);
    await expect(page.locator('.stage-content a[href*="example.org"]')).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    expect(await page.locator('body').ariaSnapshot()).not.toMatch(/ai_video_fallback|AI.*补链|候选链接/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: info.outputPath(`${size.name}-verified-only.png`), fullPage: true });
    await page.getByRole('navigation', { name: '已选知识点' }).getByRole('button', { name: data.bad.planned.name, exact: true }).click();
    await expect(page.locator('.video-cover-card')).toHaveCount(0);
    await expect(page.getByRole('status', { name: '这个知识点暂未找到视频' })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`${size.name}-actual-download-gap.png`), fullPage: true });
    expect(errors).toEqual([]);
    expect(unexpected).toEqual([]);
  });
}
