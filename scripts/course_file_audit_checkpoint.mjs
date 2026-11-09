/* Compact transport for private metadata checkpoints; never source contents. */
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const validPath = path => Array.isArray(path) && path.length > 0 && path.every(key =>
  typeof key === 'string' && !['__proto__', 'constructor', 'prototype'].includes(key));

export class CheckpointConflict extends Error {
  code = 'CHECKPOINT_CONFLICT';
}

export function checkpointDelta(previous, next, revision) {
  if (!revision || previous.connection !== next.connection ||
      !equal(previous.events, next.events.slice(0, previous.events.length))) {
    throw new Error('Checkpoint identity or append-only history changed');
  }
  const operations = [];
  function walk(before, after, path) {
    for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
      if (!path.length && ['events', '_checkpointRevision'].includes(key)) continue;
      const at = [...path, key];
      if (!validPath(at)) throw new Error('Invalid checkpoint path');
      const had = own(before, key), has = own(after, key);
      if (had && has && equal(before[key], after[key])) continue;
      if (had && has && object(before[key]) && object(after[key])) walk(before[key], after[key], at);
      else operations.push({ path: at, had, has,
        ...(had ? { before: before[key] } : {}), ...(has ? { after: after[key] } : {}) });
    }
  }
  walk(previous, next, []);
  return { connection: previous.connection, previousRevision: previous._checkpointRevision ?? null,
    revision, eventCount: previous.events.length, lastEvent: previous.events.at(-1) ?? null,
    events: next.events.slice(previous.events.length), operations };
}

export function applyCheckpointDelta(current, delta) {
  if (current.connection !== delta.connection) throw new Error('Checkpoint connection mismatch');
  if (current._checkpointRevision === delta.revision) return current;
  if ((current._checkpointRevision ?? null) !== delta.previousRevision ||
      current.events.length !== delta.eventCount || !equal(current.events.at(-1) ?? null, delta.lastEvent)) {
    throw new CheckpointConflict('Checkpoint changed since the last save');
  }
  const result = JSON.parse(JSON.stringify(current));
  for (const op of delta.operations) {
    if (!validPath(op.path) || ['events', '_checkpointRevision'].includes(op.path[0])) {
      throw new Error('Invalid checkpoint operation');
    }
    let target = result;
    for (const key of op.path.slice(0, -1)) {
      if (!own(target, key) || !object(target[key])) throw new CheckpointConflict('Checkpoint path changed');
      target = target[key];
    }
    const key = op.path.at(-1);
    if (own(target, key) !== op.had || (op.had && !equal(target[key], op.before))) {
      throw new CheckpointConflict('Checkpoint value changed');
    }
    if (op.has) target[key] = op.after;
    else delete target[key];
  }
  result.events.push(...delta.events);
  result._checkpointRevision = delta.revision;
  return result;
}
