# Phase C change impact and remaining-work reconciliation

Use this workflow for a saved assignment whose independently imported sources have changed. The academic process feature and its ordinary source-sharing permissions must be enabled. The workflow runs on demand. It uses the existing encrypted process journal, source readers and planner.

## Review an update

1. Select the saved assignment and current target imports. Keep each source’s logical ID and role stable. Bind an available target using its imported document ID and SHA-256. For an unavailable replacement, leave those two fields null. Supply a known advertised hash separately so it cannot be mistaken for verified bytes.
2. Call `observe_assignment_change` with the current record revision, target bindings and an idempotency key. A refresh can supply source-parent hashes and actual partial part coverage. The service compares the selected sources and persists the pending observation. A stale historical arrival cannot move the current head.
3. `get_assignment_change` returns the observation, its revision, impact by criterion, comparison coverage and current-selection limits. Resume here after a restart. The existing saved readiness remains tied to its own assessed versions. Store revisions and assessment revisions are separate: staging advances the journal, while an identical-byte alias retains its assessment.
4. Read affected material through the ordinary document tools, following their continuation. Submit source-grounded assessments to `reconcile_assignment_change` with the staged change ID and current record revision. Omit rows whose carry-forward proof is sufficient. Include explicit source-supported removals and materially changed fulfillment obligations. A rejected write leaves the last confirmed generation available. After a conflict, retrieve the pending change and the latest progress before submitting a rebased request.
5. Read the confirmed change and readiness. The change report accounts for each work transition, and the readiness projection returns the active work for the selected versions. Use the existing planner through `get_assignment_readiness`. An old completed occurrence or an estimate for a different fulfillment obligation remains historical. A continuing episode retains compatible personal progress, notes and scoped effort.
6. For an explicit recovery request, call `compensate_assignment_change` with the applied and current revisions. Compatible later edits survive. A conflicting later edit requires review. Compensation creates a journal revision, and repeating its idempotency key returns the confirmed receipt. This tool carries the destructive-operation hint and remains subject to the host’s approval policy.

## What the comparisons establish

A byte match identifies an alias. For a repackaged PowerPoint, a timing-equivalence proof requires a bounded native ZIP comparison, unique canonical member names and identical uncompressed bytes for every part. A changed note, relationship, embedded object or presentation-order part defeats that proof. Historical measurements retain their recorded artifact hash.

The text adapter can prove narrowly scoped changes in structured Markdown, including a numbered criterion amendment, a reference locator remap, or administrative contact metadata. Unrecognized prose, unavailable predecessor bytes and incomplete coverage require targeted review. In-place replacements whose old bytes are no longer available produce an incomparable branch; the historical source authorization still applies.

## Reproduce the integration checks

The canonical ZIP is `benchmarks/academic/phase-c/specs.zip`. Run these PowerShell commands from the repository root with locked dependencies. Use a fresh output directory for each execution.

```powershell
$env:BRIDGE_PHASE_C_OUTPUT = Join-Path $PWD '.local/phase-c-replay'
.\.venv\Scripts\python scripts/validate_phase_a.py --phase c $env:BRIDGE_PHASE_C_OUTPUT
.\.venv\Scripts\python -m pytest -q tests/test_phase_c_reconciliation.py -k 'not native'
```

The opt-in host checks also need the trusted Windows parser, a signed-in Codex CLI and the original Phase B synthetic receipts. Set `BRIDGE_PHASE_C_HOST=1` and run the same test module with `-k native`. The host receives neutral tasks, actual tool schemas, selected source bindings and the saved context. Fixture-authored reassessments are confined to adapter tests and labeled initial-state setup. The main host sequence starts from a genuine saved Phase B host assessment rebound to the exact source bytes.

The release report and receipt archive are under `evidence/sanitized-results/phase-c-reconciliation*`. Use `report.json` inside the archive for per-case verdicts and links to the Phase D handoff.
