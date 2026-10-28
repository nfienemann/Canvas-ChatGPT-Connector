# Semester intelligence — local execution record

Date: October 26, 2026. Entirely synthetic local development and loopback MCP
transport. No real academic records, live Canvas connection, deployment, account
change, host schedule or external notification delivery was used.

Production source fingerprint:
`3392efd2f007b9a758bbfac44d0abc0ed345cb376f48dbfec5104ace1591ce65`.
It was verified unchanged after the full test run and matches the benchmark receipt.

## Implemented behavior

The on-demand overview combines selected-course obligations, grade evidence,
consequential snapshot changes, requirement/deadline discrepancies, assessment
clusters, supplied calendar conflicts, conditional workload shortfalls and module
prerequisite access uncertainties. Findings carry sources, unknowns, next actions
and stable identities. Explicit acknowledgments use expiring, scope-bound receipts
and transaction-level epoch/version checks. User preferences remain separate from
educational state. Course withdrawal clears acknowledgment/delivery state.

Notification eligibility is a pure adapter contract with opt-in, fresh analysis,
course scope, quiet hours, frequency and semantic deduplication. No delivery host is
connected. The native tool cannot assert host approval or initiate monitoring.

## Executed checks

| Check | Actual result |
| --- | --- |
| Full `pytest -q --tb=short` | 1,628 passed, 28 skipped, zero failures/errors; 565.09 seconds in XML |
| `tests/test_semester_intelligence.py` | 32 passed, zero skips/failures; 8.38 seconds in XML |
| Full academic benchmark against preceding verified scientific run | 81 objective passes, 2 interpretation reviews required, zero regressions across 83 paired cases |
| Ruff check and format, `src tests scripts` | Passed; 236 Python files formatted |
| Bandit, four semester modules | Passed |
| Compliance registry validation | Valid, 23 controls; grants no authorization |
| `git diff --check` | Passed |

The full suite collected 30 semester cases. Two additional test-only cases added
during that run were subsequently covered by the separate complete 32-case semester
run; production code did not change. Skips require unavailable Linux, disposable
PostgreSQL, trusted native-conversion or OCR runtimes. They are not acceptance
evidence for those environments.

The first full run was stopped before completion to tighten unknown-submission
resolution, distinct conflict identities and returned-citation egress binding.
It is not counted as passing. An initial new-test enum import typo was corrected;
the final semester run and full run are green.

Regression coverage includes 12 simultaneous fictional courses; missing/dropped
weights; a reproduced 86% weighted grade and two cited policy discrepancies; late
revisions; repeated observations; missing baseline and partial history; resolved
conflicts; loss of submission evidence; DST elapsed-time/day-cap arithmetic;
acknowledgment, expiry, unacknowledgment and scope races; restricted source egress;
locked prerequisite title withholding; report truncation with preserved citations;
notification opt-in, scope, frequency, quiet hours, stale analysis and deduplication;
and actual MCP read/write-scope behavior. No self-judged interpretive scores are used.

## Reproduction and boundaries

Run from the repository with its locked environment:

```powershell
.venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe -m pytest tests/test_semester_intelligence.py -q
.venv/Scripts/python.exe -m canvas_bridge.benchmark_lab run --tier full --baseline evidence/sanitized-results/scientific-comprehension-v3-2026-10-26-academic.json --output .local/semester-reproduction
```

[Machine-readable checks](semester-intelligence-2026-10-26-checks.json) bind counts,
skip reasons and test report hashes. The [academic report](semester-intelligence-2026-10-26-academic.json)
uses run `e532f99eb8889603d4dfac1956a0d0aed4dcc3ec97a84a23a811bce3878cb2f9`
and preceding verified run `e8fef8feb2ac171da865a77940a4fe26e9805d450ede2e56519a6d6156899989`.
This is a descriptive paired regression census, with no justified confidence interval
or controlled latency comparison. The preceding run is not relabeled as a formally
approved stable release. No ordinary-model or competing-repository superiority
was tested or claimed.

See [the behavior and coverage contract](../../docs/semester-intelligence.md).
Syllabus/module history, exhaustive linked-file/announcement coverage, live host
acceptance and an approved notification adapter remain explicit limitations.
