"""Reviewed vocabulary for bounded independent workflow envelopes."""

FIELDS = frozenset(
    """
schema subtype value course mode expansions expansion_provenance ranker_version inventory_hash
bounded_omissions start_offset characters
effective_scope hits start end quote ranking_score ranking_reason read_continuation unread_parts
representations activities activity_kind requirement requirement_basis responsibility parent_key
aliases completion_rule reported_status revision_requested opens closes evidence official_submission
requirement_groups members minimum selected grading_rule accounting caught_up page_complete
obligation_inventory feedback_items improvements feedback work_key kind action reference practice
practice_prompt practice_optional grade_prediction saved repeated_issue author_role awarded_points
expected_hash goal_id goals concept observations attempt_id session_id prompt response evidence_kind
observation next_exercise rejected check evaluation named_comparison explained_purpose outcome
evaluation_method mastery_established event_time unresolved_issue minutes stopping_point
notifications_created history events event_id category changed_fields old_value new_value old_evidence
new_evidence impact_basis affected_plan_ids recommended_action acknowledgment delivery first_observed_at
works counterexamples
source_timestamp processing_events revision_id external_writes document_ids part coverage next_cursor
""".split()
)
