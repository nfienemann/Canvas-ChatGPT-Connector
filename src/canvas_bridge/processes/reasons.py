"""Fixed privacy-safe process failures; arbitrary exception text is never emitted."""

SAFE_CODES = frozenset(
    """
PROCESS_FEATURE_DISABLED PROCESS_SOURCE_UNAVAILABLE PROCESS_SOURCE_CHANGED PROCESS_SOURCE_STALE
PROCESS_SCOPE_MISMATCH PROCESS_CITATION_UNAVAILABLE PROCESS_STORAGE_BUDGET PROCESS_PREVIEW_LIMIT
PROCESS_PREVIEW_STALE PROCESS_STATE_CORRUPT PROCESS_ACCOUNT_CHANGED PROCESS_SUBMISSION_UNCONFIRMED
PROCESS_DEPENDENCY_MISSING PROCESS_CHANGE_KIND_MISMATCH PROCESS_RECORD_UNAVAILABLE
PROCESS_REVISION_MISMATCH PROCESS_DEPENDENCY_UNAVAILABLE PROCESS_LINEAGE_MISSING
PROCESS_PREVIEW_MISMATCH PROCESS_STORAGE_SCOPE_MISMATCH PROCESS_STATE_EXPIRED
PROCESS_SCHEMA_UNSUPPORTED PROCESS_RECORD_NOT_VALID PROCESS_CONFIRMATION_REQUIRED
PROCESS_IDEMPOTENCY_CONFLICT PROCESS_ROLLBACK_UNAVAILABLE PROCESS_EXPORT_SCOPE_REQUIRED
PROCESS_EXPORT_SCHEMA_UNSUPPORTED PROCESS_EXPORT_BUDGET PROCESS_TRANSITION_INVALID
PROCESS_GRADE_UNCONFIRMED PROCESS_IDENTITY_REVIEW_REQUIRED PROCESS_PUBLICATION_REVIEW_REQUIRED
PROCESS_CAPABILITY_DENIED
""".split()
)
# Public diagnostics use fixed remedies. Never echo host quotes or document identifiers.
READINESS_MESSAGES = {
    "HANDOFF_EXPORT_WITHHELD": "Review restricted content references in the selected packet before export.",
    "HANDOFF_RESTORE_CONFLICT": "Select a prior change or review the later edit to the affected field.",
    "HANDOFF_ADAPTER_UNAVAILABLE": "Use local payload export or record a supplied receipt. This deployment has no configured adapter for that output.",
    "HANDOFF_OUTPUT_UNAVAILABLE": "Retrieve the original packet and its exact export.",
    "HANDOFF_DESTINATION_SCOPE": "Use the packet's explicit recipients and a currently authorized destination.",
    "HANDOFF_OUTPUT_CONFLICT": "The supplied output identity or hash conflicts with its original receipt.",
    "HANDOFF_PACKET_UNAVAILABLE": "Select a saved handoff and exact packet from this assignment.",
    "HANDOFF_BASIS_CHANGED": "Retrieve current assignment and packet revisions, then prepare an updated packet.",
    "HANDOFF_RESPONSE_TIME": "Use the recorded event time for this packet and a knowledge cutoff no later than now.",
    "HANDOFF_RESPONSE_SCOPE": "Correct the original member and packet observation, or record a separate response.",
    "HANDOFF_ARTIFACT_SCOPE": "Choose the logical artifact in the selected readiness assignment.",
    "RESOURCE_STUDY_BINDING_REQUIRED": "Bind this existing Phase D block to the attended phase. Use the study-calendar workflow for its owned event.",
    "RESOURCE_OBSERVATION_ONLY": "This adapter can report requirements and supplied confirmations. Obtain the booking through the resource owner.",
    "RESOURCE_DEPENDENCY_PENDING": "Confirm the prerequisite reservation or calendar operation, then retrieve the plan.",
    "RESOURCE_BASE_CHANGED": "Retrieve the latest work, process, resource and plan revisions before applying a new proposal.",
    "RESOURCE_HORIZON_PASSED": "Choose a planning horizon that includes future work.",
    "PLAN_DEADLINE_SOURCE_MISMATCH": "Select an exact source passage containing the declared ISO date, or supply a separately declared planning deadline.",
    "PLAN_SCOPED_RECOVERY_REQUIRED": "Use the scoped effort correction or compensating study-plan workflow to preserve observed effects.",
    "EFFORT_FORECAST_BOUNDARY": "For current remaining work omit scope_start or supply the future start. Historical estimates require an already frozen forecast.",
    "EFFORT_FUTURE_ACTUAL": "Supply an observed work interval ending at or before the current time.",
    "EFFORT_SCOPE_MISMATCH": "Retrieve the original measurement and correct its exact scope.",
    "EFFORT_REVIEW_PENDING": "Finish the saved assignment reassessment before forecasting current work.",
    "PLAN_FORECAST_STALE": "Issue a current forecast from the latest work revision and comparable observations.",
    "PLAN_BLOCK_SCOPE": "Choose a local study block belonging to the selected current work episode.",
    "PLAN_TASK_SELECTION_INCOMPLETE": "Supply one forecast per current task in the accepted plan.",
    "PLAN_GENERATION_STALE": "Read the current saved study-plan generation before changing it.",
    "PLAN_OPERATION_UNRESOLVED": "Search the exact study marker and reconcile the issued operation.",
    "PLAN_PROTECTED_CONFLICT": "Review the deadline and available windows. If the student chooses to move a future pin or manual edit, retry with its saved ID in release_block_ids. Started blocks stay protected.",
    "PLAN_CALENDAR_STALE": "Refresh the full calendar window, availability and exact marker lookup.",
    "PLAN_CALENDAR_SCOPE": "Use the calendar originally selected for this generation.",
    "PLAN_OPERATION_UNKNOWN": "Select an operation ID from the current saved generation.",
    "CHANGE_SCOPED_RECOVERY_REQUIRED": "Retrieve the assignment change and use compensate_assignment_change with the applied and current revisions.",
    "CHANGE_PARENT_UNRESOLVED": "Retrieve the missing parent version or establish a complete direct comparison before selecting this target.",
    "READINESS_QUOTE_MISMATCH": "Read the selected part and surface again and supply its exact passage.",
    "READINESS_LOCATOR_INVALID": "Choose a part number returned for the selected source version.",
    "READINESS_SELECTION_INVALID": "Bind each selected document once to its logical source and byte hash.",
    "READINESS_VERSION_MISMATCH": "Retrieve the current version and review the selected sources again.",
    "READINESS_SOURCE_UNAVAILABLE": "Review the source status, sharing permission and current version.",
    "READINESS_REQUIREMENT_SOURCE_REQUIRED": "Bind the governing requirement to a selected brief.",
    "READINESS_EVIDENCE_REQUIRED": "Attach source evidence or leave the unassessed criterion unknown.",
    "READINESS_CONFLICT_EVIDENCE_REQUIRED": "Retain the competing interpretations and their evidence.",
    "READINESS_CONFLICT_STATUS_REQUIRED": "Use conflict for unresolved competing interpretations.",
    "READINESS_ACTION_REQUIRED": "Supply the action, gap kind and evidence-based completion condition.",
    "READINESS_EXTENT_INVALID": "Report only source parts actually available for inspection.",
    "READINESS_MEASUREMENT_UNBOUND": "Bind the recorded measurement to its explicit artifact hash.",
    "READINESS_DUPLICATE_REQUIREMENT": "Use one durable identifier per criterion in this assignment.",
    "READINESS_WORK_UNAVAILABLE": "Retrieve the current assignment and choose an existing work item.",
    "READINESS_PLAN_INVALID": "Use the returned work IDs and valid planning constraints.",
}
