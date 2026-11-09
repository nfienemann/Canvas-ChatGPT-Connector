/* Local adapters for CourseFileAudit. Tool transport remains host-owned. */
import { spawn } from 'node:child_process';
import { mkdir, open, readFile, rename, unlink } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { applyCheckpointDelta, CheckpointConflict } from './course_file_audit_checkpoint.mjs';

async function updateCheckpoint(path, update) {
  await mkdir(dirname(path), { recursive: true });
  const lockPath = path + '.lock';
  let lock;
  try { lock = await open(lockPath, 'wx', 0o600); }
  catch (error) {
    if (error.code === 'EEXIST') throw new CheckpointConflict('Checkpoint writer active. Reload before retrying.');
    throw new Error('Checkpoint storage unavailable.');
  }
  const pending = path + '.' + randomUUID() + '.pending';
  try {
    let current;
    try { current = JSON.parse(await readFile(path, 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw new Error('Checkpoint read failed.'); }
    const next = update(current);
    if (next !== current) {
      const file = await open(pending, 'wx', 0o600);
      try { await file.writeFile(JSON.stringify(next)); await file.sync(); }
      finally { await file.close(); }
      await rename(pending, path);
    }
    return next._checkpointRevision;
  } finally {
    try { await unlink(pending); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    finally { await lock.close(); await unlink(lockPath); }
  }
}

export async function saveCheckpointDelta(path, delta) {
  const revision = await updateCheckpoint(path, current => {
    if (!current) throw new Error('Checkpoint unavailable. Reload before continuing.');
    return applyCheckpointDelta(current, delta);
  });
  return { saved: true, revision };
}

export function imageDecoder(python) {
  return result => new Promise(resolve => {
    const decoder = fileURLToPath(new URL('./audit_image_decoder.py', import.meta.url));
    const child = spawn(python, [decoder], { windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'] });
    let output = '';
    const timeout = setTimeout(() => { child.kill(); resolve(false); }, 15000);
    child.on('error', () => { clearTimeout(timeout); resolve(false); });
    child.stdin.on('error', () => {});
    child.stdout.on('data', value => { if (output.length < 1024) output += value; });
    child.on('close', code => {
      clearTimeout(timeout);
      try { resolve(code === 0 && JSON.parse(output).decoded === true); } catch { resolve(false); }
    });
    child.stdin.end(JSON.stringify({ content: (result.content || []).filter(x => x.type === 'image') }));
  });
}

export function privateCheckpoint(path) {
  return {
    async load() {
      try { return JSON.parse(await readFile(path, 'utf8')); }
      catch (error) { if (error.code === 'ENOENT') return undefined; throw error; }
    },
    async save(state) {
      const revision = await updateCheckpoint(path, current => {
        if (current && (current.connection !== state.connection ||
            (current._checkpointRevision ?? null) !== (state._checkpointRevision ?? null))) {
          throw new CheckpointConflict('Checkpoint changed since the last save. Reload before continuing.');
        }
        return { ...state, _checkpointRevision: randomUUID() };
      });
      state._checkpointRevision = revision;
    },
  };
}
