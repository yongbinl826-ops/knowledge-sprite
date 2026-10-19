# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: project.spec.ts >> phase3 历史缺省技能不算用户修改：直接确认保留版本，不制造空技能或调用edit
- Location: tests\project.spec.ts:98:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '项目课程结果 · v1' })
Expected: visible
Timeout: 7000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('heading', { name: '项目课程结果 · v1' }) with timeout 7000ms
  - waiting for getByRole('heading', { name: '项目课程结果 · v1' })

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
    - paragraph: Mock：Excel 成绩分析工具 从相关的视频与章节开始。
    - button "← 调整知识点"
    - navigation "已选知识点":
      - paragraph: 已选知识点
      - button "全部" [pressed]
      - button "pandas 读取 Excel"
      - button "pandas 计算均值"
      - button "Matplotlib 柱状图绘制"
  - status: 已确认，按勾选的知识点分批查找推荐视频。
  - paragraph: Mock：Excel 成绩分析工具 · v2 · 检索完成
  - region "项目课程结果 · v2":
    - heading "项目课程结果 · v2" [level=2]: 推荐视频
    - paragraph: 从一个学习单元开始，将学到的内容用在项目里。
    - text: 检索完成
    - group: 查看检索进度与预算
    - heading "读取与统计" [level=3]
    - heading "pandas 读取 Excel" [level=4]
    - text: 检索完成 · 1 条推荐
    - complementary "pandas 读取 Excel的学习路线":
      - heading "从学会技能，到完成项目" [level=5]
      - status: 教学范围待核对
      - paragraph:
        - strong: 必要先修
        - text: 无额外先修，可从这里开始
      - region "先学这些技能":
        - heading "先学这些技能" [level=6]
        - paragraph: 学习可迁移的方法；教程不必使用同款项目。
        - paragraph: 此版本尚未区分可迁移技能。原项目要求保留在下方明细中，可返回知识点页补充。
      - region "带回项目练习":
        - heading "带回项目练习" [level=6]
        - text: 待自己实践
        - paragraph: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
        - strong: 项目子任务
        - paragraph: 离线 Mock 知识点说明
        - strong: 试做后这样检查
        - paragraph: 能够在本地工具中应用
      - strong: 下一步
      - paragraph: 已有相关材料，但技能教学范围仍待核对；可先查看简介、目录，再决定是否需要调整或重新检索。
      - paragraph: 课程依据只说明当前可见材料的教学范围，不代表已经学会，也不代表项目练习完成。
      - group: 原项目要求来源核对 旧口径明细
    - region "待核实线索":
      - paragraph: 待核实 · 供参考
      - article:
        - link "前往原平台学习：离线 Mock 课程 kp1":
          - /url: https://example.org/mock-course
          - text: 来源未提供封面
        - text: 其他网站 待核实
        - heading "离线 Mock 课程 kp1" [level=4]:
          - link "离线 Mock 课程 kp1":
            - /url: https://example.org/mock-course
        - paragraph: 离线测试匹配
        - paragraph: 内容相关性待确认，可前往原平台查看。
        - link "去原平台学习 ：离线 Mock 课程 kp1（在新窗口打开）":
          - /url: https://example.org/mock-course
    - heading "pandas 计算均值" [level=4]
    - text: 检索完成 · 1 条推荐
    - complementary "pandas 计算均值的学习路线":
      - heading "从学会技能，到完成项目" [level=5]
      - status: 教学范围待核对
      - paragraph:
        - strong: 必要先修
        - text: pandas 读取 Excel
      - region "先学这些技能":
        - heading "先学这些技能" [level=6]
        - paragraph: 学习可迁移的方法；教程不必使用同款项目。
        - paragraph: 此版本尚未区分可迁移技能。原项目要求保留在下方明细中，可返回知识点页补充。
      - region "带回项目练习":
        - heading "带回项目练习" [level=6]
        - text: 待自己实践
        - paragraph: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
        - strong: 项目子任务
        - paragraph: 离线 Mock 知识点说明
        - strong: 试做后这样检查
        - paragraph: 能够在本地工具中应用
      - strong: 下一步
      - paragraph: 已有相关材料，但技能教学范围仍待核对；可先查看简介、目录，再决定是否需要调整或重新检索。
      - paragraph: 课程依据只说明当前可见材料的教学范围，不代表已经学会，也不代表项目练习完成。
      - group: 原项目要求来源核对 旧口径明细
    - region "待核实线索":
      - paragraph: 待核实 · 供参考
      - article:
        - link "前往原平台学习：离线 Mock 课程 kp2":
          - /url: https://example.org/mock-course
          - text: 来源未提供封面
        - text: 其他网站 待核实
        - heading "离线 Mock 课程 kp2" [level=4]:
          - link "离线 Mock 课程 kp2":
            - /url: https://example.org/mock-course
        - paragraph: 离线测试匹配
        - paragraph: 内容相关性待确认，可前往原平台查看。
        - link "去原平台学习 ：离线 Mock 课程 kp2（在新窗口打开）":
          - /url: https://example.org/mock-course
    - heading "图表与导出" [level=3]
    - heading "Matplotlib 柱状图绘制" [level=4]
    - text: 检索完成 · 1 条推荐
    - complementary "Matplotlib 柱状图绘制的学习路线":
      - heading "从学会技能，到完成项目" [level=5]
      - status: 教学范围待核对
      - paragraph:
        - strong: 必要先修
        - text: pandas 读取 Excel
      - region "先学这些技能":
        - heading "先学这些技能" [level=6]
        - paragraph: 学习可迁移的方法；教程不必使用同款项目。
        - paragraph: 此版本尚未区分可迁移技能。原项目要求保留在下方明细中，可返回知识点页补充。
      - region "带回项目练习":
        - heading "带回项目练习" [level=6]
        - text: 待自己实践
        - paragraph: 把技能用于自己的项目。课程匹配不会自动完成这些要求。
        - strong: 项目子任务
        - paragraph: 离线 Mock 知识点说明
        - strong: 试做后这样检查
        - paragraph: 能够在本地工具中应用
      - strong: 下一步
      - paragraph: 已有相关材料，但技能教学范围仍待核对；可先查看简介、目录，再决定是否需要调整或重新检索。
      - paragraph: 课程依据只说明当前可见材料的教学范围，不代表已经学会，也不代表项目练习完成。
      - group: 原项目要求来源核对 旧口径明细
    - region "待核实线索":
      - paragraph: 待核实 · 供参考
      - article:
        - link "前往原平台学习：离线 Mock 课程 kp3":
          - /url: https://example.org/mock-course
          - text: 来源未提供封面
        - text: 其他网站 待核实
        - heading "离线 Mock 课程 kp3" [level=4]:
          - link "离线 Mock 课程 kp3":
            - /url: https://example.org/mock-course
        - paragraph: 离线测试匹配
        - paragraph: 内容相关性待确认，可前往原平台查看。
        - link "去原平台学习 ：离线 Mock 课程 kp3（在新窗口打开）":
          - /url: https://example.org/mock-course
    - paragraph: 章节信息来自实际检索证据。课程可能需要登录、选课或付费，以原平台为准。
    - button "重新检索这些知识点"
    - paragraph: 重新检索会创建新版本，上次结果保留；受相同预算与限流约束。
- contentinfo: 让学习，发生在项目里。 需求在本机服务保存 · 分析使用已配置的模型
```

# Test source

```ts
  3   | import { resolve } from 'node:path';
  4   | import type { Capabilities, ResourceItem } from '../src/types';
  5   | import type { ProjectAnalysis, ProjectInput, ProjectPointResult, ProjectVersion, ProjectView } from '../src/projectTypes';
  6   | 
  7   | // Offline Mock transport fixtures only. These are not production templates or live acceptance evidence.
  8   | const time = '2026-10-17T08:00:00Z';
  9   | const input: ProjectInput = { name: 'Mock：Excel 成绩分析工具', requirements: '读取本地 Excel，统计、绘图和导出。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: 'Python 3.11', preferred_platforms: ['bilibili'] };
  10  | const caps: Capabilities = {
  11  |   mode: 'live', search: { selected_provider: 'fixture', status: 'configured', message: '离线 Mock', providers: [] }, llm: { status: 'configured', message: '离线 Mock' },
  12  |   fetch: { status: 'available', message: '离线 Mock', browser_fallback: false }, platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 30, max_detail_pages: 40 },
  13  |   project_analysis: { status: 'configured', message: '离线 Mock 分析', model: 'mock-test-only', prompt_version: 'test-v1', max_functions: 12, max_knowledge_points: 24 },
  14  |   project_search: { max_batches: 5, max_search_requests: 150, max_detail_pages: 200, deadline_seconds: 900, batch_size: 5 },
  15  | };
  16  | function analysis(count = 3): ProjectAnalysis {
  17  |   return { scope: '本地成绩分析，不引入登录或云部署', technical_plan: '建议 Python、pandas 和 Matplotlib；这是可修改的假设。', assumptions: ['输入为本地 Excel 文件'],
  18  |     functions: [{ id: 'f1', name: '读取与统计', original_requirement: '读取本地 Excel 并统计', acceptance_criteria: '得到均值统计表', no_new_learning_reason: null }, { id: 'f2', name: '图表与导出', original_requirement: '绘图和导出', acceptance_criteria: '导出图表和统计表', no_new_learning_reason: null }],
  19  |     knowledge_points: Array.from({ length: count }, (_, index) => ({ id: `kp${index + 1}`, name: ['pandas 读取 Excel', 'pandas 计算均值', 'Matplotlib 柱状图绘制'][index] || `明确检索知识点 ${index + 1}`, description: '离线 Mock 知识点说明', function_ids: index === 0 ? ['f1', 'f2'] : [index === 1 ? 'f1' : 'f2'], why_needed: '完成所关联的功能', learning_goal: '能够在本地工具中应用', necessity: 'required', prerequisite_ids: index ? ['kp1'] : [], learning_order: index + 1, selection: 'learn' })),
  20  |   };
  21  | }
  22  | function version(document = analysis(), number = 1): ProjectVersion { return { version: number, status: 'analyzed', input: structuredClone(input), analysis: document, confirmation: null, batches: [], error: null, created_at: time, model: 'mock-test-only', prompt_version: 'test-v1' }; }
  23  | function resource(pointId: string): ResourceItem {
  24  |   return {
  25  |     resource: { resource_id: `mock-${pointId}`, title: `离线 Mock 课程 ${pointId}`, url: 'https://example.org/mock-course', canonical_url: 'https://example.org/mock-course', platform: 'other', resource_type: 'course', author: null, description: '仅测试展示', language: 'zh', duration_seconds: null, published_at: null, discovered_at: time, fetched_at: time, fetch_status: 'fetched', metadata_evidence_level: 'page', requires_login: false, requires_payment: false, requires_enrollment: false, chapters: [], field_provenance: {}, playback_verified: false },
  26  |     match: { knowledge_point_id: pointId, resource_id: `mock-${pointId}`, ranking_score: 0.8, recommendation_reason: '离线测试匹配', matched_evidence_ids: [], coverage_basis: ['title'], topic_evidence_status: 'supported' }, evidence: [],
  27  |   };
  28  | }
  29  | type MockOptions = { count?: number; unconfigured?: boolean; initial?: boolean; running?: boolean; failConfirmOnce?: boolean; failAnalyzeOnce?: boolean; analysisPending?: boolean; noResults?: boolean; maxBatches?: number; scopeMismatch?: boolean };
  30  | async function mockProject(page: Page, options: MockOptions = {}) {
  31  |   const versions = new Map<number, ProjectVersion>();
  32  |   if (options.initial) versions.set(1, version(analysis(options.count)));
  33  |   let currentVersion = options.initial ? 1 : 0;
  34  |   let savedInput = structuredClone(input);
  35  |   let created = !!options.initial;
  36  |   let confirmFailures = options.failConfirmOnce ? 1 : 0;
  37  |   let analysisFailures = options.failAnalyzeOnce ? 1 : 0;
  38  |   const calls = { create: [] as ProjectInput[], analyze: 0, edit: [] as ProjectAnalysis[], confirm: [] as { version: number; acknowledged_skipped_prerequisites: string[] }[], search: [] as number[], cancel: 0, selected: [] as string[], unexpected: [] as string[], runtime: [] as string[], console: [] as string[] };
  39  |   page.on('pageerror', error => calls.runtime.push(error.message));
  40  |   page.on('console', message => { if (message.type() === 'error') calls.console.push(message.text()); });
  41  |   function view(chosen = currentVersion): ProjectView {
  42  |     const current = versions.get(chosen) || null;
  43  |     const points: ProjectPointResult[] = (current?.analysis?.knowledge_points || []).map(point => {
  44  |       const batch = current!.batches.find(item => item.project_knowledge_point_ids.includes(point.id));
  45  |       const mismatch=options.scopeMismatch&&chosen===1&&batch?.status==='completed';
  46  |       return { project_knowledge_point_id: point.id, name: point.name, selection: point.selection, status: mismatch ? 'scope_mismatch' : point.selection !== 'learn' ? point.selection : batch?.status === 'completed' && options.noResults ? 'no_results' : batch?.status || 'not_started', batch_id: batch?.batch_id || null, job_id: batch?.job_id || null, knowledge_point_id: batch ? point.id : null, result: batch?.status === 'completed' ? { knowledge_point_id: point.id, text: point.name, total_matches: options.noResults ? 0 : 1, items: options.noResults ? [] : [resource(point.id)],
  47  |         ...(mismatch ? {scope_status:'mismatch' as const,scope_notice:'旧检索技术与本单元不一致，结果已隐藏；请重新检索。',expected_search_text:point.name} : {}) } : null };
  48  |     });
  49  |     return { project_id: 'mock-project', input: savedInput, current_version: currentVersion, versions: [...versions.values()].map(item => ({ version: item.version, status: item.status, created_at: time })), version: current, points, functions: current?.analysis?.functions || [] };
  50  |   }
  51  |   await page.route('**/*', async route => {
  52  |     const url = new URL(route.request().url());
  53  |     if (!url.pathname.startsWith('/api/')) {
  54  |       if (url.origin === new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin) return route.continue();
  55  |       calls.unexpected.push(url.href); return route.abort();
  56  |     }
  57  |     const method = route.request().method();
  58  |     const body = method === 'POST' ? route.request().postDataJSON() : {};
  59  |     if (url.pathname === '/api/capabilities') return route.fulfill({ json: { ...caps, project_analysis: { ...caps.project_analysis, status: options.unconfigured ? 'unconfigured' : 'configured' }, project_search: { ...caps.project_search, max_batches: options.maxBatches || 5 } } });
  60  |     if (url.pathname === '/api/projects' && method === 'GET') return route.fulfill({ json: { projects: created ? [{ project_id: 'mock-project', name: savedInput.name, current_version: currentVersion, created_at: time, updated_at: time }] : [] } });
  61  |     if (url.pathname === '/api/projects' && method === 'POST') { calls.create.push(body); savedInput = body; created = true; return route.fulfill({ json: view() }); }
  62  |     if (url.pathname === '/api/projects/mock-project/results') return route.fulfill({ json: view(Number(url.searchParams.get('version')) || currentVersion) });
  63  |     if (url.pathname === '/api/projects/mock-project/analyze') {
  64  |       calls.analyze += 1; savedInput = body.input;
  65  |       if (analysisFailures) { analysisFailures -= 1; return route.fulfill({ status: 503, json: { detail: '离线 Mock：模型暂时不可用，请重试。' } }); }
  66  |       currentVersion += 1;
  67  |       const next = version(analysis(options.count), currentVersion); next.input = savedInput;
  68  |       if (options.analysisPending) { next.status = 'analyzing'; next.analysis = null; }
  69  |       if (options.unconfigured) { next.status = 'analysis_failed'; next.analysis = null; next.error = { code: 'unconfigured', message: '未配置可用模型，分析失败。' }; }
  70  |       versions.set(currentVersion, next); return route.fulfill({ json: view() });
  71  |     }
  72  |     if (url.pathname === '/api/projects/mock-project/edit') { calls.edit.push(body.analysis); currentVersion += 1; const next = version(body.analysis, currentVersion); next.input = savedInput; versions.set(currentVersion, next); return route.fulfill({ json: view() }); }
  73  |     if (url.pathname === '/api/projects/mock-project/confirm') {
  74  |       calls.confirm.push(body);
  75  |       if (confirmFailures) { confirmFailures -= 1; return route.fulfill({ status: 422, json: { detail: 'Mock：暂时超出项目预算，修改已保存。', code: 'project_budget_exceeded' } }); }
  76  |       const next = versions.get(body.version)!; next.status = 'confirmed'; next.confirmation = { version: body.version, confirmed_at: time };
  77  |       return route.fulfill({ json: view(body.version) });
  78  |     }
  79  |     if (url.pathname === '/api/projects/mock-project/search') {
  80  |       calls.search.push(body.version);
  81  |       const next = versions.get(body.version)!;
  82  |       if (!next.confirmation) return route.fulfill({ status: 409, json: { detail: '必须先确认' } });
  83  |       const selected = next.analysis!.knowledge_points.filter(point => point.selection === 'learn'); calls.selected = selected.map(point => point.id);
  84  |       if (!next.batches.length) for (let offset = 0; offset < selected.length; offset += 5) next.batches.push({ batch_id: `batch-${offset}`, status: options.running ? offset ? 'pending' : 'submitted' : 'completed', project_knowledge_point_ids: selected.slice(offset, offset + 5).map(point => point.id), job_id: options.running && offset ? null : `job-${offset}` });
  85  |       next.status = options.running ? 'running' : 'completed';
  86  |       return route.fulfill({ json: view(body.version) });
  87  |     }
  88  |     if (url.pathname === '/api/projects/mock-project/cancel') { calls.cancel += 1; const next = versions.get(body.version)!; next.status = 'cancelled'; for (const batch of next.batches) if (batch.status === 'pending') batch.status = 'cancelled'; return route.fulfill({ json: view(body.version) }); }
  89  |     calls.unexpected.push(`${method} ${url.pathname}`); return route.abort();
  90  |   });
  91  |   return { calls, versions, view };
  92  | }
  93  | async function enterProject(page: Page, initial = false) {
  94  |   await page.goto(initial ? '/?project=mock-project&version=1' : '/');
  95  | }
  96  | function firstPoint(page: Page, id: string) { return page.locator(`.project-point[data-point-id="${id}"]`).first(); }
  97  | 
  98  | test('phase3 历史缺省技能不算用户修改：直接确认保留版本，不制造空技能或调用edit', async ({ page }) => {
  99  |   const mock = await mockProject(page, { initial: true });
  100 |   await enterProject(page, true);
  101 |   expect(mock.versions.get(1)!.analysis!.knowledge_points.every(point => !('learning_skills' in point))).toBe(true);
  102 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
> 103 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v1' })).toBeVisible();
      |                                                                    ^ Error: expect(locator).toBeVisible() failed
  104 |   expect(mock.calls.edit).toEqual([]);
  105 |   expect(mock.calls.confirm.map(call => call.version)).toEqual([1]);
  106 |   expect(mock.calls.search).toEqual([1]);
  107 |   expect(mock.versions.get(1)!.analysis!.knowledge_points.every(point => !('learning_skills' in point))).toBe(true);
  108 |   expect(mock.calls.unexpected).toEqual([]); expect(mock.calls.runtime).toEqual([]); expect(mock.calls.console).toEqual([]);
  109 | });
  110 | 
  111 | test('离线 Mock：真实入口结构、原始输入、共享勾选与只搜索勾选项', async ({ page }, testInfo) => {
  112 |   const mock = await mockProject(page);
  113 |   await enterProject(page);
  114 |   await page.getByLabel('项目名称', { exact: true }).fill('  我的成绩工具  ');
  115 |   await page.getByLabel('功能需求', { exact: true }).fill('  读取 Excel\n统计并绘图\n导出结果  ');
  116 |   await page.getByRole('button', { name: '分析项目' }).click();
  117 |   await expect(page.getByRole('heading', { name: '确认知识点 · v1' })).toBeVisible();
  118 |   expect(mock.calls.search).toEqual([]);
  119 |   expect(mock.calls.create[0].name).toBe('  我的成绩工具  ');
  120 |   expect(mock.calls.create[0].requirements).toBe('  读取 Excel\n统计并绘图\n导出结果  ');
  121 |   await firstPoint(page, 'kp1').getByLabel('想学习', { exact: true }).uncheck();
  122 |   await expect(page.locator('.project-point[data-point-id="kp1"]')).toHaveCount(1);
  123 |   await firstPoint(page, 'kp1').locator('summary').click();
  124 |   await expect(firstPoint(page, 'kp1').locator('.learning-detail-copy')).toContainText('读取与统计、图表与导出');
  125 |   await expect(firstPoint(page, 'kp1').getByLabel('想学习', { exact: true })).not.toBeChecked();
  126 |   await firstPoint(page, 'kp3').getByLabel('想学习', { exact: true }).uncheck();
  127 |   await expect(page.locator('.project-search-summary')).toContainText('已勾选 1 项 · 未勾选 2 项');
  128 |   await page.getByRole('checkbox', { name: /我了解未勾选/ }).check();
  129 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).click();
  130 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v2' })).toBeVisible();
  131 |   await expect(page.getByRole('heading', { name: '离线 Mock 课程 kp2' })).toBeVisible();
  132 |   expect(mock.calls.selected).toEqual(['kp2']);
  133 |   expect(mock.calls.edit[0].knowledge_points.map(point => point.selection)).toEqual(['skip', 'learn', 'skip']);
  134 |   await expect(page.locator('.resource-card')).toHaveCount(1);
  135 |   await page.screenshot({ path: testInfo.outputPath('project-desktop-results.png'), fullPage: true });
  136 |   expect(mock.calls.unexpected).toEqual([]); expect(mock.calls.runtime).toEqual([]); expect(mock.calls.console).toEqual([]);
  137 | });
  138 | 
  139 | test('离线 Mock：未勾选前置必须明确确认；刷新恢复、超过五点分批与取消', async ({ page }) => {
  140 |   const mock = await mockProject(page, { initial: true, count: 7, running: true });
  141 |   await enterProject(page, true);
  142 |   await firstPoint(page, 'kp1').getByLabel('想学习', { exact: true }).uncheck();
  143 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  144 |   await page.getByRole('checkbox', { name: /我了解未勾选/ }).check();
  145 |   await page.getByRole('button', { name: '查找推荐视频', exact: true }).dblclick();
  146 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v2' })).toBeVisible();
  147 |   expect(mock.calls.confirm[0].acknowledged_skipped_prerequisites).toEqual(['kp1']);
  148 |   expect(mock.calls.selected).toEqual(['kp2', 'kp3', 'kp4', 'kp5', 'kp6', 'kp7']);
  149 |   expect(mock.versions.get(2)!.batches.map(batch => batch.project_knowledge_point_ids.length)).toEqual([5, 1]);
  150 |   await page.reload();
  151 |   await expect(page.getByRole('heading', { name: '项目课程结果 · v2' })).toBeVisible();
  152 |   expect(mock.calls.search).toEqual([2]);
  153 |   await expect(page.locator('.platform-search-fallback')).toHaveCount(0);
  154 |   await captureResponsiveState(page, 'search-loading');
  155 |   await page.getByRole('button', { name: '取消项目检索' }).click();
  156 |   await page.locator('.search-diagnostics > summary').click();
  157 |   await expect(page.locator('.project-batches').getByText('已取消', { exact: true })).toBeVisible();
  158 |   expect(mock.calls.cancel).toBe(1); expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  159 | });
  160 | 
  161 | test('离线 Mock：全部取消勾选只保存选择，不创建空检索', async ({ page }) => {
  162 |   const mock = await mockProject(page, { initial: true });
  163 |   await enterProject(page, true);
  164 |   for (const id of ['kp1', 'kp2', 'kp3']) await firstPoint(page, id).getByLabel('想学习', { exact: true }).uncheck();
  165 |   await page.getByRole('button', { name: '保存选择', exact: true }).click();
  166 |   await expect(page.getByText('已保存选择；没有勾选知识点，未创建检索任务。')).toBeVisible();
  167 |   expect(mock.calls.confirm).toHaveLength(1); expect(mock.calls.search).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  168 | });
  169 | 
  170 | test('离线 Mock：旧版掌握仅在草稿转换，明确保存才建新版且历史不变', async ({ page }) => {
  171 |   const mock = await mockProject(page, { initial: true });
  172 |   mock.versions.get(1)!.analysis!.knowledge_points[0].selection = 'mastered';
  173 |   await enterProject(page, true);
  174 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  175 |   await expect(page.locator('.point-choices input[type="radio"]')).toHaveCount(0);
  176 |   await expect(page.getByText('已经掌握', { exact: true })).toHaveCount(0);
  177 |   await expect(page.getByText('暂时跳过', { exact: true })).toHaveCount(0);
  178 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].selection).toBe('mastered');
  179 |   expect(mock.calls.edit).toHaveLength(0);
  180 |   await expect(page.getByRole('region', { name: '前置知识冲突' })).toBeVisible();
  181 |   await expect(page.getByRole('button', { name: '查找推荐视频', exact: true })).toBeDisabled();
  182 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  183 |   await expect(page.getByRole('heading', { name: '确认知识点 · v2' })).toBeVisible();
  184 |   expect(mock.calls.edit[0].knowledge_points[0].selection).toBe('skip');
  185 |   expect(mock.calls.edit[0].knowledge_points.every(point => ['learn', 'skip'].includes(point.selection))).toBe(true);
  186 |   await firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true }).check();
  187 |   await expect(page.locator('.project-point[data-point-id="kp1"]')).toHaveCount(1);
  188 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).toBeChecked();
  189 |   await page.getByRole('button', { name: '保存修改，稍后确认', exact: true }).click();
  190 |   await expect(page.getByRole('heading', { name: '确认知识点 · v3' })).toBeVisible();
  191 |   expect(mock.calls.edit[1].knowledge_points[0].selection).toBe('learn');
  192 |   await page.getByRole('button', { name: '我的项目' }).click();
  193 |   await page.getByLabel('查看版本', { exact: true }).selectOption('1');
  194 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).not.toBeChecked();
  195 |   await expect(firstPoint(page, 'kp1').getByRole('checkbox', { name: '想学习', exact: true })).toBeDisabled();
  196 |   expect(mock.versions.get(1)!.analysis!.knowledge_points[0].selection).toBe('mastered');
  197 |   expect(mock.calls.edit).toHaveLength(2);
  198 |   expect(mock.calls.search).toEqual([]); expect(mock.calls.runtime).toEqual([]); expect(mock.calls.unexpected).toEqual([]);
  199 | });
  200 | 
  201 | test('离线 Mock：增删改与方案编辑生成新版本，删除前置需先处理引用', async ({ page }) => {
  202 |   const mock = await mockProject(page, { initial: true });
  203 |   await enterProject(page, true);
```