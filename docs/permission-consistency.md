# Permission consistency and troubleshooting

`audit_permission_consistency` explains local authorization and optional upstream
metadata checks without repairing anything. It requires the existing verified
`academic:read` MCP identity. No principal, role, credential, URL or permission
assertion can be supplied as a tool argument.

Missing or expired MCP authentication is rejected by the existing HTTP/OAuth
boundary before this tool can run. With a valid MCP identity, the report can
separately describe the owned connection and its Canvas credential evidence.

The JWT verifier emits operator-only `mcp_auth_rejected` warnings with a fixed
`reason_code` and UTC timestamp. Codes distinguish expired/not-yet-valid tokens,
signature, issuer, audience, personal-owner and required-scope failures, invalid
token/header/claim shapes, unresolved signing keys and unavailable key sources.
No token, claim value, subject, key ID, exception message, header or URL is logged.
All existing checks and client-facing rejection behavior remain unchanged.
These events describe the first failed check, not every possible token defect.
Requests rejected by the host, or by HTTP middleware before the verifier runs,
may produce no such event. An absent warning therefore cannot prove a request
reached the service or that authentication succeeded. Correlate a bounded
supported client attempt with its timestamp; never enable HTTP wire logging.

```json
{
  "connection_id": "owned-connection-reference",
  "course_id": "exact-course-reference-returned-by-the-connector",
  "resource_types": ["course", "files"],
  "include_upstream_checks": false
}
```

Omit `course_id` to audit every currently selected course, including selections
whose cached access has since been withdrawn. Omit `resource_types` to check
`course`, `files`, `modules`, `assignments`, `syllabus`, `quizzes` and `grades`.
An empty resource list is rejected. At most 30 selected courses are audited;
larger selections require an explicit single course. Existing narrower server
course limits still apply.

The default audit reads connector metadata only. It does not call Canvas, renew
an authorization lease, refresh credentials, update caches, change scope, enqueue
work, or write Canvas state. The only emitted side effect is redacted diagnostic
logging. `state_modified: false` describes persistent connector/Canvas state.

## Reading the result

Each course/resource pair includes `advertised_selected`, `connection_owned`,
`identifier_state`, `scope_authorized`, `resource_capability`,
`authorization_freshness`, `scope_snapshot_version`, `upstream_permission`,
`upstream_http_status`, `result`, `reason_code` and `recommended_action`.

- `consistent` means the evidence agrees. A selected course with a resource 403
  is a consistent resource restriction, not proof of contradictory course scope.
- `inconsistent` means an observed local mismatch: selected-but-inaccessible
  cached scope, corrupt canonical mapping, or scope changing during the audit.
- `indeterminate` means required evidence is absent, stale or ambiguous.
- `not_checked` means a requested upstream check was deliberately not performed.

`scope_authorized` describes the current local student-course lease. It is
separate from credential validity, enabled endpoint capabilities and upstream
resource permissions. `ok` for a local-only audit never means Canvas accepted a
request. Unknown upstream permission stays `not_checked` or `unknown`.

Existing `Result` statuses remain unchanged. Reports with restrictions or unknown
evidence use `partial_data`; an explicit unusable course reference uses
`permission_denied`; a disabled connection or expired/rejected credential uses
`reconnect_required`. A foreign or nonexistent connection returns the same
minimal denial, without courses or resource-existence information.

## Optional upstream checks

When explicitly enabled, probes make one allowlisted GET per eligible pair, with
`per_page=1` on collection routes, no includes, no continuation, no redirect and
no retries. Response bodies are not consumed. Requests share the configured
refresh time budget and a hard limit of 30 probes. No download, grade,
submission, quiz-question or attempt endpoint is used.

The probes cover course detail and the files, modules, assignments and classic
quiz collections. Grade and syllabus access remain `NO_SAFE_METADATA_PROBE`:
this implementation has no conclusive content-free check for them. No extra
Canvas scope is requested. These restrictions follow the existing reviewed
[scope matrix](capability-scope-matrix.md) and Canvas's
[course includes](https://developerdocs.instructure.com/services/canvas/resources/courses)
and [pagination](https://developerdocs.instructure.com/services/canvas/basics/file.pagination)
contracts.

HTTP 200 proves only that the endpoint accepted that minimal request at that
instant. It does not prove every file is unlocked, enrollment is still current,
a document can be extracted, or a grade is visible. HTTP 403 records a resource
denial; 404 does not distinguish missing from hidden/deleted; an `invalid_token`
401 challenge identifies credential rejection, not its precise cause. Bare 401
remains ambiguous. Transport failures, rate limits and server failures remain
unknown upstream permission. Probes never automatically reauthorize a denial.

## Developer decision path

`authorization.authorize_course_resource` is the shared foundation used by
`Bridge.selected`, the Canvas client's resource dispatch guards and file cache
checks. It requires an exact canonical mapping under the trusted owner and
connection, current selected/accessible active-course evidence, a current lease,
a usable local credential state, and an enabled read operation. Configured
institution endpoint scopes are enforced. Hosted profiles with no reviewed
scope ceiling fail closed. Legacy personal/synthetic profiles retain their
allowlisted reads, but their upstream grants are explicitly unverified.

Every actual resource request still faces Canvas and existing object visibility
checks. List-files permission does not imply individual-file permission. A course
or syllabus read does not imply grade permission: grading reads require their
own endpoint capability, and syllabus-only requests omit grade includes.
Cached workload/history also requires the assignment capability.

The authenticated MCP wrapper tracks successful decisions and revalidates them
before returning any content. The scope fingerprint covers connection identity,
credential version, selected/access state, course mapping/version and configured
capabilities. Selection changes advance existing epochs/versions, including
remove-and-reselect races. A changed decision discards the response; it does not
retry it under new authority. Audits instead report the observed discrepancy.
No schema migration or persistent diagnostic snapshot is required.

Course references are exact, lower-case 40-character opaque identifiers. Never
truncate, pad, case-fold, prefix-match, or guess a replacement. An owned mapping
in another connection can be identified without returning that connection's ID
or course data. Foreign users' IDs are not searched and remain indistinguishable
from nonexistent IDs.

## Reason codes and next action

| Reason | Meaning / action |
|---|---|
| `IDENTIFIER_MAPPING_FAILURE` | Invalid format, unresolved reference, or inconsistent canonical mapping. Copy the complete ID from the correct connection; investigate stored mapping only when evidence indicates corruption. |
| `IDENTIFIER_CONNECTION_MISMATCH` | This account owns the reference in another connection. Review the connection/course pair. |
| `CONNECTION_OWNERSHIP_MISMATCH` | Requested connection is unavailable to this identity; no existence claim. |
| `COURSE_NOT_SELECTED` | Review course selection through the authorized settings workflow. |
| `SELECTED_SCOPE_MISMATCH` | Selected record is absent from current local access evidence. Inspect scope mapping; do not grant access. |
| `STALE_SCOPE_SNAPSHOT` | Lease expired or scope changed during the request. Reconcile snapshots through an explicitly authorized metadata/settings workflow. |
| `MISSING_RESOURCE_CAPABILITY` | Connector endpoint capability is unavailable; review the approved capability configuration. |
| `RESOURCE_PERMISSION_DENIED` | Canvas returned 403 for that resource. Review resource permissions; no scope expansion. |
| `UPSTREAM_AUTH_EXPIRED` | Local expiry or upstream invalid-token rejection. Reconnect through the authorized account workflow. |
| `UPSTREAM_AUTH_UNVERIFIED` | Credential is unavailable. Reconnect; never paste a token into chat. |
| `CONNECTION_INACTIVE` | Disabled/deleted connection. Use the authorized reconnect workflow. |
| `RESOURCE_UNAVAILABLE` | 404 cannot establish deletion versus visibility loss. Refresh authorized metadata if requested. |
| `UPSTREAM_UNAVAILABLE` | Retry after availability returns; no permission conclusion. |
| `UNKNOWN_AUTHORIZATION_FAILURE` | Evidence does not establish a cause, including ambiguous 401. Investigate correlated safe logs. |
| `NO_SAFE_METADATA_PROBE` | Resource remains unchecked; use a separate explicit resource workflow if needed. |
| `AUTHORIZED_LOCAL_SCOPE` | Local checks passed; upstream permission is not implied. |
| `UPSTREAM_METADATA_ACCESS_CONFIRMED` | The minimal endpoint request succeeded; item access/extraction remains separate. |

## Correlation and incident investigation

Compare `correlation_id` and `scope_snapshot_version` from connection status and
the audit. Different request IDs are expected. Structured `permission_decision`
logs contain request ID, tool, hashed connection/course references, resource,
decision, reason, scope version, optional HTTP status and UTC timestamp. They
contain no raw owner/course/connection IDs, credentials, filenames, document
text, grades or academic records. Retain redacted logs under the project's
existing retention policy.

Configure `canvas_bridge.authorization` at `INFO` in the operator's logging
pipeline to collect these structured messages. Do not enable HTTP wire/debug
logging to diagnose permissions; those logs are not this redacted channel.

The audit does not retain a historical status response or infer a historical
root cause. Compare separately captured safe request evidence when diagnosing
two calls made at different times or against different service instances.

The October 21 investigation reproduced the reported denial with a supplied
39-character reference. The live status response returned a 40-character
reference differing by one final character; using that exact reference succeeded.
This confirms the cause of the reproduced failure, not the contents of an
unavailable historical tool-call trace. No authorization bypass or ID repair
was needed. The private service was subsequently started with the updated source.
The October 22 follow-up confirmed a new service process and logged
`MCP_TOKEN_NOT_YET_VALID` while the host clock lagged by approximately two seconds.
After the owner started Windows Time, measured clock alignment and installed
course/file metadata calls succeeded without changing JWT checks or scope.
After supported tool refresh, the installed diagnostic was discovered and
invoked. It first stopped safely on a stale lease with zero upstream requests.
A normal authorized course-list read refreshed that evidence; the repeated
diagnostic then returned consistent course/files scope and HTTP 200 for both
metadata checks, using two requests and changing no state. The normal installed
file listing also succeeded. Before/after comparisons confirmed preserved
credentials, permissions, selection and configuration; normal metadata reads
updated only the authorization-lease timestamp in the compared records. See
[verification and before/after evidence](../evidence/sanitized-results/permission-consistency.md).

For token-timing failures, measure small clock offsets against a trusted time
source before considering configuration changes. Use normal operating-system
time synchronization; do not weaken expiry, issued-at or not-before validation
to conceal clock drift. A successful sample does not establish persistent clock
health. A successful app refresh also does not prove a running chat has reloaded
its tool catalog: verify actual discovery and invocation separately. See the
[Windows clock maintenance procedure](windows-time.md) for the scoped,
administrator-run repair, verification and rollback steps.
