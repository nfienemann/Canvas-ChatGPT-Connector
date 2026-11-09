# Phase A integration benchmark

The benchmark imports a fictional BenchLink presentation packet into the independent-materials service and measures the actual host answer. The canonical package is `benchmarks/academic/phase-a/specs.zip`. Its fixture index, oracle, source-building inputs, two decks, fourteen previews and neutral prompts stay together at their supplied byte identity.

## Reproduce the capture

Use the project's locked Python environment, installed parser runtime, Git, and an authenticated Codex CLI supporting ephemeral sessions and HTTP MCP. The executed benchmark used Windows and the trusted parser at `%LOCALAPPDATA%/CanvasBridge/parser`. Run from the repository root on a stable checkout. Use a **new** output directory for each matrix. The first test refuses to overwrite evidence. An unrelated source edit between stages stops the capture.

```powershell
$env:BRIDGE_PHASE_A_OUTPUT = Join-Path $PWD '.local/phase-a-replay'
.\.venv\Scripts\python -m pytest -q tests/test_phase_a_benchmark.py -k bind
.\.venv\Scripts\python scripts/validate_phase_a.py $env:BRIDGE_PHASE_A_OUTPUT
.\.venv\Scripts\python -m pytest -q tests/test_phase_a_benchmark.py -k capture -x
.\.venv\Scripts\python scripts/audit_phase_a.py $env:BRIDGE_PHASE_A_OUTPUT
```

Check each exit code before advancing. The opt-in capture runs four separate host reviews and a planning turn. The host uses the configured Codex account. Each review starts with a new in-memory store, signed synthetic principal and empty host working directory. The runner imports only the case manifest's files through `IndependentSources.ingest`. It exposes four current MCP tools on loopback with a read-scoped fixture credential passed through the environment. The canonical neutral prompt is the user message. Common orchestration instructions specify the tool family and pagination strategy. Only the planning turn receives an earlier answer as additional input.

The harness separately verifies the HTTP reader and workflow after the host returns. These calls have the stage `protocol_verification` and do not count toward host quality. Host event files include rejected requests that never reach the tool manager. The audit checks the final answer against the host event, validates selected source IDs and version hashes, and compares returned slide and notes text against native PowerPoint XML. Its normalized whitespace comparison measures content coverage. The bridge returns numbered parts with combined body and notes text.

## Evaluate a replay

Freeze the raw event streams and final answers before opening the evaluator oracle. Compare each distinct requirement, timing, citation and coordinator claim to the versioned sources and returned locators. Record the actual answer text and line, coverage and judgment. Use the supplied scoring rules, including the fixed three-finding baseline denominator, three corrected classes with explicit assessment coverage, and separate missing-deck and historical timing judgments. Count host retries separately from human interventions, and distinguish host-proposed tasks from native planner output. A fresh set of answers requires fresh semantic judgments.

The completed capture and scorecard are in `evidence/sanitized-results/phase-a-benchmark-receipts.zip`. Extract it and start with `report.json`, then follow its run, evaluation and gap references. The archived SHA256SUMS covers each evidence member apart from itself. The local Codex benchmark host measures one host configuration. Installed ChatGPT, production configuration, live coursework and additional model runs are separate evidence boundaries.
