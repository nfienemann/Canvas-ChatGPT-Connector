import assert from 'node:assert/strict';
import test from 'node:test';
import { clientAuthDiagnostic, recoveringRead } from '../scripts/auth_recovery.mjs';

const challenge = Object.freeze({ code: 'UNAUTHORIZED', reason: 'www_authenticate_reauth' });
const ref = 'fictional';
const id = '1'.repeat(32);
const status = { structuredContent: { status: 'ok', meta: { request_id: id }, data: {
  connections: [{ id: ref, state: 'active', authentication_state: 'verified' }],
  authentication_diagnostic: { schema_version: 'auth/1', mcp_authentication: 'passed',
    bridge_authorization: 'passed', checked_at: new Date().toISOString(),
    freshness: 'this_request', observation_source: 'owner_scoped_store', correlation_id: id },
} } };
const args = { connection_id: ref, query: 'original' };
function harness(outcome, verified = status, replay = { ok: true }) {
  let connected = false;
  const calls = [];
  const call = recoveringRead(async (name, args) => {
    calls.push([name, structuredClone(args)]);
    if (!connected) return challenge;
    return name === 'get_connection_status' ? verified : replay;
  }, { isConnectionChallenge: r => r === challenge, reconnectSameAccount: async () => {
    calls.push(['host']); connected = true; return outcome;
  } });
  return { call, calls };
}
test('concurrent reads share host recovery and one fresh status then each resume once', async () => {
  const { call, calls } = harness('host_connection_verified');
  await Promise.all([call('list_courses', args), call('get_workload', args)]);
  assert.deepEqual(calls.map(c => c[0]), ['list_courses', 'get_workload', 'host', 'get_connection_status', 'list_courses', 'get_workload']);
  assert.deepEqual(calls[0], calls[4]);
});
for (const outcome of ['canceled', 'failed', 'browser_callback']) test(outcome, async () => {
  const { call, calls } = harness(outcome);
  assert.equal((await call('list_courses', args)).structuredContent.data.authentication_diagnostic.retry, 'none');
  assert.equal(calls.length, 2);
});
test('failed verification, changed connection, and repeated challenge stop', async () => {
  for (const invalid of [{}, challenge, { structuredContent: { ...status.structuredContent,
    data: { ...status.structuredContent.data, connections: [] } } }]) {
    const { call, calls } = harness('host_connection_verified', invalid);
    if (invalid.structuredContent) await assert.rejects(call('list_courses', args));
    else assert.equal((await call('list_courses', args)).structuredContent.data.reason_code, 'AUTH_ORIGIN_UNKNOWN');
    assert.equal(calls.length, 3);
  }
  const { call, calls } = harness('host_connection_verified', status, challenge);
  for (let i = 0; i < 2; i++) {
    assert.equal((await call('list_courses', args)).structuredContent.data.authentication_diagnostic.retry, 'none');
  }
  assert.equal(calls.filter(([s]) => s === 'host').length, 1);
});
test('status verifies itself once, and writes never enter the recovery flow', async () => {
  const { call, calls } = harness('host_connection_verified');
  assert.equal(await call('get_connection_status', {}), status);
  assert.deepEqual(calls.map(c => c[0]), ['get_connection_status', 'host', 'get_connection_status']);
  await assert.rejects(call('save_study_plan', {}));
  assert.equal(calls.length, 3);
});

test('a masked challenge is unknown and cannot mint a bridge request ID', () => {
  const auth = clientAuthDiagnostic();
  assert.equal(auth.attribution, 'unknown');
  assert.equal(auth.bridge_reached, 'unknown');
  assert.equal(auth.canvas_reached, 'unknown');
  assert.equal(auth.correlation_id, null);
  assert.equal(auth.recovery_action, 'attempt_client_reconnection');
  assert.equal(clientAuthDiagnostic({ requiresLogin: true }).code, 'CLIENT_REAUTH_REQUIRED');
});

test('a cached status predating reconnection cannot resume a read', async () => {
  const stale = structuredClone(status);
  stale.structuredContent.data.authentication_diagnostic.checked_at = '2000-01-01T00:00:00Z';
  const { call, calls } = harness('host_connection_verified', stale);
  const stopped = await call('list_courses', args);
  assert.equal(stopped.structuredContent.data.authentication_diagnostic.retry, 'none');
  assert.equal(calls.length, 3);
});
