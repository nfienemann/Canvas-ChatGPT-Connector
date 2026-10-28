# Academic workflows and voluntary study — 2026-10-28

Status: local implementation with synthetic verification. No live coursework,
external write, deployment, public release, approval change or background job was
used. Existing unrelated workspace changes were preserved.

## Implemented behavior

- Seven immutable, bounded academic workflows reuse the existing readers, grade
  calculation, planning, discrepancy, figure-receipt and calendar-proposal services.
  Shared retrieval is request-local. Missing courses, calendar information and
  source coverage remain explicit; independent partial results survive ordinary
  failures. Revocation or changed authorization withholds the aggregate.
- Workflow adapters retain the original tool permissions and discover applicable
  course policies before execution. Choosing a workflow cannot evade the existing
  academic-integrity or source-release controls.
- Six study modes preserve source passages, course context and content versions.
  Shared terminology alone does not establish conceptual equivalence. Narrow,
  deterministic definition extraction supports verified recall and multiple-choice
  practice; ambiguous and interpretive answers remain subject to review.
- Practice questions are visibly generated. Initial recall responses withhold
  answers. Feedback requires an actual voluntary response, a current encrypted
  receipt and newly checked source access. Saving minimal results is opt-in; raw
  answers and source passages are not retained in practice records. Viewing an
  explanation never establishes mastery.
- Review recommendations require explicit preferences and available time. They
  remain proposals; no reminder, calendar write or ongoing monitoring is created.

See [workflow contract](../../docs/academic-workflows.md) and
[study contract](../../docs/cross-course-study.md).

## Verification record

The final integrated full-suite run recorded **1,799 passed, 28 skipped, 1 failed**
in 618.68 seconds. Its tool-catalog assertion expected optional process tools while
that feature was disabled. Concurrent maintenance corrected the test to use the
configured catalog while retaining classification checks for every exposed tool.
The affected-test rerun passed below; this full run is not described as green.

The feature-focused suite passed **52 tests** before that full run. It exercises
all seven workflows and all six study modes through actual service paths, including
HTTP MCP contracts, scopes, partial coverage, concurrency isolation, corrupt
documents, resource budgets, timeouts, source mismatch, expiry/revocation, fresh
policy discovery, figure receipts, practice persistence and daylight-saving timing.

The first full run recorded **1,766 passed, 28 skipped, 2 failed** in 607.18 seconds.
Its failures are retained in the initial execution receipt rather than hidden:

1. The egress revocation test changed the first content-review row, which was no
   longer necessarily the target file after policy discovery. It now selects the
   exact file source; the original refusal assertion remains intact.
2. The integrity injection scenario expected `NO_POLICY_FOUND` where the policy
   interpreter returned `REVIEW_REQUIRED`. The concurrently maintained integrity
   suite corrected that expectation. Its mandatory scenarios subsequently passed.

A follow-up covering workflow, study, egress and integrity tests passed **94 tests**.
The 52-test feature check above additionally includes the later visual-resume case
and compact document projection.

After the full run, practice replay tracking was scoped to the study session: an
immediate repeated answer remains assisted, while a new review session can record a
fresh student-reported unassisted attempt. A regression test checks both source-bound
question identity and independent session identity without claiming observed mastery.
The final focused rerun passed **118 tests in 85.61 seconds**, including **53
workflow/study tests**, the catalog failure and the earlier egress/integrity failure
cases. It covers the localized practice correction. The ten-minute full suite was
not repeated again after that focused verification.

Repository Ruff lint and formatting, the configured Bandit medium/high gate,
governance validation (29 controls, no authorization granted), and whitespace checks
passed before the final full run. Lint, formatting (444 files), governance and
whitespace checks also passed after the localized practice correction. Existing
scanner suppression warnings are not
presented as new findings or as evidence that external release gates are satisfied.

## Academic benchmark

The full synthetic benchmark compared **83 paired cases** with the saved onboarding
baseline: **81 objective passes**, **2 interpretation cases awaiting independent
review**, no paired improvements and no paired regressions. Critical arithmetic
and privacy gates passed. The report records `review_complete: false`.

These curated cases support a regression census, not a population confidence
interval, comparable latency estimate, learning-outcome claim or competitive-model
superiority claim. The new workflow/study tests extend service regression coverage;
the older benchmark adapter does not itself measure the complete new conversational
experience.

## Reproduction and evidence boundaries

Executed commands use the repository environment:

```text
python -m pytest -q --disable-warnings -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/workflow-study-2026-10-28-final-full.json
python -m pytest tests/test_workflows.py tests/test_study_engine.py -q
python -m pytest tests/test_workflows.py tests/test_study_engine.py tests/test_egress_contract.py tests/test_integrity_engine.py tests/test_approval_policy_contract.py -q --disable-warnings -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/workflow-study-2026-10-28-followup.json
python -m canvas_bridge.benchmark_lab run --tier full --baseline evidence/sanitized-results/onboarding-2026-10-26-academic.json --require-baseline --output .local/workflow-study-2026-10-28-benchmark
```

Execution receipts omit captured output, parameter values and credentials. The
initial and final full receipts both record `source_unchanged: false` during
concurrent workspace maintenance. They do not certify a frozen checkout or cover
the subsequent localized practice correction. The targeted receipt records
`source_unchanged: true`, exit code zero and the completed follow-up selection. It
is not a replacement full-suite claim.

Saved machine-readable evidence:

- [Initial full run, including its two failures](workflow-study-2026-10-28-initial-full.json).
- [Final full run, including its catalog failure](workflow-study-2026-10-28-full.json).
- [Passing 118-test follow-up](workflow-study-2026-10-28-followup.json).
- [Academic benchmark and baseline comparison](workflow-study-2026-10-28-academic.json).

The 28 full-suite skips concern unavailable platform/native-runtime, OCR, converter
or disposable PostgreSQL prerequisites. Synthetic Windows checks and an SDK MCP
client do not establish actual ChatGPT usability, institutional authorization,
deployment readiness or independent scientific interpretation accuracy. Those
remain separate gates under [release gates](../release-gates.md).
