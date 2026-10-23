import { expectGalleryTitlesOnly } from './coverTitleContract';
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import type { ProjectView } from '../src/projectTypes';
import type { RelatedTopicPointer, ResourceItem } from '../src/types';

// Transport and teaching outcomes below are isolated controls, never live model/source proof.
const time = '2026-10-19T12:00:00Z';
const input = { name: 'Python 接球小游戏', requirements: '方向键移动挡板，检测碰撞并计分。', student_level: 'beginner', language: 'zh', technical_version: '', project_context: '', preferred_platforms: ['bilibili', 'icourse163'] };
const source = JSON.parse(readFileSync(resolve(process.cwd(), 'tests/fixtures/topic-pointer-actual-p26.json'), 'utf8')) as RelatedTopicPointer;
function item(id: string, point = 'k1', status: 'supported' | 'partial' | 'needs_review' = 'supported'): ResourceItem {
  const url = `https://www.bilibili.com/video/${id}/`;
  return { resource: { ...source.resource, resource_id: id, title: `离线教学封面 ${id}`, url, canonical_url: url, thumbnail_url: null, resource_type: 'video' }, evidence: [{ evidence_id: `e-${id}`, kind: 'page', source: 'offline-control', url, field: 'description', text: '离线匹配结果，非实际教学验收。' }], match: { knowledge_point_id: point, resource_id: id, ranking_score: 1, recommendation_reason: '离线受控匹配', topic_evidence_status: status, supporting_evidence_ids: status === 'needs_review' ? [] : [`e-${id}`], matched_evidence_ids: [], coverage_basis: [] } };
}
function fixture(status = 'analyzed'): ProjectView {
  return { project_id: 'motion-project', input: input as any, current_version: 1, versions: [{ version: 1, status, created_at: time }], version: { version: 1, status, input: input as any, created_at: time, error: null, batches: [], confirmation: status === 'analyzed' || status === 'analyzing' ? null : { confirmed_at: time }, analysis: status === 'analyzing' ? null : { scope: input.requirements, technical_plan: 'pygame', assumptions: [], functions: [], knowledge_points: ['pygame 事件循环', '矩形碰撞检测'].map((name, index) => ({ id: `k${index + 1}`, name, description: '', function_ids: [], why_needed: '', learning_goal: '', necessity: 'required', prerequisite_ids: [], learning_order: index + 1, selection: 'learn' })) } }, points: [] };
}
function results(): ProjectView {
  const view = fixture('partial');
  view.points = view.version!.analysis!.knowledge_points.map(point => ({ project_knowledge_point_id: point.id, name: point.name, selection: 'learn', status: 'partial', batch_id: null, job_id: null, knowledge_point_id: point.id, result: { knowledge_point_id: point.id, text: point.name, total_matches: 1, items: [item(point.id === 'k1' ? 'BV164411J7GE' : 'BV13N411Z7ik', point.id)] } }));
  return view;
}
async function setup(page: Page, initial: ProjectView | null, enabled: boolean | 'unknown' = true) {
  const state = { view: initial, writes: [] as { action: string; body: any }[], external: [] as string[], runtime: [] as string[], console: [] as string[], searchRequested: false };
  let release: ((view: ProjectView) => void) | undefined;
  page.on('pageerror', error => state.runtime.push(error.message));
  page.on('console', message => { if (['warning', 'error'].includes(message.type())) state.console.push(message.text()); });
  await page.addInitScript(() => {
    Object.defineProperty(window, 'EventSource', { value: undefined });
    (window as any).__motionStarts = [];
    document.addEventListener('animationstart', event => { (window as any).__motionStarts.push({ name: event.animationName, resource: (event.target as HTMLElement)?.dataset?.resourceId || '', at: performance.now() }); });
  });
  const origin = new URL(process.env.PLAYWRIGHT_BASE_URL!).origin;
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin) {
      if (request.resourceType() === 'image') return route.fulfill({ status: 204, body: '' });
      state.external.push(url.href); return route.abort();
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (request.method() === 'GET') {
      if (url.pathname === '/api/capabilities') return route.fulfill({ json: { mode: 'live', ...(enabled === 'unknown' ? {} : { teaching_match_enabled: enabled }), search: { status: 'configured', selected_provider: 'offline', message: 'mock', providers: [] }, project_analysis: { status: 'configured', message: 'mock' }, llm: { status: 'configured', message: 'mock' }, fetch: { status: 'available', message: 'mock', browser_fallback: false }, platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 30, max_detail_pages: 40 } } });
      if (url.pathname === '/api/projects') return route.fulfill({ json: { projects: [] } });
      if (url.pathname === '/api/projects/motion-project/results') return route.fulfill({ json: state.view });
      const job = { job_id: 'motion-job', status: 'completed', phase: 'done', request: { ...input, knowledge_points: ['pygame 事件循环'] }, progress: { queries_completed: 1, queries_planned: 1 }, created_at: time, updated_at: time, warnings: [], errors: [], knowledge_points: [] };
      if (url.pathname === '/api/search-jobs/motion-job') return route.fulfill({ json: job });
      if (url.pathname === '/api/search-jobs/motion-job/results') return route.fulfill({ json: { job_id: job.job_id, status: job.status, job, groups: state.view!.points!.map(point => ({ ...point.result, discovery_only: true })), warnings: [], search_attempts: [] } });
    }
    if (request.method() === 'POST') {
      const action = url.pathname === '/api/projects' ? 'create' : url.pathname.split('/').at(-1)!;
      const body = request.postDataJSON(); state.writes.push({ action, body });
      if (action === 'create') state.view = { ...fixture(), version: null, current_version: 0 };
      else if (action === 'analyze') state.view = fixture('analyzing');
      else if (action === 'confirm') { state.view!.version!.status = 'confirmed'; state.view!.version!.confirmation = { confirmed_at: time }; }
      else if (action === 'search') {
        state.searchRequested = true;
        const next = await new Promise<ProjectView>(resolve => { release = resolve; });
        state.view = next;
      } else { state.external.push(`${request.method()} ${url.pathname}`); return route.abort(); }
      return route.fulfill({ json: state.view });
    }
    state.external.push(`${request.method()} ${url.pathname}`); return route.abort();
  });
  return { state, releaseSearch: (view: ProjectView) => release!(view), clean: () => { expect(state.external).toEqual([]); expect(state.runtime).toEqual([]); expect(state.console).toEqual([]); } };
}
const viewportList = [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }];
async function settle(page: Page) { await page.waitForFunction(() => !document.documentElement.dataset.motionKind); }
async function sample(page: Page) {
  return page.evaluate(() => document.getAnimations().map(animation => ({ state: animation.playState, currentTime: animation.currentTime, timing: animation.effect?.getComputedTiming(), frames: (animation.effect as KeyframeEffect | null)?.getKeyframes() })));
}

// CDP frame capture avoids installing Playwright's missing ffmpeg revision.
// Original frame timestamps remain authoritative; the optional existing-binary
// WebM is a 25fps visual review aid, not a performance benchmark.
const captures = new WeakMap<Page, { frames: { data: string; timestamp: number }[]; stop: () => Promise<unknown> }>();
test.beforeEach(async ({ page }) => {
  const session = await page.context().newCDPSession(page);
  const frames: { data: string; timestamp: number }[] = [];
  session.on('Page.screencastFrame', event => {
    if (frames.length < 400) frames.push({ data: event.data, timestamp: event.metadata.timestamp || 0 });
    void session.send('Page.screencastFrameAck', { sessionId: event.sessionId }).catch(() => {});
  });
  await session.send('Page.startScreencast', { format: 'jpeg', quality: 65, maxWidth: 1440, maxHeight: 1024, everyNthFrame: 1 });
  captures.set(page, { frames, stop: () => session.send('Page.stopScreencast') });
});
test.afterEach(async ({ page }, info) => {
  const capture = captures.get(page); if (!capture) return;
  await capture.stop().catch(() => {});
  const directory = info.outputPath('motion-frames'); await mkdir(directory, { recursive: true });
  await Promise.all(capture.frames.map((frame, index) => writeFile(resolve(directory, `${String(index).padStart(4, '0')}.jpg`), Buffer.from(frame.data, 'base64'))));
  await writeFile(info.outputPath('frame-timestamps.json'), JSON.stringify(capture.frames.map(({ timestamp }, index) => ({ file: `motion-frames/${String(index).padStart(4, '0')}.jpg`, timestamp })), null, 2));
  if (process.env.MOTION_FFMPEG_PATH && capture.frames.length) {
    const processHandle = spawn(process.env.MOTION_FFMPEG_PATH, ['-y', '-f', 'image2pipe', '-c:v', 'mjpeg', '-r', '25', '-i', 'pipe:0', '-c:v', 'libvpx', '-b:v', '1M', '-vf', 'scale=1440:1024:force_original_aspect_ratio=decrease,pad=1440:1024:-1:-1', info.outputPath('motion-review.webm')], { windowsHide: true });
    let diagnostic = ''; processHandle.stderr.on('data', chunk => { diagnostic += chunk.toString(); });
    const finished = new Promise<number | null>((resolve, reject) => { processHandle.on('close', resolve); processHandle.on('error', reject); });
    processHandle.stdin.on('error', () => {});
    for (let index = 0; index < capture.frames.length; index++) {
      const frame = capture.frames[index], next = capture.frames[index + 1];
      const repeat = next ? Math.max(1, Math.min(100, Math.round((next.timestamp - frame.timestamp) * 25))) : 1;
      for (let count = 0; count < repeat; count++) processHandle.stdin.write(Buffer.from(frame.data, 'base64'));
    }
    processHandle.stdin.end();
    const exitCode = await finished; await writeFile(info.outputPath('video-encoding.json'), JSON.stringify({ binary: process.env.MOTION_FFMPEG_PATH, exitCode, frames: capture.frames.length, diagnostic }, null, 2));
    expect(exitCode).toBe(0);
  }
});
test('three steps preserve immediate actions, focus and recovery through analysis and delayed search; no empty flash', async ({ page }, info) => {
  const context = await setup(page, null);
  await page.goto('/');
  await page.getByLabel('项目名称', { exact: true }).fill(input.name);
  await page.getByLabel('功能需求', { exact: true }).fill(input.requirements);
  const before = await page.locator('.project-description').boundingBox();
  await page.getByRole('button', { name: '分析项目', exact: true }).click();
  await expect(page.locator('.analysis-progress')).toBeVisible();
  await expect(page.getByRole('region', { name: '项目描述', exact: true })).not.toBeVisible();
  const waiting = await page.locator('.analysis-progress').boundingBox();
  expect(Math.abs(waiting!.height - before!.height)).toBeLessThan(2);
  await info.attach('analysis-animation-sample', { body: JSON.stringify(await sample(page)), contentType: 'application/json' });
  await page.screenshot({ path: info.outputPath('analysis-waiting.png'), fullPage: false });
  context.state.view = fixture();
  await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  await expect(page.locator('#stage-title')).toBeFocused();
  await settle(page);
  expect(await page.locator('.simple-knowledge-point').nth(1).evaluate(node => getComputedStyle(node).animationDelay)).toBe('0.05s');
  await page.getByRole('button', { name: '查看或修改项目描述' }).click();
  await expect(page.getByLabel('项目名称', { exact: true })).toHaveValue(input.name);
  await settle(page);
  // Successive navigation requests during a running browser transition must not restore an older stage.
  await page.locator('.stage-navigation button').nth(1).click();
  await page.evaluate(() => {
    const buttons = document.querySelectorAll<HTMLButtonElement>('.stage-navigation button');
    buttons[0].click(); requestAnimationFrame(() => buttons[1].click());
  });
  await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  await settle(page); await expect(page.locator('#stage-title')).toBeFocused();
  await page.getByRole('button', { name: '查找视频', exact: true }).click();
  await expect.poll(() => context.state.searchRequested).toBe(true);
  await expect(page.getByRole('status', { name: '正在开始视频检索' })).toBeVisible();
  await expect(page.getByRole('status', { name: '这个知识点暂未找到视频' })).toHaveCount(0);
  expect(context.state.writes.map(row => row.action)).toEqual(['create', 'analyze', 'confirm', 'search']);
  expect(context.state.writes.at(-2)!.body).toEqual({ version: 1, reviewed_topic_technologies: {} });
  await page.screenshot({ path: info.outputPath('search-starting.png'), fullPage: false });
  const running = fixture('running'); running.points = running.version!.analysis!.knowledge_points.map(point => ({ project_knowledge_point_id: point.id, name: point.name, selection: 'learn', status: 'running', batch_id: null, job_id: null, knowledge_point_id: point.id, result: null }));
  context.releaseSearch(running);
  await expect(page.getByRole('status', { name: '正在读取视频封面' })).toBeVisible();
  context.state.view = results();
  await expect(page.locator('.video-cover-card')).toHaveCount(2);
  await info.attach('result-animation-sample', { body: JSON.stringify(await sample(page)), contentType: 'application/json' });
  for (const viewport of viewportList) {
    await page.setViewportSize(viewport); await settle(page);
    await page.screenshot({ path: info.outputPath(`success-${viewport.name}.png`), fullPage: false });
    await expectGalleryTitlesOnly(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
  }
  context.clean();
});

test('stream append preserves existing card identity; rapid topic switch is latest-wins, keyboard and reduced motion remain immediate', async ({ page }, info) => {
  const context = await setup(page, results());
  await page.goto('/?project=motion-project&version=1');
  await expect(page.locator('.video-cover-card')).toHaveCount(2); await settle(page);
  await page.waitForTimeout(500);
  await page.evaluate(() => { (window as any).__firstCard = document.querySelector('[data-resource-id="BV164411J7GE"]'); (window as any).__motionStarts = []; });
  context.state.view!.version!.status = 'running';
  // Resume one controlled polling stream without a second API mutation.
  await page.getByRole('button', { name: '我的项目' }).click(); await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await expect(page.locator('.video-cover-card')).toHaveCount(2);
  await settle(page); await page.waitForTimeout(350);
  await page.evaluate(() => { (window as any).__firstCard = document.querySelector('[data-resource-id="BV164411J7GE"]'); (window as any).__motionStarts = []; });
  context.state.view!.points![0].result!.items.push(item('BV1NEW000001'));
  await expect(page.locator('.video-cover-card')).toHaveCount(3);
  expect(await page.evaluate(() => (window as any).__firstCard === document.querySelector('[data-resource-id="BV164411J7GE"]'))).toBe(true);
  expect(await page.evaluate(() => (window as any).__motionStarts.filter((row: any) => row.resource === 'BV164411J7GE'))).toEqual([]);
  const nav = page.getByRole('navigation', { name: '已选知识点' });
  await nav.getByRole('button', { name: 'pygame 事件循环', exact: true }).focus(); await page.keyboard.press('Enter');
  await page.evaluate(() => { const buttons = document.querySelectorAll<HTMLButtonElement>('.topic-navigation button'); buttons[2].click(); requestAnimationFrame(() => buttons[1].click()); });
  await expect(nav.getByRole('button', { name: 'pygame 事件循环', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.video-cover-card')).toHaveCount(2); await settle(page);
  await expect(page.locator('[data-resource-id="BV13N411Z7ik"]')).toHaveCount(0);
  await expect(nav.getByRole('button', { name: 'pygame 事件循环', exact: true })).toBeFocused();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await nav.getByRole('button', { name: '矩形碰撞检测', exact: true }).click();
  await expect(page.locator('.video-cover-card')).toHaveCount(1);
  const reduced = await page.locator('.video-cover-card').evaluate(node => ({ name: getComputedStyle(node).animationName, delay: getComputedStyle(node).animationDelay, duration: getComputedStyle(node).animationDuration }));
  // Native snapshot performs the sole 100ms fade; mounted cards never double-animate.
  expect(reduced.name).toBe('none'); expect(reduced.delay).toBe('0s');
  const reducedAnimations = await sample(page);
  expect(reducedAnimations.every(animation => Number(animation.timing?.activeDuration || 0) <= 100)).toBe(true);
  expect(reducedAnimations.flatMap(animation => animation.frames || []).every(frame => !('transform' in frame))).toBe(true);
  await info.attach('reduced-animation-sample', { body: JSON.stringify(reducedAnimations), contentType: 'application/json' });
  expect(context.state.writes).toEqual([]); context.clean();
});

test('teaching true and unknown exclude unverified, pointer and raw discovery covers; explicit false retains the safe original demo paths', async ({ page }) => {
  for (const enabled of [true, 'unknown', false] as const) {
    await page.unrouteAll();
    const view = results(), group = view.points![0].result!, pointer = structuredClone(source);
    group.knowledge_point_id = pointer.pointer.knowledge_point_id;
    group.items = [item('BV1MATCHED001', group.knowledge_point_id)];
    view.version!.analysis!.knowledge_points[0].learning_skills = [pointer.pointer.skill];
    group.items.push(item('BV1PARTIAL00', group.knowledge_point_id, 'partial'), item('BV1REVIEW000', group.knowledge_point_id, 'needs_review'));
    group.related_topic_pointers = [pointer];
    const resource = { ...item('BV1DISCOVERY0').resource, thumbnail_url: null };
    group.discovery_items = [{ resource, discovery_evidence: [] }];
    const context = await setup(page, view, enabled);
    await page.goto('/?project=motion-project&version=1');
    await expect(page.locator('.video-cover-card')).toHaveCount(enabled === false ? 6 : 3);
    await expect(page.locator('[data-resource-id="BV1MATCHED001"]')).toBeVisible();
    await expect(page.locator('[data-resource-id="BV1PARTIAL00"]')).toBeVisible();
    await expect(page.locator('[data-source-kind="related-topic"]')).toHaveCount(enabled === false ? 1 : 0);
    await expect(page.locator('[data-resource-id="BV1REVIEW000"],[data-resource-id="BV1DISCOVERY0"]')).toHaveCount(enabled === false ? 2 : 0);
    await expectGalleryTitlesOnly(page);
    await page.goto('/?mode=manual&job=motion-job');
    await expect(page.locator('.discovery-card')).toHaveCount(enabled === false ? 1 : 0);
    await expect(page.locator('.section-needs_review')).toContainText('待核实');
    await expect(page.getByRole('heading', { name: enabled === false ? '课程与视频' : '推荐课程', exact: true })).toBeVisible();
    context.clean();
  }
});

test('unsupported native transitions still navigate and never leave focus or pending motion stuck', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(document, 'startViewTransition', { value: undefined }));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const context = await setup(page, results());
  await page.goto('/?project=motion-project&version=1');
  await expect(page.locator('.video-cover-card')).toHaveCount(2);
  await page.getByRole('button', { name: '← 调整知识点', exact: true }).click();
  await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  await expect(page.locator('#stage-title')).toBeFocused();
  await page.locator('.stage-navigation button').nth(2).click();
  await expect(page.locator('.video-cover-card')).toHaveCount(2);
  await expect(page.locator('#stage-title')).toBeFocused();
  await settle(page); expect(context.state.writes).toEqual([]); context.clean();
});

test('physical rapid header clicks cross native overlay at desktop and mobile; last step and heading focus win', async ({ page }, info) => {
  for (const viewport of [viewportList[0], viewportList[2]]) {
    await page.unrouteAll(); await page.setViewportSize(viewport);
    const context = await setup(page, results());
    await page.goto('/?project=motion-project&version=1');
    await expect(page.locator('.video-cover-card')).toHaveCount(2); await settle(page);
    await page.evaluate(() => {
      (window as any).__physicalClicks = [];
      document.addEventListener('click', event => {
        const target = event.target as HTMLElement;
        (window as any).__physicalClicks.push({ trusted: event.isTrusted, tag: target.tagName, button: target.closest('button')?.textContent || '', x: event.clientX, y: event.clientY });
      }, true);
    });
    const boxes = await page.locator('.stage-navigation button').evaluateAll(nodes => nodes.map(node => { const box = node.getBoundingClientRect(); return { x: box.x + box.width / 2, y: box.y + box.height / 2 }; }));
    for (const index of [0, 1, 0, 2, 1, 2]) { await page.mouse.click(boxes[index].x, boxes[index].y); await page.waitForTimeout(35); }
    const clicks = await page.evaluate(() => (window as any).__physicalClicks);
    await info.attach(`physical-clicks-${viewport.name}`, { body: JSON.stringify(clicks, null, 2), contentType: 'application/json' });
    expect(clicks).toHaveLength(6); expect(clicks.every((click: any) => click.trusted && click.button)).toBe(true);
    await expect(page.locator('.stage-main')).toHaveClass(/stage-3/); await settle(page);
    await expect(page.locator('#stage-title')).toBeFocused();
    await expect(page.locator('.video-cover-card')).toHaveCount(2);
    expect(context.state.writes).toEqual([]); context.clean();
  }
});
