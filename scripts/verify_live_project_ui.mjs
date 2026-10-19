/** Opt-in browser acceptance against the real local API. No route mocks or seeded results.
 * --reanalyze explicitly creates a new analysis version; --search submits only when not started.
 * Reruns first inspect persisted state, so interrupted work is resumed rather than resubmitted.
 */
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const require = createRequire(resolve(root, 'frontend/package.json'));
const { chromium } = require('@playwright/test');
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const base = option('--base-url', 'http://127.0.0.1:8000');
const projectId = option('--project');
if (!projectId || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw new Error('An explicit existing project and loopback URL are required');
const out = resolve(root, option('--output', 'evidence/browser/real-project'));
await mkdir(out, { recursive: true });
const report = { started_at: new Date().toISOString(), base_url: base, project_id: projectId, mock: false,
  seeded_candidates: false, playback_verified: false, browser: 'msedge',
  fallback_reason: 'CUA inventory has no connected browsers after host reconnection', steps: [], console: [], errors: [], requests_submitted: [] };
try { report.runtime_manifest = JSON.parse(await readFile(resolve(root, 'tmp/preview-runtime-manifest.json'), 'utf8')); } catch { report.runtime_manifest = null; }
const checkpoint = () => writeFile(resolve(out, 'report.json'), JSON.stringify(report, null, 2));
async function read(path) { const response = await fetch(base + path); if (!response.ok) throw new Error(`Local API HTTP ${response.status}`); return response.json(); }
const projectPath = `/api/projects/${encodeURIComponent(projectId)}/results`;
let view = await read(projectPath);
report.initial_version = view.version?.version;
report.initial_status = view.version?.status;
report.analysis_already_completed = !!view.version?.analysis;
report.original_input = view.original_input;
report.initial_version_input = view.version?.input;
await checkpoint();
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage();
async function settleVisibleCovers(label) {
  // Wait only for images actually in the viewport; lazy offscreen images are irrelevant.
  try { await page.waitForFunction(() => [...document.querySelectorAll('.course-cover img')].filter(img => {
    const box = img.getBoundingClientRect(); return box.bottom > 0 && box.top < innerHeight;
  }).every(img => img.complete), undefined, { timeout: 12000 }); } catch { /* Keep pending imagery visible in evidence. */ }
  (report.cover_observations ||= []).push({ label, images: await page.locator('.course-cover img').evaluateAll(nodes => nodes.map(img => ({
    src: img.currentSrc || img.src, complete: img.complete, natural_width: img.naturalWidth,
    visible: img.getBoundingClientRect().bottom > 0 && img.getBoundingClientRect().top < innerHeight,
  }))) });
}
page.on('pageerror', error => report.errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') report.console.push(message.text()); });
try {
  await page.goto(`${base}/?project=${encodeURIComponent(projectId)}&version=${view.version.version}`, { waitUntil: 'domcontentloaded' });
  if (args.includes('--retry-search')) {
    if (!view.version.confirmation || ['running', 'confirmed'].includes(view.version.status)) throw new Error('Retry requires a terminal confirmed current version');
    await page.getByRole('button', { name: /重新检索这些知识点/ }).click();
    report.requests_submitted.push('explicit search retry creates a new version from existing analysis');
    for (let index = 0; index < 30; index++) {
      await new Promise(done => setTimeout(done, 500));
      view = await read(projectPath);
      if (view.version.version > report.initial_version && view.version.confirmation) break;
    }
    if (view.version.version <= report.initial_version || !view.version.confirmation) throw new Error('Search retry did not create and confirm a new version');
  }
  if (args.includes('--reanalyze')) {
    if (view.version.status === 'analyzing') throw new Error('A prior analysis is still running; inspect it before resubmitting');
    await page.getByRole('button', { name: /01 项目描述/ }).click();
    await page.getByRole('button', { name: '保存需求并重新分析', exact: true }).click();
    report.requests_submitted.push('explicit new analysis version');
    console.log('Real analysis submitted; input preserved by the API');
    for (let index = 0; index < 100; index++) {
      await new Promise(done => setTimeout(done, 1500));
      view = await read(projectPath);
      if (view.version.version > report.initial_version && view.version.status !== 'analyzing') break;
    }
    if (view.version.version <= report.initial_version || !view.version.analysis) throw new Error(`Real analysis did not succeed: ${view.version.error?.code || view.version.status}`);
    await page.getByRole('heading', { name: `确认知识点 · v${view.version.version}`, exact: true }).waitFor();
  }
  report.analysis_version = view.version.version;
  report.analysis_prompt = view.version.prompt_version;
  report.analysis = view.version.analysis;
  report.analysis_input = view.version.input;
  if (!view.version.analysis) throw new Error(`No completed analysis to render: ${view.version.error?.code || view.version.status}`);
  if (view.version.confirmation) {
    await page.getByRole('button', { name: /调整知识点/ }).click();
    await page.getByRole('heading', { name: `确认知识点 · v${view.version.version}`, exact: true }).waitFor();
  }
  report.steps.push('real persisted model analysis rendered with learning units');
  await page.screenshot({ path: resolve(out, 'desktop-selection.png'), fullPage: false });
  if (view.version.confirmation) await page.getByRole('button', { name: /03 推荐视频/ }).click();
  if (args.includes('--search') && !view.version.confirmation) {
    await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
    report.requests_submitted.push('confirm and search from the real UI');
    console.log('Real selected-unit search submitted');
    await page.getByRole('heading', { name: /项目课程结果 · v/ }).waitFor();
  }
  view = await read(projectPath);
  if (view.version.confirmation) {
    await page.getByRole('heading', { name: `项目课程结果 · v${view.version.version}`, exact: true }).waitFor();
    await page.screenshot({ path: resolve(out, 'desktop-searching.png'), fullPage: false });
    const perBatchSeconds = Number(view.version.budgets?.per_batch_deadline_seconds) || 180;
    const waitIterations = Math.min(1200, Math.max(220, Math.ceil((view.version.batches.length * (perBatchSeconds + 30) + 30) / 1.5)));
    report.search_observation_limit_seconds = waitIterations * 1.5;
    for (let index = 0; index < waitIterations && ['running', 'confirmed'].includes(view.version.status); index++) {
      await new Promise(done => setTimeout(done, 1500));
      view = await read(projectPath);
      if (index % 20 === 0) { console.log(`Search state: ${view.version.status}`); report.observed_status = view.version.status; await checkpoint(); }
    }
    report.result_version = view.version.version;
    report.final_status = view.version.status;
    report.points = view.points;
    report.jobs = await Promise.all(view.version.batches.filter(batch => batch.job_id).map(batch => read(`/api/search-jobs/${batch.job_id}`)));
    if (view.version.status === 'running') throw new Error('Real project search exceeded the bounded acceptance wait; inspect before retry');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: `项目课程结果 · v${view.version.version}`, exact: true }).waitFor();
    report.visible_cards = await page.locator('.resource-card').count();
    report.links = await page.locator('.course-outbound').evaluateAll(nodes => nodes.map(node => ({ title: node.closest('article')?.querySelector('h4')?.textContent, url: node.href })));
    report.steps.push('real provider search completed and survived reload without resubmission');
    report.viewports = [];
    for (const [name, width, height] of [['desktop', 1440, 1000], ['tablet', 768, 1024], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.evaluate(() => window.scrollTo(0, 0));
      const metrics = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth,
        title_height: document.querySelector('h1').getBoundingClientRect().height, title_line_height: parseFloat(getComputedStyle(document.querySelector('h1')).lineHeight) }));
      report.viewports.push({ name, width, height, ...metrics });
      if (metrics.document > metrics.viewport + 1 || metrics.title_height > metrics.title_line_height * 2.2) throw new Error(`${name} layout overflow or title wrapping`);
      await settleVisibleCovers(name);
      await page.screenshot({ path: resolve(out, `${name}-results.png`), fullPage: false });
    }
    const corePoints = (view.points || []).filter(point => {
      const unit = view.version.analysis.knowledge_points.find(unit => unit.id === point.project_knowledge_point_id);
      return /pygame/i.test(unit?.technology || unit?.name || '') && ((point.result?.items?.length || 0) + (point.result?.partial_items?.length || 0) > 0);
    }).sort((left, right) => (right.result?.items?.length || 0) - (left.result?.items?.length || 0));
    const focusUnit = option('--focus-unit') || (args.includes('--focus-first-core') ? corePoints[0]?.name : undefined);
    if (focusUnit) {
      report.focused_unit = focusUnit;
      for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
        await page.setViewportSize({ width, height });
        await page.getByRole('button', { name: focusUnit, exact: true }).click();
        await page.evaluate(() => window.scrollTo(0, 0));
        await settleVisibleCovers(`${name}-focused`);
        await page.screenshot({ path: resolve(out, `${name}-focused-results.png`), fullPage: false });
      }
    }
    const before = view.version.batches.map(batch => batch.job_id);
    await page.getByRole('button', { name: /调整知识点/ }).click();
    await page.getByRole('heading', { name: `确认知识点 · v${view.version.version}`, exact: true }).waitFor();
    await page.getByRole('button', { name: /03 推荐视频/ }).click();
    const after = await read(projectPath);
    if (JSON.stringify(before) !== JSON.stringify(after.version.batches.map(batch => batch.job_id))) throw new Error('Navigation unexpectedly created another search');
    report.steps.push('back/review/return preserves selected units and existing jobs');
    if (!report.visible_cards) throw new Error('No real recommendation cards available; workflow reached an honest empty state');
  }
  if (report.errors.length) throw new Error('Browser runtime errors observed');
  if (report.console.some(message => /violates.*content security policy|content security policy.*violat/i.test(message))) throw new Error('Browser content-security policy violation observed');
  report.verdict = view.version.confirmation ? 'real_ui_workflow_passed_content_quality_evaluated_separately' : 'analysis_view_passed_search_not_requested';
} catch (error) {
  report.verdict = 'failed'; report.failure = error.message;
  try { await page.screenshot({ path: resolve(out, 'failure-state.png'), fullPage: false }); } catch { /* The structured failure remains available if the page disconnected. */ }
  console.error(error.message); process.exitCode = 1;
}
finally { report.finished_at = new Date().toISOString(); await checkpoint(); await browser.close(); }
