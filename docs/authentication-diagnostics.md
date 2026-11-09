# Authentication diagnostics and recovery

## Incident and deployed path, November 5, 2026

The installed Canvas Bridge Personal connector returned a client reauthentication signal for a fresh `get_connection_status` call. There was no structured bridge result, bridge request ID or Canvas response. The incident classification is **AUTH_ORIGIN_UNKNOWN**. The reliability chat also observed the signal after the user's sign-in attempt. Stop the retry sequence here. The next investigation needs an operator or platform trace for the time of the failed client call.

| Boundary | Owner and observation |
|---|---|
| Installed connection | The client/platform selects the connector, obtains or renews its application credential, attaches it and presents any sign-in control. The repository cannot inspect that exchange or tell whether the platform stopped a call or suppressed its response. |
| Public ingress | The personal installation configures an HTTPS ngrok resource and a loopback Windows bridge. Direct discovery at both addresses returned HTTP 200 with the exact configured resource and issuer. A separate, intentionally unauthenticated POST through the public tunnel returned HTTP 401 with a Bearer challenge and resource metadata. This control establishes public reachability and challenge delivery to a direct HTTP caller. It cannot locate the installed client's failed request. |
| MCP authentication | The official SDK extracts the inbound credential and owns the challenge. The bridge's JWTVerifier checks the configured WorkOS AuthKit signing keys, signature, exact issuer and resource audience, validity interval, stable subject, granted scopes and local revocation. The deployed issuer and JWKS hosts match. WorkOS supplies application identity and signing keys. Its browser login observes a different exchange from the MCP call. |
| Account and operation | The bridge derives its principal from the verified issuer and subject. Personal mode restricts the subject. Tool guards check the requested operation and bind connection lookups to that principal. An unresolved owner/connection pair has one public response regardless of whether a different account owns the identifier. |
| Stored Canvas connection | Status reads the current principal's local connection records, selection and stored verification history. It sends **zero Canvas requests**. The personal profile uses an operator-managed encrypted credential. Where approved and configured, hosted linking uses the secure settings flow and a separate Canvas OAuth client. The operator can inspect setup availability in settings. |
| Canvas API | Only an authorized downstream read opens the connection-bound credential. CanvasClient checks the allowed institution, endpoint, course scope and current permission. It can observe the actual response from Canvas. A later file-storage response or a cached denial has separate provenance. |

The reliability owner confirmed there were no active overlapping edits or restarts. The public discovery check and previous owner-only first-read evidence cover different calls. This checkout was exercised with synthetic fixtures. The installed service was left running throughout.

## Wire contract

`auth/1` is defined in `src/canvas_bridge/auth_diagnostics.py`. Status places the observation at `data.authentication_diagnostic`. Partial collections and permission audits may use the same field for one observed failure while retaining their individual coverage and check rows. Inspected tool failures use `data.diagnostic.authentication_diagnostic`. HTTP authentication challenges keep the SDK status, OAuth error fields and `WWW-Authenticate` discovery metadata. Their inspected observation is at `diagnostic.authentication_diagnostic`. The earliest bridge-controlled MCP middleware generates one opaque request ID before admission and credential validation. It returns that same ID in `X-Bridge-Request-ID` and the diagnostic. The private, bounded failure journal supports lookup by this ID. Some clients consume the challenge and hide its headers and body.

Read `code`, `failure_layer`, `attribution`, `observation_source`, `bridge_reached` and `canvas_reached` before interpreting the four named checks. `unknown` means evidence is insufficient. `not_checked` means the diagnostic records no such check. `checked_at` is the UTC observation time. `this_request` describes the check just performed, including a local store lookup. Prior provider verification has its own scope and time. `reported` marks a client observation. Use the nested `explanation`, `recovery_action` and `retry` for authentication recovery. Other diagnostic fields continue to describe the operation as a whole.

Selected fields from three sanitized examples follow. Identifiers and times are omitted except where absence is the evidence.

| Observation | Selected fields | Next step |
|---|---|---|
| Host reauthentication signal with no server evidence | `AUTH_ORIGIN_UNKNOWN`, source `client_signal`, bridge and Canvas reach `unknown`, correlation ID `null` | Offer one **attempt** through a host-provided connection flow if available. After a repeated signal, stop and contact the operator. |
| Signed application credential fails the configured audience check | `MCP_AUDIENCE_MISMATCH`, source `jwt_validator`, MCP authentication `failed`, Canvas reach `no` | Reauthorize the configured client connection. The operator can compare its resource configuration to protected-resource discovery. |
| Canvas returns an explicit invalid-token challenge | `UPSTREAM_CREDENTIAL_REJECTED`, source `canvas_response`, Canvas reach `yes`, Canvas authentication `failed` | Use the configured secure Canvas flow if available, or contact the personal deployment operator. The reason for invalidity remains unspecified. The tool returns a downstream failure inside MCP. |

A bare Canvas 401 leaves the authentication cause unknown. A Canvas 403 can establish denial of this resource. Only the recognized challenge establishes insufficient scope. An explicit throttle or HTTP 429 calls for a delay. A 5xx or validator/key-source failure calls for waiting or operator investigation. A missing local connection calls for setup review. A mapping failure calls for checking the intended account and using a reference returned for it. An accepted application identity with inadequate tool permission calls for authorization review. An explicitly expired stored credential and a provider-rejected credential have separate codes.

## Recovery at the calling client

1. Keep the requested read, its arguments and intended account/connection in the current task. Use the currently available client connection control only when it is applicable. Keep secrets, sign-in URLs with callback parameters and authorization headers out of chat, logs and support tickets.
2. On cancellation or failed sign-in, stop. A callback by itself cannot resume the task. After the host confirms reconnection to the intended account, send exactly one fresh `get_connection_status` call. A fresh successful result verifies MCP access and the local lookup. If status was the requested operation, that completes it.
3. For a Canvas read, verify the intended connection is active, and replay only the original authorized read once. Evaluate its own status and coverage before reporting course or resource access. On a repeated challenge, failed verification or account change, stop. Keep the task available for a later user-initiated attempt. Never add scopes or request persistent access as part of recovery.

The repository's course-file audit can inject the optional `recoveringRead` adapter from `scripts/auth_recovery.mjs` through its `recovery` option. One adapter covers one connection/recovery episode. The host supplies a predicate for trusted connection challenges and a same-account reconnection control. The adapter shares one verification across concurrent pending reads and uses a reviewed read allowlist. Without those controls use the guidance above. The server cannot install this adapter in a platform-owned client. Concurrent Canvas credential refresh continues to use the existing database lease, identity recheck and epoch fence.

For the operator, correlate the UTC time, operation and an actual bridge request ID when available. Use the private failure journal and the configured resource's public discovery document. If only the platform signal is visible, ask the platform operator for its request trace. Use the installed connector for post-rollout acceptance. Compare one new status result and one authorized original read, without treating direct discovery or a synthetic success as evidence of client recovery.

## Synthetic verification

Against the dirty checkout based on `5bd0863`, 316 Python tests passed across the auth, OAuth, SDK transport, permission, privacy, admission and connection-guard suites. After extending the partial-result projection, a 27-test overlapping run passed, including the real MCP client against a synthetic Canvas 401 returned by both course listing and permission audit. The four Node recovery and audit test files passed all 87 tests. Ruff and the scoped Git diff checks passed. No full-suite result was reused.

The tests covered concurrent missing, malformed, expired, wrong-issuer and wrong-audience credentials, signing-key and identity failures, insufficient operation permission, owner-scoped mapping, empty connections, malicious provider messages, explicit and ambiguous Canvas challenges, throttling and provider failure. They also exercised canceled and failed callbacks, profile mismatch, mid-request revocation, single-flight refresh, stale status rejection and bounded read replay. The synthetic host adapter and the deployed platform are separate acceptance surfaces.

For example, the client-side representation of the incident has this shape. The check time here is illustrative.

```json
{
  "schema_version": "auth/1",
  "code": "AUTH_ORIGIN_UNKNOWN",
  "failure_layer": "unknown",
  "attribution": "unknown",
  "observation_source": "client_signal",
  "bridge_reached": "unknown",
  "canvas_reached": "unknown",
  "mcp_authentication": "unknown",
  "bridge_authorization": "unknown",
  "canvas_authentication": "unknown",
  "canvas_authorization": "unknown",
  "checked_at": "2026-11-05T00:00:00.000Z",
  "freshness": "reported",
  "correlation_id": null,
  "recovery_action": "stop_and_contact_operator",
  "retry": "none",
  "explanation": "Connection recovery ended without a verified read. Stop and contact the operator."
}
```
