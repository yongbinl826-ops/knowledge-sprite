import test from 'node:test';
import assert from 'node:assert/strict';
import { openSnapshotStream } from '../src/snapshotStream.ts';

// Pure memory transport and clock: no browser, server, source query, or model.
function harness(t, callbacks = {}) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const original = Object.getOwnPropertyDescriptor(globalThis, 'EventSource');
  const sources = [];
  class FakeEventSource extends EventTarget {
    closed = 0;
    constructor(url) { super(); this.url = url; sources.push(this); }
    close() { this.closed += 1; }
    emit(type, data) { this.dispatchEvent(new MessageEvent(type, { data })); }
  }
  Object.defineProperty(globalThis, 'EventSource', { configurable: true, writable: true, value: FakeEventSource });
  t.after(() => {
    if (original) Object.defineProperty(globalThis, 'EventSource', original);
    else delete globalThis.EventSource;
  });
  const controller = new AbortController();
  const snapshots = [], completed = [], reads = [];
  const close = openSnapshotStream({
    url: '/api/projects/example/events?version=17', signal: controller.signal,
    onSnapshot: value => { callbacks.onSnapshot?.(value); snapshots.push(value); },
    onComplete: value => { callbacks.onComplete?.(value); completed.push(value); },
    // This is the watcher fallback contract: reread saved results, not search.
    onFallback: () => reads.push({ method: 'GET', url: '/api/projects/example/results?version=17' }),
  });
  t.after(close);
  return { controller, source: sources[0], close, snapshots, completed, reads };
}

const snapshot = (pending = true, image = null) => ({
  project_id: 'example', version: { version: 17, status: 'completed' },
  pipeline: { terminal: true, catalog_pending: pending },
  points: [{ resource: { resource_id: 'existing', thumbnail_url: image },
    matched_chapters: [{ chapter_id: 'reviewed', title: '条件分支' }] }],
});

test('open without a first snapshot falls back at 15 seconds, once, and ignores late data', t => {
  const h = harness(t);
  h.source.emit('open');
  t.mock.timers.tick(14_999);
  h.source.emit('open');
  assert.equal(h.reads.length, 0);
  t.mock.timers.tick(1);
  assert.equal(h.source.closed, 1);
  assert.deepEqual(h.reads, [{ method: 'GET', url: '/api/projects/example/results?version=17' }]);
  h.source.emit('snapshot', JSON.stringify(snapshot()));
  h.source.emit('complete', JSON.stringify(snapshot(false)));
  h.source.emit('error');
  t.mock.timers.tick(120_000);
  assert.equal(h.reads.length, 1);
  assert.equal(h.snapshots.length, 0);
  assert.equal(h.completed.length, 0);
});

test('a connection that never opens also uses the first-data deadline', t => {
  const h = harness(t);
  t.mock.timers.tick(15_000);
  assert.equal(h.source.closed, 1);
  assert.equal(h.reads.length, 1);
});

test('a large valid snapshot grants 60 seconds of quiet catalog work before read-only fallback', t => {
  const h = harness(t);
  t.mock.timers.tick(1000);
  const large = { ...snapshot(), diagnostics: 'x'.repeat(788_000) };
  h.source.emit('snapshot', JSON.stringify(large));
  t.mock.timers.tick(59_999);
  assert.deepEqual(h.snapshots, [large]);
  assert.equal(h.reads.length, 0);
  h.source.emit('open');
  t.mock.timers.tick(1);
  assert.equal(h.reads.length, 1);
  assert.equal(h.source.closed, 1);
  assert.deepEqual(h.snapshots[0].points, large.points);
});

test('late metadata resets the quiet deadline and terminal completion closes without fallback', t => {
  const h = harness(t);
  h.source.emit('snapshot', JSON.stringify(snapshot()));
  t.mock.timers.tick(59_000);
  const enriched = snapshot(true, 'https://i0.hdslb.com/cover.jpg');
  h.source.emit('snapshot', JSON.stringify(enriched));
  t.mock.timers.tick(59_000);
  assert.equal(h.source.closed, 0);
  assert.equal(h.reads.length, 0);
  const final = { ...enriched, pipeline: { terminal: true, catalog_pending: false } };
  h.source.emit('complete', JSON.stringify(final));
  t.mock.timers.tick(120_000);
  assert.deepEqual(h.completed, [final]);
  assert.equal(h.snapshots.at(-1).points[0].resource.thumbnail_url, 'https://i0.hdslb.com/cover.jpg');
  assert.deepEqual(h.snapshots.at(-1).points[0].matched_chapters, snapshot().points[0].matched_chapters);
  assert.equal(h.source.closed, 1);
  assert.equal(h.reads.length, 0);
});

for (const afterSnapshot of [false, true]) {
  test(`abort ${afterSnapshot ? 'after' : 'before'} first snapshot removes timers and ignores stale-version frames`, t => {
    const h = harness(t);
    if (afterSnapshot) h.source.emit('snapshot', JSON.stringify(snapshot()));
    h.controller.abort();
    h.source.emit('snapshot', JSON.stringify({ ...snapshot(), version: { version: 18 } }));
    h.source.emit('complete', JSON.stringify(snapshot(false)));
    t.mock.timers.tick(120_000);
    assert.equal(h.snapshots.length, Number(afterSnapshot));
    assert.equal(h.source.closed, 1);
    assert.equal(h.reads.length, 0);
    assert.equal(h.completed.length, 0);
  });
}

test('invalid JSON falls back immediately and never extends the timer', t => {
  const h = harness(t);
  h.source.emit('snapshot', '{broken');
  assert.equal(h.reads.length, 1);
  t.mock.timers.tick(120_000);
  assert.equal(h.reads.length, 1);
  assert.equal(h.snapshots.length, 0);
});

test('a rejected snapshot scope uses fallback without applying an invalid project', t => {
  const h = harness(t, { onSnapshot: value => {
    if (value.version.version !== 17) throw new Error('Wrong project version');
  } });
  h.source.emit('snapshot', JSON.stringify({ ...snapshot(), version: { version: 18 } }));
  assert.equal(h.reads.length, 1);
  assert.equal(h.snapshots.length, 0);
  assert.equal(h.source.closed, 1);
});

test('an invalid completion uses a saved-state read rather than closing silently', t => {
  const h = harness(t, { onComplete: value => {
    if (!value || value.pipeline.catalog_pending) throw new Error('Missing final state');
  } });
  h.source.emit('complete', JSON.stringify(snapshot()));
  assert.equal(h.reads.length, 1);
  assert.equal(h.completed.length, 0);
  assert.equal(h.source.closed, 1);
});

test('caller closing on a terminal snapshot leaves no rearmed timeout', t => {
  let close;
  const h = harness(t, { onSnapshot: () => close() });
  close = h.close;
  h.source.emit('snapshot', JSON.stringify(snapshot(false)));
  t.mock.timers.tick(120_000);
  assert.equal(h.source.closed, 1);
  assert.equal(h.reads.length, 0);
});

test('transport error closes once and immediately invokes saved-state fallback', t => {
  const h = harness(t);
  h.source.emit('error');
  h.source.emit('error');
  t.mock.timers.tick(120_000);
  assert.equal(h.source.closed, 1);
  assert.equal(h.reads.length, 1);
});
