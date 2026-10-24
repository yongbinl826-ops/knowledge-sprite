import test from 'node:test';
import assert from 'node:assert/strict';
import { readSnapshot, snapshotPollDelay } from '../src/snapshotRead.ts';

test('conditional reads retain their ETag and never parse an empty 304 body', async t => {
  const calls = []; const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return calls.length === 1 ? new Response('{"snapshot_revision":"r1"}', { headers: { ETag: '"r1"' } }) : new Response(null, { status: 304 }); };
  t.after(() => { globalThis.fetch = original; });
  const signal = new AbortController().signal;
  const first = await readSnapshot('/results?projection=ui', signal);
  const next = await readSnapshot('/results?projection=ui', signal, first.etag);
  assert.equal(first.value.snapshot_revision, 'r1'); assert.equal(next.value, null); assert.equal(next.etag, '"r1"');
  assert.equal(calls[1].options.headers['If-None-Match'], '"r1"');
  assert.equal(calls.every(call => !call.options.method || call.options.method === 'GET'), true);
});

test('unchanged background reads back off within a finite bound', () => {
  assert.equal(snapshotPollDelay(false, 0), 1500);
  assert.equal(snapshotPollDelay(true, 0), 3000);
  assert.equal(snapshotPollDelay(true, 20), 15000);
  assert(snapshotPollDelay(false, 2) > snapshotPollDelay(false, 0));
});
