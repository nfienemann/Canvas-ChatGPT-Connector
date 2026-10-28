"""Reviewed operation taxonomy and final output fencing for every MCP surface."""

from sqlalchemy import select

from canvas_bridge.domain import DomainError
from canvas_bridge.integrity.engine import evaluate_academic_assistance
from canvas_bridge.integrity.models import Activity as A
from canvas_bridge.integrity.models import AssistanceRequest, PolicySource, Scope
from canvas_bridge.storage import Material, Work

TOOLS = frozenset(
    {
        "get_academic_integrity_policy",
        "check_academic_assistance_permission",
        "record_integrity_acknowledgment",
        "provide_instructor_permission_evidence",
        "get_integrity_decision",
        "get_integrity_guidance",
        "prepare_academic_assistance",
        "get_integrity_acknowledgments",
        "revoke_integrity_acknowledgment",
    }
)
HISTORY = frozenset({"get_integrity_acknowledgments", "revoke_integrity_acknowledgment"})
LEARNING_TOOLS = frozenset(
    {
        "run_independent_academic_workflow",
        "read_course_file",
        "search_course_files",
        "fetch_course_material",
        "search_course_materials",
        "render_course_file_page",
        "render_course_slide",
        "inspect_course_figure",
        "record_course_figure_observation",
        "read_local_document",
        "search_local_documents",
        "render_local_document_page",
        "prepare_local_study_materials",
        "read_discussion_topic",
        "prepare_study_session",
        "submit_practice_response",
    }
)
PLANNING_TOOLS = frozenset(
    {
        "propose_study_plan",
        "propose_course_study_plan",
        "save_study_plan",
        "propose_calendar_sync",
        "review_assignment_requirements",
        "prepare_for_assessment",
        "run_academic_workflow",
    }
)
ADMIN_TOOLS = frozenset(
    {
        "get_connection_status",
        "audit_permission_consistency",
        "list_courses",
        "list_course_discussions",
        "get_my_discussion_participation",
        "get_course_obligations",
        "get_workload",
        "get_assignment_details",
        "get_changes",
        "get_gradebook",
        "get_course_grading_policy",
        "calculate_course_grade",
        "audit_course_grade",
        "simulate_grade_scenario",
        "reconcile_course_deadlines",
        "audit_course_consistency",
        "get_course_outline",
        "list_course_files",
        "get_file_extraction_status",
        "interpret_course_schedule",
        "list_local_documents",
        "get_local_document_status",
        "get_local_study_preferences",
        "update_local_study_preferences",
        "get_saved_study_state",
        "update_study_preferences",
        "record_personal_progress",
        "get_semester_overview",
        "acknowledge_semester_findings",
        "prepare_course_file_download",
        "get_course_file_download_payload",
        "download_original",
    }
)


def contract(name):
    from canvas_bridge.processes.surfaces import TOOLS as PROCESS_TOOLS

    if name in PROCESS_TOOLS:
        # Process APIs track facts and proposals; lifecycle assistance also calls
        # the existing current-policy service at evaluation and confirmation.
        return "A; lifecycle_activity_requires_current_decision"
    if name in TOOLS:
        return (
            "explicit_activity_decision"
            if name == "prepare_academic_assistance"
            else "integrity_control"
        )
    if name in ADMIN_TOOLS:
        return "A"
    if name in PLANNING_TOOLS:
        return "B" if name == "prepare_for_assessment" else "C"
    if name in LEARNING_TOOLS:
        return "B; known_assessed_source_requires_activity_decision"
    raise DomainError(
        "permission_denied",
        "This operation has no reviewed academic-integrity contract.",
        reason_code="INTEGRITY_TOOL_UNCLASSIFIED",
    )


def plain_arguments(arguments):
    return {
        k: v.model_dump(mode="json") if hasattr(v, "model_dump") else v
        for k, v in arguments.items()
    }


async def before_tool(bridge, owner, name, arguments):
    """Discover before normal reader entry points, not only a voluntary policy call."""
    contract(name)
    if name not in LEARNING_TOOLS | {"get_assignment_details", "review_assignment_requirements"}:
        return
    args = plain_arguments(arguments)
    if args.get("document_id"):
        doc = args["document_id"]
        # Inherit registered course/assessment context for this exact source. An
        # unassociated paper remains general learning, with honestly incomplete policy.
        scopes = [
            Scope.model_validate(r.content["scope"])
            for r in bridge.integrity.contexts(owner)
            if doc in r.content.get("hashes", {})
        ]
        scopes = scopes or [Scope(document_ids=[doc])]
    elif args.get("connection_id"):
        ref = args["connection_id"]
        courses = {args["course_id"]} if args.get("course_id") else set()
        ids = {args[k] for k in ("file_id", "material_id", "work_id") if args.get(k)}
        ids.update((args.get("request") or {}).get("material_ids", []))
        with bridge.store.transaction() as session:
            for cls in (Material, Work):
                courses.update(
                    session.scalars(
                        select(cls.course_id).where(
                            cls.owner == owner, cls.connection_id == ref, cls.id.in_(ids)
                        )
                    )
                )
        scopes = [
            Scope(connection_id=ref, course_id=c, assessment_id=args.get("work_id"))
            for c in sorted(courses)
        ]
    else:
        scopes = []
    for scope in scopes:
        activity = (
            A.REQUIREMENTS
            if name in {"get_assignment_details", "review_assignment_requirements"}
            else A.LEARNING
        )
        decision, _ = await bridge.integrity.evaluate(
            owner, AssistanceRequest(scope=scope, activity=activity)
        )
        decision.require()


def guard_result(bridge, owner, name, arguments, result):
    """A second endpoint or a stale receipt cannot release a known denied package.

    Read-only academic administration is retained. Independent raw document reading
    is learning by default; known assessed-source bindings raise that floor. This
    cannot identify undisclosed external assignments or control host-only generation.
    """
    contract(name)
    if name in TOOLS:
        scope = bridge.integrity.scope_for_arguments(owner, arguments)
        if scope:
            bridge.integrity.authorize_scope(owner, scope)
        return result
    from canvas_bridge.egress_sources import scalar_refs

    args = plain_arguments(arguments)
    ids = set(scalar_refs(args)) | set(scalar_refs(result.data)) | {s.id for s in result.sources}
    if name == "run_independent_academic_workflow":
        # Failed selections were withheld before reasoning. Recheck the included
        # sources; an omitted source must not suppress independently valid output.
        ids = set(scalar_refs(result.data)) | {s.id for s in result.sources}
    ids.update(str(args[k]) for k in ("document_id", "work_id") if args.get(k))
    courses = {s.course_id for s in result.sources if s.course_id}
    if args.get("course_id"):
        courses.add(args["course_id"])
    if args.get("connection_id") and ids:
        with bridge.store.transaction() as session:
            courses.update(
                session.scalars(
                    select(Material.course_id).where(
                        Material.owner == owner,
                        Material.connection_id == args["connection_id"],
                        Material.id.in_(ids),
                    )
                )
            )
    for row in bridge.integrity.contexts(owner):
        content = row.content
        scope = Scope.model_validate(content["scope"])
        local_match = bool(ids & set(content.get("hashes", {})))
        course_match = (
            scope.connection_id == args.get("connection_id") and scope.course_id in courses
        )
        assessment_match = bool(scope.assessment_id and scope.assessment_id in ids) or bool(
            ids & set(content.get("assessed_materials", []))
        )
        if not (local_match or course_match or assessment_match):
            continue
        bridge.integrity.authorize_scope(owner, scope)
        policies = [PolicySource.model_validate(s) for s in content["policy_sources"]]
        # Current known prohibitions remain effective even when a continuation is
        # omitted. New scope/content permissions require fresh discovery.
        activity = A.LEARNING
        if (scope.assessment_id or content.get("assessed_source")) and (
            local_match or assessment_match
        ):
            activity = A.SOLVE
        if name == "prepare_for_assessment":
            activity = A.EXAM_PREPARATION
        decision = evaluate_academic_assistance(
            activity, policies, assessment_id=scope.assessment_id, now=bridge.retention.clock()
        )
        if name in LEARNING_TOOLS or name == "prepare_for_assessment":
            decision.require()
            result.data["integrity_boundary"] = {
                "activity": str(activity),
                "permission_established": decision.permission_established,
                "reason_code": decision.reason_code,
                "completion_permission": "not_granted_by_source_read",
            }
        elif name in {
            "get_assignment_details",
            "review_assignment_requirements",
        } and evaluate_academic_assistance(
            A.DRAFT, policies, assessment_id=scope.assessment_id, now=bridge.retention.clock()
        ).state in {
            "PROHIBITED_CONFIRMED",
            "CONFLICTING",
            "REVIEW_REQUIRED",
            "PERMISSION_REQUIRED",
        }:
            # Requirements remain usable; a denied completion workflow cannot use
            # this metadata route to retrieve its substantive raw assessment again.
            def minimize(value):
                if isinstance(value, dict):
                    return {
                        k: minimize(v)
                        for k, v in value.items()
                        if k
                        not in {
                            "requirements_text",
                            "rubric",
                            "text",
                            "passage",
                            "excerpt",
                            "draft",
                            "student_draft",
                            "description",
                            "long_description",
                        }
                    }
                if isinstance(value, list):
                    return [minimize(v) for v in value]
                return value

            result.data = minimize(result.data)
            result.data["integrity_boundary"] = {
                "activity": "requirements",
                "substantive_content": "withheld",
                "reason_code": "INTEGRITY_ADMINISTRATIVE_SCOPE",
            }
    return result


def resolve_integrity_sources(engine, owner, arguments, result):
    from canvas_bridge.egress_models import ContentClassification as CC
    from canvas_bridge.egress_models import SourceContext
    from canvas_bridge.egress_sources import resolve_sources

    bridge = engine.bridge
    scope = bridge.integrity.scope_for_arguments(owner, arguments)
    if scope is None:
        return (
            SourceContext(
                "__public__", owner, "integrity-history", "", "preferences", CC.PUBLIC_OR_APPROVED
            ),
        ), None
    bridge.integrity.authorize_scope(owner, scope)
    sources, institution = [], None
    document_ids = set(scope.document_ids)
    if arguments.get("document_id"):
        document_ids.add(arguments["document_id"])
    # Resolve every selected import through its own current ownership/provenance
    # fence before separating it from institutional citations. Unknown citations
    # remain in the institutional resolver and still fail closed.
    independent = []
    for ident in document_ids:
        independent.extend(bridge.independent.sources(owner, {"document_id": ident}, result))
    local_ids = {s.source_id for s in independent}
    if scope.connection_id:
        sources, institution = resolve_sources(
            engine,
            owner,
            scope.model_dump(),
            result.model_copy(
                update={"sources": [s for s in result.sources if s.id not in local_ids]}
            ),
            "prepare_for_assessment",
        )
        sources = list(sources)
    sources.extend(independent)
    if not sources:
        sources = [
            SourceContext(
                "__public__", owner, "integrity-status", "", "safe_status", CC.PUBLIC_OR_APPROVED
            )
        ]
    return tuple(sources), institution
