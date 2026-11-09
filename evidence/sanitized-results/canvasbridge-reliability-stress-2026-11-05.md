# CanvasBridge reliability stress test, November 5, 2026

The patched checkout can return a complete workload with 50 of 150 assignments missing. Its consistency audit can also flag an explicitly replaced deadline as conflicting. Both results reached a client through the public MCP tools. The findings below have executable synthetic reproductions.

## What ran

The three pending repair chats finished before the source freeze at 4:02 a.m. New York time. The audit copied 870 Git-listed working files byte for byte, including uncommitted and untracked source, into an isolated checkout. The base commit was `5bd086356e730b01b5a9f1be9de106446ef049c6`. The sorted path-to-hash manifest had SHA-256 `2601ecf57e5e8ed73921a9a9fafee0f9aec1aa4e0c95ee3f1c54e6dff5c837b2`.

The earlier release manifest covered 869 files. Eighteen paths differed, including eleven application source files and four tests. A new full run used the frozen checkout, a private loopback test server, disposable PostgreSQL, English OCR and the native slide converter. The public-tool probes used fictional Canvas responses, local fixture identities and disposable stores. All load was local to this investigation.

## Repair priorities

### 1. Workload pagination can silently omit assignments

A fictional course contained 150 distinct assignments due inside the requested window. The client followed every workload continuation, requesting ten assignments per response. All three failing cases ended with `status=ok` and `collection_complete=true`.

| Provider continuation | Source pages requested | Distinct assignments delivered |
| --- | --- | ---: |
| Ordinary `rel="next"` | 1, 2 | 150 |
| `rel="next last"` | 1 | 100 |
| `rel="NeXt"` | 1 | 100 |
| `page=2&page=3`, with a fixture server that uses the last value | 1, 3 | 100 |

The HTTP adapter looks up the exact string `next` in the HTTP library's relation map. The continuation validator also accepts repeated pagination parameters. The mixed and uppercase relation cases reproduced against the frozen release copy. Instructure's reference serializer emits individual lowercase relation names. The frequency of the alternate forms on an actual institution's installation is unknown. The HTTP standard permits multiple relation names and specifies case-insensitive matching for registered names. [RFC 8288 §§2.1.1 and 3.3](https://www.rfc-editor.org/rfc/rfc8288.html#section-3.3) · [Canvas reference serializer](https://github.com/instructure/canvas-lms/blob/master/lib/api.rb#L478-L490)

**Fix and acceptance.** Parse the relation tokens before deciding the collection is exhausted. Reject ambiguous page parameters before dispatch. For every fixture, deliver all 150 IDs exactly once or return explicit incomplete coverage. Keep origin, course, route and query-scope validation. Start in `canvas.py` at next-link extraction and `policy.py` in `validate_continuation`.

### 2. A deadline extension becomes a false conflict

Canvas and the new syllabus deadline both said November 9. The syllabus read “Quiz 12 was originally due on November 2, 2026, but the deadline has been extended to November 9, 2026.” The public `audit_course_consistency` tool classified November 2 as `conflicting_deadlines` and November 9 as a `syllabus_only_candidate`. The matching code associated Quiz 12 with the first date and lost the association for the second. The older release copy left the two syllabus candidates unmatched. The false conflict appeared on the newer checkout.

**Fix and acceptance.** Carry the assessment identity across an explicit old-to-new amendment within the same sentence. Preserve both citations, label the former date historical, and compare the replacement date with the assignment. Ambiguous changes should remain unresolved. Start in `academic_rules.py` at `dated_obligations` and `deadline_findings`.

### 3. A temporary throttle discards previously read PDF pages

A three-page PDF was fully extracted. A status-only call then received HTTP 429 while checking file metadata. After the cooldown and a successful fresh metadata check, the public status tool returned `access_state=available`, `state=inaccessible`, `indexed=false`, and no page count. Reading the identical bytes again required another download. The same stale status appeared after a genuine 403 was followed by restored access. The 403 correctly withheld sources and invalidated the old extraction.

**Fix and acceptance.** Distinguish a transient failed check from a confirmed denial. Withhold content while access cannot be established. After fresh authorization of the same source and version, allow eligible work to resume. After a real denial, keep the purge and report that a newly accessible file needs extraction. The issue reproduced on both frozen copies. Start in `course_files.py` at `authorized` and `status`.

### 4. One canceled reader cancels 16 independent readers

Seventeen separately authorized clients requested the same assignment through the Canvas adapter. They shared one upstream request. Canceling only its leader propagated `CancelledError` to all 16 waiting readers. The shared entry cleared, and a fresh serial read succeeded. In `usage/cache.py`, the leader publishes its cancellation exception to the shared future. Both frozen copies reproduced it. This probe exercised the assignment adapter and shared cache. An installed-client cancellation was outside the run.

**Fix and acceptance.** Isolate a caller's cancellation from other callers. Surviving readers should finish under their own authorization and deadlines, or receive a typed retry result. Verify follower cancellation, last-waiter cleanup and provider-attempt accounting.

### 5. Rejected continuation links lose their cause and usable recovery guidance

* A malformed port (`bad` or `65536`) raised a raw `ValueError` in URL validation. The public workload tool turned the bad-port case into `TOOL_EXECUTION_FAILED` with zero delivered items.
* A same-route synthetic opaque page token was rejected as `EGRESS_ERROR_REDACTED` after page one. Canvas documents its pagination links as opaque. The fixture demonstrates an interoperability limit. The test did not establish which cursor format the user's institution issues. [Canvas pagination documentation](https://developerdocs.instructure.com/services/canvas/basics/file.pagination)
* A cross-course link and a nonempty user-switch parameter both stopped before any out-of-scope dispatch, but both surfaced the same generic redacted error. The real 403 control returned `RESOURCE_PERMISSION_DENIED` and zero items.
* The adapter forwarded blank injected query parameters and duplicate pagination arguments to the fictional provider. The test observed only outbound query shape. It established no impersonation or access to another person's data.

**Fix and acceptance.** Parse and validate each parameter once, including blank and duplicate values. Use an allowlisted diagnostic for invalid or unsupported continuations. Keep unsafe requests blocked. Preserve already authorized progress only when current authorization and the product's release policy allow it. Start in `policy.py`, `canvas.py` and `egress_errors.py`.

### 6. An oversized inventory page leaves no way to resume it

The public resumable tool returned all 1,000 ordinary file IDs in 13 calls, including ten provider file pages. It also returned all 100 files with 600-character multibyte display titles. With 100 files carrying 900-character display titles, the first call fetched the source page but returned `BUFFERED_OUTPUT_TOO_LARGE`, zero file IDs and no continuation. The fixture used short filenames and deliberately wide display titles to isolate the byte boundary.

**Fix and acceptance.** Split an authorized source page into byte-bounded client responses and preserve its unread suffix behind an owner- and scope-bound cursor. In the 900-character case, every ID must be reachable exactly once under the existing response limit. Start in `paged_inventory.py` at `page` and the 250,000-byte guard in `app.py`.

## Results and controls

| Check | Observed result |
| --- | --- |
| Full Windows Python suite, frozen checkout | 2,671 passed in 33 min 44 s, with 13 Linux-only skips and one JUnit reporting warning. All 38 failures and setup errors from the first repair run and all 3 failures from its follow-up passed here, matched by test ID. The disposable PostgreSQL instance stopped cleanly. |
| JavaScript suite and widget handshake | 87 passed. The shipped widget matched its build. Absent, embedded, linked and rejected host-download cases passed in the synthetic host. |
| Existing 73-case integration corpus | 71 distinct cases passed, 2 blocked. Initially 68 passed. After inspecting the actual PDF and slide PNGs, all three hash-bound visual checks passed on a separate run. |
| New adversarial and control cases | Two runs each returned the same 21 failures and 11 passes across 32 cases. The final run used the exact archived modules. The failing cases include variants and lower-level reproductions of the six repair areas above. |
| Previously intermittent deadline evidence-graph assertion | 60 fresh fixture runs passed on the frozen checkout. |
| Academic benchmark, full tier | 81 objective passes across 83 scenarios, zero objective failures, 2 requiring review. |
| Scientific retrieval and conceptual search | 10/10 scientific retrieval cases, with interpretation review outstanding. Search returned the intended result in the top five for 34/34 answerable queries, and returned no hits for all 6 unanswerable queries. |
| Private library, 1,000 fictional items | 50 samples per operation. p95 was 0.336 s for listing, 1.181 s for search and 0.052 s for finalize-after-validation. All three met their local benchmark targets. |
| Concurrent public reads | Four bursts of 32 authenticated saved-state reads across two synthetic owners. All 128 returned the expected owner's value, and both subsequent fresh-session checks succeeded. |
| Admission and PDF recovery controls | 12,000 seeded admission attempts respected global and per-key concurrency limits and returned to zero active leases after every wave. Three randomized sparse-cache walks reconstructed all 25 pages of a fictional PDF without gaps or duplicated text. |
| Grade audit under delay | All 22 delayed assignment-detail responses completed. A stall injected at automatic syllabus discovery produced `partial_data`, `indeterminate` and the correct stage in approximately 88.3 s under the default 90-second budget. |
| Static and governance checks | Repository-wide Ruff lint and formatting passed on the frozen source. The governance registry validated all 30 controls. |

The corpus still needs a genuine user acknowledgment for AI-19 and a disposable Windows installation with trusted upgrade and rollback artifacts for OP-07. This audit did not exercise a Linux kernel, production Canvas load or the installed ChatGPT client. Three visual checks reviewed specific synthetic pixels. Scientific interpretation accuracy remains unscored.

## Reproduction and evidence

The accompanying bundle contains six runnable modules and the PowerShell command. Each failed assertion captures the desired behavior for a future fix. Run the modules against the source version identified above. The archive SHA-256 is `6373b6fea83d6664ddaaf0bdf8cf3111e1ac46098ab610355d1d2bb9fa0e3f6d`. [Synthetic reproduction bundle](canvasbridge-reliability-reproducers-2026-11-05.zip)

Raw JUnit, manifests, benchmark results, repeated graph checks, and visual observation hashes are in the private workspace directory `.local/nuclear-20261105/`. All 869 files in the earlier release copy matched its manifest. All 870 original files in both the audited copy and the working checkout matched the current audit manifest on verification. The report and reproduction archive were the only new Git-visible files.

### Follow-up verification for finding 2

The two archived Quiz 12 probes failed again against the frozen audit source. Both passed against the repaired working tree, including the public MCP call. The public audit retains separate date citations for November 2 and November 9 under the same assignment. It marks November 2 historical and compares November 9 with Canvas. A synthetic Canvas deadline of November 2 produces one deadline conflict against November 9. Conditional wording, competing assessment identifiers, alternative dates and a question remain unresolved in the focused controls.

During repair, 135 tests passed across the academic dates, academic intelligence, damaged academic corpus and evidence graph modules. After the final citation and public-route test changes, the focused amendment selection passed 11 tests (56 deselected). The two archived probes passed on the final application source. Ruff lint and formatting passed for the three affected Python files, and the scoped diff passed its whitespace check. These checks used synthetic local fixtures. The full suite, installed client and deployment were outside this verification.
