/* Host adapter for a single user-approved recovery attempt. Host callbacks are
 * trusted connection controls. Never derive a control or URL from tool content. */
const reads = new Set([
  'get_connection_status', 'list_courses', 'list_course_files', 'read_course_file',
  'render_course_file_page', 'render_course_slide', 'get_assignment_details', 'get_workload',
  'get_course_outline', 'audit_permission_consistency', 'get_file_extraction_status',
  'search_local_documents',
]);

// Only a trusted host connection-state check establishes requiresLogin. An
// opaque UNAUTHORIZED/www_authenticate_reauth signal alone keeps origin unknown.
export function clientAuthDiagnostic({ requiresLogin = false, attempted = false } = {}) {
  return {
    schema_version: 'auth/1', code: requiresLogin ? 'CLIENT_REAUTH_REQUIRED' : 'AUTH_ORIGIN_UNKNOWN',
    failure_layer: requiresLogin ? 'client_connection' : 'unknown',
    attribution: requiresLogin ? 'confirmed' : 'unknown', observation_source: 'client_signal',
    bridge_reached: 'unknown', canvas_reached: 'unknown', mcp_authentication: 'unknown',
    bridge_authorization: 'unknown', canvas_authentication: 'unknown', canvas_authorization: 'unknown',
    checked_at: new Date().toISOString(), freshness: 'reported', correlation_id: null,
    recovery_action: attempted ? 'stop_and_contact_operator' :
      requiresLogin ? 'reconnect_client' : 'attempt_client_reconnection',
    retry: attempted ? 'none' : 'after_repair_once',
    explanation: attempted ? 'Connection recovery ended without a verified read. Stop and contact the operator.' :
      requiresLogin ? 'The host reports that the connection requires sign-in.' :
        'The host requested reauthentication. The rejecting layer is unknown.',
  };
}

function recoveryStopped() {
  const diagnostic = clientAuthDiagnostic({ attempted: true });
  // This is a host-side outcome. Never use Bridge Result defaults that mint an ID.
  return { isError: true, structuredContent: { status: 'operation_uncertain',
    summary: diagnostic.explanation, data: { reason_code: diagnostic.code,
      authentication_diagnostic: diagnostic } } };
}

export function recoveringRead(callTool, { isConnectionChallenge, reconnectSameAccount }) {
  // One adapter per host connection and recovery episode. Concurrent pending reads
  // share verification. Discard this adapter after the episode.
  let verification;
  async function verify() {
    if (await reconnectSameAccount() !== 'host_connection_verified') return null;
    const started = Date.now();
    const raw = await callTool('get_connection_status', {});
    const result = raw?.structuredContent;
    const evidence = result?.data?.authentication_diagnostic;
    // Reject stale observations and fail closed if client/server clocks disagree.
    const checked = Date.parse(evidence?.checked_at);
    if (!Number.isFinite(checked) || checked < started - 5000 || checked > Date.now() + 5000) return null;
    if (raw?.isError || result?.status !== 'ok' || evidence?.schema_version !== 'auth/1' ||
        evidence.mcp_authentication !== 'passed' || evidence.bridge_authorization !== 'passed' || evidence.freshness !== 'this_request' ||
        evidence.observation_source !== 'owner_scoped_store' ||
        !/^[a-f0-9]{32}$/.test(evidence.correlation_id) ||
        result.meta?.request_id !== evidence.correlation_id) return null;
    return raw;
  }
  return async function call(name, args) {
    if (!reads.has(name)) throw new Error('Recovery is restricted to reviewed read operations.');
    const original = structuredClone(args);
    const alreadyAttempted = Boolean(verification);
    let initial;
    let challenged;
    try {
      initial = await callTool(name, structuredClone(original));
      challenged = isConnectionChallenge(initial);
    } catch (error) {
      challenged = isConnectionChallenge(error);
      if (!challenged) throw new Error('Read transport unavailable.');
    }
    if (!challenged) return initial;
    if (alreadyAttempted) return recoveryStopped();
    verification ??= verify().catch(() => null);
    const status = await verification;
    if (!status) return recoveryStopped();
    if (name === 'get_connection_status') return status;
    if (original.connection_id && !status.structuredContent.data.connections?.some(
      row => row.id === original.connection_id && row.state === 'active' &&
        row.authentication_state === 'verified'
    )) throw new Error('The intended connection needs review.');
    // Use the raw transport exactly once; a repeated challenge ends this episode.
    try {
      const resumed = await callTool(name, original);
      return isConnectionChallenge(resumed) ? recoveryStopped() : resumed;
    } catch { return recoveryStopped(); }
  };
}
