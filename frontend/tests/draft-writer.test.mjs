import test from 'node:test';
import assert from 'node:assert/strict';
import { DraftWriter } from '../src/device/draftWriter.ts';

test('an edit burst saves its latest value once, and flush waits for durable acknowledgement', async () => {
  const state = {}, commits = []; let acknowledge;
  const writer = new DraftWriter(async change => { change(state); commits.push(structuredClone(state)); await new Promise(resolve => { acknowledge = resolve; }); }, 10000);
  let completed = 0;
  const edits = Array.from({ length: 30 }, (_, n) => writer.save('input', s => { s.input = n; }).then(() => completed++));
  const flush = writer.flush(); await Promise.resolve(); assert.equal(completed, 0); assert.deepEqual(commits, [{ input: 29 }]);
  acknowledge(); await flush; await Promise.all(edits); assert.equal(completed, 30);
});

test('failed durable save rejects pending callers and a later edit can retry', async () => {
  let fail = true; const state = {};
  const writer = new DraftWriter(async change => { if (fail) throw Error('disk full'); change(state); }, 10000);
  const edit = writer.save('draft', s => { s.value = 1; }); const failure = assert.rejects(edit, /disk full/);
  await assert.rejects(writer.flush(), /disk full/); await failure;
  fail = false; const retry = writer.save('draft', s => { s.value = 2; }); await writer.flush(); await retry; assert.equal(state.value, 2);
});

test('flush retries a failed latest draft before allowing navigation without another edit', async () => {
  let fail = true; const state = {};
  const writer = new DraftWriter(async change => { if (fail) throw Error('disk full'); change(state); }, 10000);
  const edit = writer.save('input', s => { s.value = 'latest'; });
  const failure = assert.rejects(edit, /disk full/);
  await assert.rejects(writer.flush(), /disk full/); await failure;
  fail = false; await writer.flush(); assert.equal(state.value, 'latest');
});
