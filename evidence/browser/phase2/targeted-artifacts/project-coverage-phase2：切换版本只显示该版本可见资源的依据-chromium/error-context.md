# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project-coverage.spec.ts >> phase2：切换版本只显示该版本可见资源的依据
- Location: tests\project-coverage.spec.ts:174:1

# Error details

```
Error: expect(page).toHaveTitle(expected) failed

Expected: "项目制知识引导小精灵 — 课程与视频检索"
Received: "项目制知识引导小精灵 · 课程与视频发现"
Timeout:  7000ms

Call log:
  - Expect "toHaveTitle" with timeout 7000ms
    17 × locator resolved to <html lang="zh-CN">…</html>
       - unexpected value "项目制知识引导小精灵 · 课程与视频发现"

```

```yaml
- link "跳转到主要内容":
  - /url: "#stage-title"
- banner:
  - text: 项目制知识引导小精灵
  - navigation "项目学习流程":
    - button "01 项目描述"
    - button "02 选择知识点"
    - button "03 推荐视频"
  - button "我的项目"
- main:
  - complementary:
    - paragraph: 03 / CURATED LEARNING
    - heading "让知识， 走进你的项目。" [level=1]
    - paragraph: 成绩分析工具 从相关的视频与章节开始。
    - button "← 调整知识点"
    - navigation "已选知识点":
      - paragraph: 已选知识点
      - button "全部" [pressed]
      - button "pandas 读取成绩、统计并导出"
  - paragraph: 成绩分析工具 · v2 · 已完成
  - region "项目课程结果 · v2":
    - heading "项目课程结果 · v2" [level=2]: 推荐视频
    - paragraph: 从一个学习单元开始，将学到的内容用在项目里。
    - text: 已完成
    - group: 查看检索进度与预算
    - heading "成绩统计与导出" [level=3]
    - heading "pandas 读取成绩、统计并导出" [level=4]
    - text: 部分完成 · 1 条推荐
    - complementary "pandas 读取成绩、统计并导出的学习路线":
      - heading "本单元学习路线" [level=5]
      - text: 1 / 3 项有内容依据
      - heading "视频可支持" [level=6]
      - list:
        - listitem: 按班级统计均值 1 个当前视频有正文或目录依据
      - heading "仍需补充" [level=6]
      - list:
        - listitem: 读取 Excel 成绩表
        - listitem: 导出统计结果
      - strong: 下一步
      - paragraph: 先学习已有内容依据的部分，再为仍需补充的子技能寻找视频或资料。
      - link "打开首个有依据的视频 ：隔离视频：按班级统计均值（在新窗口打开）":
        - /url: https://example.org/fixture/mean-video
      - paragraph:
        - strong: 项目练习
        - text: 换一份成绩表，独立生成按班级汇总的 Excel 文件。
      - paragraph: 仅依据当前版本、当前平台下展示的视频整理；子技能互补不代表整单元教学完整，也不代表已完成项目实践。
    - region "互补候选 · 部分覆盖":
      - paragraph: 部分匹配 · 可补充学习
      - article:
        - link "前往原平台学习：隔离视频：按班级统计均值":
          - /url: https://example.org/fixture/mean-video
          - text: 来源未提供封面
        - text: 其他网站 部分匹配
        - heading "隔离视频：按班级统计均值" [level=4]:
          - link "隔离视频：按班级统计均值":
            - /url: https://example.org/fixture/mean-video
        - paragraph: 仅有这一子技能的内容线索；视频/授课语言尚未由来源元数据确认。
        - text: 可参考章节
        - list:
          - listitem: pandas 按班级统计均值
        - link "去原平台学习 ：隔离视频：按班级统计均值（在新窗口打开）":
          - /url: https://example.org/fixture/mean-video
    - paragraph: 章节信息来自实际检索证据。课程可能需要登录、选课或付费，以原平台为准。
    - button "重新检索这些知识点"
    - paragraph: 重新检索会创建新版本，上次结果保留；受相同预算与限流约束。
- contentinfo: 让学习，发生在项目里。 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  1   | import { test, expect, type Page } from '@playwright/test';
  2   | import { mkdir, writeFile } from 'node:fs/promises';
  3   | import { resolve } from 'node:path';
  4   | import type { Capabilities, CollectionCoverage, ResourceItem, ResultGroup } from '../src/types';
  5   | import type { ProjectAnalysis, ProjectView } from '../src/projectTypes';
  6   | 
  7   | // Phase 2: isolated UI transport fixtures. These are not live video discovery,
  8   | // instructional-quality, source-availability or project-completion evidence.
  9   | const root = resolve(process.cwd(), process.env.QA_EVIDENCE_ROOT || '../evidence/browser/phase2');
  10  | const time = '2026-10-18T16:00:00Z';
  11  | const name = 'pandas 读取成绩、统计并导出';
  12  | const skills = [{ id: 'read', text: '读取 Excel 成绩表' }, { id: 'mean', text: '按班级统计均值' }, { id: 'export', text: '导出统计结果' }];
  13  | const input = { name: '成绩分析工具', requirements: '读取成绩表，按班级统计均值并导出结果。', student_level: 'beginner' as const, language: 'zh' as const,
  14  |   project_context: '', technical_version: 'Python 3 / pandas', preferred_platforms: ['bilibili' as const] };
  15  | const caps: Capabilities = { mode: 'live', search: { status: 'configured', message: '隔离测试', selected_provider: 'fixture', providers: [] },
  16  |   llm: { status: 'configured', message: '隔离测试' }, fetch: { status: 'available', message: '隔离测试', browser_fallback: false }, platforms: [],
  17  |   limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 30, max_detail_pages: 40 } };
  18  | const analysis: ProjectAnalysis = { scope: '本地成绩分析工具', technical_plan: 'Python / pandas', assumptions: ['Excel 来自本地'],
  19  |   functions: [{ id: 'f1', name: '成绩统计与导出', original_requirement: input.requirements, acceptance_criteria: '统计结果可导出', no_new_learning_reason: null }],
  20  |   knowledge_points: [{ id: 'unit-1', name, description: '把成绩表转为按班级汇总的统计结果', function_ids: ['f1'], why_needed: '完成统计和导出',
  21  |     learning_goal: '读取 Excel，按班级统计均值，并导出新的统计表', necessity: 'required', prerequisite_ids: [], learning_order: 1, selection: 'learn',
  22  |     concepts: skills.map(skill => skill.text), practice_check: '换一份成绩表，独立生成按班级汇总的 Excel 文件。', technology: 'Python / pandas' }] };
  23  | function course(id: string, skill: string, kind: 'page' | 'catalog' | 'search' = 'page', platform = 'bilibili'): ResourceItem {
  24  |   const text = skills.find(row => row.id === skill)!.text;
  25  |   const url = `https://example.org/fixture/${id}`;
  26  |   const eid = `evidence-${id}`;
  27  |   const description = `本视频用 pandas 演示${text}，并以成绩表进行练习。`;
  28  |   const chapter = { title: `pandas ${text}`, evidence_id: eid };
  29  |   return {
  30  |     resource: { resource_id: id, title: `隔离视频：${text}`, url, canonical_url: url, platform, resource_type: 'video', author: null,
  31  |       description: kind === 'page' ? description : null, language: null, duration_seconds: null, published_at: null, discovered_at: time,
  32  |       fetched_at: kind === 'search' ? null : time, fetch_status: kind === 'search' ? 'search_only_policy' : 'fetched', metadata_evidence_level: kind,
  33  |       requires_login: null, requires_payment: null, requires_enrollment: null, chapters: kind === 'catalog' ? [chapter] : [],
  34  |       field_provenance: kind === 'page' ? { description: { evidence_id: eid, source: 'fixture.description', url } } : {}, playback_verified: false },
  35  |     match: { knowledge_point_id: 'job-point-1', resource_id: id, ranking_score: 0.8,
  36  |       recommendation_reason: '仅有这一子技能的内容线索；视频/授课语言尚未由来源元数据确认。', matched_evidence_ids: [eid], coverage_basis: [kind],
  37  |       topic_evidence_status: 'partial', supporting_evidence_ids: [eid], subtopic_coverage: skills.map(row => ({ ...row,
  38  |         status: row.id === skill ? 'supported' : 'unknown', evidence_ids: row.id === skill ? [eid] : [], reason: row.id === skill ? '隔离来源自身记录' : '未确认' })) },
  39  |     evidence: [{ evidence_id: eid, kind, source: kind === 'page' ? 'fixture.description' : kind === 'catalog' ? 'fixture.catalog' : 'fixture.search', url,
  40  |       ...(kind === 'search' ? { title: `pandas ${text}`, snippet: description, observed_at: time }
  41  |         : { field: kind === 'page' ? 'description' : 'chapters.0', text: kind === 'page' ? description : JSON.stringify({ title: chapter.title, url: null, start_seconds: null, end_seconds: null, duration_seconds: null }), fetched_at: time }) }],
  42  |   };
  43  | }
  44  | function fixtureGroup(): ResultGroup {
  45  |   const read = course('read-video', 'read');
  46  |   const mean = course('mean-video', 'mean', 'catalog', 'other');
  47  |   const snippet = course('snippet-only', 'export', 'search');
  48  |   const review = course('review-only', 'export'); review.match.topic_evidence_status = 'needs_review';
  49  |   const coverage: CollectionCoverage = { decomposition_status: 'applied', shared_context: ['pandas'], status: 'all_subtopics_supported',
  50  |     subtopics: skills.map(skill => ({ ...skill, status: 'supported', resource_ids: ['invented-aggregate-resource'], evidence_ids: ['invented-aggregate-evidence'] })),
  51  |     single_resource_full_coverage: true, disclaimer: '故意过度宣称的服务端汇总；客户端必须根据当前可见资源重新推导。' };
  52  |   return { knowledge_point_id: 'job-point-1', text: name, total_matches: 0, items: [], section_limit: 5,
  53  |     partial_items: [read, mean, snippet], partial_platform_items: { bilibili: [read, snippet], other: [mean] }, review_items: [review], review_platform_items: { bilibili: [review] },
  54  |     collection_coverage: coverage, platform_collection_coverage: { bilibili: structuredClone(coverage), other: structuredClone(coverage) } };
  55  | }
  56  | type Logs = { runtime: string[]; console: string[]; unexpected: string[] };
  57  | const diagnostics = new WeakMap<Page, Logs>();
  58  | test.afterEach(async ({ page }, info) => {
  59  |   const log = diagnostics.get(page)!;
  60  |   await info.attach('phase2-browser-diagnostics', { body: JSON.stringify(log, null, 2), contentType: 'application/json' });
  61  |   expect(log.runtime).toEqual([]); expect(log.console).toEqual([]); expect(log.unexpected).toEqual([]);
  62  | });
  63  | async function setup(page: Page, groups: Map<number, ResultGroup | null>, status = 'completed') {
  64  |   const log: Logs = { runtime: [], console: [], unexpected: [] }; diagnostics.set(page, log);
  65  |   page.on('pageerror', error => log.runtime.push(error.message));
  66  |   page.on('console', message => { if (['warning', 'error'].includes(message.type())) log.console.push(message.text()); });
  67  |   const current = Math.max(...groups.keys());
  68  |   await page.route('**/*', route => {
  69  |     const request = route.request(); const url = new URL(request.url());
  70  |     const origin = new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin;
  71  |     if (url.origin === origin && !url.pathname.startsWith('/api/')) return route.continue();
  72  |     if (request.method() === 'GET' && url.pathname === '/api/capabilities') return route.fulfill({ json: caps });
  73  |     if (request.method() === 'GET' && url.pathname === '/api/projects') return route.fulfill({ json: { projects: [{ project_id: 'coverage-project', name: input.name, current_version: current, created_at: time, updated_at: time }] } });
  74  |     if (request.method() === 'GET' && url.pathname === '/api/projects/coverage-project/results') {
  75  |       const selected = Number(url.searchParams.get('version')) || current; const result = groups.get(selected);
  76  |       const view: ProjectView = { project_id: 'coverage-project', input, current_version: current,
  77  |         versions: [...groups.keys()].map(version => ({ version, status, created_at: time })),
  78  |         version: { version: selected, status, input, analysis, confirmation: { version: selected, confirmed_at: time },
  79  |           batches: [{ batch_id: `batch-${selected}`, status, project_knowledge_point_ids: ['unit-1'], job_id: `job-${selected}` }], error: null, created_at: time },
  80  |         points: [{ project_knowledge_point_id: 'unit-1', name, selection: 'learn', status: status === 'running' ? 'running' : result?.partial_items?.length ? 'partial' : 'no_results',
  81  |           batch_id: `batch-${selected}`, job_id: `job-${selected}`, knowledge_point_id: result?.knowledge_point_id || null, result: result || null }] };
  82  |       return route.fulfill({ json: view });
  83  |     }
  84  |     log.unexpected.push(`${request.method()} ${url.href}`); return route.abort('blockedbyclient');
  85  |   });
  86  |   await page.goto(`/?project=coverage-project&version=${current}`);
> 87  |   await expect(page).toHaveTitle('项目制知识引导小精灵 — 课程与视频检索');
      |                      ^ Error: expect(page).toHaveTitle(expected) failed
  88  |   await expect(page.getByRole('heading', { name: `项目课程结果 · v${current}` })).toBeVisible();
  89  |   await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  90  |   return log;
  91  | }
  92  | const routeSummary = (page: Page) => page.getByRole('complementary', { name: `${name}的学习路线` });
  93  | 
  94  | test('phase2：可见视频的正文与目录支持可互补，摘要和待核实项不能补齐覆盖', async ({ page }) => {
  95  |   await setup(page, new Map([[1, fixtureGroup()]]));
  96  |   const summary = routeSummary(page);
  97  |   await expect(summary).toContainText('2 / 3 项有内容依据');
  98  |   await expect(summary.locator('.unit-coverage-supported li>span')).toHaveText(skills.slice(0, 2).map(row => row.text));
  99  |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText([skills[2].text]);
  100 |   await expect(summary).toContainText('子技能互补不代表整单元教学完整，也不代表已完成项目实践');
  101 |   await expect(summary).toContainText(analysis.knowledge_points[0].practice_check!);
  102 |   await expect(summary.getByRole('link', { name: /打开首个有依据的视频/ })).toHaveAttribute('href', 'https://example.org/fixture/read-video');
  103 |   await expect(page.locator('[data-resource-id="snippet-only"] .match-partial')).toBeVisible();
  104 |   await expect(page.locator('[data-resource-id="review-only"] .match-needs_review')).toBeVisible();
  105 |   await expect(page.locator('.recommendation-reason').first()).toContainText('视频/授课语言尚未由来源元数据确认');
  106 | });
  107 | 
  108 | test('phase2：切换平台重新计算子技能，不借隐藏视频或服务端全量汇总补足', async ({ page }) => {
  109 |   await setup(page, new Map([[1, fixtureGroup()]]));
  110 |   const summary = routeSummary(page);
  111 |   await page.getByLabel('项目课程来源').selectOption('bilibili');
  112 |   await expect(summary).toContainText('1 / 3 项有内容依据');
  113 |   await expect(summary.locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  114 |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText(skills.slice(1).map(row => row.text));
  115 |   await expect(page.locator('[data-resource-id="mean-video"]')).toHaveCount(0);
  116 |   await page.getByLabel('项目课程来源').selectOption('other');
  117 |   await expect(summary.locator('.unit-coverage-supported li>span')).toHaveText([skills[1].text]);
  118 |   await expect(summary.locator('.unit-coverage-missing li')).toHaveText([skills[0].text, skills[2].text]);
  119 |   await page.getByLabel('项目课程来源').selectOption('all');
  120 |   await expect(summary).toContainText('2 / 3 项有内容依据');
  121 | });
  122 | 
  123 | test('phase2：全部子项有依据仍保留练习与完整性边界，不宣称已掌握', async ({ page }) => {
  124 |   const group = fixtureGroup();
  125 |   const third = course('export-video', 'export', 'catalog');
  126 |   group.partial_items = [...group.partial_items!.slice(0, 2), third]; group.partial_platform_items = undefined;
  127 |   await setup(page, new Map([[1, group]]));
  128 |   const summary = routeSummary(page);
  129 |   await expect(summary).toContainText('3 / 3 项有内容依据');
  130 |   await expect(summary.locator('.unit-coverage-missing')).toContainText('仍需核对深度与完整性');
  131 |   await expect(summary).toContainText('再用下面的项目练习检验');
  132 |   await expect(summary).not.toContainText('已掌握');
  133 |   await expect(summary).toContainText('不代表已完成项目实践');
  134 | });
  135 | 
  136 | test('phase2：错配ID、标题字段、重复记录、目录篡改及跨资源引用不能成为内容依据', async ({ page }) => {
  137 |   const group = fixtureGroup(); group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined;
  138 |   const variants: [string, (item: ResourceItem) => void][] = [
  139 |     ['missing ID', item => { item.match.supporting_evidence_ids = ['missing']; }],
  140 |     ['wrong point', item => { item.match.knowledge_point_id = 'old-point'; }],
  141 |     ['wrong resource', item => { item.match.resource_id = 'different-resource'; }],
  142 |     ['title only', item => { item.evidence[0].field = 'title'; }],
  143 |     ['duplicate evidence', item => { item.evidence.push(structuredClone(item.evidence[0])); }],
  144 |     ['foreign URL', item => { item.evidence[0].url = 'https://example.org/another-course'; }],
  145 |     ['unbound description', item => { item.resource.description = '另一份描述'; }],
  146 |     ['wrong subtopic text', item => { item.match.subtopic_coverage![0].text = '无关的标题命中'; }],
  147 |     ['tampered catalog', item => { item.resource.chapters[0].title = '篡改的目录标题'; }],
  148 |   ];
  149 |   group.partial_items = [course('invalid', 'read')];
  150 |   await setup(page, new Map([[1, group]]));
  151 |   for (const [label, mutate] of variants) {
  152 |     const candidate = course('invalid', 'read', label === 'tampered catalog' ? 'catalog' : 'page'); mutate(candidate);
  153 |     group.partial_items = [candidate]; await page.reload();
  154 |     await expect(routeSummary(page), label).toContainText('0 / 3 项有内容依据');
  155 |     await expect(routeSummary(page).locator('.unit-coverage-missing li')).toHaveText(skills.map(row => row.text));
  156 |     await expect(routeSummary(page).getByRole('link', { name: /打开首个有依据的视频/ })).toHaveCount(0);
  157 |   }
  158 | });
  159 | 
  160 | for (const state of ['missing', 'empty'] as const) test(`phase2：${state} 覆盖信息给出待核对内容与下一步`, async ({ page }) => {
  161 |   const group = fixtureGroup(); delete group.collection_coverage; delete group.platform_collection_coverage;
  162 |   if (state === 'empty') { group.partial_items = []; group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  163 |   await setup(page, new Map([[1, group]]));
  164 |   const summary = routeSummary(page);
  165 |   await expect(summary).toContainText('子技能覆盖待确认');
  166 |   await expect(summary).toContainText(`学习时请核对：${skills.map(row => row.text).join('、')}`);
  167 |   await expect(summary.getByRole('link')).toHaveCount(0);
  168 |   if (state === 'empty') {
  169 |     await expect(summary).toContainText('返回调整知识点');
  170 |     await expect(page.locator('.group-empty')).toContainText('本次没有找到');
  171 |   } else await expect(summary).toContainText('先到原平台核对简介或目录');
  172 | });
  173 | 
  174 | test('phase2：切换版本只显示该版本可见资源的依据', async ({ page }) => {
  175 |   const old = fixtureGroup(); const latest = fixtureGroup();
  176 |   old.partial_items = [old.partial_items![0]]; latest.partial_items = [latest.partial_items![1]];
  177 |   for (const group of [old, latest]) { group.partial_platform_items = undefined; group.review_items = []; group.review_platform_items = undefined; }
  178 |   await setup(page, new Map([[1, old], [2, latest]]));
  179 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[1].text]);
  180 |   await page.goto('/?project=coverage-project&version=1');
  181 |   await expect(routeSummary(page).locator('.unit-coverage-supported li>span')).toHaveText([skills[0].text]);
  182 |   await expect(page.locator('[data-resource-id="mean-video"]')).toHaveCount(0);
  183 |   await expect(page.getByRole('button', { name: /重新检索这些知识点/ })).toHaveCount(0);
  184 | });
  185 | 
  186 | async function contrast(page: Page) {
  187 |   return page.locator('.unit-coverage').evaluate(container => {
```