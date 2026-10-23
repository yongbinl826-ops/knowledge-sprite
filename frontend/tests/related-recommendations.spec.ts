import { expectGalleryTitlesOnly } from './coverTitleContract';
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Retained producer rows stay unchanged. Wrapper and explicit duplicate/MOOC
// controls below are synthetic API fixtures, never a fresh search/verdict.
const retained = JSON.parse(readFileSync(new URL('./related-recommendations-actual.json', import.meta.url), 'utf8'));
const actual = retained.cases.pygame.points.find((point: any) => point.references.length);
const stamp = '2026-10-20T07:50:00Z';
function fixture() {
  const references = structuredClone(actual.references), pid = references[0].reference.knowledge_point_id;
  const moocUrl = 'https://www.icourse163.org/course/QA-100001';
  references.push({ resource: { resource_id: 'synthetic-mooc', title: '合成课程控制', url: moocUrl, canonical_url: moocUrl, platform: 'icourse163', resource_type: 'course', thumbnail_url: null, fetch_status: 'pending', video_evidence_status: 'search_discovered', access_notice: '登录或选课条件请到平台核对' },
    reference: { policy: 'related-reference-v1', kind: 'related_reference', knowledge_point_id: pid, ranking_score: 30, reason: '仅检索简介相关，页面详情尚未读取；精确讲授未验证。<img src=x onerror=alert(1)>', exact_teaching_verified: false, basis: ['search'], evidence_ids: ['synthetic-evidence'], technical_context: 'unconfirmed' },
    evidence: [{ evidence_id: 'synthetic-evidence', kind: 'search', source: 'synthetic-control', url: moocUrl, title: '合成课程控制' }] });
  const first = references[0], ev = first.evidence[0];
  const strict = { resource: first.resource, evidence: first.evidence,
    match: { knowledge_point_id: pid, resource_id: first.resource.resource_id, ranking_score: 90, recommendation_reason: 'Synthetic partial duplicate control; not a producer teaching verdict.', matched_evidence_ids: [ev.evidence_id], coverage_basis: ['synthetic'], topic_evidence_status: 'partial', supporting_evidence_ids: [ev.evidence_id] } };
  const raw = { resource: { ...first.resource, resource_id: 'unfiltered-raw', title: '旧未过滤发现，不应显示', url: 'https://example.org/unfiltered', canonical_url: 'https://example.org/unfiltered' }, discovery_evidence: [] };
  const group = { knowledge_point_id: pid, text: actual.name, total_matches: 0, items: [], partial_items: [strict], review_items: [],
    recommendation_policy: 'related-reference-v1', related_recommendations: references, total_related_recommendations: references.length,
    related_platform_recommendations: { bilibili: references.filter((r: any) => r.resource.platform === 'bilibili'), icourse163: references.filter((r: any) => r.resource.platform === 'icourse163') }, discovery_items: [raw] };
  const input = { name: '相关参考离线合成项目', requirements: '只验证已保存资料的前端展示，不发起实际分析或搜索。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili', 'icourse163'] };
  const planned = (id: string, name: string, order: number) => ({ id, name, description: '', function_ids: ['f1'], why_needed: '', learning_goal: '', necessity: 'required', prerequisite_ids: [], learning_order: order, selection: 'learn' });
  const analysis = { scope: 'synthetic wrapper', technical_plan: '', assumptions: [], functions: [{ id: 'f1', name: '合成功能', original_requirement: '', acceptance_criteria: '', no_new_learning_reason: null }], knowledge_points: [planned('K6', actual.name, 1), planned('empty', '栈', 2)] };
  const project = { project_id: 'reference-project', input, current_version: 1, versions: [{ version: 1, status: 'partial', created_at: stamp }],
    version: { version: 1, status: 'partial', input, analysis, confirmation: { version: 1, confirmed_at: stamp }, batches: [], error: null, created_at: stamp },
    points: [{ project_knowledge_point_id: 'K6', name: actual.name, selection: 'learn', status: 'partial', batch_id: null, job_id: 'reference-job', knowledge_point_id: pid, result: group },
      { project_knowledge_point_id: 'empty', name: '栈', selection: 'learn', status: 'no_results', batch_id: null, job_id: 'reference-job', knowledge_point_id: 'empty-search', result: { knowledge_point_id: 'empty-search', text: '栈', items: [], total_matches: 0, recommendation_policy: 'related-reference-v1', related_recommendations: [], discovery_items: [raw] } }] };
  const request = { knowledge_points: [actual.name], ...Object.fromEntries(Object.entries(input).filter(([key]) => !['name', 'requirements'].includes(key))) };
  const job = { job_id: 'reference-job', status: 'completed', phase: 'completed', created_at: stamp, updated_at: stamp, request,
    progress: { queries_planned: 1, queries_completed: 1, search_requests: 1, search_successes: 1, search_failures: 0, candidates_discovered: 4, resources_discovered: 4, details_attempted: 0, details_completed: 0, cache_hits: 0 }, budgets: { max_search_requests: 1, max_detail_pages: 0, deadline_seconds: 60 }, warnings: [], errors: [], knowledge_points: [{ knowledge_point_id: pid, text: actual.name }] };
  return { group, project, job, results: { job_id: 'reference-job', status: 'completed', job, groups: [group], warnings: [], search_attempts: [], recommendation_policy: 'related-reference-v1', pipeline: { stage: 'completed', search_requests: 1, search_budget: 1, candidates: 4, checking: 0, displayed: 0, filtered: 0, unknown: 4, terminal: true, source_limited: false } } };
}
async function setup(page: Page) {
  const data = fixture(), requests: string[] = [], unexpected: string[] = [], errors: string[] = [];
  let matching: boolean | undefined = true;
  const origin = new URL(process.env.PLAYWRIGHT_BASE_URL!).origin;
  await page.emulateMedia({ reducedMotion: 'reduce' });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin) return request.resourceType() === 'image' ? route.fulfill({ status: 204, body: '' }) : route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    requests.push(`${request.method()} ${url.pathname}`);
    if (request.method() !== 'GET') { unexpected.push('write denied'); return route.abort(); }
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'synthetic-reference-qa', teaching_match_enabled: matching, search: { status: 'available', message: 'mock', providers: [], selected_provider: 'mock' }, llm: { status: 'unconfigured', message: 'no real model' }, fetch: { status: 'available', message: 'mock', browser_fallback: false }, platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 5, max_detail_pages: 5 } } });
    if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [{ project_id: 'reference-project', name: data.project.input.name, current_version: 1, created_at: stamp, updated_at: stamp }] } });
    if (url.pathname === '/api/projects/reference-project/results') return route.fulfill({ json: data.project });
    if (url.pathname === '/api/search-jobs/reference-job') return route.fulfill({ json: data.job });
    if (url.pathname === '/api/search-jobs/reference-job/results') return route.fulfill({ json: data.results });
    unexpected.push(url.pathname); return route.abort();
  });
  return { data, requests, matching: (value: boolean | undefined) => { matching = value; }, clean: () => { expect(unexpected).toEqual([]); expect(errors).toEqual([]); expect(requests.every(row => row.startsWith('GET '))).toBe(true); } };
}
test('actual retained related rows work in true/false/unknown modes; covers only, canonical dedupe, empty state and keyboard at three widths', async ({ page }, info) => {
  const s = await setup(page);
  await page.goto("/");
  await expect(page.locator("#project-name")).toBeVisible();
  await expect(page.locator("#project-background")).toHaveCount(0);
  await expect(page.locator("#project-level")).toHaveCount(0);
  await expect(page.locator("#project-language")).toBeVisible();
  for (const matching of [true, false, undefined]) {
    s.matching(matching); await page.goto('/?project=reference-project&version=1');
    await expect(page.locator('.video-cover-card')).toHaveCount(2);
    await expect(page.locator('[data-resource-id="unfiltered-raw"]')).toHaveCount(0);
    await expect(page.locator('[data-source-kind="recommendation"]')).toHaveCount(1);
    await expect(page.locator('[data-source-kind="related-reference"]')).toHaveCount(1);
    await expect(page.locator('[data-resource-id="synthetic-mooc"]')).toHaveCount(0);
    await expect(page.locator('[data-resource-id="res_4fcb8a049bf2ce2d9e4f7937"]')).toHaveCount(0);
    await expect(page.locator('.project-empty-message')).toHaveCount(0);
    await expectGalleryTitlesOnly(page);
    const link = page.locator('[data-source-kind="related-reference"] a').first();
    await expect(link).toHaveAttribute('aria-label', /相关参考.*精确讲授未验证/);
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    await link.focus(); await expect(link).toBeFocused();
    const nav = page.getByRole('navigation', { name: '已选知识点' });
    await nav.getByRole('button', { name: '栈', exact: true }).click();
    await expect(page.locator('.video-cover-card')).toHaveCount(0);
    await expect(page.locator('.video-cover-skeleton')).toHaveCount(0);
    await nav.getByRole('button', { name: '全部', exact: true }).click();
    await expect(page.locator('.video-cover-card')).toHaveCount(2);
    if (matching === true) for (const size of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
      await page.setViewportSize(size); await page.waitForFunction(() => !document.documentElement.dataset.motionKind);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await expectGalleryTitlesOnly(page);
      await page.screenshot({ path: info.outputPath(`${size.name}-reference-covers.png`), fullPage: true });
    }
  }
  s.clean();
});
test('direct results keep related reasons/access uncertainty, course CTA and platform filter; strict and reference duplicates render once', async ({ page }, info) => {
  const s = await setup(page); s.data.job.status = 'no_results'; s.data.results.status = 'no_results';
  s.matching(false); await page.goto('/?job=reference-job');
  await expect(page.locator('.resource-card')).toHaveCount(4);
  await expect(page.locator('.job-status')).toHaveText('检索完成');
  await expect(page.locator('.search-pipeline')).toHaveCount(0);
  await expect(page.locator('.related-recommendations')).toContainText('精确讲授未验证');
  await expect(page.locator('[data-resource-id="unfiltered-raw"]')).toHaveCount(0);
  expect(await page.locator('[onerror]').count()).toBe(0);
  await page.getByRole('combobox', { name: '来源平台' }).selectOption('icourse163');
  await expect(page.locator('.resource-card')).toHaveCount(1);
  await expect(page.locator('.search-pipeline')).toHaveCount(0);
  await expect(page.locator('.related-recommendations')).toContainText('页面详情尚未读取');
  await expect(page.locator('.related-recommendations')).toContainText('登录或选课条件请到平台核对');
  await expect(page.getByRole('link', { name: /在新窗口查看课程/ })).toHaveAttribute('href', 'https://www.icourse163.org/course/QA-100001');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath('mobile-direct-reference.png'), fullPage: true });
  s.clean();
});
