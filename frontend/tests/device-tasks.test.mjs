import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DeviceStore } from '../src/device/deviceStorage.ts';
import { LocalProjectService } from '../src/device/localProjectService.ts';
import { MobileApi, createTicket, mobileApiBase, retryAfter, deviceDevelopment } from '../src/device/mobileApi.ts';

const retained = JSON.parse(readFileSync(new URL('./fixtures/retained-r9-ui-projects.json', import.meta.url), 'utf8')).cases.browser_flashcards_intermediate;
const input = { name: 'Synthetic device project', requirements: 'Local public QA input only', student_level: 'intermediate', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili', 'icourse163'] };
class Disk { values = new Map(); fail = false; async get(key) { return this.values.get(key) ?? null; } async set(key, value) { if (this.fail) throw Error('full'); this.values.set(key, value); } }
function setup(handler) {
  const disk = new Disk(), store = new DeviceStore(disk), calls = [];
  const api = new MobileApi('https://service.example', async (url, options) => {
    calls.push({ url, options }); return handler({ url: new URL(url), options, store, disk, calls });
  });
  return { disk, store, api, calls, service: new LocalProjectService(store, api) };
}
const reply = (id, body, status = 'completed', result = retained) => new Response(JSON.stringify({ task_id: id, kind: body.kind, expires_at: new Date(Date.now() + 7200000).toISOString(), status, error: null, result }), { status: 200, headers: { 'Content-Type': 'application/json' } });

test('identical result revisions and conditional 304 reads never rewrite device history', async () => {
  const expires = new Date(Date.now() + 7200000).toISOString(); let gets = 0, body;
  const x = setup(({ url, options }) => {
    if (options.method === 'POST') body = JSON.parse(options.body);
    if (body.kind === 'analysis') return reply(url.pathname.split('/').at(-1), body);
    if (options.method === 'GET') { gets++; if (gets === 2) { assert.equal(options.headers['If-None-Match'], '"stable"'); return new Response(null, { status: 304 }); } }
    const result = structuredClone(retained); result.pipeline = { terminal: true, catalog_pending: true };
    return new Response(JSON.stringify({ task_id: url.pathname.split('/').at(-1), kind: body.kind, expires_at: expires, status: 'completed', error: null, result, snapshot_revision: 'stable' }), { headers: { ETag: '"stable"' } });
  });
  await x.service.analyze(input); await x.service.confirmAndSearch((await x.service.snapshot()).view.version.analysis, false);
  const before = (await x.store.load()).revision;
  assert.equal(await x.service.poll(), false); assert.equal(await x.service.poll(), false);
  assert.equal((await x.store.load()).revision, before); assert.equal(gets, 2);
});

test('switching views flushes the latest merged input before completing', async () => {
  const x = setup(() => { throw Error('no network'); });
  const saves = Array.from({ length: 30 }, (_, i) => x.service.inputDraft({ ...input, name: `edit ${i}` }));
  await x.service.select(''); await Promise.all(saves);
  const state = await new DeviceStore(x.disk).load();
  assert.equal(state.inputDraft.name, 'edit 29'); assert.equal(state.revision, 2); assert.equal(x.calls.length, 0);
});

test('release API is HTTPS only, development HTTP is explicit loopback only', () => {
  assert.equal(mobileApiBase('https://api.example/base', false), 'https://api.example/base');
  for (const url of ['http://api.example', 'http://127.0.0.1', 'https://user:pass@api.example', 'https://api.example/?token=a']) assert.throws(() => mobileApiBase(url, false));
  assert.equal(mobileApiBase('http://127.0.0.1:5194', true), 'http://127.0.0.1:5194');
  assert.throws(() => mobileApiBase('http://192.168.1.2', true)); assert.throws(() => mobileApiBase(undefined, false));
  assert.equal(mobileApiBase('http://127.0.0.1:8014', deviceDevelopment(false, 'true')), 'http://127.0.0.1:8014');
  for (const flag of [undefined, 'false', '1']) assert.throws(() => mobileApiBase('http://127.0.0.1:8014', deviceDevelopment(false, flag)));
});
test('each new action gets a fresh UUID and 32-byte capability; token is Authorization only', async () => {
  const a = createTicket('local', 1, { kind: 'analysis', input }), b = createTicket('local', 1, { kind: 'analysis', input });
  assert.match(a.capability, /^[A-Za-z0-9_-]{43}$/); assert.notEqual(a.capability, b.capability); assert.notEqual(a.id, b.id);
  let sent; const api = new MobileApi('https://service.example', async (url, options) => { sent = { url, options }; return reply(a.id, JSON.parse(a.body)); });
  await api.task(a, 'GET'); assert(!sent.url.includes(a.capability)); assert.equal(sent.options.headers.Authorization, `Bearer ${a.capability}`);
  assert.equal(sent.options.credentials, 'omit'); assert.equal(sent.options.redirect, 'error');
});
test('ticket, immutable body and send intent are durable before the single POST; terminal result keeps local identity and clears capability', async () => {
  const x = setup(async ({ url, options, store }) => {
    const saved = Object.values((await store.load()).projects)[0].ticket;
    assert.equal(saved.phase, 'submitted'); assert.equal(saved.body, options.body); assert.equal(saved.id, url.pathname.split('/').at(-1));
    assert.deepEqual(JSON.parse(options.body), { kind: 'analysis', input }); return reply(saved.id, JSON.parse(saved.body));
  });
  await x.service.analyze(input); const result = await x.service.snapshot();
  assert.notEqual(result.view.project_id, retained.project_id); assert.equal(result.view.version.version, 1); assert.deepEqual(result.view.version.input, input);
  assert.deepEqual(result.view.version.analysis, retained.version.analysis); assert.equal(result.project.ticket.capability, ''); assert.equal(x.calls.length, 1);
});
test('failed ticket persistence means zero network, while old records remain', async () => {
  const x = setup(() => { throw Error('must not call'); }); await x.service.inputDraft(input); const before = await x.store.load(); x.disk.fail = true;
  await assert.rejects(x.service.analyze(input), /可靠保存/); x.disk.fail = false;
  assert.deepEqual(await x.store.load(), before); assert.equal(x.calls.length, 0);
});
test('uncertain POST is never repeated, including a new service/cold start; recovery GET uses original capability', async () => {
  let body; const x = setup(({ url, options }) => { if (options.method === 'POST') { body = JSON.parse(options.body); throw new TypeError('offline after possible acceptance'); } return reply(url.pathname.split('/').at(-1), body); });
  await assert.rejects(x.service.analyze(input), /未确认/); const before = await x.service.snapshot(); assert.equal(before.project.ticket.phase, 'uncertain');
  const restarted = new LocalProjectService(new DeviceStore(x.disk), x.api); await restarted.poll();
  assert.deepEqual(x.calls.map(c => c.options.method), ['POST', 'GET']); assert.equal(x.calls[0].options.headers.Authorization, x.calls[1].options.headers.Authorization);
  assert.equal((await restarted.snapshot()).project.ticket.phase, 'complete');
});

test('completed recommendations keep the original capability for late catalogs across restart and stop reads afterwards', async () => {
  let finalCatalog = false;
  const bodies = new Map();
  const x = setup(({ url, options }) => {
    const id = url.pathname.split('/').at(-1);
    if (options.method === 'POST') bodies.set(id, JSON.parse(options.body));
    const body = bodies.get(id);
    const result = structuredClone(retained);
    if (body.kind === 'search') {
      result.version.status = 'completed';
      result.pipeline = { terminal: true, catalog_pending: !finalCatalog, catalog_status: finalCatalog ? 'completed' : 'running' };
      result.points = [{ project_knowledge_point_id: 'p1', result: { knowledge_point_id: 'p1', recommendation_policy: 'helpful-video-v1', video_recommendations: [{
        resource: { resource_id: 'same-card', title: 'Python 教程', url: 'https://www.bilibili.com/video/BV1234567890/', platform: 'bilibili' },
        matched_chapters: finalCatalog ? [{ chapter_id: 'ch3', title: '第 3 章 循环结构' }] : [],
      }] } }];
    }
    return reply(id, body, 'completed', result);
  });
  await x.service.analyze(input);
  await x.service.confirmAndSearch((await x.service.snapshot()).view.version.analysis, false);
  const before = await x.service.snapshot();
  assert.equal(before.view.pipeline.terminal, true);
  assert.equal(before.project.ticket.phase, 'submitted');
  assert(before.project.ticket.capability);
  const restarted = new LocalProjectService(new DeviceStore(x.disk), x.api);
  await restarted.poll();
  assert.equal((await restarted.snapshot()).project.ticket.id, before.project.ticket.id);
  finalCatalog = true;
  await restarted.poll();
  const after = await restarted.snapshot();
  assert.equal(after.view.project_id, before.view.project_id);
  assert.equal(after.view.version.version, before.view.version.version);
  assert.equal(after.view.points[0].result.video_recommendations[0].resource.resource_id, 'same-card');
  assert.equal(after.view.points[0].result.video_recommendations[0].matched_chapters[0].title, '第 3 章 循环结构');
  assert.equal(after.project.ticket.phase, 'complete'); assert.equal(after.project.ticket.capability, '');
  await restarted.poll();
  assert.deepEqual(x.calls.map(call => call.options.method), ['POST', 'POST', 'GET', 'GET']);
  assert.equal(x.calls[1].options.headers.Authorization, x.calls[2].options.headers.Authorization);
  assert.equal(x.calls[1].options.headers.Authorization, x.calls[3].options.headers.Authorization);
});

function catalogMutationSetup(failCancel = false) {
  const bodies = new Map();
  const x = setup(({ url, options }) => {
    const cancelling = url.pathname.endsWith('/cancel');
    const id = url.pathname.split('/').at(cancelling ? -2 : -1);
    if (!cancelling && options.method === 'POST') bodies.set(id, JSON.parse(options.body));
    const body = bodies.get(id), result = structuredClone(retained);
    if (cancelling && failCancel) return new Response('{"detail":"cancel unavailable"}', { status: 503 });
    if (body.kind === 'search') {
      result.version.status = 'completed';
      result.pipeline = { terminal: true, catalog_pending: !cancelling, catalog_status: cancelling ? 'cancelled' : 'running' };
    }
    return reply(id, body, 'completed', result);
  });
  return x;
}

for (const action of ['retry', 'analyze', 'save']) test(`explicit ${action} cancels only pending catalogs before replacing a completed local version`, async () => {
  const x = catalogMutationSetup();
  await x.service.analyze(input);
  await x.service.confirmAndSearch((await x.service.snapshot()).view.version.analysis, false);
  const before = await x.service.snapshot(), oldTicket = before.project.ticket;
  if (action === 'retry') await x.service.retrySearch();
  else if (action === 'analyze') await x.service.analyze(input);
  else await x.service.save(before.view.version.analysis);
  const after = await x.service.snapshot();
  assert.equal(new URL(x.calls[2].url).pathname, `/api/mobile/tasks/${oldTicket.id}/cancel`);
  assert.equal(x.calls[2].options.headers.Authorization, `Bearer ${oldTicket.capability}`);
  assert.equal(after.view.version.version, before.view.version.version + 1);
  assert.equal(after.project.views.find(view => view.version.version === before.view.version.version).version.status, 'completed');
  assert.equal(after.project.views.find(view => view.version.version === before.view.version.version).pipeline.catalog_pending, false);
  assert.deepEqual(after.project.views.find(view => view.version.version === before.view.version.version).points, before.view.points);
  assert.equal(x.calls.length, action === 'save' ? 3 : 4);
  if (action !== 'save') assert.notEqual(after.project.ticket.id, oldTicket.id);
});

test('catalog cancellation failure keeps completed cards and blocks a second search submission', async () => {
  const x = catalogMutationSetup(true);
  await x.service.analyze(input);
  await x.service.confirmAndSearch((await x.service.snapshot()).view.version.analysis, false);
  const before = await x.service.snapshot();
  await assert.rejects(x.service.retrySearch(), /取消状态尚未确认/);
  const after = await x.service.snapshot();
  assert.equal(after.project.ticket.id, before.project.ticket.id);
  assert.equal(after.project.ticket.phase, 'uncertain');
  assert.equal(after.view.version.version, before.view.version.version);
  assert.equal(after.view.version.status, 'completed');
  assert.deepEqual(after.view.points, before.view.points);
  assert.equal(x.calls.length, 3);
  assert(x.calls[2].url.endsWith('/cancel'));
});
test('result storage failure keeps ticket/cap and can recover by GET without a second POST', async () => {
  let body; const x = setup(({ url, options, disk }) => { body ||= JSON.parse(options.body); if (options.method === 'POST') disk.fail = true; return reply(url.pathname.split('/').at(-1), body); });
  await assert.rejects(x.service.analyze(input)); x.disk.fail = false;
  assert((await x.service.snapshot()).project.ticket.capability); await x.service.poll();
  assert.deepEqual(x.calls.map(c => c.options.method), ['POST', 'GET']); assert.equal((await x.service.snapshot()).project.ticket.capability, '');
});
test('offline selection, version history and learned flag are independent and never contact server', async () => {
  const x = setup(({ url, options }) => reply(url.pathname.split('/').at(-1), JSON.parse(options.body)));
  await x.service.analyze(input); const first = await x.service.snapshot(), id = first.view.project_id;
  const edited = structuredClone(first.view.version.analysis); edited.knowledge_points[0].selection = 'skip';
  await x.service.draft(id, 1, edited); await x.service.learned(id, 1, edited.knowledge_points[0].id, true);
  assert.equal((await x.service.snapshot()).project.learned[`1:${edited.knowledge_points[0].id}`].learned, true);
  assert.equal((await x.service.snapshot()).project.drafts[1].knowledge_points[0].selection, 'skip');
  await x.service.save(edited); await x.service.select(id, 1); const history = await x.service.snapshot();
  assert.deepEqual(history.view.version.analysis, first.view.version.analysis); assert.equal(history.view.current_version, 2); assert.equal(x.calls.length, 1);
});
test('404 after accepted task preserves local input/history and requires a new explicit task', async () => {
  const x = setup(({ url, options }) => options.method === 'POST' ? reply(url.pathname.split('/').at(-1), JSON.parse(options.body), 'queued', null) : new Response('{"detail":"任务不存在或已失效"}', { status: 404 }));
  await x.service.analyze(input); await assert.rejects(x.service.poll()); const snapshot = await x.service.snapshot();
  assert.equal(snapshot.project.ticket.phase, 'expired'); assert.equal(snapshot.project.ticket.capability, ''); assert.equal(snapshot.view.version.status, 'analysis_failed');
  assert.deepEqual(snapshot.view.version.input, input); assert.match(snapshot.view.version.error, /手动|明确/); assert.deepEqual(x.calls.map(c => c.options.method), ['POST', 'GET']);
});
test('absolute local two-hour TTL cannot be extended by server and expires without GET', async () => {
  const x = setup(({ url, options }) => reply(url.pathname.split('/').at(-1), JSON.parse(options.body), 'queued', null));
  await x.service.analyze(input); await x.store.update(state => { Object.values(state.projects)[0].ticket.expiresAt = new Date(Date.now() - 1).toISOString(); });
  await x.service.poll(); assert.equal(x.calls.length, 1); assert.equal((await x.service.snapshot()).project.ticket.phase, 'expired');
});
test('429 stores Retry-After and no early poll or automatic POST occurs', async () => {
  let body; const x = setup(({ url, options }) => { body ||= JSON.parse(options.body); return options.method === 'POST' ? reply(url.pathname.split('/').at(-1), body, 'queued', null) : new Response('{}', { status: 429, headers: { 'Retry-After': '60' } }); });
  await x.service.analyze(input); await assert.rejects(x.service.poll()); const snapshot = await x.service.snapshot();
  assert(Date.parse(snapshot.project.ticket.nextPollAt) - Date.now() > 59000); await x.service.poll(); assert.equal(x.calls.length, 2);
  assert.equal(retryAfter('0'), 1500); assert.equal(retryAfter('bogus'), 1500);
});
test('server task ID mismatch cannot overwrite original local data or clear capability', async () => {
  const x = setup(({ options }) => reply('foreign-task', JSON.parse(options.body)));
  await assert.rejects(x.service.analyze(input)); const snap = await x.service.snapshot();
  assert.equal(snap.view.version.analysis, null); assert(snap.project.ticket.capability); assert.equal(snap.project.ticket.phase, 'uncertain');
});
test('public library request has only explicit public filters, no personal state or task token', async () => {
  const x = setup(({ url, options }) => { assert.equal(options.method, 'GET'); assert.equal(url.pathname, '/api/mobile/courses'); assert.deepEqual([...url.searchParams.keys()], ['query', 'offset', 'limit', 'platform']); assert(!options.headers); return new Response('{"items":[],"total":0,"has_more":false}'); });
  await x.api.courses('pandas', 'icourse163', 12); assert.equal(x.calls.length, 1);
});
test('empty public platform filter is omitted and no private identifiers are added', async () => {
  const x = setup(({ url }) => { assert.equal(url.searchParams.has('platform'), false); assert.equal(url.searchParams.get('limit'), '12'); return new Response('{"items":[],"total":0,"has_more":false}'); });
  await x.api.courses('', '', 0);
});
test('explicit local deletion releases project space only after task is resolved; it never calls shared API', async () => {
  const x = setup(({ url, options }) => reply(url.pathname.split('/').at(-1), JSON.parse(options.body), 'queued', null));
  await x.service.analyze(input); const id = (await x.service.snapshot()).view.project_id;
  await assert.rejects(x.service.remove(id), /先明确取消/); assert.equal(Object.keys((await x.service.snapshot()).state.projects).length, 1);
  await x.store.update(state => { state.projects[id].ticket.phase = 'expired'; });
  await x.service.remove(id); const state = (await x.service.snapshot()).state;
  assert.equal(state.selected.id, ''); assert.equal(Object.keys(state.projects).length, 0); assert.equal(x.calls.length, 1);
});
test('frozen actual-ASGI response shapes roundtrip analysis/search/direct through device mapping; no upstream', async () => {
  const fixture = JSON.parse(readFileSync(new URL('./device-api-fixture.json', import.meta.url), 'utf8')).responses;
  const issued = new Map();
  const x = setup(({ url, options }) => {
    const id = url.pathname.split('/').at(-1);
    if (options.method === 'POST') issued.set(id, JSON.parse(options.body).kind);
    const kind = issued.get(id), key = kind === 'direct_search' ? 'direct' : kind;
    const shape = structuredClone(fixture[`${key}_${options.method === 'POST' ? 'created' : 'completed'}`]);
    shape.task_id = id; shape.expires_at = new Date(Date.now() + 7200000).toISOString(); return new Response(JSON.stringify(shape));
  });
  const localInput = fixture.analysis_completed.result.input;
  await x.service.analyze(localInput); await x.service.poll(); const analyzed = await x.service.snapshot();
  assert.deepEqual(analyzed.view.version.analysis, fixture.analysis_completed.result.version.analysis);
  assert.notEqual(analyzed.view.project_id, fixture.analysis_completed.result.project_id);
  await x.service.confirmAndSearch(analyzed.view.version.analysis, false); await x.service.poll();
  const searched = await x.service.snapshot(); assert.deepEqual(searched.view.points, fixture.search_completed.result.points);
  // A second explicit search from review preserves the prior result as local history.
  await x.service.confirmAndSearch(searched.view.version.analysis, false); await x.service.poll();
  assert.equal((await x.service.snapshot()).view.version.version, 2);
  const request = { knowledge_points: ['Python list indexing'], student_level: 'beginner', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili', 'icourse163'] };
  await x.service.directSearch(request); await x.service.poll(); const direct = await x.service.snapshot();
  assert.equal(direct.view.points[0].project_knowledge_point_id, 'direct-1');
  assert.deepEqual(direct.view.points[0].result, fixture.direct_completed.result.groups[0]);
  assert.equal(Object.keys(direct.state.projects).length, 2);
});
test('offline confirmation with selected concepts is durable and makes no task; repeating confirmation preserves history', async () => {
  const x = setup(({ url, options }) => reply(url.pathname.split('/').at(-1), JSON.parse(options.body)));
  await x.service.analyze(input); const initial = await x.service.snapshot(), analysis = initial.view.version.analysis;
  await x.service.confirmLocal(analysis, false); const confirmed = await x.service.snapshot();
  assert.equal(confirmed.view.version.status, 'confirmed'); assert.equal(confirmed.view.version.confirmation.local_only, true);
  assert.deepEqual(confirmed.view.version.confirmation.selected_ids, analysis.knowledge_points.filter(p => p.selection === 'learn').map(p => p.id));
  assert.equal(x.calls.length, 1); assert.equal(confirmed.project.ticket.id, initial.project.ticket.id);
  await x.service.confirmLocal(analysis, false); assert.equal((await x.service.snapshot()).view.version.version, confirmed.view.version.version); assert.equal(x.calls.length, 1);
  assert.equal((await x.service.snapshot()).view.pipeline, undefined);
});

test('minimal concept list persists through restart and search without synthesized legacy fields', async () => {
  const minimal = { analysis_format: 'concept_list_v1', scope: '合成范围', technical_plan: '本地处理', assumptions: [], knowledge_points: [
    { id: 'k2', name: '输入校验', description: '检查输入字段并反馈错误。', technology: 'Python', selection: 'learn' },
    { id: 'k1', name: '模板渲染', description: '按模板生成文档。', technology: 'python-docx', selection: 'learn' },
  ] };
  const x = setup(({ url, options }) => {
    const body = JSON.parse(options.body), result = structuredClone(retained);
    result.version.analysis = structuredClone(body.analysis || minimal); result.version.status = 'analyzed'; result.points = [];
    delete result.functions;
    return reply(url.pathname.split('/').at(-1), body, 'completed', result);
  });
  await x.service.analyze(input);
  const restarted = new LocalProjectService(new DeviceStore(x.disk), x.api), before = await restarted.snapshot();
  assert.deepEqual(before.view.version.analysis, minimal);
  await restarted.draft(before.view.project_id, 1, minimal);
  assert.deepEqual((await restarted.snapshot()).project.drafts[1], minimal);
  await restarted.confirmAndSearch(minimal, false);
  const sent = JSON.parse(x.calls.at(-1).options.body);
  assert.deepEqual(sent.analysis, minimal); assert.equal(sent.acknowledged_skipped_prerequisites, undefined);
  assert.deepEqual(sent.analysis.knowledge_points.map(point => point.id), ['k2', 'k1']);
  assert.equal(sent.analysis.functions, undefined);
  assert.deepEqual((await new LocalProjectService(new DeviceStore(x.disk), x.api).snapshot()).view.version.analysis, minimal);
});

test('direct search creates minimal concepts and retry uses array order despite historical order metadata', async () => {
  const x = setup(({ url, options }) => {
    const body = JSON.parse(options.body);
    return reply(url.pathname.split('/').at(-1), body, 'completed', {
      job_id: 'synthetic-direct', status: 'completed', groups: body.request.knowledge_points.map((name, index) => ({
        knowledge_point_id: `returned-${index}`, text: name, items: [], total_matches: 0,
      })),
    });
  });
  const request = { knowledge_points: ['模板渲染', '输入校验', '文件下载'], student_level: 'any', language: 'zh', project_context: '', technical_version: '', preferred_platforms: ['bilibili', 'icourse163'] };
  await x.service.directSearch(request);
  const initial = (await x.service.snapshot()).view.version.analysis;
  assert.equal(initial.analysis_format, 'concept_list_v1'); assert.equal(initial.functions, undefined);
  for (const point of initial.knowledge_points) assert.deepEqual(Object.keys(point).sort(), ['description', 'id', 'name', 'selection', 'technology']);
  const legacy = { ...initial, knowledge_points: initial.knowledge_points.map((point, index) => ({
    ...point, learning_order: [24, 1, 2][index], prerequisite_ids: ['legacy-only'], selection: index === 1 ? 'skip' : 'learn',
  })) };
  delete legacy.analysis_format;
  await x.service.save(legacy); await x.service.retrySearch();
  const sent = JSON.parse(x.calls.at(-1).options.body);
  assert.deepEqual(sent.request.knowledge_points, ['模板渲染', '文件下载']);
  const searched = (await x.service.snapshot()).view;
  assert.deepEqual(searched.version.analysis, legacy);
  assert.equal(searched.points[0].result.text, '模板渲染');
  assert.equal(searched.points[1].status, 'not_selected'); assert.equal(searched.points[1].result, null);
  assert.equal(searched.points[2].result.text, '文件下载');
});
