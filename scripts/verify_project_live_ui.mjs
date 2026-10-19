// Real local UI acceptance. No API routing, model mocks, candidate injection or
// previous search IDs are used. This run deliberately records unavailable AI.
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const output = fileURLToPath(new URL('../reports/project-analysis-v1-20261017/live/', import.meta.url));
await mkdir(output, { recursive: true });
const save = (name, value) => writeFile(output + name, JSON.stringify(value, null, 2), 'utf8');
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const context = await browser.newContext({ viewport: { width: 1536, height: 1024 } });
const page = await context.newPage();
const errors = [], warnings = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => {
  if (message.type() === 'error') errors.push(message.text());
  if (message.type() === 'warning') warnings.push(message.text());
});
const origin = process.env.PROJECT_ACCEPTANCE_URL || 'http://127.0.0.1:18117';
try {
  await page.goto(origin);
  await expect(page.getByRole('heading', { name: '想学的知识，去哪里学？' })).toBeVisible();
  const capabilities = await (await context.request.get(origin + '/api/capabilities')).json();
  await save('capabilities.json', capabilities);
  if (capabilities.project_analysis.status !== 'unconfigured') throw new Error('This acceptance script expects unavailable-model configuration; do not silently claim AI success.');
  await page.getByRole('button', { name: '从项目开始', exact: true }).click();
  const original = { name: '  Excel 成绩分析工具  ', requirements: ' 读取本地 Excel 成绩表\n计算各科平均分、最高分和及格率\n绘制各科平均分柱状图\n导出统计表和图表，仅供本机使用，不需要登录或云部署。\n' };
  await page.getByLabel('项目名称', { exact: true }).fill(original.name);
  await page.getByLabel('功能需求', { exact: true }).fill(original.requirements);
  await page.getByRole('button', { name: '保存项目并检查分析配置', exact: true }).click();
  await expect(page.locator('.project-version-label')).toContainText('分析失败');
  const projectId = new URL(page.url()).searchParams.get('project');
  const project = await (await context.request.get(`${origin}/api/projects/${projectId}/results`)).json();
  if (project.original_input.name !== original.name || project.original_input.requirements !== original.requirements) throw new Error('Original project input was changed');
  if (project.version.error.code !== 'unconfigured' || project.version.analysis !== null) throw new Error('Unavailable model was represented as an analysis');
  const forbidden = await context.request.post(`${origin}/api/projects/${projectId}/search`, { data: { version: project.version.version } });
  if (forbidden.status() !== 409) throw new Error('Unconfirmed search was admitted');
  await save('unconfigured-project.json', project);
  await save('unconfirmed-search.json', { status: forbidden.status(), body: await forbidden.json() });
  await page.reload();
  await expect(page.getByLabel('功能需求', { exact: true })).toHaveValue(original.requirements);
  await expect(page.locator('.project-version-label')).toContainText('分析失败');
  await page.screenshot({ path: output + 'project-unconfigured-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  if (overflow) throw new Error('Project mobile viewport overflows');
  await page.screenshot({ path: output + 'project-unconfigured-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1536, height: 1024 });
  await page.getByRole('button', { name: '直接搜索知识点', exact: true }).click();
  await page.getByLabel('知识点', { exact: true }).fill('pandas Excel 文件读取');
  await page.getByRole('button', { name: '开始查找', exact: true }).click();
  await expect(page).toHaveURL(/job=/);
  const jobId = new URL(page.url()).searchParams.get('job');
  await save('submitted.json', { project_id: projectId, job_id: jobId, model_analysis_completed: false,
    manual_search_only: true, knowledge_point: 'pandas Excel 文件读取', fresh_ui_input: true });
  console.log(JSON.stringify({ project_id: projectId, job_id: jobId, phase: 'real_search_submitted' }));
  let job;
  const until = Date.now() + 300_000;
  while (Date.now() < until) {
    job = await (await context.request.get(`${origin}/api/search-jobs/${jobId}`)).json();
    if (!['queued', 'running'].includes(job.status)) break;
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if (['queued', 'running'].includes(job.status)) throw new Error('Live task did not finish within acceptance window');
  const results = await (await context.request.get(`${origin}/api/search-jobs/${jobId}/results`)).json();
  await save('manual-job.json', job);
  await save('manual-results.json', results);
  await page.reload();
  await expect(page.locator('.job-status')).toContainText(job.status === 'partial' ? '部分完成' : job.status === 'completed' ? '检索完成' : job.status === 'failed' ? '检索失败' : '任务');
  await page.screenshot({ path: output + 'manual-results-desktop.png', fullPage: true });
  const cards = await page.locator('.resource-card').count();
  await page.setViewportSize({ width: 390, height: 844 });
  const resultsOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await page.screenshot({ path: output + 'manual-results-mobile.png', fullPage: true });
  const summary = { checked_at: new Date().toISOString(), url: page.url(), title: await page.title(),
    project_id: projectId, job_id: jobId, project_input_exactly_preserved: true, refresh_restores_input: true,
    unconfirmed_search_http: forbidden.status(), real_model_analysis: 'not_run_unconfigured',
    real_project_full_chain: 'not_completed_model_unconfigured', manual_job_status: job.status,
    manual_visible_cards: cards, mobile_overflow: overflow || resultsOverflow,
    page_errors_and_console_errors: errors, console_warnings: warnings, mock_used: false,
    search_requests: job.progress.search_requests, details_attempted: job.progress.details_attempted,
    search_cache_hits: results.search_attempts.filter(item => item.cache_hit).length,
    detail_cache_hits: job.progress.details_cached || 0, framework_overlay: await page.locator('vite-error-overlay').count() };
  await save('ui-verification.json', summary);
  console.log(JSON.stringify(summary));
  if (errors.length || resultsOverflow) throw new Error('UI errors or overflow were observed');
} catch (error) {
  await save('ui-failure.json', { error: String(error), url: page.url(), errors, warnings });
  await page.screenshot({ path: output + 'ui-failure.png', fullPage: true }).catch(() => {});
  throw error;
} finally { await context.close(); await browser.close(); }
