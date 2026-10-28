# October 28 stress follow-up — verification record

This follow-up fixes the three failures in the [initial report](stress-repair-2026-10-28.md)
and establishes additional evidence for sixteen previously blocked cases. The
original 73 scenarios, fixture bytes and gold expectations were not changed.
All corpus execution uses disposable synthetic data. Institutional access must
remain disconnected, authentication revoked, integration disabled and provider
approval NOT_ASSESSED.

[Implementation and reproduction](../../docs/stress-followup-2026-10-28.md)
describe the code changes and their limits. Changes are uncommitted on base
`eaa1d9fbed79dbfaae7492753218005bebd529e5`; pre-existing work is preserved.

## Final validation

The final 73-case corpus run completed with **70 PASS, 0 FAIL, 3 BLOCKED** in
148.93 seconds, exit 0. Source hashes remained unchanged throughout execution.
Fingerprint: `6f10bd61e20d0408154aa3b0414079944280da10f2971baab9af014ccb7d3707`.
The final full repository regression completed with **1,924 passed, 29 skipped**
in 720.54 seconds, exit 0. Its receipt confirms complete selection, no interruption
and unchanged source. The broader repository fingerprint is
`5baa1a7182038077de21ece157a2a6e9196ac582b3b0569d77ca86c93599c7a8`.
The 29 skips require Linux, a disposable PostgreSQL database, a trusted native
converter or an operator OCR runtime; they are not passes.

- [All 73 final statuses](stress-followup-73-cases-2026-10-28.json)
- [Build and dependency identity](../../.local/stress-followup-final-2026-10-28/build.json)
- [Complete synthetic case receipts and rendered PNGs](../../.local/stress-followup-final-2026-10-28.zip)
- [Exact hash-bound model pixel observation](../../.local/stress-followup-final-2026-10-28/visual-observation.json)
- [Corpus execution log](../../.local/stress-followup-final-corpus.log)
- [Full repository test receipt](../../.local/stress-followup-final-full.json)
- [Full repository test log](../../.local/stress-followup-final-full.log)
- [Files changed since the initial repair run, with before/after hashes](../../.local/stress-followup-change-manifest.json)

All 47 original corpus fixture hashes match the initial repair run.
Ruff checks passed for the changed Python files, and `git diff --check` passed.

The ordinary repository suite does not discover the explicit corpus file. Its
three blocked cases appear as skips only within that separately labeled run.

Completed diagnostic checks: the combined corpus probe had 70 PASS, 0 FAIL and
3 BLOCKED; focused regression groups had 216 and 119 passes, and the final small
adapter/negative-control group had 33 passes. These overlapping selections are
not added together. The unchanged package self-checks had 24 passes in the prior
turn and were not redundantly rerun.

## Repaired failures

| Case | Repair and observed behavior |
| --- | --- |
| RQ-01 | Clause-scoped requirement modifiers preserve the two conflicting mandatory word-count ranges. A neighboring optional figure no longer suppresses that conflict. |
| AI-04 | A fully recognized list of prohibited drafting/outlining/rewriting/diagram activities no longer erases a separate brainstorming allowance. Unknown remainders and negation remain conservative. |
| AI-07 | "Spelling and grammar only" is recognized as mechanical editing. Rewriting and assessed drafting remain denied. |

## Previously blocked cases now exercised

| Cases | Evidence and boundary |
| --- | --- |
| GR-05 | Native calculation with explicit percentage-drop semantics, exact ratios, unequal denominators and never-drop protection. This is the source's percentage rule, not generalized Canvas retained-grade optimization. |
| DE-01, DE-02, DE-03 | Original source hashes and passages feed the pure process reconciliation API. Conflicts retain both sources; explicit synthetic amendments apply only to the exact section/subject. Cross-scope amendments fail. This does not establish a general prose adapter or installed-client acceptance. |
| DE-05 | HTTP MCP deadline extraction returns both UTC possibilities for the repeated DST wall time and selects neither. The additional one-line synthetic setup is explicitly recorded. |
| DP-02 | HTTP MCP extraction retains separate top-level post and reply candidates from the original discussion instructions. |
| RQ-02 | The recommended figure is explicitly classified as nonmandatory with source evidence. |
| AI-05, AI-06, AI-20 | Actual brainstorming allowance now permits the corpus to test activity escalation, continuations and changed-source/stale-permission rejection. |
| AI-14 | Mixed provider/local evidence crosses only its appropriate ownership/classification paths; the local purported override cannot authorize prohibited drafting. |
| VI-01, VI-02 | Actual original PDF pixels were delivered through HTTP MCP, saved and inspected by Codex. Control 50 and treatment 75 support 1.5x, not the source's twice-control claim. No sample size, p-value or error bars were invented. Exact PDF/PNG hashes bind the observation to reruns. This is a specific model observation, not automatic backend interpretation. |
| VI-09 | HTTP MCP local reads preserve the DOCX table's cells, unique coordinates and the criterion/requirement/scope row association. Oversized tables are omitted whole with limitations. |
| KN-04 | Actual study preparation uses a PDF made from the original fictional source, recording both hashes. Questions are returned without answer keys or source passages, with an explicit wait-for-response action. |
| OP-03 | Disposable process export succeeds while authorized and is denied after revocation. Deletion clears the process inventory; restoring an older encrypted backup with the current deletion journal restores neither the deleted account nor process state. |

## Remaining three blocked cases

| Case | Exact missing acceptance |
| --- | --- |
| AI-19 | Genuine acknowledgment through the test UI. No human consent was supplied or manufactured. |
| VI-08 | Supported original PPTX slide pixel delivery and observation. The real independent rendering call returns unsupported; no trusted native slide converter is configured. Text/notes or embedded media do not substitute for whole-slide pixels. |
| OP-07 | Separate disposable OS installation, appropriate current/previous packages and controlled deployment-recovery interruption. Synthetic SQLite recovery does not establish this. |

No database migration, production import, credential refresh, institutional
reconnection, approval, consent, external write, publication or push was performed.
All release and independent-review gates remain in force. Installed service
restart and read-only boundary verification are separate from local product
acceptance.

## Installed service after restart

The user restarted the elevated service. New Python parent/child processes were
verified, created October 28 at 14:27:07 America/New_York. The configured helper
uses this workspace's interpreter. No running-process build attestation endpoint
exists, and no source-based personal workflow success is claimed.

[Installed boundary receipts](stress-followup-live-2026-10-28.json) verify the same
disabled institutional state before and after, an empty independent inventory,
and `CONNECTION_INACTIVE` on course listing. With no policy evidence, both
brainstorming and mechanical editing report `allowed=false` and
`permission_established=false`. Submission preparation is denied, with no sources
released and `transmitted=false`. No approvals or acknowledgments were created.
