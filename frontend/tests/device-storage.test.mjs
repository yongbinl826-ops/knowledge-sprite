import test from 'node:test';
import assert from 'node:assert/strict';
import { DeviceStore, emptyDeviceState } from '../src/device/deviceStorage.ts';
import { devicePlatformStorage } from '../src/device/devicePlatformStorage.ts';

class MemoryDisk {
  values = new Map(); fail = () => false;
  async get(key) { if (this.fail('get', key)) throw Error('disk unavailable'); return this.values.get(key) ?? null; }
  async set(key, value) { if (this.fail('set', key)) throw Error('disk full'); this.values.set(key, value); }
}
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
  await store.update(state => { state.selected.id = 'latest'; }); const head = await disk.get('knowledge-sprite.device.v1.head');
  disk.values.set(`knowledge-sprite.device.v1.slot${head}`, 'corrupted retained raw');
  const restarted = new DeviceStore(disk); assert.deepEqual(await restarted.load(), previous); assert.match(restarted.recoveryNotice, /副本/);
  assert.equal(disk.values.get(`knowledge-sprite.device.v1.slot${head}`), 'corrupted retained raw');
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
