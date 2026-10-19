# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project-coverage.spec.ts >> phase2 TWT DOM v2：结构旗标、版本降级、标题或摘要破坏不能替代真实自身绑定
- Location: tests\project-coverage.spec.ts:382:1

# Error details

```
Error: ENOENT: no such file or directory, open 'C:\Users\xiaoer\Documents\Codex\2026-10-18\task-2\tmp\phase3-topic-pointers\tests\fixtures\techwithtim\basic-movement-key-presses.html'
```

```
TypeError: Cannot read properties of undefined (reading 'runtime')
```

# Test source

```ts
  1   | import { test, expect, type Page } from '@playwright/test';
  2   | import { mkdir, writeFile } from 'node:fs/promises';
  3   | import { resolve } from 'node:path';
  4   | import { readFileSync } from 'node:fs';
  5   | import { createHash } from 'node:crypto';
  6   | import type { Capabilities, CollectionCoverage, ResourceItem, ResultGroup } from '../src/types';
  7   | import type { ProjectAnalysis, ProjectView } from '../src/projectTypes';
  8   | 
  9   | // Phase 2: isolated UI transport fixtures. These are not live video discovery,
  10  | // instructional-quality, source-availability or project-completion evidence.
  11  | const root = resolve(process.cwd(), process.env.QA_EVIDENCE_ROOT || '../evidence/browser/phase2');
  12  | const sourceRoot = resolve(process.cwd(), process.env.QA_SOURCE_ROOT || '..');
  13  | const time = '2026-10-18T16:00:00Z';
  14  | const name = 'pandas 读取成绩、统计并导出';
  15  | const skills = [{ id: 'read', text: '读取 Excel 成绩表' }, { id: 'mean', text: '按班级统计均值' }, { id: 'export', text: '导出统计结果' }];
  16  | const input = { name: '成绩分析工具', requirements: '读取成绩表，按班级统计均值并导出结果。', student_level: 'beginner' as const, language: 'zh' as const,
  17  |   project_context: '', technical_version: 'Python 3 / pandas', preferred_platforms: ['bilibili' as const] };
  18  | const caps: Capabilities = { mode: 'live', search: { status: 'configured', message: '隔离测试', selected_provider: 'fixture', providers: [] },
  19  |   llm: { status: 'configured', message: '隔离测试' }, fetch: { status: 'available', message: '隔离测试', browser_fallback: false }, platforms: [],
  20  |   limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 30, max_detail_pages: 40 } };
  21  | const analysis: ProjectAnalysis = { scope: '本地成绩分析工具', technical_plan: 'Python / pandas', assumptions: ['Excel 来自本地'],
  22  |   functions: [{ id: 'f1', name: '成绩统计与导出', original_requirement: input.requirements, acceptance_criteria: '统计结果可导出', no_new_learning_reason: null }],
  23  |   knowledge_points: [{ id: 'unit-1', name, description: '把成绩表转为按班级汇总的统计结果', function_ids: ['f1'], why_needed: '完成统计和导出',
  24  |     learning_goal: '读取 Excel，按班级统计均值，并导出新的统计表', necessity: 'required', prerequisite_ids: [], learning_order: 1, selection: 'learn',
  25  |     concepts: skills.map(skill => skill.text), practice_check: '换一份成绩表，独立生成按班级汇总的 Excel 文件。', technology: 'Python / pandas' }] };
  26  | function course(id: string, skill: string, kind: 'page' | 'catalog' | 'search' = 'page', platform = 'bilibili'): ResourceItem {
  27  |   const text = skills.find(row => row.id === skill)!.text;
  28  |   const url = `https://example.org/fixture/${id}`;
  29  |   const eid = `evidence-${id}`;
  30  |   const description = `本视频用 pandas 演示${text}，并以成绩表进行练习。`;
  31  |   const chapter = { title: `pandas ${text}`, evidence_id: eid };
  32  |   return {
  33  |     resource: { resource_id: id, title: `隔离视频：${text}`, url, canonical_url: url, platform, resource_type: 'video', author: null,
  34  |       description: kind === 'page' ? description : null, language: null, duration_seconds: null, published_at: null, discovered_at: time,
  35  |       fetched_at: kind === 'search' ? null : time, fetch_status: kind === 'search' ? 'search_only_policy' : 'fetched', metadata_evidence_level: kind,
  36  |       requires_login: null, requires_payment: null, requires_enrollment: null, chapters: kind === 'catalog' ? [chapter] : [],
  37  |       field_provenance: kind === 'page' ? { description: { evidence_id: eid, source: 'fixture.description', url } } : {}, playback_verified: false },
  38  |     match: { knowledge_point_id: 'job-point-1', resource_id: id, ranking_score: 0.8,
  39  |       recommendation_reason: '仅有这一子技能的内容线索；视频/授课语言尚未由来源元数据确认。', matched_evidence_ids: [eid], coverage_basis: [kind],
  40  |       topic_evidence_status: 'partial', supporting_evidence_ids: [eid], subtopic_coverage: skills.map(row => ({ ...row,
  41  |         status: row.id === skill ? 'supported' : 'unknown', evidence_ids: row.id === skill ? [eid] : [], reason: row.id === skill ? '隔离来源自身记录' : '未确认' })) },
  42  |     evidence: [{ evidence_id: eid, kind, source: kind === 'page' ? 'fixture.description' : kind === 'catalog' ? 'fixture.catalog' : 'fixture.search', url,
  43  |       ...(kind === 'search' ? { title: `pandas ${text}`, snippet: description, observed_at: time }
  44  |         : { field: kind === 'page' ? 'description' : 'chapters.0', text: kind === 'page' ? description : JSON.stringify({ title: chapter.title, url: null, start_seconds: null, end_seconds: null, duration_seconds: null }), fetched_at: time }) }],
  45  |   };
  46  | }
  47  | function fixtureGroup(): ResultGroup {
  48  |   const read = course('read-video', 'read');
  49  |   const mean = course('mean-video', 'mean', 'catalog', 'other');
  50  |   const snippet = course('snippet-only', 'export', 'search');
  51  |   const review = course('review-only', 'export'); review.match.topic_evidence_status = 'needs_review';
  52  |   const coverage: CollectionCoverage = { decomposition_status: 'applied', shared_context: ['pandas'], status: 'all_subtopics_supported',
  53  |     subtopics: skills.map(skill => ({ ...skill, status: 'supported', resource_ids: ['invented-aggregate-resource'], evidence_ids: ['invented-aggregate-evidence'] })),
  54  |     single_resource_full_coverage: true, disclaimer: '故意过度宣称的服务端汇总；客户端必须根据当前可见资源重新推导。' };
  55  |   return { knowledge_point_id: 'job-point-1', text: name, total_matches: 0, items: [], section_limit: 5,
  56  |     partial_items: [read, mean, snippet], partial_platform_items: { bilibili: [read, snippet], other: [mean] }, review_items: [review], review_platform_items: { bilibili: [review] },
  57  |     collection_coverage: coverage, platform_collection_coverage: { bilibili: structuredClone(coverage), other: structuredClone(coverage) } };
  58  | }
  59  | type Logs = { runtime: string[]; console: string[]; unexpected: string[] };
  60  | const diagnostics = new WeakMap<Page, Logs>();
  61  | test.afterEach(async ({ page }, info) => {
  62  |   const log = diagnostics.get(page)!;
  63  |   await info.attach('phase2-browser-diagnostics', { body: JSON.stringify(log, null, 2), contentType: 'application/json' });
> 64  |   expect(log.runtime).toEqual([]); expect(log.console).toEqual([]); expect(log.unexpected).toEqual([]);
      |              ^ TypeError: Cannot read properties of undefined (reading 'runtime')
  65  | });
  66  | async function setup(page: Page, groups: Map<number, ResultGroup | null>, status = 'completed', document = analysis, projectInput = input, pointState?: { current: string }, mockImageUrls: string[] = []) {
  67  |   const log: Logs = { runtime: [], console: [], unexpected: [] }; diagnostics.set(page, log);
  68  |   page.on('pageerror', error => log.runtime.push(error.message));
  69  |   page.on('console', message => { if (['warning', 'error'].includes(message.type())) log.console.push(message.text()); });
  70  |   const current = Math.max(...groups.keys());
  71  |   await page.route('**/*', route => {
  72  |     const request = route.request(); const url = new URL(request.url());
  73  |     const origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
  74  |     if (url.origin === origin && !url.pathname.startsWith('/api/')) return route.continue();
  75  |     if (request.method() === 'GET' && url.pathname === '/api/capabilities') return route.fulfill({ json: caps });
  76  |     if (request.method() === 'GET' && url.pathname === '/api/projects') return route.fulfill({ json: { projects: [{ project_id: 'coverage-project', name: projectInput.name, current_version: current, created_at: time, updated_at: time }] } });
  77  |     if (request.method() === 'GET' && url.pathname === '/api/projects/coverage-project/results') {
  78  |       const selected = Number(url.searchParams.get('version')) || current; const result = groups.get(selected);
  79  |       const view: ProjectView = { project_id: 'coverage-project', input: projectInput, current_version: current,
  80  |         versions: [...groups.keys()].map(version => ({ version, status, created_at: time })),
  81  |         version: { version: selected, status, input: projectInput, analysis: document, confirmation: { version: selected, confirmed_at: time },
  82  |           batches: [{ batch_id: `batch-${selected}`, status, project_knowledge_point_ids: [document.knowledge_points[0].id], job_id: `job-${selected}` }], error: null, created_at: time },
  83  |         points: [{ project_knowledge_point_id: document.knowledge_points[0].id, name: document.knowledge_points[0].name, selection: 'learn', status: pointState?.current ?? (status === 'running' ? 'running' : result?.items.length ? 'completed' : result?.partial_items?.length || result?.review_items?.length ? 'partial' : 'no_results'),
  84  |           batch_id: `batch-${selected}`, job_id: `job-${selected}`, knowledge_point_id: result?.knowledge_point_id || null, result: result || null }] };
  85  |       return route.fulfill({ json: view });
  86  |     }
  87  |     if (request.resourceType() === 'image' && mockImageUrls.includes(url.href)) return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jrZkAAAAASUVORK5CYII=', 'base64') });
  88  |     log.unexpected.push(`${request.method()} ${url.href}`); return route.abort('blockedbyclient');
  89  |   });
  90  |   await page.goto(`/?project=coverage-project&version=${current}`);
  91  |   await expect(page).toHaveTitle('项目制知识引导小精灵 · 课程与视频发现');
  92  |   await expect(page.getByRole('heading', { name: `项目课程结果 · v${current}` })).toBeVisible();
  93  |   await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  94  |   await openLegacy(page);
  95  |   return log;
  96  | }
  97  | // Phase 3 keeps the exact old evidence contract inside an explicit disclosure.
  98  | // These regression cases inspect that retained contract; the new primary skill
  99  | // and practice axes are independently exercised in learning-support.spec.ts.
  100 | async function openLegacy(page: Page) {
  101 |   for (const disclosure of await page.locator('.legacy-requirements').all()) {
  102 |     if (!await disclosure.evaluate(element => (element as HTMLDetailsElement).open)) await disclosure.locator(':scope>summary').click();
  103 |   }
  104 | }
  105 | const routeSummary = (page: Page) => page.locator('.unit-coverage');
  106 | const primaryNext = (page: Page) => page.locator('.learning-route-next');
  107 | 
  108 | test('phase2 API 使用核心：真实来源离线回放保留部分材料，原学习目标仍为 0/8', async ({ page }) => {
  109 |   const fixturePath = 'tests/fixtures/api-operation-core-coverage.json';
  110 |   const bytes = readFileSync(resolve(process.cwd(), fixturePath));
  111 |   const digest = createHash('sha256').update(bytes).digest('hex');
  112 |   expect(digest).toBe('d2601f82c5ea044298e19a131d91db4847c6f43f0f7b20c12a0875288bcb00ab');
  113 |   const fixture = JSON.parse(bytes.toString('utf8')) as {
  114 |     planned: ProjectAnalysis['knowledge_points'][number]; result_group: ResultGroup;
  115 |     network_requests: number; model_calls: number; database_reads: number; database_writes: number;
  116 |     fresh_search: boolean; production_response: boolean; producer: Record<string, string>;
  117 |   };
  118 |   expect([fixture.network_requests, fixture.model_calls, fixture.database_reads, fixture.database_writes]).toEqual([0, 0, 0, 0]);
  119 |   expect(fixture.fresh_search).toBe(false); expect(fixture.production_response).toBe(false);
  120 |   const group = fixture.result_group, parts = group.collection_coverage!.subtopics;
  121 |   expect(group.items).toHaveLength(0); expect(group.partial_items).toHaveLength(1); expect(group.review_items).toHaveLength(0);
  122 |   expect(parts).toHaveLength(8); expect(parts.every(part => part.status === 'unknown' && !part.resource_ids.length && !part.evidence_ids.length)).toBe(true);
  123 |   expect(parts.filter(part => part.id.startsWith('learning_target_')).map(part => part.text)).toEqual(fixture.planned.concepts);
  124 |   const item = group.partial_items![0];
  125 |   expect(item.match.subtopic_coverage!.filter(part => part.status === 'supported').map(part => part.id)).toEqual(['api_operation_core_1']);
  126 |   expect(parts.some(part => part.id === 'api_operation_core_1')).toBe(false);
  127 |   const document = structuredClone(analysis);
  128 |   document.knowledge_points = [fixture.planned];
  129 |   document.functions = [{ id: 'f2', name: '时间数据清洗', original_requirement: fixture.planned.description,
  130 |     acceptance_criteria: fixture.planned.practice_check!, no_new_learning_reason: null }];
  131 |   const mockImageUrl = item.resource.thumbnail_url!.replace(/^http:/, 'https:');
  132 |   await page.emulateMedia({ reducedMotion: 'reduce' });
  133 |   await setup(page, new Map([[1, group]]), 'partial', document, input, undefined, [mockImageUrl]);
  134 |   const summary = page.locator('.unit-coverage');
  135 |   const card = page.locator('.resource-card');
  136 |   await expect(card).toHaveCount(1);
  137 |   await expect(card).toContainText('Python pandas.to_datetime函数方法的使用');
  138 |   await expect(card).toContainText('部分匹配');
  139 |   await expect(card).toContainText('pandas.to_datetime API 使用核心（参数未确认）');
  140 |   await expect(card).toContainText('不表示别名或参数等价');
  141 |   for (const text of fixture.planned.concepts!) await expect(card).toContainText(text);
  142 |   await expect(summary).toContainText('0 / 8 项有内容依据');
  143 |   await expect(summary.locator('.unit-coverage-supported li')).toHaveCount(0);
  144 |   await expect(summary.locator('.unit-coverage-supported p')).toHaveText('这些原项目要求尚无足够的本课正文或目录依据；请结合主路线区分补学与实践。');
  145 |   await expect(summary).not.toContainText('当前视频尚无足够的正文或目录依据');
  146 |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText(parts.map(part => part.text));
  147 |   for (const [index, part] of parts.entries()) await expect(summary.locator('.unit-coverage-missing li').nth(index)).toHaveAttribute('data-requirement-ids', JSON.stringify([part.id]));
  148 |   await expect(summary.locator('.unit-coverage-missing')).not.toContainText('API 使用核心');
  149 |   await expect(summary.locator('.unit-coverage-next')).toContainText('参数教学仍需证据，项目应用则需要自己实践');
  150 |   await expect(primaryNext(page)).toContainText('先到原平台核对教学范围');
  151 |   await expect(summary.getByRole('link')).toHaveCount(0);
  152 |   await expect(summary.locator('.unit-coverage-practice span')).toHaveText(fixture.planned.practice_check!);
  153 |   await expect(summary).toContainText('不代表已完成项目实践');
  154 |   await mkdir(resolve(root, 'screenshots'), { recursive: true }); const observations = [];
  155 |   for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'tablet', width: 768, height: 1024 }, { name: 'mobile', width: 390, height: 844 }]) {
  156 |     await page.setViewportSize({ width: viewport.width, height: viewport.height });
  157 |     const overflow = await page.evaluate(() => globalThis.document.documentElement.scrollWidth > innerWidth); expect(overflow).toBe(false);
  158 |     const colors = await contrast(page); expect(colors.every(row => row.ratio >= 4.5), JSON.stringify(colors)).toBe(true);
  159 |     expect(colors.some(row => row.text === '这些原项目要求尚无足够的本课正文或目录依据；请结合主路线区分补学与实践。')).toBe(true);
  160 |     await page.screenshot({ path: resolve(root, `screenshots/api-core-${viewport.name}.png`), fullPage: true, animations: 'disabled' });
  161 |     observations.push({ viewport, overflow, colors });
  162 |   }
  163 |   await writeFile(resolve(root, 'api-core-observations.json'), JSON.stringify({ mock: true, source: 'Actual retained source -> offline JobService.results replay; API and exact thumbnail request fulfilled locally; no live requests or instructional-completion claim', fixture: fixturePath, fixtureSha256: digest, producer: fixture.producer, denominator: parts, partialMaterialCount: 1, originalSupportedTargets: 0, observations }, null, 2));
  164 | });
```