# Phase E resource and lead-time planning

Select a saved readiness assignment and its current Phase D forecast. The academic process feature and source-sharing permissions govern the resource plan and every readback.

1. Call `save_resource_plan` with the assignment, work and journal revisions, the frozen forecast ID and a versioned process. Bind active phases to the same forecast scope as a partition, or declare a scoped override. Supply equipment capacities with units, student windows, operating calendars, confirmed or tentative bookings, and any dependencies or supply releases. Source passages are optional. The service verifies supplied passages against the selected imported versions.
2. Read `get_resource_plan` for the saved generation. Attended setup, active runs and cleanup consume student time. An unattended run may occupy equipment continuously. Check `resource_usage`, `lead_time_results`, rejected candidates and latest-start proof scope before explaining a plan. Missing evidence can leave the result conditional. Search is bounded.
3. Repair with the current journal revision and expected generation. Link existing same-work Phase D commitments through `study_blocks`. Retain their study-calendar identity. Update the revision of any changed equipment or calendar snapshot. A previously issued uncertain effect must be reconciled first.
4. On an observation-only resource, obtain a scoped confirmation through the resource owner. A configured conditional provider can apply an explicitly confirmed operation through `apply_resource_plan_operation`. The service writes intent before dispatch, looks up uncertain effects by operation ID, and records the provider receipt independently for each effect. Calendar operations may also use `check_resource_calendar` with a fresh complete host calendar readback. `compensate_resource_effects` prepares a conditional inverse and preserves subsequent edits that conflict with it.
5. Read `handoff_schema_version` and the step-specific `handoff` records for the Phase F interface. A booking or projected end time supplies no evidence that an artifact is complete.

## Local verification

```powershell
.venv/Scripts/python scripts/validate_phase_a.py .local/phase-e-validation --phase e
$env:BRIDGE_PHASE_E_OUTPUT = '.local/phase-e-results'
.venv/Scripts/python -m pytest -q tests/test_phase_e_resources.py
$env:BRIDGE_PHASE_E_HOST = '.local/phase-e-host-replay'
.venv/Scripts/python -m pytest -q tests/test_phase_e_resources.py::test_native_resource_journey
```

The native run requires a working Codex CLI. It starts local synthetic MCP servers and persists fixtures in SQLite. The provider double commits a booking and loses its reply so a newly started server must find the same effect. A production equipment provider requires its own owned-identity lookup, conditional revision checks and idempotent writes. No production equipment provider ships with this phase.
