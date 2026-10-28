# Academic integrity implementation evidence — 2026-10-28

## Scope and provenance

Implemented AI-01 through AI-06 after reviewing all eight Markdown documents,
including the README and appendix. Bundle SHA-256:
`5761b046cfdb2e7c104cb05b4233bece895b6c44ff8b3fe7e5b44779b51cecaf`.
Document text supplied requirements, not authority to deploy or change accounts.
All academic test records and principals are fictional. The Rowan reference test
contains a short public-policy excerpt, with partial coverage explicitly recorded.

See [implementation and requirement mapping](../../docs/academic-integrity.md).
The working checkout contained substantial preexisting and concurrent changes;
this report does not attribute all checkout changes to this implementation.

## Delivered behavior

- Separate administration, learning, logistical planning, substantive assistance
  and submission-content classifications, with activity-specific permissions.
- Authorized source discovery, coverage and provenance; reviewed public-policy
  references; conservative interpretation of restrictions, narrow grants,
  mandatory permission, conflict and source versions.
- Explicit, owned, expiring uncertainty acknowledgments that cannot override
  prohibitions or mandatory instructor/tool permission. Uploaded permission
  evidence does not automatically become verified instructor authority.
- MCP entry and output enforcement, offline known-copy restrictions, fresh
  source checks, controlled evidence packages and disclosure guidance.
- Encrypted, minimal and bounded receipts, expiry/deletion, six governance
  controls and reproducible measurement/report generation.

## Actual execution results

| Execution | Result | Evidence boundary |
| --- | --- | --- |
| Full suite | 1,785 passed, 28 skipped, 2 failed; one warning; 607.62 s | Checkout changed during execution. Not a passing or source-stable full-suite receipt. |
| Broad focused regression | 154 passed, 1 failed; 139.76 s | The remaining failure was a new test accessing `DomainError.details` instead of `reason_code`; corrected afterward. |
| Final integrity, approval and egress modules | 81 passed; 58.78 s | All selected tests passed, including the two original failures. Concurrent source changes invalidated whole-source freshness. |
| Fresh integrity engine and workflow modules | 64 passed; 8.75 s | Complete selection, no skips/failures, source unchanged, matching measurement/report snapshot. |
| Deterministic measurements | 19 of 19 expected outcomes | Fictional rule cases only; no general semantic-accuracy claim. |
| Targeted Ruff lint/format, whitespace and registry | Passed | Lint covered the new subsystem and touched integration modules; format covered 14 selected files. Registry validated 29 controls. |

The two full-suite failures were resolved in the selected regression modules:
the tool inventory assertion now accounts for disabled process features, and the
egress revocation fixture targets the exact source instead of relying on list order.
The full suite was not rerun after these focused repairs. Platform-dependent skips
remain unverified by this Windows execution.

The accepted integrity receipt binds source commit
`eaa1d9fbed79dbfaae7492753218005bebd529e5` plus dirty working-tree digest
`0a8fcb58ab55a0db43822251dce7a7a6a5f9e2561ee6bf2c1992b870e9c4311a`
(435 reviewed source files). This is a dated snapshot, not a claim that concurrent
or future edits inherit its verification.

## Transparent measures

| Measure | Observed result |
| --- | --- |
| Explicit prohibition cases | 4/4 expected decisions |
| Incorrectly allowed applicable restriction cases | 0/10 |
| False confirmed prohibitions among negative cases | 0/4 |
| Narrow activity scope | 4/4 expected decisions |
| Administrative availability | 2/2 expected decisions |
| Mandatory requirements | 3/3 expected decisions |
| Complete source/version/locator/passage citations | 13/13 cases containing policy rules |
| Override rejection workflows | 2/2 passed |
| Cross-tool bypass rejection workflows | 4/4 passed |
| Version/review invalidation workflows | 3/3 passed |
| Offline compatibility workflows | 2/2 passed |

Workflow groups can overlap. Counts describe these fixtures and assertions, not
population accuracy, complete attack coverage or a general prevention rate.

## Evidence artifacts and reproduction

- [Stable integrity receipt](academic-integrity-bound-2026-10-28.json)
- [Stable measurement report](academic-integrity-bound-measurements-2026-10-28.json)
- [Passing 81-test receipt with freshness limitation](academic-integrity-final-2026-10-28.json)
- [Original full-suite receipt](academic-integrity-full-2026-10-28.json)
- [Generated governance report](../../.local/academic-integrity-bound-review-2026-10-28/report.md)

The generated governance report derives `TESTED` for `CB-INTEGRITY-01` through
`CB-INTEGRITY-06` for the accepted snapshot. The registry itself remains
`IMPLEMENTED_UNVERIFIED`; test execution does not rewrite approval state.
All release gates remain `BLOCKED` because unrelated required evidence and
external approvals are not established by this run.

Use new output names when reproducing:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_integrity_engine.py tests/test_integrity_workflows.py -q -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/integrity-rerun.json
.\.venv\Scripts\python.exe scripts/build_integrity_evidence.py --results .local/integrity-rerun.json --output .local/integrity-rerun-measurements.json
.\.venv\Scripts\python.exe -m canvas_bridge.cli compliance-report --results .local/integrity-rerun.json --output .local/integrity-rerun-review
```

## Limits and external review

Interpretation supports a bounded set of English clauses; unfamiliar wording,
incomplete extraction and uncertain authority require institution-specific review.
Public-policy lookup uses an expiring operator-reviewed offline reference adapter;
missing references report unavailability. No live Rowan policy configuration was
installed. The Bridge controls its own resources and tools, not independent host
conversations or undisclosed external assessments. Original-file downloads retain
their separate source-access contract.

No service restart, live Canvas probe, deployment, push, external publication,
credential change, misconduct reporting or institutional approval occurred.
No technical result in this report establishes legal or institutional certification.
