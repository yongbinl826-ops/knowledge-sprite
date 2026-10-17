import { test, expect, type Page } from '@playwright/test';
import type { Capabilities, Chapter, Evidence, SearchJob, SearchResults, ResourceItem } from '../src/types';

// These isolated transport fixtures are tests only. The production app has no fixture or demo import.
const time = '2026-10-13T07:00:00Z';
const caps: Capabilities = {
  mode: 'live', search: { selected_provider: 'searxng', status: 'configured', message: '已配置，待验证', providers: [{ name: 'searxng', status: 'configured', message: '参数已配置' }] },
  llm: { status: 'unconfigured', message: '使用规则查询与规则排序' }, fetch: { status: 'available', message: '仅采集允许访问的公开页面', browser_fallback: false },
  platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 30, max_detail_pages: 40 },
};
const baseJob: SearchJob = {
  job_id: 'test-job', status: 'completed', phase: 'done', created_at: time, updated_at: time,
  request: { knowledge_points: ['非预设知识点：空间哈希', '边界条件'], student_level: 'beginner', language: 'zh', technical_version: '', project_context: '', preferred_platforms: ['bilibili'] },
  progress: { queries_planned: 4, queries_completed: 4, search_requests: 4, search_successes: 4, search_failures: 0, candidates_discovered: 2, resources_discovered: 2, details_attempted: 2, details_completed: 1, cache_hits: 1 },
  budgets: { max_search_requests: 30, max_detail_pages: 40, deadline_seconds: 180 }, warnings: [], errors: [],
  knowledge_points: [{ knowledge_point_id: 'kp1', text: '非预设知识点：空间哈希' }, { knowledge_point_id: 'kp2', text: '边界条件' }],
};
const item: ResourceItem = {
  resource: { resource_id: 'r1', title: '测试响应：空间哈希 <img src=x onerror=alert(1)>', url: 'https://www.bilibili.com/video/BV_TEST_ONLY?p=2', canonical_url: 'https://www.bilibili.com/video/BV_TEST_ONLY?p=2', platform: 'bilibili', resource_type: 'video', author: null, description: null, language: null, duration_seconds: null, published_at: null, discovered_at: time, fetched_at: null, fetch_status: 'robots_blocked', metadata_evidence_level: 'search', requires_login: null, requires_payment: null, requires_enrollment: null, chapters: [], field_provenance: { title: { evidence_id: 'e1', source: 'search' } }, cache: { hit: true, cached_at: time, stale: true }, playback_verified: false },
  match: { knowledge_point_id: 'kp1', resource_id: 'r1', ranking_score: 0.73, recommendation_reason: '根据标题与摘要匹配，可能涉及空间哈希。', matched_evidence_ids: ['e1'], coverage_basis: ['title', 'snippet'] },
  evidence: [{ evidence_id: 'e1', kind: 'search', source: 'searxng', query: '空间哈希 教程', url: 'https://www.bilibili.com/video/BV_TEST_ONLY?p=2', snippet: '测试摘要，仅用于自动化测试。', observed_at: time }],
};
const otherItem: ResourceItem = { ...item, resource: { ...item.resource, resource_id: 'r2', title: '测试响应：公开教程页面', url: 'https://example.org/tutorial?chapter=2', platform: 'other', fetch_status: 'fetched', metadata_evidence_level: 'page', fetched_at: time, cache: { hit: false, cached_at: null, stale: false } }, match: { ...item.match, resource_id: 'r2' } };
const results: SearchResults = {
  job_id: 'test-job', status: 'completed', warnings: [],
  groups: [{ knowledge_point_id: 'kp1', text: '非预设知识点：空间哈希', total_matches: 2, items: [item, otherItem] }, { knowledge_point_id: 'kp2', text: '边界条件', total_matches: 1, items: [item] }],
  search_attempts: [{ knowledge_point_id: 'kp1', query: '空间哈希 教程', provider: 'searxng', status: 'success', candidate_count: 2, cached_at: null, cache_hit: false, stale: false }],
};
const diagnostics = new WeakMap<Page, { runtime: string[]; console: string[]; blocked: string[] }>();
const uiOrigin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
test.beforeEach(async ({ page }) => {
  const log = { runtime: [] as string[], console: [] as string[], blocked: [] as string[] };
  diagnostics.set(page, log);
  page.on('pageerror', error => log.runtime.push(error.message));
  page.on('console', message => { if (['warning', 'error'].includes(message.type())) log.console.push(message.text()); });
  // Default deny every API and external HTTP request. Specific fixtures added
  // later override this route, so no test can fall through to the real backend.
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === uiOrigin && !url.pathname.startsWith('/api/')) return route.continue();
    log.blocked.push(url.href);
    return route.abort('blockedbyclient');
  });
});
test.afterEach(async ({ page }, testInfo) => {
  const log = diagnostics.get(page)!;
  await testInfo.attach('browser-diagnostics', { body: JSON.stringify(log, null, 2), contentType: 'application/json' });
  expect(log.runtime).toEqual([]);
  expect(log.blocked).toEqual([]);
});
async function setup(page: Page, capability = caps, job = baseJob, resourceResults = results) {
  await page.route('**/api/capabilities', route => route.fulfill({ json: capability }));
  await page.route('**/api/search-jobs', route => route.fulfill({ status: 202, json: { job_id: 'test-job', status: 'queued' } }));
  await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: job }));
  await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: resourceResults }));
}

function chapterEvidence(chapter: Chapter, index: number): Evidence {
  return { evidence_id: chapter.evidence_id || `fixture-chapter-${index}`, kind: 'catalog', field: `chapters.${index}`,
    source: 'fixture.explicit_chapter', url: 'https://example.org/course', fetched_at: time,
    text: JSON.stringify(Object.fromEntries(['title', 'url', 'start_seconds', 'end_seconds', 'duration_seconds'].map(key => [key, chapter[key as keyof Chapter] ?? null]))) };
}

test('平台筛选能显示全平台前五名之外的课程', async ({ page }) => {
  const mooc: ResourceItem = { ...item, resource: { ...item.resource, resource_id: 'fixture-mooc', title: '测试：第六名 MOOC 课程', url: 'https://www.icourse163.org/course/TEST-123456', platform: 'icourse163', resource_type: 'course' } };
  const topFive = Array.from({ length: 5 }, (_, i) => ({ ...item, resource: { ...item.resource, resource_id: `fixture-${i}` } }));
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], total_matches: 6, items: topFive, platform_items: { bilibili: topFive, icourse163: [mooc] } }] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.resource-card')).toHaveCount(5);
  await expect(page.getByRole('heading', { name: '测试：第六名 MOOC 课程', exact: true })).toHaveCount(0);
  await page.getByLabel('来源平台').selectOption('icourse163');
  await expect(page.locator('.resource-card')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: '测试：第六名 MOOC 课程', exact: true })).toBeVisible();
  await page.getByLabel('来源平台').selectOption('all');
  await expect(page.locator('.resource-card')).toHaveCount(5);
});

test('未配置状态、必填和知识点预算校验；无假结果', async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on('pageerror', error => consoleErrors.push(error.message));
  await setup(page, { ...caps, search: { ...caps.search, status: 'unconfigured', message: '请先在服务端接入 SearXNG，或启用已配置的 Tavily。' } });
  await page.goto('/');
  await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
  await expect(page.getByText('搜索服务暂不可用')).toBeVisible();
  await expect(page.locator('.resource-card')).toHaveCount(0);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('desktop-empty.png'), fullPage: true });
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByRole('alert')).toHaveText('请至少输入一个知识点。');
  await page.getByLabel('知识点', { exact: true }).fill('一\n二\n三\n四\n五\n六');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByRole('alert')).toHaveText('最多输入 5 个知识点，请分批查找。');
  expect(consoleErrors).toEqual([]);
});

test('多知识点提交、分组筛选、简洁占位封面与安全原平台外链', async ({ page }, testInfo) => {
  await setup(page);
  let submitted: unknown;
  await page.route('**/api/search-jobs', async route => { submitted = route.request().postDataJSON(); await route.fulfill({ status: 202, json: { job_id: 'test-job' } }); });
  let pollCount = 0;
  await page.route('**/api/search-jobs/test-job', route => {
    pollCount += 1;
    return route.fulfill({ json: pollCount === 1 ? { ...baseJob, status: 'running', phase: 'searching', progress: { ...baseJob.progress, queries_completed: 1 } } : baseJob });
  });
  await page.goto('/');
  await page.getByLabel('知识点', { exact: true }).fill('非预设知识点：空间哈希\n边界条件\n边界条件');
  await page.getByText('更多筛选', { exact: true }).click();
  await page.getByLabel('技术版本').fill('WebGL 2');
  await page.getByLabel('项目背景').fill('地图可视化');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByText('正在查找', { exact: true })).toBeVisible();
  await expect(page.locator('.search-progress')).toContainText('1/4');
  await expect(page.getByText('检索完成', { exact: true })).toBeVisible();
  expect(submitted).toMatchObject({ knowledge_points: ['非预设知识点：空间哈希', '边界条件'], technical_version: 'WebGL 2', project_context: '地图可视化' });
  await expect(page.locator('.result-group')).toHaveCount(2);
  await expect(page.locator('.resource-card')).toHaveCount(3);
  await expect(page.locator('.resource-card img')).toHaveCount(0);
  await expect(page.locator('.cover-placeholder')).toHaveCount(3);
  await expect(page.locator('.course-cover').first()).toHaveAttribute('href', 'https://www.bilibili.com/video/BV_TEST_ONLY?p=2');
  await expect(page.locator('.course-cover').first()).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(page.locator('.course-cover').first()).toHaveAttribute('target', '_blank');
  await expect(page.locator('.resource-card').first()).toContainText('内容相关性待确认，可前往原平台查看。');
  await expect(page.locator('.resource-card h4').first()).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.chapter-list, .evidence-details, video, iframe')).toHaveCount(0);
  await page.getByLabel('来源平台').selectOption('other');
  await expect(page.locator('.resource-card')).toHaveCount(1);
  await expect(page.getByText('当前平台下暂无课程，可切换到全部平台。')).toBeVisible();
  await page.getByLabel('来源平台').selectOption('all');
  await expect(page.locator('.resource-card')).toHaveCount(3);
  await page.screenshot({ path: testInfo.outputPath('desktop-fixture-results.png'), fullPage: true });
});

test('正常无结果区别于服务失败', async ({ page }) => {
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], total_matches: 0, items: [] }] });
  await page.goto('/?job=test-job');
  await expect(page.getByText('本次没有找到相关课程，试试调整知识点。')).toBeVisible();
  await expect(page.getByText('本次搜索未能完成，请稍后重试。')).toHaveCount(0);
});

test('全部服务失败不会降级为预设课程', async ({ page }) => {
  await setup(page, caps, { ...baseJob, status: 'failed', errors: [{ code: 'configuration_error', message: '搜索服务未配置' }] }, { ...results, status: 'failed', groups: [{ ...results.groups[0], total_matches: 0, items: [] }], search_attempts: [] });
  await page.goto('/?job=test-job');
  await expect(page.getByText('本次搜索未能完成，请稍后重试。')).toBeVisible();
  await expect(page.getByText('本次没有找到相关课程，试试调整知识点。')).toHaveCount(0);
  await expect(page.locator('.resource-card')).toHaveCount(0);
  await page.getByText('本次查找说明').click();
  await expect(page.locator('.task-records')).toContainText('搜索服务未配置');
});

test('部分失败保留结果、任务中断如实显示', async ({ page }) => {
  await setup(page, caps, { ...baseJob, status: 'partial', warnings: ['详情预算已达到限制'], errors: [{ code: 'search_unavailable', message: '一个搜索请求失败' }] }, { ...results, status: 'partial' });
  await page.goto('/?job=test-job');
  await expect(page.getByText('已找到以下课程，部分来源尚未完成核验。')).toBeVisible();
  await expect(page.locator('.resource-card')).toHaveCount(3);
  await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: 'interrupted' } }));
  await page.reload();
  await expect(page.getByText('查找已中断，可重新提交；已找到的课程仍可查看。')).toBeVisible();
  await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
});

test('移动端无横向溢出，表单可用', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, { ...caps, search: { ...caps.search, status: 'unconfigured', message: '请先在服务端接入 SearXNG，或启用已配置的 Tavily。' } });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '想学的知识，去哪里学？' })).toBeVisible();
  await page.getByLabel('知识点', { exact: true }).fill('任意新知识点');
  await page.getByLabel('学习语言').selectOption('en');
  await expect(page.getByLabel('学习语言')).toHaveValue('en');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('mobile-empty.png'), fullPage: true });
});

test('请求出错明确显示错误', async ({ page }) => {
  await setup(page);
  await page.route('**/api/search-jobs', route => route.fulfill({ status: 503, json: { detail: '当前搜索服务不可用' } }));
  await page.goto('/');
  await page.getByLabel('知识点', { exact: true }).fill('任意新知识点');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByRole('alert')).toContainText('当前搜索服务不可用');
  await expect(page.locator('.resource-card')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
});

test('封面按来源图片展示，加载失败回退；点击入口保留原平台地址', async ({ page }) => {
  const coverUrl = 'https://images.example.org/isolated-cover.png';
  const brokenUrl = 'https://images.example.org/isolated-missing.png';
  const picture: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, title: '隔离封面图片 fixture', thumbnail_url: coverUrl } };
  const broken: ResourceItem = { ...picture, resource: { ...picture.resource, resource_id: 'broken-cover', title: '加载失败封面 fixture', thumbnail_url: brokenUrl } };
  const unsafe: ResourceItem = { ...picture, resource: { ...picture.resource, resource_id: 'unsafe-cover', title: '非法链接 fixture', url: 'javascript:alert(1)', thumbnail_url: 'javascript:alert(1)' } };
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [picture, broken, unsafe] }] });
  // Images are isolated fixture responses, never external network reads.
  await page.route(coverUrl, route => route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64') }));
  await page.route(brokenUrl, route => route.fulfill({ status: 404, body: 'fixture image unavailable' }));
  await page.goto('/?job=test-job');
  const cards = page.locator('.resource-card');
  await expect(cards.nth(0).locator('.course-cover img')).toHaveAttribute('src', coverUrl);
  await expect.poll(() => cards.nth(0).locator('.course-cover img').evaluate(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0)).toBe(true);
  await expect(cards.nth(0).locator('.course-cover img')).toHaveAttribute('referrerpolicy', 'no-referrer');
  await expect(cards.nth(0).locator('.course-cover')).toHaveAttribute('href', picture.resource.url);
  await cards.nth(1).scrollIntoViewIfNeeded();
  await expect(cards.nth(1).locator('.cover-placeholder')).toBeVisible();
  await expect(cards.nth(1).locator('.course-cover img')).toHaveCount(0);
  await expect(cards.nth(2).locator('.cover-placeholder')).toBeVisible();
  await expect(cards.nth(2).locator('a')).toHaveCount(0);
  await expect(page.locator('.chapter-list, .evidence-details, video, iframe')).toHaveCount(0);
});

test('目录仅用于最多两条知识点匹配章节，标题转义且不展示播放器或完整目录', async ({ page }, testInfo) => {
  const chapters: Chapter[] = [
    { title: '第一章：坐标转换', url: 'https://www.bilibili.com/video/BV_TEST_ONLY?p=35', evidence_id: 'c1', start_seconds: 65, duration_seconds: 2743 },
    { title: '坐标转换 <img src=x onerror=alert(1)>', url: null, evidence_id: 'c2' },
    { title: '坐标转换扩展章节', url: null, evidence_id: 'c3' },
    { title: '坐标转换非法直链', url: 'javascript:alert(1)', evidence_id: 'c4' },
    { title: '无关：矩阵乘法', url: null, evidence_id: 'c5' },
    { title: '坐标转换无逐行来源', url: null },
  ];
  const catalogItem: ResourceItem = { ...otherItem,
    resource: { ...otherItem.resource, title: '隔离课程 fixture', resource_type: 'course', metadata_evidence_level: 'catalog', chapters },
    match: { ...otherItem.match, topic_evidence_status: 'supported', supporting_evidence_ids: ['c1'] },
    evidence: chapters.slice(0, 5).map(chapterEvidence) };
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], text: '坐标转换', items: [catalogItem] }] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.learning-location li')).toHaveText(['第一章：坐标转换', '坐标转换 <img src=x onerror=alert(1)>']);
  const chapterLink = page.locator('.learning-location a');
  await expect(chapterLink).toHaveCount(1);
  await expect(chapterLink).toHaveText('第一章：坐标转换');
  await expect(chapterLink).toHaveAttribute('href', 'https://www.bilibili.com/video/BV_TEST_ONLY?p=35');
  await expect(chapterLink).toHaveAttribute('target', '_blank');
  await expect(chapterLink).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(page.locator('.learning-location li').nth(1).locator('a')).toHaveCount(0);
  await expect(page.locator('.learning-location img, a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.locator('.resource-card')).not.toContainText('坐标转换扩展章节');
  await expect(page.locator('.resource-card')).not.toContainText('矩阵乘法');
  await expect(page.locator('.chapter-list, .evidence-details, video, iframe')).toHaveCount(0);
  await expect(page.locator('.course-cover')).toHaveAttribute('href', catalogItem.resource.url);
  await expect(page.locator('.resource-card h4 a')).toHaveAttribute('href', catalogItem.resource.url);
  await expect(page.locator('.course-cover')).toHaveAttribute('target', '_blank');
  await expect(page.locator('.course-cover')).toHaveAttribute('rel', 'noopener noreferrer');
  await page.screenshot({ path: testInfo.outputPath('matched-chapters-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('matched-chapters-mobile.png'), fullPage: true });
});

test('同课程在不同知识点分组只能展示当前组匹配章节', async ({ page }) => {
  const chapters: Chapter[] = [{ title: 'Python列表', evidence_id: 'list' }, { title: 'Python字典', evidence_id: 'dict' }];
  const course: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, title: 'Python基础', resource_type: 'course', chapters },
    match: { ...otherItem.match, topic_evidence_status: 'supported', supporting_evidence_ids: ['list', 'dict'] }, evidence: chapters.map(chapterEvidence) };
  await setup(page, caps, baseJob, { ...results, groups: [
    { ...results.groups[0], text: 'Python 列表', items: [course] },
    { ...results.groups[1], text: 'Python 字典', items: [{ ...course, match: { ...course.match, knowledge_point_id: 'kp2' } }] },
  ] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.result-group').nth(0).locator('.learning-location li')).toHaveText(['Python列表']);
  await expect(page.locator('.result-group').nth(1).locator('.learning-location li')).toHaveText(['Python字典']);
});

test('目录逐行身份和数值校验拒绝交叉引用、篡改与非法时长', async ({ page }) => {
  const chapters: Chapter[] = [
    { title: '坐标转换有效未知字段章节', evidence_id: 'strict-0', url: null, start_seconds: null, end_seconds: null, duration_seconds: null },
    { title: '坐标转换有效零起点章节', evidence_id: 'strict-1', start_seconds: 0, end_seconds: 0, duration_seconds: 1 },
  ];
  const records = chapters.map(chapterEvidence);
  // Missing and explicit null are equivalent unknowns in either direction.
  records[0].text = JSON.stringify({ title: chapters[0].title });
  const add = (values: Record<string, unknown>) => {
    const index = chapters.length;
    const chapter = { title: `坐标转换不应验证的章节 ${index}`, url: null, evidence_id: `strict-${index}`, ...values } as unknown as Chapter;
    chapters.push(chapter);
    const record = chapterEvidence(chapter, index);
    records.push(record);
    return { chapter, record };
  };
  // Identical facts with another row's ID still cannot certify this index.
  add({ title: chapters[0].title, url: null, start_seconds: null, end_seconds: null, duration_seconds: null }).chapter.evidence_id = chapters[0].evidence_id;
  for (const [field, value] of Object.entries({ title: '篡改后的标题', url: 'https://example.org/tampered', start_seconds: 10, end_seconds: 10, duration_seconds: 10 })) {
    const { chapter } = add({});
    Object.assign(chapter, { [field]: value });
  }
  for (const duration of [true, false, '12', -1, 0, '__INFINITE_SECONDS__']) {
    const { record } = add({ duration_seconds: duration });
    if (duration === '__INFINITE_SECONDS__') record.text = record.text!.replace('"__INFINITE_SECONDS__"', '1e309');
  }
  for (const offsets of [{ start_seconds: true }, { end_seconds: '1' }, { start_seconds: -1 }, { start_seconds: 2, end_seconds: 1 }]) add(offsets);
  add({}).record.field = 'chapters.999';
  add({}).record.text = undefined;
  add({}).record.text = '[]';
  add({}).record.url = 'https://user:secret@example.org/course';
  add({}).record.url = 'javascript:alert(1)';
  add({ url: 'javascript:alert(1)' });
  const catalogItem: ResourceItem = { ...otherItem,
    resource: { ...otherItem.resource, metadata_evidence_level: 'catalog', chapters },
    // Invalid rows get tie-breaking priority so the two-row display cap cannot
    // hide them if row validation accidentally starts accepting their claims.
    match: { ...otherItem.match, topic_evidence_status: 'supported', supporting_evidence_ids: records.slice(2).map(record => record.evidence_id) }, evidence: records };
  const strictResults: SearchResults = { ...results, groups: [{ ...results.groups[0], text: '坐标转换', items: [catalogItem] }] };
  await setup(page, caps, baseJob, strictResults);
  // JSON number overflow is legal JSON but becomes Infinity in the browser.
  const body = JSON.stringify(strictResults).replaceAll('"__INFINITE_SECONDS__"', '1e309');
  await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ contentType: 'application/json', body }));
  await page.goto('/?job=test-job');
  await expect(page.locator('.learning-location li')).toHaveText(['坐标转换有效未知字段章节', '坐标转换有效零起点章节']);
  await expect(page.locator('.learning-location')).not.toContainText('不应验证');
  await expect(page.locator('.chapter-list, .chapter-time, a[href^="javascript:"], a[href*="secret@"]')).toHaveCount(0);
});

test('缺少目录证据保持章节待定位，未知资源不进入课程视频推荐', async ({ page }) => {
  const unverified: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_type: 'course', chapters: [{ title: '空间哈希', url: 'https://example.org/unverified', evidence_id: 'missing' }] },
    match: { ...otherItem.match, topic_evidence_status: 'supported', supporting_evidence_ids: ['e1'] } };
  const unknown: ResourceItem = { ...unverified, resource: { ...unverified.resource, resource_id: 'unknown-type', title: '未知类型 fixture', resource_type: 'unknown' } };
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], text: '空间哈希', items: [unverified, unknown] }] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.resource-card')).toHaveCount(1);
  await expect(page.locator('.learning-location li')).toHaveCount(0);
  await expect(page.locator('.chapter-pending')).toHaveText('具体章节待定位，可前往原平台查看。');
  await expect(page.getByRole('heading', { name: '未知类型 fixture' })).toHaveCount(0);
});

test('推荐区只列课程视频，平台筛选不会把文字资料与未知类型当成课程', async ({ page }) => {
  const textItem: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_type: 'article' } };
  const unknownItem: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_id: 'r3', title: '测试响应：未知类型', resource_type: 'unknown' } };
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [item, textItem, unknownItem] }] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.resource-card')).toHaveCount(1);
  await expect(page.locator('.course-meta')).toContainText('B站');
  await expect(page.getByLabel('资源类型')).toHaveCount(0);
  await page.getByLabel('来源平台').selectOption('other');
  await expect(page.locator('.resource-card')).toHaveCount(0);
  await expect(page.locator('.group-empty')).toHaveText('当前平台下暂无课程，可切换到全部平台。');
  await page.getByLabel('来源平台').selectOption('all');
  await expect(page.locator('.resource-card')).toHaveCount(1);
});

test('采集失败不伪造章节，异常说明折叠保留且搜索候选仍可去原平台', async ({ page }) => {
  const statuses = ['budget_limited', 'site_policy_blocked', 'network_error'];
  const entries = statuses.map((status, index): ResourceItem => ({ ...otherItem,
    resource: { ...otherItem.resource, resource_id: `follow-${index}`, title: `目录跟随 fixture ${index}`, catalog_fetch_status: status },
  }));
  await setup(page, caps, { ...baseJob, status: 'partial', warnings: ['隔离来源目录读取未完成'] }, { ...results, groups: [{ ...results.groups[0], items: entries }] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.resource-card')).toHaveCount(3);
  await expect(page.locator('.learning-location li, .evidence-details, .chapter-list, video, iframe')).toHaveCount(0);
  await expect(page.locator('.match-needs_review')).toHaveCount(3);
  await expect(page.locator('a.course-cover')).toHaveCount(3);
  await expect(page.locator('.task-records')).not.toHaveAttribute('open', '');
  await page.getByText('本次查找说明').click();
  await expect(page.locator('.task-records')).toContainText('隔离来源目录读取未完成');
});

test('取消执行中的任务只发一次请求，保留结果并停止轮询', async ({ page }, testInfo) => {
  await setup(page);
  let cancelled = false, cancels = 0, polls = 0;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/search-jobs/test-job', route => { polls += 1; return route.fulfill({ json: { ...baseJob, status: cancelled ? 'cancelled' : 'running', phase: cancelled ? 'done' : 'searching' } }); });
  await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: { ...results, status: cancelled ? 'cancelled' : 'running' } }));
  await page.route('**/api/search-jobs/test-job/cancel', async route => {
    cancels += 1; expect(route.request().method()).toBe('POST');
    await gate; cancelled = true;
    await route.fulfill({ json: { job_id: 'test-job', status: 'cancelled', cancelled: true } });
  });
  await page.goto('/?job=test-job');
  await expect(page.locator('.resource-card')).toHaveCount(3);
  await page.getByRole('button', { name: '取消', exact: true }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect(page.getByRole('button', { name: '正在取消…' })).toBeDisabled();
  await expect.poll(() => cancels).toBe(1);
  release();
  await expect(page.locator('.job-status')).toHaveText('任务已取消');
  await expect(page.getByText('已取消查找，保留已找到的课程。')).toBeVisible();
  await expect(page.locator('.resource-card')).toHaveCount(3);
  await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
  await expect.poll(() => polls).toBeGreaterThan(1);
  const endedPolls = polls;
  await page.waitForTimeout(1700);
  expect(polls).toBe(endedPolls);
  await page.screenshot({ path: testInfo.outputPath('cancelled-preserved-results.png'), fullPage: true });
});

test('重复提交锁与后端复用原任务提示', async ({ page }) => {
  await setup(page);
  let submissions = 0;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/search-jobs', async route => {
    submissions += 1; await gate;
    await route.fulfill({ status: 202, json: { job_id: 'test-job', status: 'running', reused: true } });
  });
  await page.goto('/');
  await page.getByLabel('知识点', { exact: true }).fill('隔离重复提交测试');
  await page.locator('form').evaluate(form => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await expect.poll(() => submissions).toBe(1);
  await expect(page.getByRole('button', { name: '正在查找…' })).toBeDisabled();
  release();
  await expect(page.getByText('已返回相同需求的原任务，未重复发起搜索。')).toBeVisible();
  await expect(page.locator('.resource-card')).toHaveCount(3);
});

test('创建超时重试沿用幂等key，明确重新检索使用新key', async ({ page }) => {
  await page.clock.install();
  await setup(page);
  const keys: string[] = [];
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/search-jobs', async route => {
    keys.push(route.request().headers()['idempotency-key']);
    if (keys.length === 1) { await gate; await route.abort().catch(() => {}); return; }
    await route.fulfill({ status: 202, json: { job_id: keys.length === 2 ? 'test-job' : 'new-job', status: 'completed', reused: keys.length === 2 } });
  });
  await page.route('**/api/search-jobs/new-job', route => route.fulfill({ json: { ...baseJob, job_id: 'new-job' } }));
  await page.route('**/api/search-jobs/new-job/results', route => route.fulfill({ json: { ...results, job_id: 'new-job' } }));
  await page.goto('/');
  await page.getByLabel('知识点', { exact: true }).fill('隔离创建超时测试');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect.poll(() => keys.length).toBe(1);
  await page.clock.fastForward(15_001);
  await expect(page.getByRole('alert')).toContainText('创建状态尚未确认');
  await expect(page.getByRole('button', { name: '开始查找' })).toBeEnabled();
  release();
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.locator('.job-status')).toHaveText('检索完成');
  expect(keys[0]).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
  expect(keys[1]).toBe(keys[0]);
  await expect(page.getByText('已返回相同需求的原任务，未重复发起搜索。')).toBeVisible();
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page).toHaveURL(/job=new-job/);
  await expect(page.locator('.resource-card')).toHaveCount(3);
  expect(keys[2]).not.toBe(keys[1]);
});

test('取消后新任务不会被迟到的旧轮询覆盖', async ({ page }) => {
  await setup(page);
  let cancelled = false, resultCalls = 0;
  let releaseOld!: () => void;
  const oldGate = new Promise<void>(resolve => { releaseOld = resolve; });
  await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: cancelled ? 'cancelled' : 'running' } }));
  await page.route('**/api/search-jobs/test-job/results', async route => {
    resultCalls += 1;
    if (!cancelled) await oldGate;
    await route.fulfill({ json: { ...results, status: cancelled ? 'cancelled' : 'running' } }).catch(() => {});
  });
  await page.route('**/api/search-jobs/test-job/cancel', route => { cancelled = true; return route.fulfill({ json: { job_id: 'test-job', status: 'cancelled', cancelled: true } }); });
  await page.route('**/api/search-jobs', route => route.fulfill({ status: 202, json: { job_id: 'new-job', status: 'completed', reused: false } }));
  await page.route('**/api/search-jobs/new-job', route => route.fulfill({ json: { ...baseJob, job_id: 'new-job' } }));
  const newResults: SearchResults = { ...results, job_id: 'new-job', groups: [{ ...results.groups[0], items: [{ ...otherItem, resource: { ...otherItem.resource, title: '新任务的唯一结果' } }] }] };
  await page.route('**/api/search-jobs/new-job/results', route => route.fulfill({ json: newResults }));
  await page.goto('/?job=test-job');
  await expect.poll(() => resultCalls).toBeGreaterThanOrEqual(1);
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.locator('.job-status')).toHaveText('任务已取消');
  await page.getByLabel('知识点', { exact: true }).fill('新任务');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByRole('heading', { name: '新任务的唯一结果' })).toBeVisible();
  releaseOld();
  await page.waitForTimeout(100);
  await expect(page.locator('.resource-card')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: '新任务的唯一结果' })).toBeVisible();
  await expect(page).toHaveURL(/job=new-job/);
});

test('轮询任一请求失败会及时取消同轮兄弟请求', async ({ page }) => {
  await page.addInitScript(() => {
    const target = window as typeof window & { __fetchAudit: { url: string; aborted: boolean }[] };
    target.__fetchAudit = [];
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const entry = { url: String(input), aborted: false };
      target.__fetchAudit.push(entry);
      init?.signal?.addEventListener('abort', () => { entry.aborted = true; }, { once: true });
      return nativeFetch(input, init);
    };
  });
  await setup(page);
  let recovered = false;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/search-jobs/test-job', route => {
    return route.fulfill(!recovered ? { status: 503, json: { detail: '隔离轮询故障' } } : { json: baseJob });
  });
  await page.route('**/api/search-jobs/test-job/results', async route => {
    if (!recovered) await gate;
    await route.fulfill({ json: results }).catch(() => {});
  });
  await page.goto('/?job=test-job');
  await expect(page.getByRole('alert')).toContainText('隔离轮询故障');
  await expect.poll(() => page.evaluate(() => {
    const entries = (window as typeof window & { __fetchAudit: { url: string; aborted: boolean }[] }).__fetchAudit.filter(entry => entry.url.endsWith('/results'));
    return entries.length >= 2 && entries.every(entry => entry.aborted);
  })).toBe(true);
  recovered = true; release();
  await expect(page.locator('.job-status')).toHaveText('检索完成');
  await expect(page.locator('.resource-card')).toHaveCount(3);
});

test('取消请求失败保持未确认状态，不假装取消成功', async ({ page }) => {
  await setup(page, caps, { ...baseJob, status: 'running', phase: 'searching' }, { ...results, status: 'running' });
  await page.route('**/api/search-jobs/test-job/cancel', route => route.abort('connectionreset'));
  await page.goto('/?job=test-job');
  await expect(page.locator('.job-status')).toHaveText('正在查找');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('取消状态尚未确认');
  await expect(page.locator('.job-status')).toHaveText('正在查找');
  await expect(page.getByText('已取消查找，保留已找到的课程。')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '取消', exact: true })).toBeEnabled();
});

test('任务已自然结束时取消返回原终态，不覆盖为cancelled', async ({ page }) => {
  await setup(page);
  let completed = false;
  await page.route('**/api/search-jobs/test-job', route => route.fulfill({ json: { ...baseJob, status: completed ? 'completed' : 'running' } }));
  await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: { ...results, status: completed ? 'completed' : 'running' } }));
  await page.route('**/api/search-jobs/test-job/cancel', route => { completed = true; return route.fulfill({ json: { job_id: 'test-job', status: 'completed', cancelled: false } }); });
  await page.goto('/?job=test-job');
  await expect(page.locator('.job-status')).toHaveText('正在查找');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.locator('.job-status')).toHaveText('检索完成');
  await expect(page.getByText('任务已结束，已保留原任务状态。')).toBeVisible();
  await expect(page.getByText('已取消查找，保留已找到的课程。')).toHaveCount(0);
});

test('来源说明折叠保留平台条款，不展示内部采集配置或宣称播放已验证', async ({ page }, testInfo) => {
  const capability: Capabilities = { ...caps, platforms: [
    { id: 'bilibili', name: 'B站', discovery: 'search', metadata: 'site_policy_blocked', playback: 'unknown', source_url: 'https://example.org/terms', reviewed_at: time,
      policy_basis: '隔离条款 fixture：自动工具读取范围受限。', policy_section: '5.6(3)' },
    { id: 'icourse163', name: '中国大学 MOOC', discovery: 'search', metadata: 'public_course_metadata_only', playback: 'unknown',
      policy_basis: '隔离范围 fixture：仅匿名读取公开课程页。' },
  ] };
  await setup(page, capability);
  await page.goto('/?job=test-job');
  await expect(page.locator('.capabilities-footer details')).not.toHaveAttribute('open', '');
  await page.getByText('来源与访问说明', { exact: true }).click();
  await expect(page.locator('.platform-capabilities section').first()).toContainText('隔离条款 fixture：自动工具读取范围受限。');
  await expect(page.locator('.platform-capabilities section').nth(1)).toContainText('隔离范围 fixture：仅匿名读取公开课程页。');
  const terms = page.getByRole('link', { name: '查看平台条款（5.6(3)）' });
  await expect(terms).toHaveAttribute('href', 'https://example.org/terms');
  await expect(terms).toHaveAttribute('target', '_blank');
  await expect(terms).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(page.locator('.capabilities-detail')).toContainText('点击封面前往原平台');
  await expect(page.locator('.capabilities-detail')).not.toContainText('浏览器无法访问');
  await expect(page.locator('.capabilities-detail')).not.toContainText('已验证播放');
  await expect(page.locator('.capabilities-detail')).not.toContainText('DoH');
  await page.screenshot({ path: testInfo.outputPath('compact-source-notice.png'), fullPage: true });
});

test('取得的目录证据可参与章节定位，内部渲染诊断不进入课程卡片', async ({ page }) => {
  const source = 'html.microsoft_ai.curriculum_table';
  const url = 'https://microsoft.github.io/AI-For-Beginners/';
  const acquisition = { acquisition: 'offline_rendered_dom', render_id: 'render-fixture', dom_sha256: 'a'.repeat(64) };
  const chapters: Chapter[] = [{ title: 'Fixture chapter A', evidence_id: 'render-chapter-0' }, { title: 'Fixture chapter B', evidence_id: 'render-chapter-1' }];
  const dynamic: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_id: 'render-gain', title: '动态课程 fixture', url,
    resource_type: 'course', metadata_evidence_level: 'catalog', chapters,
    render_diagnostics: { ...acquisition, status: 'rendered', source_url: url, static_chapter_count: 0, rendered_chapter_count: 2, added_fields: ['chapters'] } },
    match: { ...otherItem.match, topic_evidence_status: 'supported', supporting_evidence_ids: ['render-chapter-0'] },
    evidence: chapters.map((chapter, index) => ({ ...chapterEvidence(chapter, index), ...acquisition, url, source })) };
  const timeout: ResourceItem = { ...otherItem, resource: { ...otherItem.resource, resource_id: 'render-timeout', title: '动态超时 fixture',
    render_diagnostics: { status: 'render_timeout', static_chapter_count: 0, dom_sha256: '<img src=x onerror=alert(1)>' } } };
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], text: 'Fixture chapter', items: [dynamic, timeout] }] });
  await page.goto('/?job=test-job');
  await expect(page.locator('[data-resource-id="render-gain"] .learning-location li')).toHaveText(['Fixture chapter A', 'Fixture chapter B']);
  await expect(page.locator('[data-resource-id="render-timeout"] .learning-location li')).toHaveCount(0);
  await expect(page.locator('.render-diagnostics, .identity-details, .identity-summary, .chapter-list, .evidence-details, video, iframe')).toHaveCount(0);
  await expect(page.locator('.resource-card img')).toHaveCount(0);
});

test('创建响应丢失后刷新可按原幂等key恢复已结束任务，确认后清除tab存储', async ({ page }, testInfo) => {
  await setup(page);
  const requests: { key: string | undefined; body: unknown }[] = [];
  await page.route('**/api/search-jobs', async route => {
    requests.push({ key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON() });
    if (requests.length === 1) return route.abort('connectionreset');
    return route.fulfill({ status: 202, json: { job_id: 'test-job', status: 'completed', reused: true } });
  });
  await page.goto('/');
  await page.getByLabel('知识点', { exact: true }).fill('响应丢失后的原知识点');
  await page.getByLabel('学生基础').selectOption('intermediate');
  await page.getByLabel('学习语言').selectOption('en');
  await page.getByText('更多筛选', { exact: true }).click();
  await page.getByLabel('技术版本').fill('fixture version');
  await page.getByLabel('项目背景').fill('fixture background');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByText(/创建状态尚未确认/)).toBeVisible();
  const beforeReload = await page.evaluate(() => sessionStorage.getItem('knowledge-guide.pending-creation.v1'));
  expect(JSON.parse(beforeReload!).key).toBe(requests[0].key);
  await page.reload();
  const recovery = page.getByRole('region', { name: '未确认提交恢复' });
  await expect(recovery).toContainText('响应丢失后的原知识点');
  expect(requests).toHaveLength(1);
  await recovery.getByText('查看原学习需求').click();
  await expect(recovery).toContainText('fixture version');
  await expect(recovery).toContainText('fixture background');
  await page.screenshot({ path: testInfo.outputPath('submission-recovery-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: '继续上次未确认提交' }).click();
  await expect(page.locator('.job-status')).toHaveText('检索完成');
  await expect(page).toHaveURL(/job=test-job/);
  await expect(page.locator('.resource-card')).toHaveCount(3);
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
  expect(await page.evaluate(() => sessionStorage.getItem('knowledge-guide.pending-creation.v1'))).toBeNull();
  await expect(recovery).toHaveCount(0);
  await page.reload();
  await expect(page.locator('.resource-card')).toHaveCount(3);
  expect(requests).toHaveLength(2);
});

test('刷新后的不同需求不会使用旧幂等key，清除入口不会请求取消', async ({ page }) => {
  await setup(page);
  const keys: (string | undefined)[] = [];
  const bodies: unknown[] = [];
  await page.route('**/api/search-jobs', async route => {
    keys.push(route.request().headers()['idempotency-key']); bodies.push(route.request().postDataJSON());
    if (keys.length < 3) return route.abort('connectionreset');
    return route.fulfill({ status: 202, json: { job_id: 'test-job', status: 'completed' } });
  });
  await page.goto('/');
  await page.getByLabel('知识点', { exact: true }).fill('旧的未确认需求');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByText(/创建状态尚未确认/)).toBeVisible();
  await page.reload();
  await page.getByLabel('知识点', { exact: true }).fill('不同的新需求');
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.getByText(/创建状态尚未确认/)).toBeVisible();
  expect(keys[1]).not.toBe(keys[0]);
  expect(bodies[1]).not.toEqual(bodies[0]);
  await expect(page.getByRole('region', { name: '未确认提交恢复' })).toContainText('不同的新需求');
  await page.getByRole('button', { name: '清除此恢复入口' }).click();
  expect(await page.evaluate(() => sessionStorage.getItem('knowledge-guide.pending-creation.v1'))).toBeNull();
  await expect(page.getByRole('button', { name: '继续上次未确认提交' })).toHaveCount(0);
  await page.getByRole('button', { name: '开始查找' }).click();
  await expect(page.locator('.job-status')).toHaveText('检索完成');
  expect(keys[2]).not.toBe(keys[1]);
});


// v7 topic fixtures are isolated UI inputs, never evidence of live course discovery.
function topicFixture(id: string, title: string, status: 'supported' | 'partial' | 'needs_review', reason: string, platform = 'bilibili'): ResourceItem {
  const evidenceId = `fixture-topic-${id}`;
  const url = `https://example.org/fixture/${id}`;
  return { ...item, resource: { ...item.resource, resource_id: id, title, url, canonical_url: url, platform, cache: undefined },
    match: { ...item.match, resource_id: id, topic_evidence_status: status,
      topic_evidence_reasons: [{ code: `fixture_${id}`, message: reason, evidence_ids: [evidenceId] }],
      supporting_evidence_ids: status === 'needs_review' ? [] : [evidenceId], subtopic_coverage: [] },
    evidence: [{ evidence_id: evidenceId, kind: 'search', source: 'isolated_ui_fixture', url, title, snippet: reason, observed_at: time }] };
}

test('弱证据保留待核标记，平台切换不能把预约或相邻概念提升为推荐', async ({ page }, testInfo) => {
  const strong = topicFixture('clear-topic', '模拟来源：直接主题课程', 'supported', '本条标题与摘要明确支持所请求主题。');
  const weak = [
    topicFixture('live-preview', '模拟来源：预约直播预告', 'needs_review', '仅预约预告，尚无教学内容或回放的证据。'),
    topicFixture('comparison', '模拟来源：比较背景', 'needs_review', '目标概念仅用于比较背景，未证明本条讲解该主题。'),
    topicFixture('concept-confusion', '模拟来源：匿名函数', 'needs_review', '匿名函数与闭包不能等同，当前只有匿名函数依据。'),
    topicFixture('external-list', '模拟来源：泛四元数外链', 'needs_review', '目标仅在外链清单出现，未证明当前资源覆盖。', 'other'),
  ];
  await setup(page, caps, baseJob, { ...results, groups: [{ ...results.groups[0], items: [strong, ...weak], section_limit: 5,
    platform_items: { bilibili: [strong, ...weak.slice(0, 3)], other: [weak[3]] }, review_items: weak,
    review_platform_items: { bilibili: weak.slice(0, 3), other: [weak[3]] } }] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.section-supported .resource-card')).toHaveCount(1);
  await expect(page.locator('.section-needs_review .resource-card')).toHaveCount(4);
  await expect(page.locator('.resource-card')).toHaveCount(5);
  for (const row of weak) {
    const card = page.locator(`[data-resource-id="${row.resource.resource_id}"]`);
    await expect(card).toHaveAttribute('data-topic-status', 'needs_review');
    await expect(card.locator('.match-needs_review')).toHaveText('待核实');
    await expect(card.locator('.chapter-pending')).toContainText('内容相关性待确认');
    await expect(card.locator('.learning-location li')).toHaveCount(0);
  }
  await expect(page.locator('[data-resource-id="clear-topic"]')).toHaveAttribute('data-topic-status', 'supported');
  await expect(page.locator('.topic-support, .topic-reasons, .evidence-details, video, iframe')).toHaveCount(0);
  await page.getByLabel('来源平台').selectOption('other');
  await expect(page.locator('.section-supported .resource-card')).toHaveCount(0);
  await expect(page.locator('.section-needs_review .resource-card')).toHaveCount(1);
  await expect(page.locator('[data-resource-id="external-list"]')).toHaveAttribute('data-topic-status', 'needs_review');
  await page.getByLabel('来源平台').selectOption('bilibili');
  await expect(page.locator('.section-supported .resource-card')).toHaveCount(1);
  await expect(page.locator('.section-needs_review .resource-card')).toHaveCount(3);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('[data-resource-id="live-preview"]').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('v7-isolated-weak-evidence-mobile.png') });
});

function complementaryFixture() {
  const concurrency = topicFixture('concurrency-part', '模拟来源：JavaScript Promise 并发', 'partial', '仅有并发子项依据，错误处理未知。');
  const errors = topicFixture('errors-part', '模拟来源：JavaScript Promise 错误处理课程', 'partial', '仅有错误处理子项依据，并发未知。', 'other');
  errors.resource.resource_type = 'course';
  for (const [row, supported] of [[concurrency, 'concurrency'], [errors, 'errors']] as const) row.match.subtopic_coverage = [
    { id: 'concurrency', text: '并发', status: supported === 'concurrency' ? 'supported' : 'unknown', evidence_ids: supported === 'concurrency' ? row.match.supporting_evidence_ids! : [], reason: supported === 'concurrency' ? '本条摘要明确说明并发组合。' : '本条没有并发依据。' },
    { id: 'errors', text: '错误处理', status: supported === 'errors' ? 'supported' : 'unknown', evidence_ids: supported === 'errors' ? row.match.supporting_evidence_ids! : [], reason: supported === 'errors' ? '本条摘要明确说明错误处理。' : '本条没有错误处理依据。' },
  ];
  const coverage = { decomposition_status: 'applied', shared_context: ['JavaScript', 'Promise'], status: 'all_subtopics_supported',
    subtopics: [{ id: 'concurrency', text: '并发', status: 'supported', resource_ids: ['concurrency-part'], evidence_ids: concurrency.match.supporting_evidence_ids! },
      { id: 'errors', text: '错误处理', status: 'supported', resource_ids: ['errors-part'], evidence_ids: errors.match.supporting_evidence_ids! }],
    // Deliberately overclaims the server aggregate: the UI must derive from visible rows.
    single_resource_full_coverage: true, disclaimer: '模拟集合，不能当作真实教学核验。' } as const;
  const group: SearchResults['groups'][number] = { ...results.groups[0], text: 'JavaScript Promise 并发与错误处理', items: [], total_matches: 0, section_limit: 2,
    partial_items: [concurrency, concurrency, errors], total_partial_matches: 2, partial_platform_items: { bilibili: [concurrency], other: [errors] },
    collection_coverage: { ...coverage, shared_context: [...coverage.shared_context], subtopics: coverage.subtopics.map(part => ({ ...part, resource_ids: [...part.resource_ids] })) } };
  return { concurrency, errors, group };
}

test('复合点候选保留部分匹配，筛选去重限额有效且不展示内部覆盖报表', async ({ page }, testInfo) => {
  const { group } = complementaryFixture();
  await setup(page, caps, baseJob, { ...results, groups: [group] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.section-partial .resource-card')).toHaveCount(2);
  await expect(page.locator('.section-supported .resource-card')).toHaveCount(0);
  for (const card of await page.locator('.section-partial .resource-card').all()) {
    await expect(card.locator('.match-partial')).toHaveText('部分匹配');
    await expect(card).toHaveAttribute('data-topic-status', 'partial');
  }
  await expect(page.locator('.collection-coverage, .subtopic-coverage')).toHaveCount(0);
  await page.getByLabel('来源平台').selectOption('bilibili');
  await expect(page.locator('.section-partial .resource-card')).toHaveCount(1);
  await page.getByLabel('来源平台').selectOption('other');
  await expect(page.locator('.section-partial .resource-card')).toHaveCount(1);
  await expect(page.locator('[data-resource-id="errors-part"]')).toBeVisible();
  await page.getByLabel('来源平台').selectOption('all');
  await expect(page.locator('.section-partial .resource-card')).toHaveCount(2);
  await page.screenshot({ path: testInfo.outputPath('v7-isolated-complementary-coverage.png'), fullPage: true });
  await page.route('**/api/search-jobs/test-job/results', route => route.fulfill({ json: { ...results, groups: [{ ...group, section_limit: 1 }] } }));
  await page.reload();
  await expect(page.locator('.section-partial .resource-card')).toHaveCount(1);
  await expect(page.locator('[data-resource-id="concurrency-part"]')).toBeVisible();
});

test('不借其他资源的证据补足子项，缺少支持记录保持待核且隐藏内部理由', async ({ page }) => {
  const { errors, group } = complementaryFixture();
  errors.match.supporting_evidence_ids = ['not-returned'];
  errors.match.subtopic_coverage![1].evidence_ids = ['fixture-topic-concurrency-part'];
  errors.match.topic_evidence_reasons = [{ code: 'fixture_missing', message: '<img src=x onerror=alert(1)> 缺少属于本条的错误处理记录。', evidence_ids: ['not-returned'] }];
  group.partial_items = [group.partial_items![0], errors];
  await setup(page, caps, baseJob, { ...results, groups: [group] });
  await page.goto('/?job=test-job');
  await expect(page.locator('.section-partial .resource-card')).toHaveCount(1);
  await expect(page.locator('.section-needs_review .resource-card')).toHaveCount(1);
  const card = page.locator('[data-resource-id="errors-part"]');
  await expect(card).toHaveAttribute('data-topic-status', 'needs_review');
  await expect(card.locator('.match-needs_review')).toHaveText('待核实');
  await expect(card.locator('.chapter-pending')).toContainText('内容相关性待确认');
  await expect(card.locator('.learning-location li, .topic-support, img')).toHaveCount(0);
});
