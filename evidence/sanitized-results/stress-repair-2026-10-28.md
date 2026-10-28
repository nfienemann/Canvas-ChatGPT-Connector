# October 28 stress repair — verification record

This records the initial repair. The later [follow-up verification](stress-followup-2026-10-28.md)
fixes its three failures and establishes evidence for sixteen of its blocked cases.

The repair brief's diagnostics, guidance and offline testability changes are
implemented. After the user's service restart, the installed connector returned
the repaired results. Institutional state remained disconnected, authentication
revoked, live integration disabled and provider approval NOT_ASSESSED. The
independent import inventory remained empty. No personal academic records were
imported, read or migrated, and no external writes or approvals were performed.

## Scope and build identity

- [Implementation and reproducible commands](../../docs/stress-repair-2026-10-28.md)
- Git base: `eaa1d9fbed79dbfaae7492753218005bebd529e5`; working changes are uncommitted.
- Final corpus run fingerprint:
  `9ea6beeee3714ff693ea1c0991339610646454e97398d7ad0907e3b07b10d5e8`.
- The corpus run verified unchanged source hashes throughout execution.
- [Build and exact per-case inputs/outputs](../../.local/stress-repair-final-2026-10-28/build.json)
  and [complete fictional receipt archive](../../.local/stress-repair-final-2026-10-28.zip)
  are retained locally. They contain no personal source material or authentication
  secrets. The build hashes source, tests, migrations, fixture registry and schemas.
- Python dependency versions: MCP 1.30.0, Pydantic 2.14.1, SQLAlchemy 2.1.5,
  pytest 9.1.1 and Alembic 1.20.0.

## Separate validation suites

| Suite | Observed result | Meaning and limit |
| --- | --- | --- |
| Supplied fixture self-checks | 24 passed | The reviewed package's arithmetic/structural oracles only; not Bridge execution. Local log: `.local/stress-fixture-selfcheck/result.log`. |
| Initial focused product regressions | 76 passed | Independent engine, diagnostics, integrity workflows and egress contract through HTTP MCP; subsequent added diagnostic cases are in the final full run. |
| Twelve-course adapter/import regression | 17 passed | All 36 fictional course Markdown files imported through the normal store, actual IDs/hashes obtained, all 12 independent requirement calls completed with LMS access disabled; native schema snapshots match. |
| 73-case product benchmark | **51 PASS, 3 FAIL, 19 BLOCKED** | Current source-bound outcome. Explicitly invoked outside ordinary pytest discovery; failing exit status. This does not certify the full feature collection. |
| Final repository regression | **1,908 passed, 29 skipped** in 718.59 seconds | Complete selection, exit 0, uninterrupted, source hashes unchanged. Skips require Linux, disposable PostgreSQL, native conversion or OCR runtimes. This is separate from the explicit 73-case benchmark. |
| Installed connector after restart | Diagnostic acceptance passed | Seven missing-source calls, two empty-scope calls, unavailable-policy guidance/preparation and disabled institutional access. No source-based live workflow success is claimed. |
| Code hygiene | Passed | Ruff on all repair Python files and `git diff --check`; Git printed existing line-ending normalization notices, not whitespace errors. |

The first full run had 1,886 passes, 29 environment skips and 20 fixture-registry
failures. The new fictional fixtures were then explicitly hash-registered. A
focused rerun had 73 passes and one stale-source assertion while documentation
was being edited. Those runs are diagnostic history, not a clean final acceptance
claim. The [final full-run receipt](../../.local/stress-repair-final-full-suite.json)
and [log](../../.local/stress-repair-final-full-suite.log) confirm a complete,
passing run with implementation, fixtures and documentation unchanged throughout.

## Installed diagnostic proof

[Before restart](stress-repair-live-smoke-2026-10-28.json), five missing-source
capabilities returned `EGRESS_ERROR_REDACTED`; deadlines and consistency already
returned an actionable missing-input result. The initial helper restart did not
replace the elevated Windows process: its command line was inaccessible and a
verified process termination returned Access denied. That unsuccessful attempt
is retained [separately](stress-repair-restart-attempt-2026-10-28.json).

After the user restarted the service, [the installed checks](stress-repair-live-after-restart-2026-10-28.json)
verified:

- All seven capabilities: `needs_input / INDEPENDENT_INPUT_MISSING`, minimal
  required fields, import/selection remediation and zero sources.
- Empty policy and assistance scopes: `INTEGRITY_SCOPE_MISSING`, with local
  course/document alternatives instead of mandatory institutional identifiers.
- Unavailable-policy guidance: `allowed=false`, `permission_established=false`,
  explicit alternatives, limits, evidence requirements and clarification topics.
- The downstream preparation still refused submission drafting and released no
  sources; guidance did not manufacture permission.
- Disabled institutional `list_courses`: `CONNECTION_INACTIVE` plus setup checks
  and an explicit statement that reconnection alone cannot establish approval.
- Before/after institutional access state unchanged and import inventory zero.

Request IDs and fixed outcome fields are saved without connection IDs, prompts,
tokens or real document contents. The live server has no exact-process build
endpoint; the current workspace interpreter path and changed installed behavior
were verified, rather than inventing a deployed commit attestation.

## Open product findings from the 73-case corpus

The [complete case status list](stress-repair-73-cases-2026-10-28.json) retains all
73 outcomes. The three failures are outside the brief's error/guidance repair:

| Case | Observed defect | Consequence |
| --- | --- | --- |
| RQ-01 | Both explicit word-count ranges were extracted, but a neighboring sentence saying a figure is recommended/not mandatory caused both ranges to become ambiguous/nonmandatory; `conflicts` was empty. | The mandatory word-count conflict was missed. Clause-level requirement interpretation needs separate repair. |
| AI-04 | The recognized brainstorming allowance was combined with an overly broad denial derived from a sentence prohibiting drafting/outlining/rewriting/diagrams. | Legitimate narrow brainstorming remained denied as a policy conflict. No unauthorized drafting was enabled. |
| AI-07 | “AI may correct spelling and grammar only” was classified ambiguous rather than a narrow mechanical-editing allowance. | Mechanical editing remained denied pending acknowledgment; this run supplied no invented acknowledgment. |

The 19 blocked cases retain these limits:

| Cases | Missing evidence or capability |
| --- | --- |
| GR-05 | Unequal-point drop optimization unsupported by the native grade engine; calculation refused. |
| DE-01, DP-02 | Exact scoped deadline/checkpoint adaptation unavailable on this imported-text route. |
| DE-02, DE-03 | Supersession kernel worked, but section/student-specific scope isolation is not represented by the native process model. |
| DE-05 | Native timestamps require an explicit offset; no unresolved two-instant DST object exists. |
| RQ-02 | No structured figure-requirement classification for the exact assertion. |
| AI-05, AI-06, AI-20 | The original brainstorming clause failed AI-04, so no prior allow existed for escalation/stale-permission testing. Separate regression tests do not count as corpus passes. |
| AI-14 | Mixed provider/local evidence was withheld by the classification boundary before integrity reconciliation. No permission expansion was released. |
| AI-19 | Actual test-UI acknowledgment was not supplied or forged. |
| VI-01, VI-02, VI-08 | No actual model-visible pixel inspection was performed by this automated harness. |
| VI-09 | DOCX cell text/ranges survived, but flattened local-reader output did not establish table-column relationships. |
| KN-04 | The corpus's active-recall case lacks an implemented adapter in this harness. |
| OP-03 | Process export denial and deletion worked; the complete combined export/index/backup-restore scenario was not established. |
| OP-07 | A separate disposable OS installation and current/previous packaged release were not provided. |

Successful OP-02 exercised a controlled exception after a real disposable SQLite
migration, verified encrypted backup creation, resumed the upgrade and retained
a fictional canary record. It is one interruption boundary, not every power-loss
point. ST-06 restored an older encrypted synthetic backup with the current deletion
journal and verified that the revoked connection was not restored. Neither test
touched the personal database or a production backup.

All original release, authorization, source-sharing and independent-review gates
remain in force. No publication, push, credential refresh or production consent
was performed by this repair.
