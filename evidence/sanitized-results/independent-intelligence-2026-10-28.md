# Academic intelligence authorization repair — October 28, 2026

Status: implemented and verified locally with synthetic data. The final full suite
passed **1,868 tests**, with **29 environment-dependent skips** and no failures.
No installed service, approval, credential, real academic record, user database,
calendar or deployment was changed.

## Root cause and repair

`get_saved_study_state(include_institutional=false)` correctly bypassed the
institutional policy dispatcher, but its downstream `Bridge.local_state` called
`Store.connection` unconditionally. That helper requires an active connection and
returned `CONNECTION_INACTIVE` after disconnect. The failure was reproduced through
actual local HTTP MCP before editing the path.

The local branch now verifies owner-scoped legacy state without an active LMS
lease, returns only the narrow validated preference schema, and withholds mixed or
unknown records. The connection ID is optional: an omitted ID uses the existing
independent account-preference namespace. Empty local state is a successful empty
result. Institutional mode still requires its original authorization and connection.

The audit found the same unnecessary gate in legacy preference writes. Only the
`preferences/default` branch now uses an owner-locked namespace instead of an active
connection lease. Plan, progress and other institutional record writes retain the
original fence. Reads of independent preferences now validate retained provenance,
schema and content identity. Local storage failures have a local diagnostic rather
than misleading reconnect advice.

## Components and source-independent services

The [complete audit and supported contract](../../docs/independent-academic-intelligence.md)
classifies every examined surface as a confirmed defect, legitimate institutional
gate or missing independent adapter. Protected course-oriented contracts are retained.

| Component | Change |
| --- | --- |
| `academic/independent_models.py` | Bounded, extra-field-rejecting work/grade inputs and seven-capability request schema; no connection or caller classification. |
| `academic/independent_engine.py` | Source-neutral planning, assessment excerpts, requirements, grades, deadlines/consistency and calendar proposals over existing kernels. |
| `independent_intelligence.py` | Exact owned-source acquisition, source/version/operation and recipient checks, partial-source isolation, normalized lineage, diagnostics and final rechecks. |
| `service.py`, `storage.py` | Local-only saved-state repair, owner-scoped preference writes, validated/hash-bound new preference provenance. |
| `independent.py`, `independent_ui.py` | Retained origin/classification validation, operation-specific consent, current permitted-use checks, no silent expansion of old imports. |
| `app.py`, `policy_surfaces.py`, `source_authorization.py` | Additive read-only MCP tool and classified contract; optional legacy connection argument. |
| `egress_sources.py`, `egress_error_codes.py`, `egress_errors.py`, `privacy/output_fields.json` | Exact source reconstruction, capability-specific purposes, safe local errors and preservation of reviewed pagination/provenance metadata. |
| `integrity/surfaces.py` | Source-policy checks remain mandatory; omitted restricted sources do not suppress unrelated valid evidence. |
| `academic_intelligence.py`, `academic_rules.py`, `planning.py`, `calendar_sync.py`, `domain.py` | Share excerpt construction and existing algorithms, use accurate independent labels, and avoid empty-URL calendar matches. |
| `tests/test_independent_intelligence.py`, `tests/test_retention.py`, fictional fixture files | Reproduction, independent successful workflows, negative boundaries, early and database secret rejection, and compatibility assertions. |
| `governance/controls.json`, `governance/fixtures.json`, README and architecture documentation | New `CB-IND-01` control, exact fictional fixture fingerprints and supported-boundary documentation. |

There is no second planner, grading implementation, scheduler, authorization system
or chatbot. The new adapter does not invoke institutional acquisition. Pure reasoning
receives normalized inputs and source evidence; the adapter owns permission checks.

## Persistence and compatibility

No SQL schema change or migration was required. Existing encrypted independent and
connection-bound namespaces remain separate. New imports and preferences gain
additive provenance metadata; old narrow preferences are validated at read time.
Ambiguous records are retained and withheld, not destructively migrated or declared
independent because a connection disappeared. New legacy preference envelopes bind
the exact validated value to the owner and permitted preference operation.

Independent inputs are explicit permitted document imports. Structured work/grades
use the documented `independent-academic-1` TXT/Markdown format. Known restricted
copies, unknown classification, mixed lineage and institutional source identifiers
remain disallowed. Ordinary source text cannot select privileges or grant permission.
No model-callable source import or administrative approval action was introduced.

## Executed checks

- The original focused repair suite passed **37 tests in 19.43 seconds**. The final
  follow-up passed **110 tests in 57.55 seconds**, including **39 independent repair
  cases**, retention, personal preferences, independent recovery and approval
  contracts. Both receipts record `source_unchanged: true` and exit code zero.
  The follow-up applies each connection state after fixture setup and asserts its
  exact denial reason, separately proving disconnected, revoked, denied, unapproved
  and operator-disabled behavior while local-only preferences remain available.
- The initial full suite reported **1,865 passed, 29 skipped and 1 failed in 680.09
  seconds**, with `source_unchanged: true`. The failed retention test expected a
  database-level secret rejection, but the new preference schema rejected its
  payload first. Invalid preferences now return a sanitized local error without
  echoing rejected input. The updated regression verifies both early rejection and
  the unchanged database secret guard, with zero stored rows. Its passing follow-up
  and the original failing receipt are both retained; the failure was not waived.
- An earlier integration run passed **210 tests** across independent recovery,
  academic comparison, planning, timing, lifecycle, local preferences and grade
  calculations. A subsequent security-focused run passed **97 tests** across the
  new adapter, recovery, integrity, egress and approval contracts. These preceded
  the final narrow coverage additions and are not substituted for the final run.
- Repository Ruff lint and formatting passed (**454 files**). `git diff --check`
  passed. The configured Bandit medium/high severity/confidence gate passed; its
  existing obsolete-suppression warnings are not hidden or treated as security proof.
- Governance validation passed with **30 controls** and `authorization_granted: false`.
  The two new original fictional fixture files have explicit CC0 provenance and
  individually registered fingerprints. No unknown fixture set was blanket-approved.
- The full academic benchmark passed its objective, critical and regression gates:
  **81 objective passes**, **2 interpretation cases awaiting independent review**,
  **83 paired cases**, no improvements and no regressions versus the previous saved
  local workflow/study report. No comparative latency, population confidence
  interval, model superiority or learning-effectiveness claim follows.
  This benchmark preceded the final preference-error and test-fixture refinements;
  those refinements did not change academic reasoning.

The final full suite after the correction passed **1,868 tests in 677.50 seconds**,
with **29 skips**, zero failures/errors and all **1,897 cases** accounted for. Its
receipt records `source_unchanged: true`, `complete_selection: true`, exit code zero
and Windows execution. It includes all **39 independent repair cases**. Skips were
13 real-Linux checks, 9 disposable-PostgreSQL checks, 5 checks needing an explicitly
configured native converter, and 2 checks needing the optional OCR runtime. These
environment-specific checks remain separate release gates.

Sanitized, source-bound receipts: [final full run](independent-intelligence-2026-10-28-final-full.json),
[initial full run](independent-intelligence-2026-10-28-initial-full.json),
[original focused run](independent-intelligence-2026-10-28-focused.json),
[corrected follow-up](independent-intelligence-2026-10-28-followup.json),
and [academic benchmark](independent-intelligence-2026-10-28-academic.json).

Reproduction commands (using the repository environment):

```text
python -m pytest tests/test_independent_intelligence.py -q --disable-warnings --tb=short -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/independent-intelligence-2026-10-28-focused.json
python -m pytest tests/test_independent_intelligence.py tests/test_retention.py tests/test_personal.py tests/test_recovery_independence.py tests/test_approval_policy_contract.py -q --disable-warnings --tb=short -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/independent-intelligence-2026-10-28-followup.json
python -m pytest -q --disable-warnings --tb=short -p canvas_bridge.compliance.pytest_plugin --compliance-results=.local/independent-intelligence-2026-10-28-final-full.json
python -m canvas_bridge.benchmark_lab run --tier full --baseline evidence/sanitized-results/workflow-study-2026-10-28-academic.json --require-baseline --output .local/independent-intelligence-2026-10-28-benchmark
```

## Security findings and remaining boundaries

All seven new capabilities were exercised through MCP with **zero LMS connection
rows, an empty institution registry, and connection/network entry points set to fail
if invoked**. The pure planner's output matches the existing planner on equivalent
normalized inputs. Institutional failure did not block permitted independent inputs.

Negative cases cover cross-user identifiers, mixed/unknown legacy payloads, changed
hashes, expired/revoked sources, retained institutional lineage, denied use and
recipient purposes, source changes after reasoning, syllabus review version mismatch,
unknown grades/weights, unsupported rules, prompt injection, restricted assessments,
missing calendar evidence and local storage failure. Privacy filtering and final
source authorization run on the actual MCP output. These checks found no authorization
bypass in the repaired and newly implemented paths.

The implementation preserves safe limitations: a mixed individual import is withheld
as a whole; arbitrary undisclosed origin cannot be conclusively inferred from text;
source rights remain attested/review-dependent. Assessment packages cover cited
excerpts, not a guaranteed full exam syllabus. Qualitative grading and scientific
visual interpretation still require review. Calendar proposals require independent
calendar evidence and later explicit approval; no writes occur here.

Structured manual data uses the existing import path; this work does not add a
conversational manual-entry interface. Real-client usability, deployment, institution
approvals, operating-system-specific isolation and expert interpretation are separate
[release gates](../release-gates.md). No production-readiness claim is made.
