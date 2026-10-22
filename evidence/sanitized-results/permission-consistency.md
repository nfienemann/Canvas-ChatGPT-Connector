# Permission consistency verification — 2026-10-21–22

Current result: **PASS for the requested private installed-MCP course/files
diagnostic and metadata audit.** On October 22 the installed diagnostic returned
consistent scope, HTTP 200 for both resources, two minimal upstream requests and
no state modification. The normal installed file listing returned 36 files.
Protected-state comparisons confirm unchanged credentials, selection,
permissions and private configuration. Normal metadata reads updated only the
authorization-lease timestamp in the compared connection/course records.
Document downloads/extraction, future OAuth renewal stability and durable
Windows clock synchronization remain outside this proof.

Initial October 21 scope: local implementation and synthetic security/MCP tests in the existing
Windows checkout. This is an additive schema-1.0 change. No migration, deployment,
course selection repair, permission grant or public-release action was performed.
Existing unrelated visual-reader, network and packaging edits were preserved.
Subsequent authorized deployment and installed verification are recorded below.

Requirement links: R01 (isolation), R10 (least privilege), R11 (safe credentials),
R12 (MCP contract), R14 (honest failures), R17 (regressions), R18 (observability)
and R40 (evidence). This record verifies the named cases, not full requirement
or release-gate acceptance. Tested working tree was based on `a0e5e86` and included
uncommitted edits; no new commit was created for this work.

## Investigation: observed versus unknown

The supplied incident reference was one character shorter than the canonical
reference returned by the installed connector during the authorized live retest.
The supplied reference reproduced the original `permission_denied` / “outside
the selected scope” response. An exact reference copied from the status response
successfully listed course-file metadata on the same connection immediately
afterward. Document contents and grades were not requested.

This establishes identifier truncation as the cause of the reproduced request
failure. It does not establish the exact arguments of the unavailable original
historical call. There is no evidence here of an authorization bypass or of a
production permission defect repaired by this implementation. Production IDs,
course names, filenames and raw tool responses are deliberately not stored in
this repository. At that checkpoint the running service had not been redeployed
with the new audit tool.

Code inspection also identified an independent diagnostic weakness: status used
stored selected/access flags, while resource tools refreshed course membership
before filtering exact IDs. The old single scope error could not distinguish a
malformed ID, changed selection, inaccessible course or mismatched connection.
These alternatives are tested independently; none is asserted as a second live
incident cause without evidence.

## Before and after

| Scenario | Before | After / observed evidence |
|---|---|---|
| Supplied shortened reference | Generic `permission_denied`, selected-scope wording | Live legacy retest reproduces the denial. New synthetic audit: `IDENTIFIER_MAPPING_FAILURE`, `identifier_state=invalid_format`; no suggested replacement or content. |
| Exact current reference | Current status advertised it | Live legacy metadata listing succeeds. New synthetic audit: local scope authorized; upstream remains `not_checked` by default. |
| Selected course, files restricted | Could be confused with course selection failure | `scope_authorized=true`, upstream `denied`, HTTP 403, `RESOURCE_PERMISSION_DENIED`. No unauthorized files. |
| Selected record no longer accessible | Generic scope denial | `SELECTED_SCOPE_MISMATCH`, `result=inconsistent`; no state repair. |
| Expired entitlement lease | Refresh-needed message | `STALE_SCOPE_SNAPSHOT`, `result=indeterminate`; no automatic refresh. |
| Valid reference in another owned connection | Generic scope denial | `IDENTIFIER_CONNECTION_MISMATCH`; no other connection ID or course data. Foreign-user and unknown IDs remain indistinguishable. |
| Expired/rejected credential | Could be obscured by a later selected-scope error | Local expiry or explicit invalid-token rejection produces `UPSTREAM_AUTH_EXPIRED`; no audit refresh or repeated probe after authentication failure. Bare 401 remains unknown. |
| Transport failure / 404 | Broad unavailable/permission statuses | Machine-readable transport reason or `RESOURCE_UNAVAILABLE`, retaining uncertainty about visibility versus absence. |

Executed fictional examples, including the complete report envelopes, are in
[permission-consistency-examples.json](permission-consistency-examples.json).
These were generated with the synthetic provider and an in-memory database;
temporary fixture encryption material was removed with its temporary directory.

## Implementation evidence

- `src/canvas_bridge/authorization.py`: trusted-owner decisions, exact canonical
  mapping, connection isolation, selected/access lease, endpoint capability
  checks, redacted correlation logs and request completion checks.
- `src/canvas_bridge/permission_audit.py`: local-only default; optional bounded
  GET probes without response-body reads, retries or credential refresh; explicit
  unknowns; scope-change detection; recommendations only.
- `src/canvas_bridge/app.py`: typed discoverable read-only MCP tool, additive
  reason-code error data, request IDs and authorization recheck before response.
- Existing course read paths use `Bridge.selected` and per-resource client
  guards. File object visibility, grade capability, cached-work checks and
  syllabus-only includes remain independently restricted.
- [Tool contracts](../../docs/tool-contracts.md) and
  [developer troubleshooting](../../docs/permission-consistency.md) document the
  limits and authorized recovery paths.

## Required scenario coverage

All records are fictional. `tests/test_permission_consistency.py` covers the
decision and diagnostic behavior; `tests/test_permission_consistency_contract.py`
uses the actual official MCP HTTP client and a loopback Uvicorn service.

| Required scenario | Evidence |
|---|---|
| Selected course with listable files | Exact-ID incident regression and minimal successful probe |
| Selected course with restricted files | Parametrized 403 and locked-file tests; no unauthorized search results |
| Unselected course | Shared `COURSE_NOT_SELECTED` decision; no upstream probe |
| Different connection / different user | Owned-connection mismatch plus indistinguishable foreign/unknown references; authenticated MCP denial |
| Stale scope snapshot | Expired lease, inaccessible selection and retained-state comparisons |
| Expired upstream credential | Stored expiry, invalid-token challenge, near-expiry no-refresh and error propagation |
| Inaccessible/deleted resource | Local course-access loss and ambiguous upstream 404; no deletion inference |
| Mapping inconsistencies | Truncated ID and corrupt stored canonical mapping |
| Concurrent selection changes | Remove/reselect race, final MCP response rejection and lease expiry during a probe |
| MCP reconnection after server restart | Stop server, recreate Bridge/Store against persisted synthetic SQLite, initialize a new authenticated MCP session; identical current scope |
| Course access without grade capability | Grade tools denied; syllabus-only request omits grade includes |
| Resource denial after course authorization | Distinct collection/object permissions and missing object visibility evidence |

Additional checks assert every persisted table is unchanged by the diagnostic,
no response body is consumed by probes, unsupported grade/syllabus probes stay
unchecked, no quiz attempts are authorized, cached workload cannot bypass a
missing assignment capability, and logs contain no raw identity/course refs or
fixture credentials.

## Checks executed

- Initial existing security/file/obligation/MCP regression batch: **125 passed**.
- Expanded affected security, grade, academic, obligation and MCP batch:
  **177 passed** at that implementation stage.
- Final focused permission suite plus the file-message regression: **38 passed**.
- Final complete suite: **518 passed, 21 skipped in 129.22 seconds**. Skips were
  12 Linux kernel checks, 7 disposable PostgreSQL checks and 2 optional OCR checks.
- Ruff lint and format checks on `src` and `tests`: passed.
- `git diff --check`: passed (Git emitted CRLF normalization notices only).

Earlier runs identified an expected catalog-count update and a file-error
wording compatibility issue;
both were corrected. An initial external TCP positive-control timeout in the
AppContainer test passed on the next full run. No test was weakened or skipped
to conceal that earlier failure.

## Verification limits

At initial implementation, the new diagnostic had not been deployed or invoked
through the installed live connector. Subsequent deployment and authentication
checks are recorded below. The initial live evidence concerns existing
status/file-listing tools.
Metadata probes cannot prove item-level permissions, enrollment completeness,
document extraction, or grade/syllabus access. The diagnostic retains no historic
status snapshot and cannot prove a cause for an unrecorded past request.

Linux kernel checks, disposable PostgreSQL checks and optional OCR checks depend
on their respective environment/runtime and are not established by Windows
SQLite fixtures. Public/institutional release gates remain unchanged.

## Authorized live follow-up — 2026-10-21 17:26 UTC

The owner subsequently requested deployment and a read-only course/files audit.
The private PostgreSQL service preflight passed, with the existing schema at
`4be2ca7831f0`; no migration or credential setup was needed. Automatic approval
review rejected the guarded service-stop/restart command as "blocked by policy"
without a more specific reason. The running MCP service was not restarted and
deployment remains incomplete. The command was not retried through another path.

The new diagnostic function was then executed through the existing private
operator configuration against the live connection, using the exact opaque
course ID from connection status. This is live upstream evidence, not proof of
deployment or invocation of the new tool through the installed MCP connector.

- Report: `ok`, active connection, canonical mapping, selected course, owned
  connection, current authorization lease and consistent scope.
- Course and file-list metadata probes: HTTP 200 and
  `UPSTREAM_METADATA_ACCESS_CONFIRMED` for both resources.
- Exactly two upstream requests; no response bodies, grades, quiz questions,
  submissions or document contents were read.
- Before/after comparisons confirmed unchanged connection/course rows during
  the audit and unchanged selection, permissions, stored Canvas credentials and
  private configuration from the deployment preflight.
- No retry, credential refresh, permission repair or selection change occurred.
  Individual file download/extraction authorization was not tested.

The detailed report remains in the private operator directory outside the
repository; no real course IDs, course names, credentials or resource metadata
are included here. The previous full suite (518 passed, 21 skipped) was not
repeated because this follow-up made no application-code changes.

## Restart and connector renewal — 2026-10-22

The owner reported restarting the MCP server and authorized completing the work.
Initial inspection found no private service listener or tunnel process; the
installed connector returned an unavailable/404 transport error. Starting the
existing private launcher with `Start -NoBrowser` restored PostgreSQL, the API
and the same tunnel without a stop command, migration or configuration edit.
The installed connector then returned `ok` for connection status, including the
new scope version, correlation ID and per-course authorization fields. This
confirms the updated service is running. It does not prove the new diagnostic
has been discovered or invoked by the installed ChatGPT connector.

The requested course remained selected with its exact canonical ID. Its previous
authorization lease had expired. The diagnostic executed through the existing
private operator path returned `partial_data` / `STALE_SCOPE_SNAPSHOT` for both
course and files, made zero upstream requests and reported no state modification.
This is an expired cached-access finding, not a Canvas resource-permission denial.

ChatGPT's supported Refresh tools UI failed twice with "Couldn't update the app."
A normal course-metadata read through the installed connector then returned
`UNAUTHORIZED` / "Reauthentication required" before any refresh could complete.
The owner explicitly authorized renewing the existing ChatGPT connector sign-in,
while retaining the same account, permissions and Canvas credential. The normal
Reconnect flow displayed "Primary is now connected". Nevertheless, subsequent
installed-tool calls still returned reauthentication-required, and the next
catalog refresh failed. The cause of that remaining host/identity-provider
failure is not established; a UI connection toast is not successful MCP proof.
No access-control check was bypassed and no new credentials were manufactured.

Hash comparisons after these actions confirmed unchanged connector permissions,
selected courses, stored Canvas credentials, connection/course rows and private
configuration. Today's file access remains unverified; the previous day's HTTP
200 probes are historical evidence only. Detailed reports and UI screenshots
remain outside the repository in the private operator directory. No application
code changed, so the previously completed full suite was not repeated.

Remaining acceptance: successful authentication from the installed connector,
successful catalog refresh exposing `audit_permission_consistency`, then the
authorized normal course-metadata refresh and exact-ID course/files diagnostic.

The owner requested a handoff to a fresh chat to test whether the existing chat
retains stale connector-session or tool-catalog state. That explanation remains
unverified. A read-only check found the configured issuer's signing-key endpoint
reachable through the service verifier, with one RSA signing key. The saved
ChatGPT base-scope setting contains only `offline_access`, but the actual scopes
issued by the renewed grant were not observed; this is an investigation lead,
not a confirmed configuration defect. No scope setting was changed. The private
handoff records the exact identifiers, evidence paths, preserved authorization
boundaries and next checks. Only documentation changed during handoff preparation;
the completed full test suite was not repeated.

## Fresh-session authentication investigation — 2026-10-22

The first installed `get_connection_status` call in a fresh chat returned
`UNAUTHORIZED`, `TRIGGER_REAUTHENTICATION`, reason `www_authenticate_reauth`.
The fresh available-tool catalog still lacked `audit_permission_consistency`;
the supported app UI likewise displayed 28 read tools without that diagnostic
and marked the existing account "Authentication update required". A fresh chat
did not resolve the observed failure. No additional course/file call was made
while this authentication prerequisite remained unsatisfied.

Read-only service and public OAuth checks found:

- API and existing tunnel listeners present; public health HTTP 200.
- Protected-resource, OAuth and OIDC discovery returned HTTP 200. Resource,
  issuer and configured signing-key URL matched exact service configuration.
- The verifier retrieved one RSA signing key. The issuer advertises authorization
  code and refresh-token grants and S256 PKCE. These are capability metadata,
  not evidence that the latest grant received a working refresh token.
- A deliberately unauthenticated MCP initialize returned HTTP 401 with the
  expected protected-resource challenge. No credential was supplied or created.
- The canonical course reference still resolves to an owned active connection
  and a selected, stored-accessible course. Its authorization lease is stale.
  The separately retained shortened reference has no exact stored mapping.
  These are private stored-state observations, not current Canvas access proof.

After the owner signed into the existing identity-provider dashboard, read-only
inspection confirmed the expected static ChatGPT client, exact callback,
`academic:read` application permission and matching MCP resource indicator.
The latest visible provider event recorded successful Google authentication for
the configured owner. That event belongs to the environment login context; it
does not expose the ChatGPT Connect grant, issued token claims, or renewal
exchange result. The separate user-sessions page supplied no usable Connect
renewal evidence. No scope, callback, resource, identity or permission setting
was edited. The owner's report that app sign-in fails while cloud reconnection
appears short-lived is retained as a report, not a measured token lifetime.

The existing verifier collapsed all JWT validation failures into the same
rejection. A narrow diagnostic addition now emits operator-only fixed reason
codes and timestamps, without tokens, claims, identifiers, exception messages,
headers or URLs. Signature, issuer, audience, expiry, subject and required-scope
checks remain intact, as does the client-facing rejection. Synthetic tests cover
denial reasons, log redaction, unavailable keys and unchanged valid acceptance.
These diagnostics identify the first failed check; they do not establish the
cause of earlier unobserved requests.

Actual checks after this application-code change:

- Focused authentication, service-security, personal and MCP suite: **63 passed**.
- Complete suite: **533 passed, 21 skipped in 151.66 seconds**. Skips remain
  Linux kernel (12), disposable PostgreSQL (7) and optional OCR (2).
- Ruff lint and format checks on the changed Python files: passed after a
  formatting-only correction to the new tests.
- `git diff --check`: passed (existing CRLF normalization notices only).

Private before/after hashes at this stage confirmed unchanged connection/course
rows, encrypted Canvas credential, course selection, authorization state and
private configuration. The stored scope was not refreshed, and no upstream
Canvas request or document-content read was performed in this follow-up.

Deployment of these rejection diagnostics was initially pending. Automatic approval review
rejected the guarded API-only restart as "blocked by policy" without a more
specific reason. The command did not execute and was not retried through another
route. The owner's reported restart was checked against the API process: its
start time still preceded the diagnostic change. Manual launcher attempts then
reported parsing/path errors. A single path-existence check in the owner's
PowerShell returned false, while the agent's execution environment returned true
for the same launcher path; both reported the same Windows computer name. The
cause was subsequently resolved by opening the launcher and asking Windows for
its final filesystem path: the logical Local AppData path maps to the Codex
Windows package's private `LocalCache/Local` directory. The logical and physical
files have identical hashes, and the physical directory contains the existing
database and configuration. This explains why ordinary PowerShell could not
find the logical path while the agent could. The launcher is not a symlink, and
the observations do not indicate a different computer or account.

The existing launcher was supplied to the owner using that resolved physical
path, without copying it or changing its configuration. Vault and institution
configuration paths already name the physical directory. Parser/OCR paths are
only used for document operations, which are outside this metadata-only audit.
A new pre-restart snapshot still matches the earlier protected-state hashes.
At this checkpoint no successful restart or deployment of the new rejection
logging is claimed; the physical-path restart is awaiting confirmation.

During this investigation the cloud settings UI stopped showing its authentication
warning and exposed Refresh tools. A new installed status call still returned
the same `UNAUTHORIZED` reauthentication result. The agent did not initiate
another reconnect or tool-catalog refresh loop. The UI state change is not
successful MCP authentication evidence.

At that checkpoint the installed diagnostic invocation, fresh authorization and
file-listing acceptance remained incomplete. The subsequent bounded checks
below supersede that operational status without changing the historical record.

### Confirmed restart, clock evidence and current metadata reads

The owner ran the existing launcher at its resolved physical path. A new API
process started at 18:41:22 UTC, after the authentication diagnostic source
change; local/public health and the expected resource metadata returned 200.
The same database and tunnel were running. Before/after restart comparisons
matched all connection/course rows, credential, selection, authorization state
and private configuration hashes.

An actual installed `get_connection_status` succeeded at 18:42:35 UTC. A supported
Refresh tools attempt then failed, and installed `list_courses` returned the
reauthentication error. Newly deployed logs recorded `MCP_TOKEN_NOT_YET_VALID`
at the time of these failures. No token or claim values were collected. Windows
Time was stopped; three NTP samples measured the PC approximately 1.99 seconds
behind, corroborated by public issuer and independent HTTP Date comparisons.
The earlier coarse assertion that the server clock was consistent did not rule
out this small offset and is superseded by these measurements.

The agent could not start Windows Time because Windows denied service access.
The owner started it with administrator privileges and requested ordinary time
synchronization. The resync command reported no time data; subsequent status
showed a new successful-sync timestamp, and NTP samples measured offsets within
two milliseconds, including a later check around 18:50 UTC. Windows still
reported unsynchronized status, so durable clock health is not established.
No time-source configuration, JWT leeway, authentication check, permission,
Canvas credential or connector configuration was changed by the agent.

After the measured clock correction:

- Installed connection status succeeded at 18:46:17 UTC.
- Supported Refresh tools completed without the previous error. The existing
  app's visible catalog now contains 29 read tools, including
  `audit_permission_consistency`; a private screenshot records discovery.
- Installed `list_courses` returned `ok`, live, complete pagination, and an
  active selected target course at 18:47:01 UTC.
- Installed `list_course_files`, using the exact canonical reference, returned
  `ok` and 36 files at 18:47:18 UTC. Its inventory coverage reports pages,
  files and modules complete, no inventory failures, and
  `document_content_included: false`. Generic source evidence still carries
  collection/version limitations; this does not establish document download
  authorization or extraction success.
- Installed status at 18:49:58 UTC showed `scope_authorized: true` for the
  selected target. Status itself still reports upstream permission unchecked;
  the separate live course/file reads supply the current endpoint evidence.

After the normal metadata reads, credential, selection and private-configuration
hashes still match. Full connection/course and authorization hashes changed as
expected. An in-memory comparison restoring only the previous entitlement
timestamp (reconstructed exactly in the original database timezone) reproduces
both original hashes. Thus the only change in those protected records was the
normal authorization-lease timestamp update. No database value was manually
modified during comparison. The shortened reference remains distinct and
unresolved.

These observations establish current token-timing rejections followed by
successful installed metadata calls after clock correction. They do not prove
the cause of every earlier app/cloud failure or the behavior of future renewal.
No application code changed after the recorded 533-test run, so that full suite
was not repeated.

At the end of that turn one acceptance item remained: the running chat still exposed the earlier
28-tool list even though the existing app UI displays the refreshed 29-tool
catalog. The diagnostic has been discovered in the installed app but has not
yet been invoked through an available installed tool in this chat. Do not treat
the successful course/file reads, UI catalog or private operator invocation as
that missing proof. Check catalog availability on the next turn, then invoke
the diagnostic with the exact stored references and course/files upstream checks.

### Final installed-MCP acceptance — October 22

After the owner confirmed Refresh tools, this chat discovered the actual
`audit_permission_consistency` tool and its input schema. Both diagnostic calls
below used the exact 40-character canonical course reference, the existing
connection, `resource_types: ["course", "files"]` and
`include_upstream_checks: true`. The separately preserved 39-character reference
was neither repaired nor substituted.

| Installed operation | Observed result |
|---|---|
| Connection status, 18:53:38 UTC | `ok`; target selected, but local authorization lease had become stale |
| Diagnostic, 18:53:41 UTC | `partial_data`; both resources `STALE_SCOPE_SNAPSHOT`; zero upstream requests; `state_modified: false` |
| Normal course-list read, 18:53:54 UTC | `ok`, live, complete pagination; active selected target; normal authorization evidence refreshed |
| Diagnostic, 18:54:08 UTC | `ok`; `scope_consistency: consistent`; exact canonical mapping; current local authorization; both resources HTTP 200 / `UPSTREAM_METADATA_ACCESS_CONFIRMED`; two upstream metadata requests; `state_modified: false`; no recommended repair |
| Normal course-file listing, 18:54:40 UTC | `ok`, live; 36 files and six modules; inventory coverage complete for pages/files/modules; no inventory failures; no document contents included |

Separate before/after snapshots for each diagnostic matched full connection/course
and authorization hashes, encrypted credential, selection and all six private
configuration hashes. The final comparison against the pre-restart baseline
again matched every protected field after accounting solely for the normal
entitlement timestamp update in memory. No stored value was manually changed.
The last redacted token rejection remained before clock correction; none was
observed during these successful installed calls.

This completes the requested deployed-tool discovery/invocation and current
course-selection, authorization and file-listing acceptance. It is an actual
installed-MCP result, distinct from earlier private operator and synthetic
results. The endpoint probes do not establish permission to download every
listed file, and no document extraction was attempted. Broader institutional,
hosted-pilot and public-release gates are unchanged. Durable clock health and
future token renewal are still not established.

All raw responses, exact references and protected-state comparisons remain
outside Git in the private operator directory. No application code changed
after the 533-passed/21-skipped suite; the redundant full run was skipped.
Documentation `git diff --check` and checks for private identifiers in these
updated documents passed.

### Persistent Windows clock configuration — October 22

The owner subsequently authorized durable clock maintenance and appropriate Git
publication. Read-only inspection found a non-domain host without W32Time Group
Policy, Manual service startup, an enabled existing Microsoft NTP source, and a
32,768-second special poll interval. The clock had corrected, but status still
reported unsynchronized. No changes to connector authentication were needed.

The generic `scripts/windows_time_sync.ps1` was syntax-checked and dry-run with
`-Apply -WhatIf`. The owner ran its reviewed local copy as administrator. It
saved clock-only backups outside Git, set Automatic startup, removed service
triggers, set the existing source's special poll interval to 3,600 seconds and
restarted only Windows Time. The ordinary resync command completed successfully
at 19:03:33 UTC. An independent read-back confirmed Running/Automatic, no service
triggers, hourly polling, Leap Indicator 0, stratum 5 and the expected source.
Peer information showed the next poll scheduled approximately an hour away.

The script refuses domain/policy-managed hosts, a different source, a disabled
NTP client or incompatible polling bounds. It does not elevate itself, alter
service accounts/ACLs, create a privileged task, change a firewall, modify
connector configuration, or weaken token validation. Private clock backups,
Canvas credentials and academic records are excluded from Git.

This verifies persistent settings and successful synchronization after a service
restart, not observation across a reboot, a future hourly poll or a prolonged
network outage. The earlier clock-health uncertainty is resolved for the
observed configuration/status; future availability is not guaranteed.

### Isolated publication validation — October 22

An isolated worktree applied only the permission-consistency, redacted-authentication
and clock-maintenance changes to the newer remote main commit `46d0e3d`. The
owner's running checkout, private operator files and unrelated dirty changes
were preserved. The only integration conflict was the synthetic read-only
catalog count: current main's 32 tools plus the diagnostic equals 33. This
integrated branch was not substituted for the running private service.

A fresh isolated virtual environment was synchronized from the unchanged lockfile.
The full suite was rerun because this combined tree differs from the previously
tested deployment: **670 passed, 21 skipped** in 313.53 seconds. Skips were the
12 Linux-only checks, seven disposable-PostgreSQL checks and two unavailable OCR
runtime checks. Ruff lint, formatting (153 files), staged whitespace validation,
PowerShell syntax parsing and the clock script's `-Apply -WhatIf` check passed.
The explicitly staged 25 files contained no known private identifiers, private
hostnames, JWT/private-key patterns, operator configuration or database backups.

At 19:10:51 UTC a further actual installed connection-status call returned `ok`
with current selected-course authorization. Windows Time remained Running and
Automatic with no service triggers, a 3,600-second special poll interval and
Leap Indicator 0. Credentials, selection and all private configuration hashes
still matched. Full connection/course and authorization hashes also matched
after normalizing only the normal entitlement-refresh timestamp in memory;
no database values were manually edited.

Git publication preserves the generic implementation and sanitized evidence.
It does not configure another Windows host, deploy the integrated branch, merge
it into main or satisfy broader release gates.
