import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import type { ProjectView } from '../src/projectTypes';

const retained = JSON.parse(readFileSync(new URL('./fixtures/retained-r9-ui-projects.json', import.meta.url), 'utf8')) as { cases: Record<string, ProjectView> };
const candidateUrl = 'https://example.org/internal-ai-video-candidate';
const internalMessage = 'AI 补充链接并抓取候选视频';

// Source evidence is retained unchanged. Lifecycle values and internal diagnostics
// are synthetic API controls; this test makes no claim of a new live AI result.
function fixture() {
  const finished = structuredClone(retained.cases.arduino_pot_button_beginner);
  const planned = finished.version!.analysis!.knowledge_points.find(point => point.selection === 'learn')!;
  const point = finished.points!.find(row => row.project_knowledge_point_id === planned.id)!;
  const group = point.result!;
  const resource = group.items[0].resource;
  finished.version!.status = 'completed';
  finished.pipeline = { stage: 'complete', terminal: true, search_requests: 1, search_budget: 3, candidates: 1, checking: 0, displayed: 1, filtered: 0, unknown: 0, source_limited: false };
  const running = structuredClone(finished);
  running.version!.status = 'running';
  running.pipeline = { ...finished.pipeline, stage: 'ai_video_fallback', terminal: false, displayed: 0 };
  for (const row of running.points || []) if (row.selection === 'learn') { row.result = null; row.status = 'running'; }
  const job = (complete: boolean) => ({
    job_id: 'fallback-visibility-job', status: complete ? 'completed' : 'running', phase: complete ? 'completed' : 'searching',
    created_at: finished.version!.created_at, updated_at: finished.version!.created_at,
    request: { knowledge_points: [group.text], ...finished.input },
    progress: { queries_planned: 1, queries_completed: 1, search_requests: 1, search_successes: 1, search_failures: 0, candidates_discovered: 1, resources_discovered: complete ? 1 : 0, details_attempted: 1, details_completed: complete ? 1 : 0, cache_hits: 0 },
    budgets: { max_search_requests: 3, max_detail_pages: 3, deadline_seconds: 60 }, warnings: [], errors: [],
    knowledge_points: [{ knowledge_point_id: group.knowledge_point_id, text: group.text }],
    ai_video_fallback: { status: complete ? 'completed' : 'fetching', message: internalMessage, candidates: [{ url: candidateUrl }], errors: ['AI 候选链接尚未校验'] },
  });
  return { finished, running, planned, resource, job, results: (complete: boolean) => ({ job_id: 'fallback-visibility-job', status: complete ? 'completed' : 'running', job: job(complete), groups: complete ? [group] : [], pipeline: complete ? finished.pipeline : running.pipeline, warnings: [], search_attempts: [] }) };
}

async function expectPrivateProcessHidden(page: Page) {
  const snapshot = await page.locator('body').ariaSnapshot();
  expect(snapshot).not.toContain(internalMessage);
  expect(snapshot).not.toContain('ai_video_fallback');
  expect(snapshot).not.toContain(candidateUrl);
  expect(snapshot).not.toContain('AI 候选链接尚未校验');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await expect(page.locator('body')).not.toHaveText('');
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(`background video fallback stays private through project and direct results at ${viewport.name} width`, async ({ page }, info) => {
    const data = fixture(), errors: string[] = [], unexpected: string[] = [];
    const base = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
    let complete = false;
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (['warning', 'error'].includes(message.type())) errors.push(message.text()); });
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.addInitScript(() => { Object.defineProperty(window, 'EventSource', { value: undefined }); });
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (request.method() !== 'GET') { unexpected.push(`${request.method()} ${url.pathname}`); return route.abort(); }
      if (url.origin !== base) {
        if (request.resourceType() === 'image' && url.href !== candidateUrl) return route.fulfill({ status: 204, body: '' });
        unexpected.push(url.href); return route.abort();
      }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'live', teaching_match_enabled: true, search: { status: 'configured', providers: [] }, project_analysis: { status: 'unconfigured', message: '未配置模型' }, llm: { status: 'unconfigured' }, fetch: { status: 'available' }, platforms: [], limits: { max_knowledge_points: 15, max_results_per_point: 5 } } });
      if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
      if (url.pathname === `/api/projects/${data.finished.project_id}/results`) return route.fulfill({ json: complete ? data.finished : data.running });
      if (url.pathname === '/api/search-jobs/fallback-visibility-job') return route.fulfill({ json: data.job(complete) });
      if (url.pathname === '/api/search-jobs/fallback-visibility-job/results') return route.fulfill({ json: data.results(complete) });
      unexpected.push(url.pathname); return route.abort();
    });

    await page.goto(`/?project=${data.finished.project_id}&version=${data.finished.version!.version}`);
    await expect(page).toHaveTitle('项目制学习引导小精灵 · 课程与视频发现');
    await expect(page).toHaveURL(new RegExp(`project=${data.finished.project_id}`));
    await expect(page.locator('.project-progress .pipeline-description')).toHaveText('正在搜索相关视频 · 已显示 0 条');
    await expect(page.locator('.video-cover-card')).toHaveCount(0);
    await expectPrivateProcessHidden(page);
    await page.screenshot({ path: info.outputPath(`project-background-${viewport.name}.png`), fullPage: false });

    complete = true;
    await expect(page.locator('.video-cover-title')).toHaveText(data.resource.title);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    await page.getByRole('navigation', { name: '已选知识点' }).getByRole('button', { name: data.planned.name, exact: true }).click();
    await expect(page.locator('.video-cover-card')).toHaveCount(1);
    await expect(page.locator('.video-cover-title a')).toHaveAttribute('href', data.resource.url);
    await expectPrivateProcessHidden(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: info.outputPath(`project-complete-${viewport.name}.png`), fullPage: false });

    complete = false;
    await page.goto('/?mode=manual&job=fallback-visibility-job');
    await expect(page.locator('.pipeline-description')).toHaveText('正在搜索相关视频 · 已显示 0 条');
    await expect(page.locator('.task-records')).toHaveCount(0);
    await expectPrivateProcessHidden(page);
    complete = true;
    await expect(page.locator('.resource-card h4')).toHaveText(data.resource.title);
    await expect(page.locator('.search-pipeline')).toHaveCount(0);
    await expect(page.locator('.task-records')).toHaveCount(0);
    await expectPrivateProcessHidden(page);
    expect(errors).toEqual([]);
    expect(unexpected).toEqual([]);
  });
}
