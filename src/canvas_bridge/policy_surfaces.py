"""Reviewed output categories. New MCP tools fail closed until classified here."""

from canvas_bridge.approval_policy import CATEGORIES
from canvas_bridge.domain import DomainError
from canvas_bridge.integrity.surfaces import TOOLS as INTEGRITY_TOOLS
from canvas_bridge.processes.surfaces import TOOLS as PROCESS_TOOLS
from canvas_bridge.source_authorization import (
    INDEPENDENT_INTELLIGENCE_TOOLS,
    LOCAL_DOCUMENT_TOOLS,
    PREFERENCE_TOOLS,
)

TOOL_CATEGORIES = {
    "prepare_study_session": {"courses", "files", "pages"},
    "submit_practice_response": {"courses", "files", "pages"},
    "run_academic_workflow": {"courses"},
    "get_semester_overview": CATEGORIES,
    "acknowledge_semester_findings": {"courses", "assignments", "grades"},
    "list_courses": {"courses"},
    "list_course_discussions": {"courses", "discussions"},
    "read_discussion_topic": {"courses", "discussions"},
    "get_my_discussion_participation": {"courses", "discussions"},
    "get_workload": {"courses", "assignments", "grades"},
    "get_assignment_details": {"courses", "assignments", "grades"},
    "get_changes": {"courses", "assignments", "grades"},
    "get_gradebook": {"courses", "assignments", "grades", "syllabus"},
    "get_course_grading_policy": CATEGORIES,
    "calculate_course_grade": CATEGORIES,
    "audit_course_grade": CATEGORIES,
    "simulate_grade_scenario": CATEGORIES,
    "reconcile_course_deadlines": CATEGORIES,
    "review_assignment_requirements": CATEGORIES,
    "prepare_for_assessment": CATEGORIES,
    "audit_course_consistency": CATEGORIES,
    "get_course_obligations": CATEGORIES,
    "get_course_outline": CATEGORIES,
    "fetch_course_material": CATEGORIES,
    "search_course_materials": CATEGORIES,
    "propose_calendar_sync": {"courses", "assignments", "grades"},
    "propose_study_plan": {"courses", "assignments", "grades"},
    "propose_course_study_plan": CATEGORIES,
    "save_study_plan": {"courses", "assignments", "grades"},
    "get_saved_study_state": CATEGORIES,
    "record_personal_progress": {"courses", "assignments"},
    "audit_permission_consistency": CATEGORIES,
    **{
        name: {"courses", "files"}
        for name in (
            "prepare_course_file_download",
            "get_course_file_download_payload",
            "list_course_files",
            "render_course_slide",
            "render_course_file_page",
            "inspect_course_figure",
            "record_course_figure_observation",
            "interpret_course_schedule",
            "read_course_file",
            "search_course_files",
            "get_file_extraction_status",
        )
    },
}
# Assignment snapshots include the authenticated student's submission state.
for _categories in TOOL_CATEGORIES.values():
    if "assignments" in _categories and isinstance(_categories, set):
        _categories.add("submissions")
# Status redacts unapproved cached data itself. Preferences only echo user input.
OFFLINE_TOOLS = (
    {"get_connection_status", "update_study_preferences", "get_saved_study_state"}
    | LOCAL_DOCUMENT_TOOLS
    | PREFERENCE_TOOLS
    | INTEGRITY_TOOLS
    | PROCESS_TOOLS
    | INDEPENDENT_INTELLIGENCE_TOOLS
)


def authorize_tool(bridge, owner, name, arguments):
    if name in PROCESS_TOOLS:
        # Each adapter resolves and rechecks exact source identities; no caller
        # source label bypasses institutional approval or independent ownership.
        bridge.processes.enabled()
        return
    if name in INTEGRITY_TOOLS:
        scope = bridge.integrity.scope_for_arguments(owner, arguments)
        if scope:
            bridge.integrity.authorize_scope(owner, scope)
        return
    if name == "get_saved_study_state" and arguments.get("include_institutional"):
        if not arguments.get("connection_id"):
            raise DomainError("needs_input", "Select a connection to request institutional state.")
        bridge.connection_policy(owner, arguments["connection_id"], TOOL_CATEGORIES[name])
        return
    if name in OFFLINE_TOOLS:
        return
    if name not in TOOL_CATEGORIES or not arguments.get("connection_id"):
        raise DomainError(
            "permission_denied",
            "This tool has no reviewed data-sharing scope.",
            reason_code="POLICY_TOOL_UNCLASSIFIED",
        )
    bridge.connection_policy(owner, arguments["connection_id"], TOOL_CATEGORIES[name])
    if name == "propose_calendar_sync":
        from canvas_bridge.oauth_security import require_capabilities

        with bridge.store.transaction() as session:
            conn = bridge.store.connection(session, owner, arguments["connection_id"])
            require_capabilities(
                bridge, bridge.registry.entries[conn.institution], {"calendar_proposals"}
            )
