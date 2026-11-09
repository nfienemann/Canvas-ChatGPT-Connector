# Public-path file audit — November 3, 2026

This is implementation/test evidence, not a clean-course or release claim.
Live identifiers, filenames, course names, source contents and signed URLs are
excluded. Live checkpoint/report files reside in the operator's local application
data directory, outside this repository and its synchronized workspace.

Implemented a host-injected public-tool audit with stable course/file identity,
discovery-path retention, text continuation tracking, sheet/page coverage checks,
actual in-memory image decoding, bounded retries, whole-sweep throttle holds and
atomic checkpoint adapters. Unknown/missing inventory branches are incomplete.
Malformed tool envelopes cannot silently count as file results. Checkpoints bind
to the connection and complete selection refreshes discard withdrawn courses.

Repairs:

- Membership refresh propagates the underlying failure instead of falling through
  to a stale-scope error; normal successful refresh still renews the lease.
- Empty failed course listings retain a connection-bound metadata source and safe
  error diagnostics rather than becoming unclassified derived content.
- File inventory privacy filtering receives the actual Canvas user identifier.
  Known restricted source classifications remain enforced on inventory metadata.
- Inventory minimization retains stable IDs, source versions, module references,
  coverage and safe branch reasons; projection truncation stays partial.
- Retry-After survives collection/refresh/error projection. Existing durable
  cooldowns return a wait hint without weakening admission or authorization.
- The synthetic benchmark extraction adapter no longer infers visual reading
  from an unfamiliar partial-text coverage label.
- Regenerated the stale independent workflow request schema from its current model.

Executed checks (overlapping selections, not additive):

- Full repository run: **2,227 passed, 31 skipped, 2 failed**. The failures were the
  benchmark visual-interpretation inference and the stale request schema.
- After those repairs: all **75 benchmark tests** and a **53-test schema/audit/
  private-grant selection** passed. No subsequent full-suite pass is claimed.
- **105 focused reader/inventory/egress/rate-limit tests** passed before the final
  diagnostic additions; subsequent affected tests passed independently.
- **26 usage integration tests passed, 1 skipped** (no disposable PostgreSQL DB).
- Latest diagnostic/private-grant selection: **37 passed**.
- Final affected HTTP/schema/audit selection: **38 passed**.
- **15 Node audit tests passed**; the Pillow decoder also passed a real synthetic
  PNG decode and corrupt/truncated-image rejection test. Ruff and diff checks passed.

Installed connector calls reproduced stale scope, missing governance, unknown
classification, a content-hash review requirement and throttling. All-course
coverage explicitly reported a later unavailable course and a subsequent course
not refreshed. Live requests used the installed public tools and their existing
recipient settings; no local content read replaced a denied plugin response.
The private application was restarted through its verified existing helper.
No permission evidence, source review, recipient grant or upstream limit was waived.

## Remaining acceptance boundaries

Follow-up discovery repairs added course-scoped flat folder enumeration (including
subfolders), cycle/parent/context validation, assignment-anchor file resolution,
and opaque provenance through both egress minimization and final privacy projection.
No folder URL is followed and linked files still require course-qualified metadata.
Truncated assignment lists/anchors and unresolved files have explicit reason codes.
Interrupted discovery resumes after completed courses. Changed file versions reset
read proof while retaining historical discovery paths. A continuation can never
be hidden by a contradictory complete flag.

Follow-up checks: **118** focused inventory/privacy/reader checks, **58**
authorization/egress checks, **50** final projection/privacy checks, **6**
assignment/folder reason-code checks, and **17** Node runner tests passed. These
selections overlap; they are not an additional full-suite run.
After adding the fixed inventory reason codes to the error projection, the
**16-test** inventory/refresh diagnostic selection passed. The installed public
connector retained the unresolved-assignment-file diagnostic in its next response.
The Windows restart helper now handles unavailable listener ownership reported as
PID zero using its existing verified resource/process-tree checks; known unrelated
listeners still refuse shutdown. **8** synthetic PowerShell acceptance cases passed.

The subsequent resumable implementation adds `inventory_mode` and `cursor` to the
existing public file-list tool. One bounded operation advances an immutable,
encrypted owner/connection/course/epoch-bound checkpoint; Replay, scope changes,
normal lease renewal, explicit cursor expiry, throttling, folder graph handling,
and reference-only denied files have synthetic regressions. Restrictive assignment
reviews also deny the release of linked-file provenance through real synthetic MCP.
Checks: **142** focused inventory/privacy/egress tests passed, followed by **9**
final cursor/public-MCP tests and **19** Node runner tests. Selections overlap.

The private service was restarted. Although the displayed host schema lacked the
new arguments, an installed native-tool capability probe accepted resumable mode
and its next cursor, reporting the ChatGPT recipient. The new full crawl is in
progress; this capability probe alone does not establish complete enumeration.
Folder-file pages now require fresh course-qualified folder metadata with matching
course context before any global folder route is permitted. Cross-course and
unbound global-folder reads are rejected. **73** focused synthetic checks passed
after this change. Source-content and visual grants remain independent of metadata discovery.
Cold/warm-cache behavior and scope renewal have synthetic coverage; blocked live
content release does not establish live full-text, all-sheet or visual acceptance.
See `docs/course-file-audit.md` for the runner's limitations and resume contract.

After the folder boundary and resumable changes, the full synthetic suite passed:
**2,262 passed, 31 skipped** in 1,272.35 seconds. Skips require unavailable
PostgreSQL, Linux, OCR, or explicit native-converter runtimes. The audit runner's
**20** tests passed, including preservation of the first failing operation/request
ID and removal of stale failures at a new inventory pass. These checks do not
establish live document release or rendering acceptance. The expanded installed
inventory and final reader pass remain separately recorded in the private report.

The runner subsequently gained independent visual checks after text-release
failure, and now continues to later known pages after a page-specific rendering
failure. **23** Node tests pass, including actual decoder-result requirements,
separate text/image permission outcomes, and incomplete text remaining partial
even when images are available. No Python service code changed after the full
suite above. Live visual acceptance remains separate from these fixtures.

The subsequent visual pass exposed fixed renderer error codes being replaced by
`EGRESS_ERROR_REDACTED`. The positive error vocabulary now retains only the
renderer-defined codes and reviewed processing stages; arbitrary error text and
unreviewed codes remain redacted. **51 passed, 2 skipped** in the focused
projection/egress/visual selection after this change. The runner's **24** tests
also cover public metadata fallback after page-one rendering failure. This small
Python projection change occurred after the full-suite result recorded above.

Reproduced PDF image-output limits now get one bounded retry at the existing
standard 1600-pixel resolution. Byte caps, worker limits, source authorization,
hash checks and post-render permission checks remain unchanged. The returned
limitations disclose the fallback. Other failures do not trigger this retry.
The expanded focused selection passed **55 tests, 2 skipped**. The subsequent full
suite passed **2,283 tests, 31 skipped** in 1,339.58 seconds. All **26** Node runner
tests pass, including explicit retry reset for old partial coverage and visual
failures. Five targeted live PDF retests no longer returned the image-output
limit after the bounded fallback; they returned the classification gate instead.
No released or decoded live pixels are established by that change. The remaining
live visual sweep is recorded in the private checkpoint.

The installed final discovery and text-reader attempts finished. The independent
visual sweep stopped at its bounded retry limit on `LOCAL_REQUEST_BUSY`; it is
not a completed final audit. The private report/checkpoint retains unfinished
visual routes and the last failing operation/request ID. No live image decoding
acceptance was established. Previously completed Omics/all-course/HW5 comparison
probes remain historical evidence; their final refresh was deferred by this hold.
Source listing denials and content governance/processing failures independently
prevent a clean result. Resume through the public tools after the active request
finishes, honoring Retry-After; do not clear the governor or reconnect merely for
local capacity contention.

The Node audit suite is included in CI. The full-suite and focused results above
precede concurrent governor/error-guidance edits observed during the final live
run; they do not establish validation of those later edits. No remote CI run,
commit, or publication was performed by this audit. Permission evidence and
ChatGPT recipient settings were not changed. Private live reports remain outside
the repository.

At the user's request to reduce testing contention, personal-development
accounting now defaults to two concurrent requests per token, configurable from
one through four. The owner cap accommodates that choice; production defaults,
provider throttles, budgets, authorization and content-release checks remain.
The private service was restarted. **105 focused governor/integration/request
tests passed, 1 PostgreSQL-only test skipped**. The new regression verifies two
admissions, third-request contention, capacity recovery and authorization calls.
The native visual audit resumed and reached ordinary classification denials on
the next references; this is transport progress, not content-read acceptance.

After that change, every remaining visual route reached a recorded terminal
outcome. One route exhausted a bounded malformed-response retry; no decoded live
page coverage was established. The final native comparison probes completed:
the single-course request refreshed its assignments, while the all-course request
explicitly left later courses unrefreshed. The assignment-detail governance denial
persisted. Exact private counts, references and request IDs remain in the local
report. The result remains not clean; completed attempts are not full reads.
