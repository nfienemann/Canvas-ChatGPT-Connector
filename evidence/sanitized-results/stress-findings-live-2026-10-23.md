# October 23 stress findings: personal deployment and installed-tool checks

The owner explicitly authorized deployment and four live read checks. The
personal service restarted successfully at 20:44:30 America/New_York on
October 23, 2026 (00:44:30 UTC October 24), using its existing private
configuration. Windows elevation was approved through the normal UAC prompt.
The restart checked the existing service identity, saved process relationship,
loopback listener, and configuration fingerprints before replacing only that
service. Database and tunnel processes were left running.

An 11-module source fingerprint manifest was captured at restart and still
matched after the live checks. New response fields were observed through the
installed Canvas Bridge Personal tools in this Codex session. These are actual
installed-connector calls, not direct Python invocation of academic functions.
This does not repeat or expand ordinary ChatGPT client compatibility evidence.

## Four live checks

| Check | Observed result | Coverage boundary |
|---|---|---|
| `get_workload`, October 23 through November 6, overdue and undated included | 36 records; 16 historical past-due dates; 13 of those have submitted/resubmitted evidence and `none_indicated` action. Zero submitted/resubmitted items are classified overdue. The other three past-due items retain unknown action. | Assignment collection coverage complete for all four selected courses. No overdue unfinished item happened to be present; unfinished/uncertain edge cases remain covered by synthetic regression tests. |
| `reconcile_course_deadlines`, without material IDs | Automatic discovery found two prioritized documents and reviewed both within the existing bounds. The schedule produced 17 candidates. All 17 preserve its exact source metadata version, content hash (`document_version`), and PDF page 1 locator. | `partial_data`; OCR schedule extraction remains partial/uncertain. Candidates are not confirmed deadlines. Inventory coverage remains incomplete. No classroom activities were returned by this particular source; their separation is covered synthetically. |
| `search_course_files`, query `Motivation`, `include_unread=true`, maximum three documents | The schedule matched on PDF page 1 via English OCR. Its document diagnostics are empty, with no zero-text warning. Generic parser cautions remain separate. Confidence is 79/100; coverage reports one attempted and accepted page, zero failures or budget skips. | Bounded search inspected three documents, returned four passages, and left 31 documents for continuation. Another document exposed partial OCR and two budget-skipped pages. Search inventory reported 25 fresh and nine retained references, plus an explicit inventory-budget failure. No full-course absence claim is supported. |
| `list_course_files` | 34 references returned, all freshly checked through course-qualified module file metadata in this call. Every row exposes origin, freshness and access-verification fields. | `partial_data`: module collection complete; page listing returned 404 and file listing 403. Both branch failures and deterministic reason codes remain visible. A list result still requires fresh authorization for subsequent content reads. |

The current inventory count is 34, compared with the owner's earlier observation
of 33. This record reports the current bounded result and does not infer which
upstream or previously undiscovered reference accounts for the difference.
The search call additionally exercised retained-reference reporting when its
inventory budget was exhausted; the later standalone inventory call finished
its metadata checks successfully. Partial coverage propagated into both search
and deadline reconciliation.

Installed request receipts, in the same order as the table:

- `f64976cd0a5542be9d32b39bec288ca6` — 00:45:01 UTC, `ok`.
- `c1f82b7640144c8ab4b533565a8b4207` — 00:45:40 UTC, `partial_data`.
- `5813e204941a4c79b21ece5f1a8e9438` — 00:46:22 UTC, `partial_data`.
- `da30d9c842e9435fb839d584ad7eeeb8` — 00:46:51 UTC, `partial_data`.

## State preservation and verification

Read-only database snapshots before restart, immediately after restart, and
after all four checks confirmed identical fingerprints for:

- Encrypted credentials and credential lifecycle fields.
- Course selection: the same four courses remain selected.
- Authorization state: connection state/epoch, principal generation, course
  access, enrollment, selection and permission versions.
- Saved local records and background jobs.
- Private configuration, vault key, service launcher, and tunnel configuration.

Normal read-cache and refresh timestamps are outside the protected-state
comparison. No permissions, credentials, or selection were repaired or changed.
MCP saved-state writes stayed disabled, Calendar remained disconnected, and no
Canvas or Calendar write tools were invoked. The read-only provider boundary
and synthetic GET-only checks remain in place. PDF pixel delivery and
LibreOffice conversion code/configuration were not changed in this deployment
turn.

Full responses and private state proofs are retained only in the private
operator directory, outside tracked repository content. This record contains
aggregate outcomes, limitations and request receipts, not source passages,
student records or secrets.

The preceding implementation turn completed **835 passed, 24 skipped**, plus
**36 new regression tests**, focused checks, Ruff and whitespace validation;
see the [synthetic record](stress-findings-2026-10-23.md). No application code
changed in this deployment turn, so the redundant full suite was not rerun,
as permitted by the working agreement. Final `git diff --check` passed.
