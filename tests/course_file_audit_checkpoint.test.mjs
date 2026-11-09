import test from 'node:test';
import assert from 'node:assert/strict';
import { checkpointDelta, applyCheckpointDelta } from '../scripts/course_file_audit_checkpoint.mjs';
import { saveCheckpointDelta } from '../scripts/course_file_audit_node.mjs';
import { CourseFileAudit } from '../scripts/course_file_audit.mjs';
import { mkdtemp, writeFile, readFile, unlink, rmdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const initial = () => ({ connection: 'synthetic', courses: { c: { files: {
  f: { hash: 'v1', rendered: [1], textDone: false },
} } }, events: [{ request_id: 'first' }], hold: null });
function changed(before) {
  const after = structuredClone(before);
  after.courses.c.files.f.rendered.push(2);
  after.events.push({ request_id: 'second' });
  after.hold = { reason: 'retry', retryAt: 123 };
  return after;
}
test('compact checkpoint applies exactly and retries idempotently after lost acknowledgement', () => {
  const before = initial(), after = changed(before), patch = checkpointDelta(before, after, 'revision-1');
  const saved = applyCheckpointDelta(before, patch);
  assert.deepEqual(saved, { ...after, _checkpointRevision: 'revision-1' });
  assert.deepEqual(applyCheckpointDelta(saved, patch), saved);
  assert.deepEqual(before, initial());
});
test('a stale writer cannot overwrite a changed checkpoint', () => {
  const before = initial(), patch = checkpointDelta(before, changed(before), 'revision-1');
  for (const mutate of [s => s.events.push({ request_id: 'other' }),
    s => s.connection = 'other', s => s._checkpointRevision = 'other',
    s => s.courses.c.files.f.rendered.push(3)]) {
    const current = structuredClone(before); mutate(current);
    const snapshot = structuredClone(current);
    assert.throws(() => applyCheckpointDelta(current, patch), /Checkpoint/);
    assert.deepEqual(current, snapshot);
  }
});
test('history replacement is rejected and unchanged history is absent from transport', () => {
  const before = initial(); before.events.push(...Array.from({ length: 1000 }, (_, n) => ({ request_id: `old-${n}` })));
  const after = changed(before), patch = checkpointDelta(before, after, 'revision-1');
  assert.equal(patch.events.length, 1);
  assert.ok(JSON.stringify(patch).length < 1000);
  after.events[0].request_id = 'replaced';
  assert.throws(() => checkpointDelta(before, after, 'revision-2'), /append-only/);
});
test('additions, deletions, and successive revisions preserve exact state', () => {
  let before = initial();
  for (let n = 1; n <= 3; n++) {
    const after = changed(before);
    after.courses.c.files.new = { rendered: [n] };
    delete after.courses.c.files.f.textDone;
    const saved = applyCheckpointDelta(before, checkpointDelta(before, after, `revision-${n}`));
    assert.deepEqual(saved, { ...after, _checkpointRevision: `revision-${n}` });
    before = saved;
  }
});
test('prototype paths and direct history replacement cannot be applied', () => {
  const before = initial(), patch = checkpointDelta(before, changed(before), 'revision-1');
  for (const path of [['__proto__', 'polluted'], ['events'], ['courses', 'constructor']]) {
    assert.throws(() => applyCheckpointDelta(before, { ...patch, operations: [{ path, had: false, has: true, after: true }] }), /Invalid/);
  }
  assert.equal({}.polluted, undefined);
});

test('atomic file adapter preserves the checkpoint after conflicts and repeated acknowledgements', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'synthetic-audit-checkpoint-'));
  const path = join(directory, 'state.json');
  try {
    const before = initial(), patch = checkpointDelta(before, changed(before), 'revision-1');
    await writeFile(path, JSON.stringify(before));
    await saveCheckpointDelta(path, patch);
    const once = await readFile(path, 'utf8');
    assert.deepEqual(await saveCheckpointDelta(path, patch), { saved: true, revision: 'revision-1' });
    assert.equal(await readFile(path, 'utf8'), once);
    await assert.rejects(saveCheckpointDelta(path, { ...patch, revision: 'stale' }), /changed/);
    assert.equal(await readFile(path, 'utf8'), once);
  } finally { await unlink(path); await rmdir(directory); }
});

test('simultaneous checkpoint writers cannot both commit the same base revision', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'audit-race-'));
  const path = join(directory, 'checkpoint.json');
  try {
    const before = initial();
    await writeFile(path, JSON.stringify(before));
    const saves = ['a', 'b'].map(id => saveCheckpointDelta(path, checkpointDelta(before, changed(before), id)));
    const outcomes = await Promise.allSettled(saves);
    assert.equal(outcomes.filter(x => x.status === 'fulfilled').length, 1);
    const winner = outcomes.find(x => x.status === 'fulfilled').value;
    assert.equal(JSON.parse(await readFile(path, 'utf8'))._checkpointRevision, winner.revision);
  } finally { await unlink(path); await rmdir(directory); }
});

test('inventory failure annotations persist through the compact writer without rewriting history', async () => {
  let disk, previous, revision = 0;
  const audit = new CourseFileAudit({ connection: 'synthetic', resumableInventory: true,
    callTool: async name => name === 'list_courses'
      ? { status: 'ok', data: { courses: [{ id: 'c', selected: true }] }, meta: {
        request_id: 'courses', coverage: [{ resource: 'courses', state: 'complete', pagination_complete: true }],
      } }
      : { status: 'partial_data', data: { files: [], page_identity: 'page0', inventory_operation: 'files',
        coverage: { files: 'partial', folders: 'complete', modules: 'complete', assignments: 'complete' },
        inventory_reason_codes: { files: { reason_code: 'UNKNOWN_AUTHORIZATION_FAILURE' } },
      }, meta: { freshness: 'live', request_id: 'inventory' } },
    save: async state => {
      const id = `inventory-${++revision}`;
      disk = applyCheckpointDelta(disk, checkpointDelta(previous, state, id));
      state._checkpointRevision = id;
      previous = structuredClone(disk);
    },
  });
  disk = structuredClone(audit.state); previous = structuredClone(disk);
  await audit.discover();
  assert.equal(audit.report().rows[0].inventoryComplete, false);
  assert.ok(disk.events.some(e => e.request_id === 'inventory' &&
    e.inventory_failures?.some(f => f.reason === 'UNKNOWN_AUTHORIZATION_FAILURE')));
});

test('acknowledged revision survives a no-change flush and the next worker handoff', async () => {
  let disk, published, sequence = 0;
  const callTool = async () => ({ status: 'ok', data: {}, meta: {} });
  const saver = initialState => {
    let previous = structuredClone(initialState);
    return async state => {
      const revision = `handoff-${++sequence}`;
      const delta = checkpointDelta(previous, state, revision);
      if (delta.operations.length || delta.events.length) {
        disk = applyCheckpointDelta(disk, delta);
        state._checkpointRevision = revision;
        previous = structuredClone(disk);
      }
      published = structuredClone(state);
    };
  };
  const first = new CourseFileAudit({ connection: 'synthetic', callTool, save: async () => {} });
  disk = structuredClone(first.state);
  first.save = saver(disk);
  await first.call('list_courses', {});
  await first.flush(); // The final no-op must not republish the initial revision.
  const second = new CourseFileAudit({ connection: 'synthetic', callTool,
    state: structuredClone(published), save: saver(published) });
  await second.call('list_course_files', { course_id: 'c' }, 'c');
  assert.equal(disk.events.length, 2);
  assert.equal(second.state._checkpointRevision, disk._checkpointRevision);
  assert.equal(published._checkpointRevision, disk._checkpointRevision);
});

test('a failed save cannot advance the acknowledged in-memory revision', async () => {
  const audit = new CourseFileAudit({ connection: 'synthetic', callTool: async () => ({}),
    save: async state => { state._checkpointRevision = 'unacknowledged'; throw new Error('save failed'); } });
  audit.state._checkpointRevision = 'known-good';
  await assert.rejects(audit.flush(), /save failed/);
  assert.equal(audit.state._checkpointRevision, 'known-good');
  assert.equal(audit.report().checkpoint_status, 'CHECKPOINT_COMMIT_UNCERTAIN');
  assert.equal(audit.report().clean, false);
});
