import { expectGalleryTitlesOnly } from './coverTitleContract';
import { test, expect, type Page } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import type { Capabilities, ResourceItem } from '../src/types';
import type { ProjectAnalysis, ProjectInput, ProjectPointResult, ProjectVersion, ProjectView } from '../src/projectTypes';

// Teaching mode stays true. Positive mocks bind title and video-page evidence to
// the same resource; their synthetic records are not real source or playback proof.
// Offline Mock transport fixtures only. These are not production templates or live acceptance evidence.
const time = '2026-10-17T08:00:00Z';
const input: ProjectInput = { name: 'Mock：Excel 成绩分析工具', requirements: '读取本地 Excel，统计、绘图和导出。', student_level: 'beginner', language: 'zh', project_context: '', technical_version: 'Python 3.11', preferred_platforms: ['bilibili'] };
const caps: Capabilities = {
  mode: 'live', teaching_match_enabled: true, search: { selected_provider: 'fixture', status: 'configured', message: '离线 Mock', providers: [] }, llm: { status: 'configured', message: '离线 Mock' },
  fetch: { status: 'available', message: '离线 Mock', browser_fallback: false }, platforms: [], limits: { max_knowledge_points: 5, max_results_per_point: 5, max_search_requests: 30, max_detail_pages: 40 },
  project_analysis: { status: 'configured', message: '离线 Mock 分析', model: 'mock-test-only', prompt_version: 'test-v1', max_functions: 12, max_knowledge_points: 24 },
  project_search: { max_batches: 5, max_search_requests: 150, max_detail_pages: 200, deadline_seconds: 900, batch_size: 5 },
};
function analysis(count = 3): ProjectAnalysis {
  return { scope: '本地成绩分析，不引入登录或云部署', technical_plan: '建议 Python、pandas 和 Matplotlib；这是可修改的假设。', assumptions: ['输入为本地 Excel 文件'],
    functions: [{ id: 'f1', name: '读取与统计', original_requirement: '读取本地 Excel 并统计', acceptance_criteria: '得到均值统计表', no_new_learning_reason: null }, { id: 'f2', name: '图表与导出', original_requirement: '绘图和导出', acceptance_criteria: '导出图表和统计表', no_new_learning_reason: null }],
    knowledge_points: Array.from({ length: count }, (_, index) => ({ id: `kp${index + 1}`, name: ['pandas 读取 Excel', 'pandas 计算均值', 'Matplotlib 柱状图绘制'][index] || `明确检索知识点 ${index + 1}`, description: '离线 Mock 知识点说明', function_ids: index === 0 ? ['f1', 'f2'] : [index === 1 ? 'f1' : 'f2'], why_needed: '完成所关联的功能', learning_goal: '能够在本地工具中应用', necessity: 'required', prerequisite_ids: index ? ['kp1'] : [], learning_order: index + 1, selection: 'learn' })),
  };
}
function version(document = analysis(), number = 1): ProjectVersion { return { version: number, status: 'analyzed', input: structuredClone(input), analysis: document, confirmation: null, batches: [], error: null, created_at: time, model: 'mock-test-only', prompt_version: 'test-v1' }; }
function resource(pointId: string, verified = true): ResourceItem {
  const resourceId = `${verified ? 'mock' : 'unverified'}-${pointId}`;
  const url = `https://example.org/${verified ? 'mock' : 'unverified'}-video`;
  const title = `离线 Mock ${verified ? '页面视频' : '搜索线索'} ${pointId}`;
  const titleId = `${resourceId}-title`, videoId = `${resourceId}-video`;
  const source = verified ? 'offline.mock.video_page' : 'offline.mock.search';
  return {
    resource: { resource_id: resourceId, title, url, canonical_url: url, platform: 'other', resource_type: 'video', author: null, description: '仅离线测试展示', language: 'zh', duration_seconds: null, published_at: null, discovered_at: time, fetched_at: verified ? time : null, fetch_status: verified ? 'fetched' : 'not_fetched', video_evidence_status: verified ? 'page_verified' : 'search_discovered', metadata_evidence_level: verified ? 'page' : 'search', requires_login: false, requires_payment: false, requires_enrollment: false, chapters: [], field_provenance: { title: { evidence_id: titleId, source, url }, ...(verified ? { video_evidence_status: { evidence_id: videoId, source, url } } : {}) }, playback_verified: false },
    match: { knowledge_point_id: pointId, resource_id: resourceId, ranking_score: 0.8, recommendation_reason: '离线测试匹配', matched_evidence_ids: [titleId], supporting_evidence_ids: [titleId], coverage_basis: ['title'], topic_evidence_status: 'supported' },
    evidence: [{ evidence_id: titleId, kind: verified ? 'page' : 'search', source, url, field: 'title', title, text: title }, ...(verified ? [{ evidence_id: videoId, kind: 'page', source, url, field: 'video_evidence_status', text: '离线 Mock 视频页包含播放器；不是实际抓取或播放验证。' }] : [])],
  };
}
type MockOptions = { count?: number; unconfigured?: boolean; initial?: boolean; running?: boolean; failConfirmOnce?: boolean; failAnalyzeOnce?: boolean; analysisPending?: boolean; noResults?: boolean; maxBatches?: number; scopeMismatch?: boolean };
async function mockProject(page: Page, options: MockOptions = {}) {
  const versions = new Map<number, ProjectVersion>();
  if (options.initial) versions.set(1, version(analysis(options.count)));
  let currentVersion = options.initial ? 1 : 0;
  let savedInput = structuredClone(input);
  let created = !!options.initial;
  let confirmFailures = options.failConfirmOnce ? 1 : 0;
  let analysisFailures = options.failAnalyzeOnce ? 1 : 0;
  const calls = { create: [] as ProjectInput[], analyze: 0, edit: [] as ProjectAnalysis[], confirm: [] as { version: number; acknowledged_skipped_prerequisites?: string[] }[], search: [] as number[], cancel: 0, selected: [] as string[], unexpected: [] as string[], runtime: [] as string[], console: [] as string[] };
  page.on('pageerror', error => calls.runtime.push(error.message));
  page.on('console', message => { if (message.type() === 'error') calls.console.push(message.text()); });
  function view(chosen = currentVersion): ProjectView {
    const current = versions.get(chosen) || null;
    const points: ProjectPointResult[] = (current?.analysis?.knowledge_points || []).map(point => {
      const batch = current!.batches.find(item => item.project_knowledge_point_ids.includes(point.id));
      const mismatch=options.scopeMismatch&&chosen===1&&batch?.status==='completed';
      return { project_knowledge_point_id: point.id, name: point.name, selection: point.selection, status: mismatch ? 'scope_mismatch' : point.selection !== 'learn' ? point.selection : batch?.status === 'completed' && options.noResults ? 'no_results' : batch?.status || 'not_started', batch_id: batch?.batch_id || null, job_id: batch?.job_id || null, knowledge_point_id: batch ? point.id : null, result: batch?.status === 'completed' ? { knowledge_point_id: point.id, text: point.name, total_matches: options.noResults ? 0 : 2, items: options.noResults ? [] : [resource(point.id), resource(point.id, false)],
        ...(mismatch ? {scope_status:'mismatch' as const,scope_notice:'旧检索技术与本单元不一致，结果已隐藏；请重新检索。',expected_search_text:point.name} : {}) } : null };
    });
    return { project_id: 'mock-project', input: savedInput, current_version: currentVersion, versions: [...versions.values()].map(item => ({ version: item.version, status: item.status, created_at: time })), version: current, points, functions: current?.analysis?.functions || [] };
  }
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) {
      if (url.origin === new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').origin) return route.continue();
      calls.unexpected.push(url.href); return route.abort();
    }
    const method = route.request().method();
    const body = method === 'POST' ? route.request().postDataJSON() : {};
    if (url.pathname === '/api/capabilities') return route.fulfill({ json: { ...caps, project_analysis: { ...caps.project_analysis, status: options.unconfigured ? 'unconfigured' : 'configured' }, project_search: { ...caps.project_search, max_batches: options.maxBatches || 5 } } });
    if (url.pathname === '/api/projects' && method === 'GET') return route.fulfill({ json: { projects: created ? [{ project_id: 'mock-project', name: savedInput.name, current_version: currentVersion, created_at: time, updated_at: time }] : [] } });
    if (url.pathname === '/api/projects' && method === 'POST') { calls.create.push(body); savedInput = body; created = true; return route.fulfill({ json: view() }); }
    if (url.pathname === '/api/projects/mock-project/results') return route.fulfill({ json: view(Number(url.searchParams.get('version')) || currentVersion) });
    if (url.pathname === '/api/projects/mock-project/analyze') {
      calls.analyze += 1; savedInput = body.input;
      if (analysisFailures) { analysisFailures -= 1; return route.fulfill({ status: 503, json: { detail: '离线 Mock：模型暂时不可用，请重试。' } }); }
      currentVersion += 1;
      const next = version(analysis(options.count), currentVersion); next.input = savedInput;
      if (options.analysisPending) { next.status = 'analyzing'; next.analysis = null; }
      if (options.unconfigured) { next.status = 'analysis_failed'; next.analysis = null; next.error = { code: 'unconfigured', message: '未配置可用模型，分析失败。' }; }
      versions.set(currentVersion, next); return route.fulfill({ json: view() });
    }
    if (url.pathname === '/api/projects/mock-project/edit') { calls.edit.push(body.analysis); currentVersion += 1; const next = version(body.analysis, currentVersion); next.input = savedInput; versions.set(currentVersion, next); return route.fulfill({ json: view() }); }
    if (url.pathname === '/api/projects/mock-project/confirm') {
      calls.confirm.push(body);
      if (confirmFailures) { confirmFailures -= 1; return route.fulfill({ status: 422, json: { detail: 'Mock：暂时超出项目预算，修改已保存。', code: 'project_budget_exceeded' } }); }
      const next = versions.get(body.version)!; next.status = 'confirmed'; next.confirmation = { version: body.version, confirmed_at: time };
      return route.fulfill({ json: view(body.version) });
    }
    if (url.pathname === '/api/projects/mock-project/search') {
      calls.search.push(body.version);
      const next = versions.get(body.version)!;
      if (!next.confirmation) return route.fulfill({ status: 409, json: { detail: '必须先确认' } });
      const selected = next.analysis!.knowledge_points.filter(point => point.selection === 'learn'); calls.selected = selected.map(point => point.id);
      if (!next.batches.length) for (let offset = 0; offset < selected.length; offset += 5) next.batches.push({ batch_id: `batch-${offset}`, status: options.running ? offset ? 'pending' : 'submitted' : 'completed', project_knowledge_point_ids: selected.slice(offset, offset + 5).map(point => point.id), job_id: options.running && offset ? null : `job-${offset}` });
      next.status = options.running ? 'running' : 'completed';
      return route.fulfill({ json: view(body.version) });
    }
    if (url.pathname === '/api/projects/mock-project/cancel') { calls.cancel += 1; const next = versions.get(body.version)!; next.status = 'cancelled'; for (const batch of next.batches) if (batch.status === 'pending') batch.status = 'cancelled'; return route.fulfill({ json: view(body.version) }); }
    calls.unexpected.push(`${method} ${url.pathname}`); return route.abort();
  });
  return { calls, versions, view };
}
async function enterProject(page: Page, initial = false) {
  await page.goto(initial ? '/?project=mock-project&version=1' : '/');
}
const firstPoint=(page:Page,id:string)=>page.locator(`.simple-knowledge-point[data-point-id="${id}"]`);
const gallery=(page:Page)=>page.getByRole('region',{name:'视频封面',exact:true});
const clean=(mock:Awaited<ReturnType<typeof mockProject>>,expectedHttp:number[]=[])=>{expect(mock.calls.unexpected).toEqual([]);expect(mock.calls.runtime).toEqual([]);const codes=mock.calls.console.map(message=>{const code=/^Failed to load resource: the server responded with a status of (\d+) \(/.exec(message);expect(code,message).not.toBeNull();return Number(code![1]);});expect(codes).toEqual(expectedHttp);};
async function fillBrief(page:Page){await page.getByLabel('项目名称',{exact:true}).fill('Excel 成绩分析工具');await page.getByLabel('功能需求',{exact:true}).fill('读取本地 Excel 成绩表，统计均值，绘图并导出。');}
async function analyze(page:Page){await fillBrief(page);await page.getByRole('button',{name:'分析项目',exact:true}).click();await expect(page.getByRole('heading',{name:'确认知识点 · v1'})).toBeVisible();}

test('当前专业术语：历史缺省字段直接确认不制造空技能、不隐式edit',async({page})=>{
 const mock=await mockProject(page,{initial:true});await enterProject(page,true);
 await page.getByRole('button',{name:'查找视频',exact:true}).click();await expect(gallery(page)).toBeVisible();
 expect(mock.calls.edit).toEqual([]);expect(mock.calls.confirm).toEqual([{version:1,reviewed_topic_technologies:{}}]);expect(mock.calls.search).toEqual([1]);
 expect(mock.versions.get(1)!.analysis!.knowledge_points.every(p=>!('learning_skills'in p))).toBe(true);clean(mock);
});
test('当前专业术语：保留原始输入，只搜索勾选项且不强制先修确认',async({page})=>{
 const mock=await mockProject(page);await enterProject(page);await page.getByLabel('项目名称',{exact:true}).fill('  我的成绩工具  ');await page.getByLabel('功能需求',{exact:true}).fill('  读取 Excel\n统计并绘图\n导出结果  ');await page.getByRole('button',{name:'分析项目',exact:true}).click();
 await expect(firstPoint(page,'kp1')).toBeVisible();expect(mock.calls.create[0].name).toBe('  我的成绩工具  ');expect(mock.calls.create[0].requirements).toBe('  读取 Excel\n统计并绘图\n导出结果  ');
 await firstPoint(page,'kp1').getByRole('checkbox').uncheck();await firstPoint(page,'kp3').getByRole('checkbox').uncheck();
 await expect(page.locator('.project-search-summary')).toContainText('已选择 1 个知识点');await expect(page.getByRole('checkbox',{name:/我了解未勾选/})).toHaveCount(0);
 await page.getByRole('button',{name:'查找视频',exact:true}).click();await expect(gallery(page).locator('a.course-cover')).toHaveCount(1);
 expect(mock.calls.selected).toEqual(['kp2']);expect(mock.calls.confirm[0].acknowledged_skipped_prerequisites).toBeUndefined();expect(mock.calls.edit[0].knowledge_points.map(p=>p.selection)).toEqual(['skip','learn','skip']);await expectGalleryTitlesOnly(page);clean(mock);
});
test('当前流程：超过五点分批、重复提交锁、刷新不重复检索',async({page})=>{
 const mock=await mockProject(page,{initial:true,count:7,running:true});await enterProject(page,true);await firstPoint(page,'kp1').getByRole('checkbox').uncheck();
 await page.getByRole('button',{name:'查找视频',exact:true}).dblclick();await expect(gallery(page)).toBeVisible();
 expect(mock.calls.confirm).toHaveLength(1);expect(mock.calls.confirm[0].acknowledged_skipped_prerequisites).toBeUndefined();expect(mock.versions.get(2)!.batches.map(b=>b.project_knowledge_point_ids.length)).toEqual([5,1]);
 await page.reload();await expect(gallery(page)).toBeVisible();expect(mock.calls.search).toEqual([2]);await expect(page.getByRole('status',{name:'正在读取视频封面'})).toBeVisible();clean(mock);
});
test('当前流程：全部取消勾选只保存，不创建空检索',async({page})=>{
 const mock=await mockProject(page,{initial:true});await enterProject(page,true);for(const id of ['kp1','kp2','kp3'])await firstPoint(page,id).getByRole('checkbox').uncheck();
 await page.getByRole('button',{name:'保存选择',exact:true}).click();await expect(page.getByRole('status')).toContainText('没有勾选知识点');expect(mock.calls.confirm).toHaveLength(1);expect(mock.calls.search).toEqual([]);clean(mock);
});
test('当前流程：旧mastered原样保留，仅显式选择才编辑且历史只读',async({page})=>{
 const mock=await mockProject(page,{initial:true});mock.versions.get(1)!.analysis!.knowledge_points[0].selection='mastered';await enterProject(page,true);
 await expect(firstPoint(page,'kp1').getByRole('checkbox')).not.toBeChecked();await expect(page.getByRole('button',{name:'保存修改',exact:true})).toBeDisabled();expect(mock.calls.edit).toEqual([]);
 await firstPoint(page,'kp1').getByRole('checkbox').check();await page.getByRole('button',{name:'保存修改',exact:true}).click();await expect(page.getByRole('heading',{name:'确认知识点 · v2'})).toBeVisible();expect(mock.calls.edit[0].knowledge_points[0].selection).toBe('learn');
 await page.getByRole('button',{name:'我的项目'}).click();await page.getByLabel('查看版本',{exact:true}).selectOption('1');await expect(firstPoint(page,'kp1').getByRole('checkbox')).not.toBeChecked();await expect(firstPoint(page,'kp1').getByRole('checkbox')).toBeDisabled();expect(mock.versions.get(1)!.analysis!.knowledge_points[0].selection).toBe('mastered');clean(mock);
});
test('当前流程：编辑后确认失败保留新版本，重试不重复edit',async({page})=>{
 const mock=await mockProject(page,{initial:true,failConfirmOnce:true});await enterProject(page,true);await firstPoint(page,'kp2').getByRole('textbox').fill('pandas 均值与缺失值');
 await page.getByRole('button',{name:'查找视频',exact:true}).click();await expect(page.getByRole('alert')).toContainText('修改已保存');await expect(page.getByRole('heading',{name:'确认知识点 · v2'})).toBeVisible();
 await page.getByRole('button',{name:'查找视频',exact:true}).click();await expect(gallery(page)).toBeVisible();expect(mock.calls.edit).toHaveLength(1);expect(mock.calls.confirm.map(c=>c.version)).toEqual([2,2]);expect(mock.calls.search).toEqual([2]);clean(mock,[422]);
});
test('当前流程：预算超限不删点，需求修改后阻止旧分析确认',async({page})=>{
 const mock=await mockProject(page,{initial:true,count:7,maxBatches:1});await enterProject(page,true);await expect(page.getByText('选择数量超过本次检索上限，请减少一些知识点。')).toBeVisible();await expect(page.getByRole('button',{name:'查找视频',exact:true})).toBeDisabled();await expect(page.locator('.simple-knowledge-point')).toHaveCount(7);
 await page.getByRole('button',{name:'查看或修改项目描述'}).click();await page.getByLabel('功能需求',{exact:true}).fill('需要重新分析的新需求');await page.getByRole('navigation',{name:'项目学习流程'}).getByRole('button',{name:/选择知识点/}).click();await expect(page.getByText(/需求已有未保存修改/)).toBeVisible();await expect(page.getByRole('button',{name:'查找视频',exact:true})).toBeDisabled();expect(mock.calls.search).toEqual([]);clean(mock);
});
test('当前流程：模型未配置仍保留输入与直接搜索入口',async({page})=>{
 const mock=await mockProject(page,{unconfigured:true});await enterProject(page);await expect(page.getByText(/项目分析不可用/)).toBeVisible();await fillBrief(page);await page.getByRole('button',{name:'保存项目并检查分析配置'}).click();await expect(page.getByRole('alert')).toContainText('未配置可用模型');await expect(page.getByLabel('功能需求',{exact:true})).toHaveValue(/读取本地 Excel/);expect(mock.calls.search).toEqual([]);await page.getByRole('button',{name:'直接搜索知识点',exact:true}).click();await expect(page.getByLabel('知识点',{exact:true})).toBeVisible();clean(mock);
});
test('当前流程：历史封面保留，新版本不混旧结果且无写操作',async({page},info)=>{
 const mock=await mockProject(page,{initial:true});await enterProject(page,true);await page.getByRole('button',{name:'查找视频',exact:true}).click();await expect(gallery(page).locator('a.course-cover')).toHaveCount(1);
 await page.getByRole('button',{name:'← 调整知识点',exact:true}).click();await firstPoint(page,'kp2').getByRole('textbox').fill('pandas 缺失值统计');await page.getByRole('button',{name:'保存修改',exact:true}).click();await expect(page.getByRole('heading',{name:'确认知识点 · v2'})).toBeVisible();await expect(page.locator('.video-cover-card')).toHaveCount(0);
 await page.getByRole('button',{name:'我的项目'}).click();await page.getByLabel('查看版本',{exact:true}).selectOption('1');await expect(gallery(page).locator('a.course-cover')).toHaveCount(1);await expect(page.getByRole('button',{name:'重新检索这些知识点'})).toHaveCount(0);await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('mobile-history-covers.png'),animations:'disabled'});expect(mock.calls.search).toEqual([1]);clean(mock);
});
test('当前流程：文字资源不冒充视频封面，已终态空结果不假装运行',async({page})=>{
 const mock=await mockProject(page,{initial:true});const v=mock.versions.get(1)!;v.status='partial';v.confirmation={version:1,confirmed_at:time};v.batches=[{batch_id:'done',status:'completed',project_knowledge_point_ids:['kp1','kp2','kp3'],job_id:'old-job'}];
 await page.route('**/api/projects/mock-project/results*',route=>{const view=mock.view();for(const p of view.points!)p.result={knowledge_point_id:p.project_knowledge_point_id,text:p.name,total_matches:0,items:[],partial_items:[{...resource(p.project_knowledge_point_id),resource:{...resource(p.project_knowledge_point_id).resource,resource_type:'article'}}]};return route.fulfill({json:view});});await enterProject(page,true);await expect(page.getByRole('status',{name:'这个知识点暂未找到视频'})).toBeVisible();await expect(gallery(page).locator('a.course-cover')).toHaveCount(0);expect(await page.locator('.stage-content .gallery-motion').innerText()).toBe('');clean(mock);
});
test('当前流程：读取暂时失败自动恢复，但不清除确认失败的错误',async({page})=>{
 const mock=await mockProject(page,{initial:true,failConfirmOnce:true});let reads=0,fail=false;await page.route('**/api/projects/mock-project/results*',route=>{reads++;if(fail){fail=false;return route.fulfill({status:503,json:{detail:'Mock：一次暂时读取失败'}});}return route.fulfill({json:mock.view()});});await enterProject(page,true);await expect(firstPoint(page,'kp1')).toBeVisible();fail=true;await page.getByRole('button',{name:'我的项目'}).click();await page.getByRole('button',{name:'重新读取',exact:true}).click();await expect(page.getByRole('alert')).toContainText('一次暂时读取失败');await expect(page.getByRole('alert')).toHaveCount(0);const before=reads;await page.getByRole('button',{name:'查找视频',exact:true}).click();await expect.poll(()=>reads).toBeGreaterThan(before);await expect(page.getByRole('alert')).toContainText('暂时超出项目预算');expect(mock.calls.search).toEqual([]);clean(mock,[503,422]);
});
for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'tablet',width:768,height:1024},{name:'mobile',width:390,height:844}])test(`当前流程：${viewport.name} 三步只保留专业术语与封面`,async({page},info)=>{
 const mock=await mockProject(page);await page.setViewportSize(viewport);await enterProject(page);await expect(page.getByRole('navigation',{name:'项目学习流程'}).getByRole('button',{name:/选择知识点/})).toBeDisabled();await fillBrief(page);await page.screenshot({path:info.outputPath('01-input.png'),animations:'disabled'});await page.getByRole('button',{name:'分析项目',exact:true}).click();await expect(firstPoint(page,'kp1')).toBeVisible();await expect(page.locator('.simple-knowledge-point')).toHaveCount(3);await expect(page.locator('.simple-knowledge-review textarea,.analysis-suggestions,.point-details')).toHaveCount(0);await page.screenshot({path:info.outputPath('02-professional-terms.png'),animations:'disabled'});await page.getByRole('button',{name:'查找视频',exact:true}).click();await expect(gallery(page).locator('a.course-cover')).toHaveCount(1);await expectGalleryTitlesOnly(page);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('03-covers.png'),animations:'disabled'});await page.getByRole('navigation',{name:'已选知识点'}).getByRole('button',{name:'pandas 计算均值',exact:true}).click();await expect(gallery(page).locator('a.course-cover')).toHaveCount(1);await page.getByRole('button',{name:'← 调整知识点',exact:true}).click();await expect(firstPoint(page,'kp1')).toBeVisible();clean(mock);
});
test('当前流程：跳过页头、键盘填写、选择和步骤焦点恢复',async({page})=>{
 const mock=await mockProject(page);await enterProject(page);await page.keyboard.press('Tab');await expect(page.getByRole('link',{name:'跳转到主要内容'})).toBeFocused();await page.keyboard.press('Enter');await expect(page.locator('#stage-title')).toBeFocused();await page.keyboard.press('Tab');await page.keyboard.type('Keyboard project');await page.keyboard.press('Tab');await page.keyboard.type('Read local data and export a chart.');await page.keyboard.press('Tab');await expect(page.locator('#project-language')).toBeFocused();await page.keyboard.press('Tab');await expect(page.getByRole('button',{name:'分析项目',exact:true})).toBeFocused();await page.keyboard.press('Enter');await expect(firstPoint(page,'kp1')).toBeVisible();await expect(page.locator('#stage-title')).toBeFocused();await firstPoint(page,'kp1').getByRole('checkbox').focus();await page.keyboard.press('Space');await page.getByRole('button',{name:'查找视频',exact:true}).focus();await page.keyboard.press('Enter');await expect(gallery(page)).toBeVisible();await expect(page.locator('#stage-title')).toBeFocused();expect(mock.calls.selected).toEqual(['kp2','kp3']);expect(mock.calls.confirm[0].acknowledged_skipped_prerequisites).toBeUndefined();clean(mock);
});
test('当前流程：输入与知识点草稿恢复，不隐式创建版本',async({page})=>{
 const mock=await mockProject(page);await enterProject(page);await fillBrief(page);await expect(page.locator('#project-level')).toHaveCount(0);await page.locator('#project-language').selectOption('en');await expect(page.locator('#project-background')).toHaveCount(0);await page.evaluate(()=>{const key='knowledge-guide-project-input-v1';const saved=JSON.parse(localStorage.getItem(key)!);saved.project_context='retained historical context';saved.student_level='intermediate';localStorage.setItem(key,JSON.stringify(saved));});await page.reload();await expect(page.getByLabel('项目名称',{exact:true})).toHaveValue('Excel 成绩分析工具');await expect(page.locator('#project-level')).toHaveCount(0);await expect(page.locator('#project-language')).toHaveValue('en');expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('knowledge-guide-project-input-v1')!).student_level)).toBe('intermediate');expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('knowledge-guide-project-input-v1')!).project_context)).toBe('retained historical context');expect(mock.calls.create).toEqual([]);await page.getByRole('button',{name:'分析项目',exact:true}).click();expect(mock.calls.create[0].project_context).toBe('retained historical context');expect(mock.calls.create[0].student_level).toBe('intermediate');await firstPoint(page,'kp2').getByRole('textbox').fill('pandas 缺失值处理');await firstPoint(page,'kp3').getByRole('checkbox').uncheck();await page.reload();await expect(firstPoint(page,'kp2').getByRole('textbox')).toHaveValue('pandas 缺失值处理');await expect(firstPoint(page,'kp3').getByRole('checkbox')).not.toBeChecked();expect(mock.calls.edit).toEqual([]);expect(mock.calls.confirm).toEqual([]);expect(mock.calls.search).toEqual([]);clean(mock);
});
test('当前流程：分析失败输入保留，显式重试复用已保存项目',async({page})=>{
 const mock=await mockProject(page,{failAnalyzeOnce:true});await enterProject(page);await fillBrief(page);await page.getByRole('button',{name:'分析项目',exact:true}).click();await expect(page.getByRole('alert')).toContainText('模型暂时不可用');await expect(page.getByLabel('项目名称',{exact:true})).toHaveValue('Excel 成绩分析工具');await page.getByLabel('功能需求',{exact:true}).fill('方向键控制、计分、重新开始。');await page.getByRole('button',{name:'分析项目',exact:true}).click();await expect(firstPoint(page,'kp1')).toBeVisible();expect(mock.calls.create).toHaveLength(1);expect(mock.calls.analyze).toBe(2);clean(mock,[503]);
});
test('当前流程：分析加载刷新恢复、减少动态、保留原输入',async({page},info)=>{
 const mock=await mockProject(page,{analysisPending:true});await page.emulateMedia({reducedMotion:'reduce'});await enterProject(page);await fillBrief(page);await page.getByRole('button',{name:'分析项目',exact:true}).click();await expect(page.getByText('正在梳理项目知识点',{exact:true})).toBeVisible();await page.reload();await expect(page.getByText('正在梳理项目知识点',{exact:true})).toBeVisible();await expect(page.locator('.project-description')).toHaveAttribute('inert','');await expect(page.locator('.project-description')).not.toBeVisible();await expect(page.locator('.project-description .primary-button')).toBeDisabled();await expect(page.getByLabel('功能需求',{exact:true})).toHaveValue(/读取本地 Excel/);const styles=await page.locator('.breathing-dots i,.stage-content,.primary-button').evaluateAll(nodes=>nodes.map(n=>({a:getComputedStyle(n).animationName,t:getComputedStyle(n).transitionDuration})));expect(styles.every(s=>s.a==='none'&&s.t.split(',').every(x=>parseFloat(x)===0))).toBe(true);await page.screenshot({path:info.outputPath('loading-reduced-motion.png'),animations:'disabled'});expect(mock.calls.create).toHaveLength(1);expect(mock.calls.analyze).toBe(1);clean(mock);
});
