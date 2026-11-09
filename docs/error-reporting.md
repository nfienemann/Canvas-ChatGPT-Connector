# Error reporting and retry guidance

## Recovering a failed MCP request

1. Copy the public `meta.request_id` and the diagnostic code. For a protocol error use
   `error.data.diagnostic.request_id`. An interrupted original download supplies
   `X-Bridge-Request-Id` before its first byte. A static emergency response includes
   the ID in its fixed message.
2. On the serving machine, from the same deployment directory and configuration, run
   `python -m canvas_bridge.failure_events REQUEST_ID` with the service interpreter.
   The local read-only lookup prints one JSON event per matching failure. An empty
   result means the journal has no retained match. Disk or permission failures can
   prevent recording. Check local journal access and free space.
3. Read `stage`, `code`, and `next_action`. For classification review, refer the source
   to its authorized reviewer. For stale membership, refresh the selected course
   list, then repeat an eligible read once. For a receipt failure, use the build,
   tool and attempt ID to reproduce the final serializer and SDK fence with synthetic
   input. For an internal error, investigate the registered handler. Keep source
   content, user inputs and credentials out of support messages.
4. A retry after repair is a separate observation. Verify the resulting content and
   authorization independently before describing the original task as delivered.

### Wire contract

Tool errors keep the Result 1.0 envelope, legacy reason and text representation.
The additive `data.diagnostic.schema_version` is `"1"`. Read the three explicitly
scoped fields independently. `requested_operation_outcome` describes this attempt,
`requested_content_policy` records an observed decision about the requested
content, and `sanitized_error_release` records the error envelope's policy
decision. Clients must check the operation outcome even if `meta.egress` says
`ALLOW`. A missing or mismatched receipt withholds the buffered payload.
`content_delivery` concerns only this attempt. A completed local send does not
establish remote receipt. After a committed stream fails, consult the local event.

`requested_operation` is null before dispatch or on a non-tool protocol/HTTP
request. The fixed action and retry identifiers are for client logic. Display
the reviewed summary to the user. A confirmed receipt failure identifies the
failed verification step. Its underlying software cause can still be unknown.

`operation_failed` extends the status enum for execution, response-contract and
verification failures. Treat it as a terminal failure of the current attempt.
Clients with a closed legacy status enum must update that enum. Clients that
ignore additive fields can continue using status, summary and reviewed reason;
older server responses without a diagnostic retain their legacy interpretation.
HTTP/JSON-RPC failures keep protocol correlation separate from the Bridge ID.
Emergency responses carry fixed text only and can lack structured content.

The server automatically refreshes membership and repeats at most one
`get_gradebook` or `get_course_outline` after a verified stale-snapshot failure.
Each attempt has its own ID under one request ID. Other operations receive
guidance or use their existing membership preflight. Automatic replay is
disabled for writes, ambiguous side effects, and deterministic failures.

### Local journal

The service stores failure events in the restricted `failure-events` directory
beside its vault key. Use a deployment state directory outside synchronized
folders. The journal rotates in 512 KiB segments, expires segments after seven
days, and caps all event segments together at 10 MiB. The running service checks
expiry during routine retention sweeps and on writes. The lookup also filters
expired events. Access follows the operator-only directory ACL on Windows and
owner-only creation permissions on POSIX. The journal has no network lookup or
upload facility. The build field uses the package version and a fingerprint of
the diagnostic implementation when source is available. Events carry a fixed
exception class, nullable tool, UTC time, attempt, policy mode, schema and
failure-handler versions. Ordinary diagnosis requires no deeper capture.

## Legacy reason and guidance fields

Errors retain a stable `reason_code` and a public request ID. Reviewed common
failures also include `error_origin`, `recommended_action` and `retry_condition`.
When the service knows a retry delay, `retry_after_seconds` survives the final MCP
privacy filter. Clients must honor it; absence of a delay is not permission to
retry continuously. These fields describe the failure and never authorize access.

| Code | Meaning | Next step |
|---|---|---|
| `LOCAL_REQUEST_BUSY` | Bridge request capacity is occupied, including local queue/cache admission | Let the current request finish, then retry; reconnecting is unnecessary |
| `AUTHORIZATION_BUSY` | A serialized connection read or maintenance operation is active | Wait for the operation to finish |
| `UPSTREAM_THROTTLED` | Provider throttling or an active provider cooldown | Honor Retry-After; this code alone does not prove HTTP 429 |
| `UPSTREAM_CIRCUIT_OPEN` | Recovery probing after repeated provider failures | Wait for provider recovery |
| `STALE_SCOPE_SNAPSHOT` | Scope snapshot or authorization lease is no longer current | Successfully refresh the course list before retrying |
| `EGRESS_CLASSIFICATION_UNKNOWN` | Source classification is missing | Obtain an authorized classification review |
| `EGRESS_GOVERNANCE_MISSING` | Source or recipient sharing evidence is missing | Review applicable sharing permissions |
| `EGRESS_CONTENT_HASH_REVIEW_REQUIRED` | Current source version lacks the required review | Review the current exact source version |
| `EGRESS_MODALITY_REVIEW_REQUIRED` | Requested sharing channel is not covered | Review that modality; text permission is not image permission |
| `RENDER_DEPENDENCY_UNAVAILABLE` | Required renderer is unavailable | Check the configured runtime installation |
| `RENDER_IMAGE_OUTPUT_LIMIT` | Image exceeds the bounded output limit | Request a smaller supported render |
| `INVENTORY_PAGINATION_CYCLE` | Traversal repeated a page | Keep partial results and report the request ID |
| `INVENTORY_CURSOR_INVALID` | Checkpoint is invalid, expired or unavailable | Restart discovery in the current selected scope |

Guidance is reconstructed from reviewed constants in `error_guidance.py`.
Minimized workload and grade metadata preserve reviewed coverage warnings for
refresh time budgets, request budgets, access denials and temporary failures.
For a refresh budget limit, request the affected course separately. Missing items
in partial coverage do not establish that no work is due. Arbitrary upstream
warning text remains replaced with a generic notice.

Document setup failures now distinguish `DOCUMENT_SANDBOX_SETUP_TIMEOUT` from
`DOCUMENT_RUNTIME_SETUP_FAILED`. A sandbox setup timeout means the document
worker was not started by that attempt. Operators should check installation and
filesystem performance using the request ID. Public Office runtime permission
setup has a bounded 90-second allowance; ordinary sandbox permission operations
retain their 15-second allowance. Worker isolation and execution limits are unchanged.

Caller-supplied explanations, arbitrary exception messages, URLs, credential
values, contract identifiers and source text are never copied into it. Unknown
codes retain legacy `EGRESS_ERROR_REDACTED` in `data.reason_code`. New MCP clients
read `UNCLASSIFIED_FAILURE` with unknown certainty in `data.diagnostic`. Unexpected-failure logs contain the same request ID and exception
class, without the exception message. A partial result never establishes complete
resource coverage, even when its error is understandable.

Content classification failures identify `processing_stage: source_classification`.
`content_decision` describes the denied academic payload, whereas `meta.egress`
describes release of the reconstructed safe error. Blocked result releases emit
a warning-level `data_egress_blocked` event containing only the request ID, fixed
reason code and decision. No source names, opaque source IDs or content are logged.
An unknown classification can mask later recipient/operation authorization gaps;
a source review alone does not guarantee that retrying will succeed.

`tests/test_actionable_error_diagnostics.py` exercises admission classification,
repeated safe projection, hostile diagnostic fields, real MCP privacy filtering,
retry timing and request-ID correlation. The public audit runner holds the entire
sweep for local contention, authorization contention and provider cooldowns.

## Inventory, reading and visual recovery

| Observation | Recovery |
|---|---|
| A collection is partial, unavailable, unsupported, or has yet to refresh | Use the branch state and reviewed cause. A missing assignment or file can still exist. Only a complete empty branch establishes an empty result for that collection and scope. |
| A resumable inventory has a cursor | Pass the returned cursor with the same selected course. A temporary failure retains the unfinished step. The first failing step's request ID stays with its branch across resume. |
| The assignments or files route returned 403 or 404 | Check that specific resource in Canvas. A 404 establishes unavailability to this request. A verified authentication challenge has a separate reconnect action. |
| A read reports an incomplete text extraction | Check `unit_coverage` for the unit kind, attempted units, usable units and omitted positions. A text continuation retrieves already extracted characters. Use an authorized visual read for a supported page or slide when text is insufficient. |
| A deadline expires | Use the observed stage, deadline and elapsed time when present. A stopped worker is reported only after a confirmed wait. An unknown operation state calls for operator follow-up before another attempt. A smaller slide range can still require deck conversion. |
| A request waits on admission | Honor the reported delay. A provider response carries its actual HTTP status. A cached cooldown, local contention or usage limit uses local evidence. A pending reservation can complete or expire under the normal ledger rules. |
| A page render exceeds the image budget | The PDF route makes at most one lower-resolution attempt. A failed fallback is reported as `resolution_fallback=failed`. Use the text route only if separately authorized. |
| A worker prepared an image | Check the image release and host capability separately. A native block in a prepared response gives no client decoding receipt. A client-side decoder can verify that particular image. |
| A source or parser version changes | Restart the affected read at its beginning. New read continuations include both `expected_hash` and `expected_parser`. Keep any notes about the older version separate. |
| A checkpoint write conflicts or its acknowledgement is uncertain | Reload the last committed revision before continuing. Full and delta file adapters serialize writers. After an interrupted local writer, establish that all writers have stopped before an operator clears a stale checkpoint lock. |

The additive `inventory_progress` fields describe the selected inventory. Counts deduplicate verified file identities. Incomplete or older resumable scans can report a lower bound. `reference_only_access_unverified` and retained metadata are lookup aids. Each new read still checks access. A server predating these fields has unknown coverage unless its existing coverage fields establish more.

`unit_coverage` supplements the existing extraction and OCR fields. It uses page, slide, sheet, section, or document positions. A sparse page can contain a footer while the body still needs OCR. Recognition confidence applies to the indicated page. Search results and page images have separate coverage.

Optional typed diagnostic fields include `resource_kind`, `blocking_scope`, `reservation_state`, `render_failure`, `operation_state`, `elapsed_ms`, and `deadline_seconds`. An absent field supplies no evidence. A long or unknown hold can lack a public delay. The audit runner keeps such holds for explicit resumption. Existing envelope and reason-code fields continue to work with clients that ignore additions.
