import { createServer, type ServerResponse } from 'node:http';
import { test, expect, type Page } from '@playwright/test';
import type { ProjectInput, ProjectView } from '../src/projectTypes';
import type { Capabilities, DiscoveredVideo, SearchJob, SearchPipeline, SearchResults } from '../src/types';

// Native EventSource against a local, controlled streaming HTTP server. No search providers run.
const time = '2026-10-19T10:00:00Z';
const input: ProjectInput = { name: '流式课程验收', requirements: '了解 pandas 数据聚合。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili', 'icourse163'] };
const caps: Capabilities = { mode: 'live', teaching_match_enabled: false, search: { selected_provider: 'offline', status: 'configured', message: '离线传输测试', providers: [] }, llm: { status: 'unconfigured', message: '不调用模型' }, fetch: { status: 'available', message: '离线测试', browser_fallback: false }, platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 60, max_detail_pages: 60 } };
const pipeline = (displayed = 0, terminal = false): SearchPipeline => ({ stage: terminal ? 'complete' : 'searching', search_requests: 2, search_budget: 12, candidates: 5, checking: terminal ? 0 : 1, displayed, filtered: 1, unknown: terminal ? 0 : 1, terminal, source_limited: false });
const fixtureVideoIds = new Map<string, number>();
function video(id: string, mooc = false): DiscoveredVideo {
  const number = fixtureVideoIds.get(id) ?? fixtureVideoIds.size + 1;
  fixtureVideoIds.set(id, number);
  const url = mooc ? `https://www.icourse163.org/course/OFFLINE-${1000000000 + number}`
    : `https://www.bilibili.com/video/BV1${number.toString(36).padStart(9, '0')}/`;
  // URLs and page-verification fields are synthetic offline controls for the
  // transport/UI contract. No source page is fetched or claimed verified here.
  return { resource: { resource_id: id, title: mooc ? 'pandas 分组聚合课程（大纲已确认）' : `B站 pandas 教程 ${id}`, url, canonical_url: url, platform: mooc ? 'icourse163' : 'bilibili', resource_type: mooc ? 'course' : 'video', thumbnail_url: null, fetch_status: 'fetched', video_evidence_status: 'page_verified' }, discovery_evidence: [] };
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

async function setupRetry(page: Page) {
  const context = await setup(page);
  context.state.project = project([video('PREVIOUS')], 2, true);
  const requests: { action: string; release: (status?: number) => void }[] = [];
  const reads: { release: () => void }[] = [];
  let holdRunningRead = false;
  await page.route('**/api/projects/stream-project/**', async route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() === 'GET' && url.pathname.endsWith('/results') && holdRunningRead && context.state.project.version?.status === 'running') {
      holdRunningRead = false;
      const snapshot = structuredClone(context.state.project);
      await new Promise<void>(resolve => reads.push({ release: resolve }));
      return route.fulfill({ json: snapshot });
    }
    const action = url.pathname.split('/').at(-1)!;
    if (request.method() !== 'POST' || !['edit', 'confirm', 'search'].includes(action)) return route.fallback();
    const body = request.postDataJSON() as { expected_version?: number; version?: number };
    const status = await new Promise<number>(resolve => requests.push({ action, release: (code = 200) => resolve(code) }));
    if (status !== 200) return route.fulfill({ status, json: { detail: '离线重试提交失败' } });
    const version = action === 'edit' ? body.expected_version! + 1 : body.version!;
    const snapshot = project([], version, action !== 'search');
    snapshot.current_version = version;
    snapshot.version!.status = action === 'edit' ? 'analyzed' : action === 'confirm' ? 'confirmed' : 'running';
    if (action === 'edit') snapshot.version!.confirmation = null;
    snapshot.versions = [...context.state.project.versions.filter(row => row.version !== version),
      { version, status: snapshot.version!.status, created_at: time }];
    snapshot.points = [];
    if (action === 'search') snapshot.pipeline = { ...pipeline(), stage: 'queued' };
    context.state.project = snapshot;
    // Mutation responses use projects.view and contain neither pipeline nor point results.
    const response = structuredClone(snapshot); delete response.pipeline; delete response.points;
    return route.fulfill({ json: response });
  });
  return { ...context, requests, reads, holdRunningRead: () => { holdRunningRead = true; },
    cleanup: async () => { for (const request of requests) request.release(503); for (const read of reads) read.release(); await context.cleanup(); } };
}

async function gateCancellation(page: Page, response: ProjectView) {
  const requests: { body: unknown; release: (status?: number) => void }[] = [];
  await page.route('**/api/projects/stream-project/cancel', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    const body = route.request().postDataJSON() as unknown;
    const status = await new Promise<number>(resolve => requests.push({ body, release: (code = 200) => resolve(code) }));
    if (status !== 200) return route.fulfill({ status, json: { detail: '离线取消提交失败' } });
    const mutation = structuredClone(response); delete mutation.pipeline; delete mutation.points;
    return route.fulfill({ json: mutation });
  });
  return requests;
}

test('project native stream shows page-verified B站 then appends page-verified MOOC controls, retaining covers through completion and mobile filtering', async ({ page }, info) => {
  const context = await setup(page);
  try {
    await page.goto('/?project=stream-project&version=2');
    await expect(page).toHaveTitle('项目制学习引导小精灵 · 课程与视频发现');
    await expect(page.getByRole('region', { name: '视频封面', exact: true })).toBeVisible();
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('已显示 0 条');
    const progress = page.getByRole('status', { name: '搜索与匹配进度' });
    const bar = progress.getByRole('progressbar');
    await expect(progress).toHaveAttribute('data-state', 'active');
    await expect(progress.locator('p')).toHaveCount(1);
    await expect(progress.locator('ol,li,.pipeline-limit')).toHaveCount(0);
    await expect(bar).not.toHaveAttribute('aria-valuenow');
    await expect(progress.locator('.pipeline-bar-fill')).toHaveCSS('animation-name', 'pipeline-travel');
    await expect(page.locator('.stage-intro .action-notice,.project-search-controls p')).toHaveCount(0);
    await expect.poll(() => context.streams.length).toBe(1);
    const initialReads = context.state.projectReads;
    const first = project([video('BVFIRST')]); context.send(first);
    await expect(page.locator('.video-cover-card')).toHaveCount(1);
    await expect(page.locator('[data-resource-id="BVFIRST"]')).toBeVisible();
    await expect(progress).toHaveText('正在搜索相关视频 · 已显示 1 条');
    await expect(page.locator('a[href*="icourse163.org"]')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('stream-searching-desktop.png'), animations: 'disabled' });
    const second = project([video('BVFIRST'), video('BVSECOND'), libraryCourse('123456')]);
    second.pipeline = { ...pipeline(3), stage: 'checking' }; context.send(second);
    await expect(page.locator('.video-cover-card')).toHaveCount(3);
    await expect(page.locator('[data-resource-id="BVFIRST"]')).toBeVisible();
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toContainText('已显示 3 条');
    await expect(progress).toHaveText('正在校验视频与大纲 · 已显示 3 条');
    await expect(page.locator('.video-cover-card a.course-cover[href*="icourse163.org"]')).toHaveCount(1);
    await expect(page.locator('[data-resource-id="123456"] a')).toHaveCount(2);
    for (const link of await page.locator('[data-resource-id="123456"] a').all()) { await expect(link).toHaveAccessibleName(/pandas 分组聚合课程/); await expect(link).toHaveAttribute('rel', 'noopener noreferrer'); await expect(link).toHaveAttribute('target', '_blank'); }
    await expect(page.locator('body')).not.toContainText(internalLibraryLabels);
    const final = project(second.points![0].result!.discovery_items!, 2, true);
    final.version!.batches = [{ batch_id: 'batch1', status: 'submitted', job_status: 'completed', project_knowledge_point_ids: ['p1'], job_id: 'stream-job' }];
    context.send(final, 'complete');
    await expect.poll(() => context.streams[0].closed).toBe(true);
    await expect(progress).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    await page.getByRole('navigation', { name: '已选知识点' }).getByRole('button', { name: 'pandas 分组聚合', exact: true }).click();
    await expect(page.locator('.video-cover-card')).toHaveCount(3);
    await page.screenshot({ path: info.outputPath('stream-complete-desktop.png'), animations: 'disabled' });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('region', { name: '视频封面', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath('stream-complete-mobile.png'), animations: 'disabled' });
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    expect(context.state.projectReads).toBe(initialReads); expect(context.streams).toHaveLength(1); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

for (const terminal of [true, false]) test(`cancellation removes the progress bar and its project wrapper with pipeline terminal=${terminal}`, async ({ page }) => {
  const context = await setup(page);
  try {
    await page.goto('/?project=stream-project&version=2');
    await expect.poll(() => context.streams.length).toBe(1);
    const progress = page.getByRole('status', { name: '搜索与匹配进度' });
    await expect(progress).toBeVisible();
    const cancelled = project([], 2, terminal);
    cancelled.version!.status = 'cancelled';
    context.send(cancelled, terminal ? 'complete' : 'snapshot');
    await expect(progress).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    if (terminal) await expect.poll(() => context.streams[0].closed).toBe(true);
    assertClean(context.diagnostics);
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
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
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
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toBeVisible();
    context.state.results = result([video('BVFIRST'), libraryCourse('123456')], true);
    context.streams[0].response.end();
    await expect(page.locator('.discovery-card')).toHaveCount(2);
    await expect(page.locator('[data-resource-id="BVFIRST"]')).toBeVisible();
    await expect(page.locator('[data-resource-id="123456"]')).toContainText('pandas 分组聚合课程');
    await expect(page.locator('body')).not.toContainText(internalLibraryLabels);
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toHaveCount(0);
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
    const progress = page.getByRole('status', { name: '搜索与匹配进度' });
    await expect(progress).toHaveText('正在搜索相关视频 · 已显示 1 条');
    await expect(progress).toHaveAttribute('data-state', 'active');
    await expect(progress.getByRole('progressbar')).toBeVisible();
    expect(context.streams[0].closed).toBe(false);
    context.send(result([video('BVFIRST'), video('123456', true)], true), 'complete');
    await expect(page.locator('.discovery-card')).toHaveCount(2);
    await expect(progress).toHaveCount(0);
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
    await expect(page.getByRole('status', { name: '搜索与匹配进度' })).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    expect(context.streams).toHaveLength(0); assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

test('retry immediately restores progress through gated mutations and first snapshot, hides on completion and works again on mobile', async ({ page }, info) => {
  const context = await setupRetry(page);
  try {
    await page.goto('/?project=stream-project&version=2');
    const progress = page.getByRole('status', { name: '搜索与匹配进度' });
    await expect(page.locator('[data-resource-id="PREVIOUS"]')).toBeVisible();
    await expect(progress).toHaveCount(0);
    for (let round = 0; round < 2; round += 1) {
      await page.setViewportSize(round === 0 ? { width: 1440, height: 1000 } : { width: 390, height: 844 });
      await page.getByRole('button', { name: '重新检索这些知识点', exact: true }).click();
      for (const [offset, action] of ['edit', 'confirm', 'search'].entries()) {
        const index = round * 3 + offset;
        await expect.poll(() => context.requests.length).toBe(index + 1);
        expect(context.requests[index].action).toBe(action);
        await expect(page.locator('.stage-main')).toHaveClass(/\bstage-3\b/);
        await expect(progress).toBeVisible();
        await expect(progress).toBeInViewport();
        await expect(progress).toContainText('正在准备搜索');
        await expect(progress.locator('p')).toHaveCount(1);
        if (action === 'search') context.holdRunningRead();
        context.requests[index].release();
      }
      await expect.poll(() => context.reads.length).toBe(round + 1);
      // The search POST has settled, but the running result still has no pipeline in the UI.
      await expect(page.getByRole('button', { name: '取消项目检索', exact: true })).toBeEnabled();
      await expect(page.locator('.stage-main')).toHaveClass(/\bstage-3\b/);
      await expect(progress).toBeVisible();
      await expect(progress).toContainText('正在准备搜索');
      await page.screenshot({ path: info.outputPath(`retry-preparing-${round}.png`), animations: 'disabled' });
      context.reads[round].release();
      await expect.poll(() => context.streams.length).toBe(round + 1);
      await expect(progress).toBeVisible();
      const completed = project([video(`RETRY-${round + 1}`)], 3 + round, true);
      completed.current_version = 3 + round;
      completed.versions = context.state.project.versions.map(row => row.version === completed.current_version ? { ...row, status: 'completed' } : row);
      context.state.project = completed;
      context.send(completed, 'complete', round);
      await expect(page.locator(`[data-resource-id="RETRY-${round + 1}"]`)).toBeVisible();
      await expect(progress).toHaveCount(0);
      await expect(page.locator('.project-progress')).toHaveCount(0);
      await expect.poll(() => context.streams[round].closed).toBe(true);
      await expect(page.getByRole('button', { name: '重新检索这些知识点', exact: true })).toBeEnabled();
      await page.screenshot({ path: info.outputPath(`retry-complete-${round}.png`), animations: 'disabled' });
    }
    expect(context.requests.map(request => request.action)).toEqual(['edit', 'confirm', 'search', 'edit', 'confirm', 'search']);
    assertClean(context.diagnostics);
  } finally { await context.cleanup(); }
});

test('retry search submission failure removes temporary progress and allows another explicit retry', async ({ page }) => {
  const context = await setupRetry(page);
  try {
    await page.goto('/?project=stream-project&version=2');
    const progress = page.getByRole('status', { name: '搜索与匹配进度' });
    const retry = page.getByRole('button', { name: '重新检索这些知识点', exact: true });
    await retry.click();
    for (const [index, action] of ['edit', 'confirm', 'search'].entries()) {
      await expect.poll(() => context.requests.length).toBe(index + 1);
      expect(context.requests[index].action).toBe(action);
      await expect(progress).toBeVisible();
      await expect(page.locator('.stage-main')).toHaveClass(/\bstage-3\b/);
      context.requests[index].release(action === 'search' ? 503 : 200);
    }
    await expect(page.getByRole('alert')).toContainText('离线重试提交失败');
    await expect(progress).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    await expect(retry).toBeEnabled();
    await retry.click();
    await expect.poll(() => context.requests.length).toBe(4);
    expect(context.requests[3].action).toBe('edit');
    await expect(progress).toBeVisible();
    context.requests[3].release(503);
    await expect(page.getByRole('alert')).toContainText('离线重试提交失败');
    await expect(progress).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    await expect(retry).toBeEnabled();
    expect(context.streams).toHaveLength(0);
    expect(context.diagnostics.runtime).toEqual([]);
    expect(context.diagnostics.unexpected).toEqual([]);
    expect(context.diagnostics.console.every(message => /503|Service Unavailable/.test(message))).toBe(true);
  } finally { await context.cleanup(); }
});

test('cancel immediately hides progress before its POST completes, ignores stale running snapshots, and retry restores it', async ({ page }) => {
  const context = await setupRetry(page);
  context.state.project = project([video('BEFORE-CANCEL')]);
  const cancelled = project([video('BEFORE-CANCEL')], 2, true);
  cancelled.version!.status = 'cancelled';
  cancelled.versions[1].status = 'cancelled';
  const cancellations = await gateCancellation(page, cancelled);
  try {
    await page.goto('/?project=stream-project&version=2');
    const progress = page.getByRole('status', { name: '搜索与匹配进度' });
    const wrapper = page.locator('.project-progress');
    const cancel = page.getByRole('button', { name: '取消项目检索', exact: true });
    await expect(progress).toBeVisible();
    await expect.poll(() => context.streams.length).toBe(1);
    await cancel.click();
    await expect.poll(() => cancellations.length).toBe(1);
    expect(cancellations[0].body).toEqual({ version: 2 });
    await expect(cancel).toBeDisabled();
    // The response is still held: hiding must come from the click, not a terminal snapshot.
    await expect(progress).toHaveCount(0);
    await expect(wrapper).toHaveCount(0);
    await expect.poll(() => context.streams[0].closed).toBe(true);

    context.state.project = project([video('STALE-READ')]);
    cancellations[0].release();
    await expect(page.locator('[data-resource-id="STALE-READ"]')).toBeVisible();
    await expect.poll(() => context.streams.length).toBe(2);
    await expect(progress).toHaveCount(0);
    await expect(wrapper).toHaveCount(0);
    context.send(project([video('STALE-EVENT')]), 'snapshot', 1);
    await expect(page.locator('[data-resource-id="STALE-EVENT"]')).toBeVisible();
    await expect(progress).toHaveCount(0);
    await expect(wrapper).toHaveCount(0);

    context.state.project = cancelled;
    context.send(cancelled, 'complete', 1);
    await expect.poll(() => context.streams[1].closed).toBe(true);
    await expect(progress).toHaveCount(0);
    await page.getByRole('button', { name: '重新检索这些知识点', exact: true }).click();
    for (const [index, action] of ['edit', 'confirm', 'search'].entries()) {
      await expect.poll(() => context.requests.length).toBe(index + 1);
      expect(context.requests[index].action).toBe(action);
      await expect(progress).toBeVisible();
      context.requests[index].release();
    }
    await expect.poll(() => context.streams.length).toBe(3);
    await expect(progress).toBeVisible();
    const completed = project([video('AFTER-CANCEL-RETRY')], 3, true);
    completed.current_version = 3;
    completed.versions = context.state.project.versions.map(row => row.version === 3 ? { ...row, status: 'completed' } : row);
    context.state.project = completed;
    context.send(completed, 'complete', 2);
    await expect(page.locator('[data-resource-id="AFTER-CANCEL-RETRY"]')).toBeVisible();
    await expect(progress).toHaveCount(0);
    await expect(wrapper).toHaveCount(0);
    assertClean(context.diagnostics);
  } finally { for (const cancellation of cancellations) cancellation.release(503); await context.cleanup(); }
});

test('cancel failure restores active progress after hiding it while the POST is pending', async ({ page }) => {
  const context = await setup(page);
  const cancelled = project([], 2, true); cancelled.version!.status = 'cancelled';
  const cancellations = await gateCancellation(page, cancelled);
  try {
    await page.goto('/?project=stream-project&version=2');
    const progress = page.getByRole('status', { name: '搜索与匹配进度' });
    const cancel = page.getByRole('button', { name: '取消项目检索', exact: true });
    await expect(progress).toBeVisible();
    await expect.poll(() => context.streams.length).toBe(1);
    await cancel.click();
    await expect.poll(() => cancellations.length).toBe(1);
    await expect(cancel).toBeDisabled();
    await expect(progress).toHaveCount(0);
    await expect(page.locator('.project-progress')).toHaveCount(0);
    cancellations[0].release(503);
    await expect(page.getByRole('alert')).toContainText('离线取消提交失败');
    await expect(cancel).toBeEnabled();
    await expect(progress).toBeVisible();
    await expect(progress).toHaveAttribute('data-state', 'active');
    await expect(progress.getByRole('progressbar')).toBeVisible();
    await expect.poll(() => context.streams.length).toBe(2);
    expect(context.diagnostics.runtime).toEqual([]);
    expect(context.diagnostics.unexpected).toEqual([]);
    expect(context.diagnostics.console.every(message => /503|Service Unavailable/.test(message))).toBe(true);
  } finally { for (const cancellation of cancellations) cancellation.release(503); await context.cleanup(); }
});
