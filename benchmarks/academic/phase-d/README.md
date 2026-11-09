# Phase D forecasting and replanning

Enable the academic process feature and select a saved assignment readiness record. Retrieve its work IDs with `get_assignment_readiness`. Use `get_study_forecast_plan` to read the journal revision, episode-bound forecasts, measurements, evaluations and accepted generation. Writes use the readiness revision, journal revision and a new idempotency key. Retry an uncertain local write with its original arguments and key.

1. Use `record_scoped_effort` for observed minutes or active sessions with pauses. Record the measured scope and time boundaries. Correct the same observation with its expected observation revision. The original and correction remain retrievable. A reported completion can have unknown duration.
2. Use `forecast_remaining_work` for a specific episode and scope. Supply an uncalibrated baseline and comparable task family. Omit the start for a forecast beginning now. An explicit current range override retains the modeled suggestion. The effective upper bound determines the reservation. The journal keeps the cutoff and selected training references.
3. Use `save_study_replan` with current forecast IDs, priorities, deadlines and availability. During initial setup, accepted local commitments can be supplied with stable block IDs. Later manual adjustments reference existing blocks. If a deadline conflicts with a future pinned or manually edited block, review the saved generation with the student. On an explicit decision to move it, retry with its ID in `release_block_ids`. The journal records the released IDs and the original placements. Started blocks stay protected. For a selected Canvas assignment, retrieve its current effective deadline and source version through `get_assignment_details` before saving the local plan. Set `compact_reservations` only when the user requests a tighter plan. To plan from a date-only imported deadline, supply its ISO date, exact source passage and applicable course timezone. Read the generated placement, per-task accounting, structural changes and operation IDs from the saved generation.
4. Calendar execution belongs to the host. Search for exact study markers and supply the complete fresh calendar context to `check_study_calendar`. After explicit user confirmation, select one operation. Use its marker, event identity and expected version for the conditional host action. Read the event back after a write or lost response. Reuse the logical operation identity on retry. `observed` records agreement with the supplied calendar readback. `compensate_study_replan` stages the scoped inverse and retains conflicts with later edits.

## Replay with synthetic data

From the repository root on Windows:

```powershell
.venv/Scripts/python scripts/validate_phase_a.py .local/phase-d-validation --phase d
$env:BRIDGE_PHASE_D_SCENARIOS = '.local/phase-d-scenarios'
.venv/Scripts/python -m pytest -q tests/test_phase_d_forecasting.py
$env:BRIDGE_PHASE_D_HOST = '.local/phase-d-host-replay'
.venv/Scripts/python -m pytest -q tests/test_phase_d_forecasting.py -k native
```

The native run requires the installed Codex CLI and a supported model session. It uses a synthetic SQLite database and independent host processes with signed fixture credentials. The provider recovery test uses a separate SQLite calendar double to simulate an actual durable effect followed by a lost response. Keep host transcripts private until inspected and sanitized. See the Phase D evidence report for the tested scope.
