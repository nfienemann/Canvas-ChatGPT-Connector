# Phase F artifact-grounded group handoffs

Enable the academic process feature and select a saved readiness assignment. Group identities are explicit local declarations scoped to that assignment. Each operation rechecks the private owner's source and planning permissions.

1. Use `prepare_group_handoff` with the current assignment and journal revisions, logical artifact ID, explicit contributor and recipients, next-action owner, expected output and criterion prerequisites. Provide a source passage for a sourced responsibility assignment. Optionally pin the artifact hash, requirement revision and work episode, or bind an existing Phase E generation and step. A handoff review can proceed on an available draft even when other assignment criteria need work.
2. Read `get_group_handoff` to inspect the actual file identity, version, parts, evidence, gaps, process conditions and personal progress. Reassigning or changing the requested action requires a new responsibility or action revision. Reconcile against the expected prior packet ID. Presentation-only changes preserve the semantic basis.
3. Use `record_handoff_response` for a supplied observation about an exact packet. Name the responding member, event time, evidence basis and reference. The service records the authenticated recorder and knowledge time. Corrections and retractions retain the original event history. Only an explicitly requested acknowledgment prerequisite can gate the next action.
4. `export_group_handoff` saves the selected packet as an exact UTF-8 JSON or Markdown payload. Retrieve it again by packet and output ID. `record_handoff_delivery_receipt` records a supplied receipt independently of acceptance. A deployment with a destination-authorizing adapter can use `reconcile_handoff_output` for confirmed file creation or delivery. After an uncertain outcome, look up the same operation identity before retry. The default connector exports locally.
5. `restore_group_handoff` compensates selected responsibility, action or note changes. It requires the current packet and refuses to overwrite a conflicting later edit. Historical packet IDs and as-of response cutoffs are available on the read tool.

## Replay

```powershell
.venv/Scripts/python scripts/validate_phase_a.py .local/phase-f-validation --phase f
$env:BRIDGE_PHASE_F_OUTPUT = '.local/phase-f-results'
.venv/Scripts/python -m pytest -q tests/test_phase_f_handoffs.py
$env:BRIDGE_PHASE_F_HOST = '.local/phase-f-host-replay'
.venv/Scripts/python -m pytest -q tests/test_phase_f_handoffs.py::test_native_handoff
```

The opt-in host run needs the Codex CLI. It uses signed synthetic MCP sessions and restarted SQLite-backed servers. The fixture adapter writes a private local file, loses its response and recovers its receipt after a process restart. Its delivery destination is a SQLite fixture inbox. The tests use no real teammate addresses or external messaging provider.
