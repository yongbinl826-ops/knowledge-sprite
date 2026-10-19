import { createServer, type ServerResponse } from 'node:http';
import { test, expect, type Page } from '@playwright/test';
import type { ProjectInput, ProjectView } from '../src/projectTypes';
import type { Capabilities, DiscoveredVideo, SearchJob, SearchPipeline, SearchResults } from '../src/types';

// Native EventSource against a local, controlled streaming HTTP server. No search providers run.
const time = '2026-10-19T10:00:00Z';
const input: ProjectInput = { name: '流式课程验收', requirements: '了解 pandas 数据聚合。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili', 'icourse163'] };
const caps: Capabilities = { mode: 'live', teaching_match_enabled: false, search: { selected_provider: 'offline', status: 'configured', message: '离线传输测试', providers: [] }, llm: { status: 'unconfigured', message: '不调用模型' }, fetch: { status: 'available', message: '离线测试', browser_fallback: false }, platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 60, max_detail_pages: 60 } };
const pipeline = (displayed = 0, terminal = false): SearchPipeline => ({ stage: terminal ? 'complete' : 'searching', search_requests: 2, search_budget: 12, candidates: 5, checking: terminal ? 0 : 1, displayed, filtered: 1, unknown: terminal ? 0 : 1, terminal, source_limited: false });
function video(id: string, mooc = false): DiscoveredVideo {
  const url = mooc ? `https://www.icourse163.org/course/TEST-${id}` : `https://www.bilibili.com/video/${id}/`;
  return { resource: { resource_id: id, title: mooc ? 'pandas 分组聚合课程（大纲已确认）' : `B站 pandas 教程 ${id}`, url, canonical_url: url, platform: mooc ? 'icourse163' : 'bilibili', resource_type: mooc ? 'course' : 'video', thumbnail_url: null, fetch_status: mooc ? 'fetched' : 'not_started', video_evidence_status: 'search_discovered' }, discovery_evidence: [] };
}
function libraryCourse(id: string): DiscoveredVideo {
  const row = video(id, true);
  // The UI consumes the public Evidence fields; backend validation owns the
  // receipt's content/profile digest and expiry checks before emitting cards.
  row.discovery_evidence = [{ evidence_id: `library-${id}`, kind: 'course_library',
    source: 'shared_course_library', url: row.resource.url, title: row.resource.title }];
  return row;
}
const internalLibraryLabels = /共享课程库|共享库|刷新配置|shared_course_library|course_library|mooc_refresh/i;
function project(rows: DiscoveredVideo[] = [], number = 2, completed = false): ProjectView {
  const status = completed ? 'completed' : 'running';
  return { project_id: 'stream-project', input, current_version: 2, versions: [{ version: 1, status: 'completed', created_at: time }, { version: 2, status, created_at: time }], pipeline: pipeline(rows.length, completed),
    version: { version: number, status, input, analysis: { scope: '离线流式测试', technical_plan: 'pandas', assumptions: [], functions: [], knowledge_points: [{ id: 'p1', name: 'pandas 分组聚合', description: '', function_ids: [], why_needed: '', learning_goal: '', necessity: 'required', prerequisite_ids: [], learning_order: 1, selection: 'learn' }] }, confirmation: { confirmed_at: time }, batches: [], error: null, created_at: time },
    points: [{ project_knowledge_point_id: 'p1', name: 'pandas 分组聚合', selection: 'learn', status, batch_id: 'batch1', job_id: 'stream-job', knowledge_point_id: 'p1', result: { knowledge_point_id: 'p1', text: 'pandas 分组聚合', total_matches: 0, items: [], discovery_only: true, discovery_items: rows } }],
  };
}
function result(rows: DiscoveredVideo[] = [], completed = false): SearchResults {
  const job: SearchJob = { job_id: 'stream-job', status: completed ? 'completed' : 'running', phase: completed ? 'done' : 'search', created_at: time, updated_at: time,
    request: { ...input, knowledge_points: ['pandas 分组聚合'] }, progress: { queries_planned: 12, queries_completed: 2, search_requests: 2, search_successes: 2, search_failures: 0, candidates_discovered: 5, resources_discovered: 5, details_attempted: 1, details_completed: completed ? 1 : 0, cache_hits: 0 }, budgets: { max_search_requests: 12, max_detail_pages: 12, deadline_seconds: 180 }, warnings: [], errors: [], knowledge_points: [{ knowledge_point_id: 'p1', text: 'pandas 分组聚合' }] };
  return { job_id: job.job_id, status: job.status, job, pipeline: pipeline(rows.length, completed), warnings: [], groups: project(rows).points!.map(point => point.result!), search_attempts: [] };
}
async function setup(page: Page) {
  const streams: { path: string; response: ServerResponse; closed: boolean }[] = [];
  const server = createServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Access-Control-Allow-Origin': '*' });
    response.flushHeaders(); response.write(': connected\n\n');
    const stream = { path: request.url || '', response, closed: false }; streams.push(stream);
    response.on('close', () => { stream.closed = true; });
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('No local stream port');
  const streamOrigin = `http://127.0.0.1:${address.port}`;
  const uiOrigin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
  const diagnostics = { runtime: [] as string[], console: [] as string[], unexpected: [] as string[] };
  page.on('pageerror', error => diagnostics.runtime.push(error.message));
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) diagnostics.console.push(message.text()); });
  const state = { project: project(), results: result(), projectReads: 0, jobReads: 0 };
  await page.route('**/*', route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() === 'GET' && url.origin === streamOrigin) return route.continue();
    if (request.method() === 'GET' && url.origin === uiOrigin) {
      if (!url.pathname.startsWith('/api/')) return route.continue();
      if (url.pathname === '/api/capabilities') return route.fulfill({ json: caps });
      if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
      if (url.pathname.endsWith('/events')) return route.fulfill({ status: 307, headers: { Location: `${streamOrigin}${url.pathname}${url.search}` }, body: '' });
      if (url.pathname === '/api/projects/stream-project/results') {
        state.projectReads += 1;
        return route.fulfill({ json: url.searchParams.get('version') === '1' ? project([video('HISTORY')], 1, true) : state.project });
      }
      if (url.pathname === '/api/search-jobs/stream-job') return route.fulfill({ json: state.results.job });
      if (url.pathname === '/api/search-jobs/stream-job/results') { state.jobReads += 1; return route.fulfill({ json: state.results }); }
    }
    diagnostics.unexpected.push(`${request.method()} ${url.href}`); return route.abort();
  });
  const send = (value: unknown, event = 'snapshot', index = 0) => streams[index].response.write(`event: ${event}\ndata: ${JSON.stringify(value)}\n\n`);
  const cleanup = async () => {
    for (const stream of streams) stream.response.end();
    server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve()));
  };
  return { streams, state, diagnostics, send, cleanup };
}
const assertClean = (diagnostics: Awaited<ReturnType<typeof setup>>['diagnostics']) => {
  expect(diagnostics.runtime).toEqual([]); expect(diagnostics.console).toEqual([]); expect(diagnostics.unexpected).toEqual([]);
};

test('project native stream shows B站 first, only appends verified MOOC, retains covers through completion and mobile filtering', async ({ page }, info) => {
  const context = await setup(page);
  try {
    await page.goto('/?project=stream-project&version=2');
    await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
    await expect(page.getByRole('region', { name: '视频封面', exact: true })).toBeVisible();
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('已显示 0 条');
    await expect.poll(() => context.streams.length).toBe(1);
    const initialReads = context.state.projectReads;
    const first = project([video('BVFIRST')]); context.send(first);
    await expect(page.locator('.video-cover-card')).toHaveCount(1);
    await expect(page.locator('[data-resource-id="BVFIRST"]')).toBeVisible();
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('覆盖待确认 1 条');
    await expect(page.locator('a[href*="icourse163.org"]')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('stream-searching-desktop.png'), animations: 'disabled' });
    const second = project([video('BVFIRST'), video('BVSECOND'), libraryCourse('123456')]);
    second.pipeline = { ...pipeline(3), stage: 'checking' }; context.send(second);
    await expect(page.locator('.video-cover-card')).toHaveCount(3);
    await expect(page.locator('[data-resource-id="BVFIRST"]')).toBeVisible();
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('已显示 3 条');
    await expect(page.locator('a[href*="icourse163.org"]')).toHaveCount(1);
    await expect(page.locator('[data-resource-id="123456"] a')).toHaveAccessibleName(/pandas 分组聚合课程/);
    await expect(page.locator('body')).not.toContainText(internalLibraryLabels);
    const final = project(second.points![0].result!.discovery_items!, 2, true);
    final.version!.batches = [{ batch_id: 'batch1', status: 'submitted', job_status: 'completed', project_knowledge_point_ids: ['p1'], job_id: 'stream-job' }];
    context.send(final, 'complete');
    await expect.poll(() => context.streams[0].closed).toBe(true);
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('本次结果已保留');
    await page.getByRole('navigation', { name: '已选知识点' }).getByRole('button', { name: 'pandas 分组聚合', exact: true }).click();
    await expect(page.locator('.video-cover-card')).toHaveCount(3);
    await page.screenshot({ path: info.outputPath('stream-complete-desktop.png'), animations: 'disabled' });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('.search-pipeline').scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath('stream-complete-mobile.png'), animations: 'disabled' });
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    expect(context.state.projectReads).toBe(initialReads); expect(context.streams).toHaveLength(1); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

test('changing project version closes the old stream and ignores late frames', async ({ page }) => {
  const context = await setup(page);
  try {
    await page.goto('/?project=stream-project&version=2');
    await expect.poll(() => context.streams.length).toBe(1);
    context.send(project([video('LATEST')])); await expect(page.locator('[data-resource-id="LATEST"]')).toBeVisible();
    await page.getByRole('button', { name: '我的项目' }).click();
    await page.getByLabel('查看版本', { exact: true }).selectOption('1');
    await expect(page.locator('[data-resource-id="HISTORY"]')).toBeVisible();
    await expect.poll(() => context.streams[0].closed).toBe(true);
    context.send(project([video('LATE')]));
    await expect(page.locator('[data-resource-id="LATEST"],[data-resource-id="LATE"]')).toHaveCount(0);
    await expect(page.getByLabel('查看版本', { exact: true })).toHaveValue('1');
    expect(context.streams).toHaveLength(1); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

test('manual native stream preserves B站 results and falls back to reads after disconnect without a new search', async ({ page }) => {
  const context = await setup(page);
  try {
    await page.goto('/?job=stream-job&mode=manual');
    await expect.poll(() => context.streams.length).toBe(1);
    const initialReads = context.state.jobReads;
    context.send(result([video('BVFIRST')])); await expect(page.locator('.discovery-card')).toHaveCount(1);
    context.state.results = result([video('BVFIRST'), libraryCourse('123456')], true);
    context.streams[0].response.end();
    await expect(page.locator('.discovery-card')).toHaveCount(2);
    await expect(page.locator('[data-resource-id="BVFIRST"]')).toBeVisible();
    await expect(page.locator('[data-resource-id="123456"]')).toContainText('pandas 分组聚合课程');
    await expect(page.locator('body')).not.toContainText(internalLibraryLabels);
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('本次结果已保留');
    expect(context.state.jobReads).toBe(initialReads + 1); expect(context.streams).toHaveLength(1); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

test('unmounting project mode closes the active stream', async ({ page }) => {
  const context = await setup(page);
  try {
    await page.goto('/?project=stream-project&version=2');
    await expect.poll(() => context.streams.length).toBe(1);
    await page.goto('/?mode=manual');
    await expect(page.getByLabel('知识点', { exact: true })).toBeVisible();
    await expect.poll(() => context.streams[0].closed).toBe(true); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

test('deferred followups keep a nominally completed job streaming until pipeline terminal', async ({ page }) => {
  const context = await setup(page);
  try {
    const deferred = result([video('BVFIRST')]);
    deferred.status = 'completed'; deferred.job!.status = 'completed'; deferred.job!.phase = 'awaiting_followup';
    context.state.results = deferred;
    await page.goto('/?job=stream-job&mode=manual');
    await expect.poll(() => context.streams.length).toBe(1);
    context.send(deferred);
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('找到后陆续显示');
    expect(context.streams[0].closed).toBe(false);
    context.send(result([video('BVFIRST'), video('123456', true)], true), 'complete');
    await expect(page.locator('.discovery-card')).toHaveCount(2);
    await expect.poll(() => context.streams[0].closed).toBe(true); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

test('unsupported EventSource uses read-only polling with no duplicate stream', async ({ page }) => {
  const context = await setup(page);
  try {
    await page.addInitScript(() => { Object.defineProperty(window, 'EventSource', { value: undefined }); });
    await page.goto('/?project=stream-project&version=2');
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toBeVisible();
    context.state.project = project([video('BVFIRST')], 2, true);
    await expect(page.locator('[data-resource-id="BVFIRST"]')).toBeVisible();
    expect(context.streams).toHaveLength(0); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});
