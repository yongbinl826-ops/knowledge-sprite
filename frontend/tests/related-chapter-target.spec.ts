import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { expectGalleryTitlesOnly } from './coverTitleContract';

const actual = JSON.parse(readFileSync(new URL('./fixtures/streamlit-chapters-actual.json', import.meta.url), 'utf8'));
const stamp = '2026-10-21T03:00:00Z';
// Retained actual chapter facts; project/reference wrappers and navigation target
// responses are isolated UI controls. Playback is independently checked live.
function fixture(primary = false) {
  const input = { name: '分集跳转验证', requirements: '离线验证引用目录分集跳转。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili'] };
  const planned = [{ id: 'form', name: '表单输入', parts: [7, 8, 9] }, { id: 'download', name: '文件下载', parts: [6] }].map((p, i) => ({ ...p, description: '', technology: 'Streamlit', function_ids: ['f1'], prerequisite_ids: [], learning_order: i + 1, selection: 'learn', necessity: 'required', why_needed: '', learning_goal: '' }));
  const points = planned.map(p => {
    const row = { resource: structuredClone(actual.resource), evidence: structuredClone(actual.evidence), reference: { policy: 'related-reference-v1', kind: 'related_reference', knowledge_point_id: p.id, ranking_score: 60, reason: '实际目录分集的离线跳转控制；未声明精确讲授。', exact_teaching_verified: false, basis: ['catalog'], technical_context: 'observed', evidence_ids: actual.evidence.filter((e: any) => p.parts.includes(JSON.parse(e.text).page_number)).map((e: any) => e.evidence_id) } };
    const items = primary ? [{ resource: { ...row.resource, title: '主推荐标题控制', url: row.resource.url + '?uid=synthetic-control' }, evidence: row.evidence,
      match: { knowledge_point_id: p.id, resource_id: row.resource.resource_id, ranking_score: 99, recommendation_reason: 'Synthetic primary duplicate UI control', topic_evidence_status: 'supported', matched_evidence_ids: row.reference.evidence_ids, supporting_evidence_ids: row.reference.evidence_ids, coverage_basis: ['synthetic'] } }] : [];
    return { project_knowledge_point_id: p.id, name: p.name, selection: 'learn', status: 'partial', batch_id: null, job_id: null, knowledge_point_id: p.id, result: { knowledge_point_id: p.id, text: p.name, items, total_matches: items.length, recommendation_policy: 'related-reference-v1', related_recommendations: [row] } };
  });
  return { project_id: 'chapter-target', input, current_version: 1, versions: [{ version: 1, status: 'partial', created_at: stamp }], version: { version: 1, status: 'partial', input, created_at: stamp, analysis: { scope: 'offline navigation control', technical_plan: '', assumptions: [], functions: [{ id: 'f1', name: '编辑导出', original_requirement: '', acceptance_criteria: '' }], knowledge_points: planned }, confirmation: { confirmed_at: stamp }, batches: [], error: null }, points };
}

for (const primary of [false, true]) for (const size of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) test(`${primary ? 'primary duplicate' : 'related course'} cover/title open the selected point's cited chapter at ${size.name} width`, async ({ page, context }, info) => {
  const data = fixture(primary), unexpected: string[] = [], errors: string[] = [], opened: string[] = [];
  const base = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
  await page.setViewportSize(size); await page.emulateMedia({ reducedMotion: 'reduce' });
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (['warning', 'error'].includes(m.type())) errors.push(m.text()); });
  await context.route('**/*', route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() !== 'GET') { unexpected.push(request.method()); return route.abort(); }
    if (url.origin !== base) {
      if (request.resourceType() === 'image') return route.fulfill({ status: 204, body: '' });
      if (request.isNavigationRequest() && [actual.resource.url + '?p=6', actual.resource.url + '?p=7'].includes(url.href)) {
        opened.push(url.href); return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Isolated navigation control</title><p>No source playback request.</p>' });
      }
      unexpected.push(url.href); return route.abort();
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'offline-ui-control', teaching_match_enabled: true, search: { status: 'configured', providers: [] }, llm: { status: 'unconfigured' }, fetch: { status: 'available' }, platforms: [], limits: { max_knowledge_points: 15, max_results_per_point: 5 } } });
    if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
    if (url.pathname === '/api/projects/chapter-target/results') return route.fulfill({ json: data });
    unexpected.push(url.pathname); return route.abort();
  });
  await page.goto('/?project=chapter-target&version=1');
  for (const point of [{ name: '表单输入', part: 7 }, { name: '文件下载', part: 6 }]) {
    await page.getByRole('navigation', { name: '已选知识点' }).getByRole('button', { name: point.name, exact: true }).click();
    await expect(page.locator('.video-cover-card')).toHaveCount(1);
    await expectGalleryTitlesOnly(page, [primary ? '主推荐标题控制' : actual.resource.title]);
    await expect(page.locator('.video-cover-card')).toHaveAttribute('data-source-kind', primary ? 'recommendation' : 'related-reference');
    for (const selector of ['a.course-cover', '.video-cover-title a']) {
      const link = page.locator('.stage-content').locator(selector), target = actual.resource.url + `?p=${point.part}`;
      await expect(link).toHaveAttribute('href', target);
      const pending = page.waitForEvent('popup'); await link.click(); const popup = await pending;
      await popup.waitForLoadState('domcontentloaded'); await expect(popup).toHaveURL(target); await popup.close();
    }
    expect(await page.locator('body').ariaSnapshot()).not.toMatch(/ai_video_fallback|补链|候选链接/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: info.outputPath(`${size.name}-${point.part}-chapter.png`), fullPage: true });
  }
  expect(opened).toEqual([7, 7, 6, 6].map(p => actual.resource.url + `?p=${p}`));
  expect(unexpected).toEqual([]); expect(errors).toEqual([]);
});
