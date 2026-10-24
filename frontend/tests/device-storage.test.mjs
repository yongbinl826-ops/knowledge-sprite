import test from 'node:test';
import assert from 'node:assert/strict';
import { DeviceStore, emptyDeviceState } from '../src/device/deviceStorage.ts';
import { devicePlatformStorage } from '../src/device/devicePlatformStorage.ts';
import { readFileSync } from 'node:fs';

class MemoryDisk {
  values = new Map(); fail = () => false; removed = [];
  async get(key) { if (this.fail('get', key)) throw Error('disk unavailable'); return this.values.get(key) ?? null; }
  async set(key, value) { if (this.fail('set', key)) throw Error('disk full'); this.values.set(key, value); }
  async remove(key) { if (this.fail('remove', key)) throw Error('cleanup failed'); this.removed.push(key); this.values.delete(key); }
}
const retained = JSON.parse(readFileSync(new URL('./fixtures/retained-r9-ui-projects.json', import.meta.url), 'utf8')).cases.browser_flashcards_intermediate;
function historyState(count = 3) {
  const state = emptyDeviceState(), id = retained.project_id;
  state.selected = { id };
  state.projects[id] = { schema: 1, summary: { project_id: id, current_version: count, name: retained.input.name }, input: retained.input,
    views: Array.from({ length: count }, (_, i) => { const view = structuredClone(retained); view.version.version = i + 1; view.versions = []; return view; }), drafts: {}, learned: {} };
  return state;
}

for (const format of ['flat', 'historical']) test(`${format} thirty-point analysis survives storage reload with the earlier version intact`, async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk), state = historyState(2), id = retained.project_id;
  const firstVersion = structuredClone(state.projects[id].views[0]);
  const analysis = state.projects[id].views[1].version.analysis;
  analysis.knowledge_points = Array.from({ length: 30 }, (_, index) => ({
    id: `k${index + 1}`, name: `概念${index + 1}`, description: '离线容量验证', selection: 'learn',
    ...(format === 'historical' ? { learning_order: index + 1, function_ids: [], prerequisite_ids: [] } : {}),
  }));
  if (format === 'flat') { analysis.analysis_format = 'concept_list_v1'; delete analysis.functions; }
  else delete analysis.analysis_format;
  await store.update(next => Object.assign(next, state));
  const saved = await new DeviceStore(disk).load();
  assert.deepEqual(saved.projects[id].views[0], firstVersion);
  assert.deepEqual(saved.projects[id].views[1].version.analysis, analysis);
  if (format === 'historical') {
    await assert.rejects(store.update(next => {
      next.projects[id].views[1].version.analysis.knowledge_points[29].learning_order = 31;
    }));
    assert.deepEqual((await new DeviceStore(disk).load()).projects[id].views[1].version.analysis, analysis);
  }
});
test('serial shadow commits keep concurrent independent edits across a new store instance', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  await Promise.all(Array.from({ length: 12 }, (_, n) => store.update(state => { state.selected[`key${n}`] = `value${n}`; })));
  const saved = await new DeviceStore(disk).load(); assert.equal(saved.revision, 12);
  for (let n = 0; n < 12; n++) assert.equal(saved.selected[`key${n}`], `value${n}`);
});
for (const failKey of ['slot', 'head']) test(`failed ${failKey} write cannot erase the previous committed record`, async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk); await store.update(state => { state.selected.id = 'original'; });
  const original = await store.load(); disk.fail = (action, key) => action === 'set' && key.includes(failKey);
  await assert.rejects(store.update(state => { state.selected.id = 'unsaved'; }), /可靠保存/);
  disk.fail = () => false; assert.deepEqual(await new DeviceStore(disk).load(), original);
});
test('corrupted active envelope recovers previous complete slot and preserves raw data', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  await store.update(state => { state.selected.id = 'previous'; }); const previous = await store.load();
  await store.update(state => { state.selected.id = 'latest'; }); const head = await disk.get('knowledge-sprite.device.v2.head');
  disk.values.set(`knowledge-sprite.device.v2.slot${head}`, 'corrupted retained raw');
  const restarted = new DeviceStore(disk); assert.deepEqual(await restarted.load(), previous); assert.match(restarted.recoveryNotice, /副本/);
  assert.equal(disk.values.get(`knowledge-sprite.device.v2.slot${head}`), 'corrupted retained raw');
});
test('size and unavailable storage are explicit failures; no memory-only success', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk); await store.update(state => { state.selected.id = 'keep'; });
  await assert.rejects(store.update(state => { state.selected.id = 'x'.repeat(4 * 1024 * 1024); }), /上限/);
  assert.equal((await store.load()).selected.id, 'keep'); disk.fail = () => true;
  await assert.rejects(store.load(), /disk unavailable/); await assert.rejects(store.update(() => {}), /可靠保存/);
});
test('internal v0 migration copies into new namespace and never deletes old bytes', async () => {
  const disk = new MemoryDisk(), old = { ...emptyDeviceState(), schema: 0 };
  disk.values.set('knowledge-sprite.device.v0', JSON.stringify(old)); const oldBytes = await disk.get('knowledge-sprite.device.v0');
  const store = new DeviceStore(disk); assert.equal((await store.load()).schema, 1);
  await store.update(state => { state.selected.id = 'migrated-copy'; });
  assert.equal(await disk.get('knowledge-sprite.device.v0'), oldBytes); assert.match(store.recoveryNotice, /旧版/);
});
test('unknown internal legacy schema fails closed and retains old namespace', async () => {
  const disk = new MemoryDisk(); disk.values.set('knowledge-sprite.device.v0', '{"schema":99}');
  await assert.rejects(new DeviceStore(disk).load(), /无法迁移/); assert.equal(await disk.get('knowledge-sprite.device.v0'), '{"schema":99}');
});
test('self-consistent checksum cannot make a malformed project safe to render', async () => {
  const disk = new MemoryDisk();
  const state = emptyDeviceState(); state.projects.bad = { schema: 1, summary: { project_id: 'bad' }, input: {}, views: [{ project_id: 'bad', version: { version: 1, analysis: { knowledge_points: 'not-an-array' } } }], drafts: {}, learned: {} };
  const payload = JSON.stringify(state), sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(payload)))].map(n => n.toString(16).padStart(2, '0')).join('');
  const bytes = JSON.stringify({ schema: 1, payload, sha256 }); disk.values.set('knowledge-sprite.device.v1.head', '0'); disk.values.set('knowledge-sprite.device.v1.slot0', bytes);
  await assert.rejects(new DeviceStore(disk).load(), /无法读取/); assert.equal(disk.values.get('knowledge-sprite.device.v1.slot0'), bytes);
});
test('Android requires committed true; failed bridge never falls back to localStorage or memory', async () => {
  let webCalls = 0; const values = new Map(); let committed = true;
  const adapter = devicePlatformStorage(() => 'android', { async get({ key }) { return { value: values.get(key) ?? null }; }, async set({ key, value }) { if (committed) values.set(key, value); return { committed }; } }, () => { webCalls++; throw Error('forbidden web fallback'); });
  const store = new DeviceStore(adapter); await store.update(state => { state.selected.id = 'durable-old'; }); const before = await store.load();
  committed = false; await assert.rejects(store.update(state => { state.selected.id = 'unconfirmed'; }), /可靠落盘/);
  assert.deepEqual(await store.load(), before); assert.equal(webCalls, 0);
});
test('unimplemented native platforms fail closed; only explicit web mode uses browser fallback', async () => {
  const bridge = { async get() { throw Error('no plugin'); }, async set() { throw Error('no plugin'); } };
  let webCalls = 0;
  const ios = devicePlatformStorage(() => 'ios', bridge, () => { webCalls++; throw Error('forbidden'); });
  await assert.rejects(ios.get('key'), /尚未接入/); await assert.rejects(ios.set('key', 'value'), /尚未接入/); assert.equal(webCalls, 0);
  const disk = new Map(); const browser = devicePlatformStorage(() => 'web', bridge, () => ({ getItem: key => disk.get(key) ?? null, setItem: (key, value) => disk.set(key, value) }));
  await browser.set('key', 'web-only'); assert.equal(await browser.get('key'), 'web-only');
});

test('v1 migration preserves original bytes and a fresh store reads every split version', async () => {
  const disk = new MemoryDisk(), state = historyState();
  const payload = JSON.stringify(state), hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(payload)))].map(n => n.toString(16).padStart(2, '0')).join('');
  const envelope = JSON.stringify({ schema: 1, payload, sha256: hash });
  disk.values.set('knowledge-sprite.device.v1.head', '0'); disk.values.set('knowledge-sprite.device.v1.slot0', envelope);
  const store = new DeviceStore(disk); assert.deepEqual(await store.load(), state);
  await store.update(next => { next.selected.version = 2; });
  assert.equal(disk.values.get('knowledge-sprite.device.v1.slot0'), envelope);
  assert.equal((await new DeviceStore(disk).load()).projects[retained.project_id].views.length, 3);
  assert.equal((await new DeviceStore(disk).load()).selected.version, 2);
});

test('a small draft edit never rewrites existing version blocks', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  await store.update(next => Object.assign(next, historyState(20)));
  const priorKeys = new Set(disk.values.keys()), writes = [];
  const set = disk.set.bind(disk); disk.set = async (key, value) => { writes.push({ key, bytes: Buffer.byteLength(value) }); await set(key, value); };
  await store.update(next => { next.inputDraft = { ...retained.input, name: 'new draft' }; });
  assert.equal(writes.filter(row => row.key.includes('.block.') && priorKeys.has(row.key)).length, 0);
  assert(writes.reduce((sum, row) => sum + row.bytes, 0) < 20000);
  assert.equal((await new DeviceStore(disk).load()).inputDraft.name, 'new draft');
});

test('a failed block or manifest commit restores only a complete previous state', async () => {
  for (const boundary of ['.block.', '.slot', '.head']) {
    const disk = new MemoryDisk(), store = new DeviceStore(disk);
    await store.update(next => Object.assign(next, historyState())); const previous = await store.load();
    disk.fail = (action, key) => action === 'set' && key.includes(boundary);
    await assert.rejects(store.update(next => { next.inputDraft = { ...retained.input, name: 'never committed' }; }));
    assert.deepEqual(disk.removed, []);
    disk.fail = () => false; assert.deepEqual(await new DeviceStore(disk).load(), previous);
  }
});

test('repeated drafts keep only two generations while every historical version remains recoverable', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  await store.update(next => Object.assign(next, historyState(5)));
  const historyBlocks = [...disk.values.keys()].filter(key => key.includes('.block.'));
  let previous;
  for (let n = 0; n < 12; n++) {
    previous = await store.load();
    await store.update(next => { next.inputDraft = { ...retained.input, name: `draft ${n}` }; });
  }
  assert(disk.removed.length >= 10);
  assert(historyBlocks.every(key => disk.values.has(key)));
  assert.equal([...disk.values.keys()].filter(key => key.includes('.block.')).length, historyBlocks.length + 2);
  const head = await disk.get('knowledge-sprite.device.v2.head');
  disk.values.set(`knowledge-sprite.device.v2.slot${head}`, 'corrupt active');
  assert.deepEqual(await new DeviceStore(disk).load(), previous);
});

test('a reclaimed hash is written again when reused, while shared hashes are retained', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  const save = name => store.update(next => { next.inputDraft = { ...retained.input, name }; });
  await save('A'); const a = [...disk.values.keys()].find(key => key.includes('.block.'));
  await save('A'); await save('B'); assert(disk.values.has(a));
  await save('C'); assert(!disk.values.has(a));
  await save('A'); assert(disk.values.has(a));
  assert.equal((await new DeviceStore(disk).load()).inputDraft.name, 'A');
});

test('cleanup failure cannot turn a successful commit into lost or unacknowledged data', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  for (const name of ['A', 'B']) await store.update(next => { next.inputDraft = { ...retained.input, name }; });
  disk.fail = action => action === 'remove';
  await store.update(next => { next.inputDraft = { ...retained.input, name: 'C' }; });
  assert.equal((await new DeviceStore(disk).load()).inputDraft.name, 'C');
});

test('cleanup skips deletion unless both retained manifest envelopes verify from disk', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  for (const name of ['A', 'B']) await store.update(next => { next.inputDraft = { ...retained.input, name }; });
  let committed = false;
  const set = disk.set.bind(disk), get = disk.get.bind(disk);
  disk.set = async (key, value) => { await set(key, value); if (key.endsWith('.head')) committed = true; };
  disk.get = async key => committed && key.endsWith('.slot1') ? 'temporarily unreadable' : get(key);
  await store.update(next => { next.inputDraft = { ...retained.input, name: 'C' }; });
  assert.deepEqual(disk.removed, []); disk.get = get;
  assert.equal((await new DeviceStore(disk).load()).inputDraft.name, 'C');
});

test('large warm histories read only manifests and the changed draft, beyond the raw-block cache limit', async t => {
  const measure = async (count, contentBytes) => {
    const disk = new MemoryDisk(), seed = new DeviceStore(disk), state = historyState(1), id = retained.project_id;
    state.projects[id].summary.current_version = count;
    state.projects[id].views = Array.from({ length: count }, (_, index) => ({
      project_id: id, current_version: count, versions: [], input: retained.input, points: [],
      version: { version: index + 1, status: 'completed', input: retained.input, analysis: null, batches: [] },
      preservedFixtureContent: 'x'.repeat(contentBytes),
    }));
    await seed.update(next => Object.assign(next, state));
    for (const name of ['draft A', 'draft B']) await seed.update(next => { next.inputDraft = { ...retained.input, name }; });
    // Cold hydration validates content once, then editing must not reread it.
    const store = new DeviceStore(disk); await store.load();
    const historyKeys = new Set([...disk.values.keys()].filter(key => key.includes('.block.')));
    const reads = [], get = disk.get.bind(disk);
    disk.get = async key => { const value = await get(key); reads.push({ key, bytes: Buffer.byteLength(value || '') }); return value; };
    await store.update(next => { next.inputDraft = { ...retained.input, name: 'draft C' }; });
    assert.equal(reads.filter(row => historyKeys.has(row.key)).length, 0, 'no existing history block should cross the bridge');
    assert.equal(reads.length, 9, 'read count is independent of version count');
    const bytes = reads.reduce((sum, row) => sum + row.bytes, 0);
    assert(bytes < 120000, `only compact manifests and one draft should be read: ${bytes}`);
    return { reads: reads.length, bytes };
  };
  const small = await measure(3, 1024), large = await measure(300, 1024), bulky = await measure(300, 64 * 1024);
  t.diagnostic(JSON.stringify({ small, large, bulky }));
  assert.equal(small.reads, large.reads);
  assert.equal(large.bytes, bulky.bytes, 'increasing saved content from 300 KiB to 18.75 MiB must not increase edit reads');
});

test('a malformed but checksummed retained manifest disables cleanup rather than dropping references', async () => {
  const disk = new MemoryDisk(), store = new DeviceStore(disk);
  for (const name of ['A', 'B']) await store.update(next => { next.inputDraft = { ...retained.input, name }; });
  let committed = false; const set = disk.set.bind(disk), get = disk.get.bind(disk);
  disk.set = async (key, value) => { await set(key, value); if (key.endsWith('.head')) committed = true; };
  disk.get = async key => {
    const raw = await get(key);
    if (!committed || !key.endsWith('.slot1')) return raw;
    const envelope = JSON.parse(raw), manifest = JSON.parse(envelope.payload); manifest.projects = { broken: { metadata: 'invalid-hash', views: [] } };
    const payload = JSON.stringify(manifest), sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(payload)))].map(n => n.toString(16).padStart(2, '0')).join('');
    return JSON.stringify({ schema: 2, payload, sha256 });
  };
  await store.update(next => { next.inputDraft = { ...retained.input, name: 'C' }; });
  assert.deepEqual(disk.removed, []); disk.get = get;
  assert.equal((await new DeviceStore(disk).load()).inputDraft.name, 'C');
});

test('platform cleanup accepts only v2 blocks and requires native commit acknowledgement', async () => {
  const values = new Map(), key = `knowledge-sprite.device.v2.block.${'a'.repeat(64)}`;
  const browser = devicePlatformStorage(() => 'web', {}, () => ({ removeItem: name => values.delete(name) }));
  values.set(key, 'unreferenced'); await browser.remove(key); assert(!values.has(key));
  await assert.rejects(browser.remove('knowledge-sprite.device.v1.slot0'), /仅允许/);
  let called = false;
  const android = devicePlatformStorage(() => 'android', { async remove() { called = true; return { committed: false }; } }, () => { throw Error('web fallback'); });
  await assert.rejects(android.remove(key), /确认/); assert(called);
});
