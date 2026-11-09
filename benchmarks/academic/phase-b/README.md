# Persistent assignment readiness

With academic process features enabled, a supported host can remember a review of an explicitly selected independent assignment. The student sees the stored revision, findings, cited passages and their remaining work when they return.

## Review, save and return

1. Import the brief, draft and supporting files through Materials with independent academic analysis and text sharing enabled. Select the assignment within its course and term. Read each document by its imported ID and byte hash, following continuations. PowerPoint text includes bounded body and speaker-note spans when the parser supplies them.
2. Use the independent requirements workflow for mechanical checks. The host interprets qualitative criteria. Call `save_assignment_readiness` with a logical ID and role for each selected source, stable requirement IDs, governing passages, assessments, evidence and review extent. Bind each quotation to a logical source, exact part and surface. A deliberately absent artifact has a logical ID with null document ID and hash. For recorded timing, cite the rehearsal and its embedded artifact hash.
3. Use revision zero for the initial save. Retry an identical request with its original idempotency key. For a changed assessment, use the latest confirmed revision and a new key. The commit receipt identifies the record, revision and journal entry. An explicit rereview preserves earlier revisions within the existing retention limits.
4. Call `get_assignment_readiness` with the receipt's record ID, or locate the assignment in the ordinary process inventory. An omitted revision retrieves the latest saved snapshot. A revision selects historical evidence. Supplying a selection compares the chosen requirement-set revision and logical artifact versions against the saved snapshot. Unavailable or mismatched evidence limits the affected criteria. The original record remains subject to the existing retention and deletion rules.
5. Use `record_readiness_progress` for an explicit personal progress declaration, with its work ID, expected record revision and idempotency key. A done declaration alongside an unresolved finding prompts rereview. To propose a session, pass the ordinary planning windows and optional attributed effort overrides to `get_assignment_readiness`. A supplied simulation time uses `plan_as_of`. Actual policy and access checks always use the service clock.

## Projection and storage

The denominator is the set of applicable required criteria. An unresolved conflict takes priority, then supported remaining work, then unknown readiness. Incomplete membership, unknown applicability and an empty inventory prevent a ready result. Optional suggestions appear alongside the assessed scope. Explicitly requested optional or followup tasks can be selected with `requested_work` and an action, gap kind and completion condition.

The encrypted process store persists one assignment snapshot per owner, course, term and logical assignment. Each work identity includes the assignment, requirement-set revision, source-version tuple, criterion ID and gap kind. Import aliases are excluded from the work key. The planner receives the saved work IDs, personal progress, action titles and source citations. Missing deadlines or effort remain unknown. Current source access, selected-version applicability and the time of the assessment are separate observations.

## Benchmark

The supplied archive lives at `benchmarks/academic/phase-b/specs.zip`. Its structured assessments and expected results are evaluator material. In the host tests the user prompt contains the selected case and its source bindings. The host reads the files through MCP, submits its own assessment, and receives the backend projection.

From the repository root with locked dependencies and the trusted local parser installed:

```powershell
.\.venv\Scripts\python scripts/validate_phase_a.py --phase b .local/phase-b-validation
.\.venv\Scripts\python -m pytest -q tests/test_phase_b_readiness.py -k 'controls or authored or concurrent'
$env:BRIDGE_PHASE_B_OUTPUT = Join-Path $PWD '.local/phase-b-replay'
.\.venv\Scripts\python -m pytest -q tests/test_phase_b_readiness.py
```

Use a fresh output directory and a signed-in Codex CLI for host runs. Each case uses synthetic SQLite state in the pytest temporary directory. The harness stops the serving process, starts another process against the same database and vault, and opens a fresh host context for recall. Only synthetic prompts, tool results, receipts and final answers belong in published evidence. The Phase A replay uses its existing procedure and an independent output directory.

After the host runs finish, run `python scripts/audit_phase_b.py <output-directory>` with the same Python environment. It compares all fourteen scenario result sets with the independent expectations, verifies the saved and recalled fields after restart, and checks the native answers against the final CLI messages. The report also includes separate semantic adjudication of those answers.

For a rejected save, the public MCP envelope supplies a fixed reason and recovery instruction. Examples include `READINESS_QUOTE_MISMATCH` and `READINESS_LOCATOR_INVALID`. Correct the source binding and retry against the last confirmed record revision. The error response excludes the submitted source text.
