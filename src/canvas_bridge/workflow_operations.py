"""Fixed adapters to existing academic services; no model-selected executable operations."""

from datetime import timedelta
from types import MappingProxyType

from canvas_bridge.academic_intelligence import academic_request
from canvas_bridge.calendar_sync import propose_sync
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.grade_audit import collect, grading_request
from canvas_bridge.planning import PlanRequest
from canvas_bridge.retrieval import fetch_material, outline
from canvas_bridge.storage import Material

# Each adapter retains the authorization requirements of its original MCP surface.
TOOLS = MappingProxyType(
    {
        "workload": "get_workload",
        "changes": "get_changes",
        "priorities": "propose_study_plan",
        "exam": "prepare_for_assessment",
        "grade_evidence": "calculate_course_grade",
        "current_grade": "calculate_course_grade",
        "scenario": "simulate_grade_scenario",
        "course_review": "audit_course_consistency",
        "grading_review": "audit_course_grade",
        "materials": "get_course_outline",
        "reading": "fetch_course_material",
        "interpretation": "record_course_figure_observation",
        "event_proposals": "propose_calendar_sync",
    }
)
NETWORK = frozenset(TOOLS) - {"priorities", "changes", "current_grade", "scenario"}


def unavailable(summary, code):
    return Result(status="needs_input", summary=summary, data={"reason_code": code})


def calendar_ready(request):
    calendar = request.calendar
    return bool(
        calendar
        and -timedelta(minutes=1) <= utcnow() - calendar.retrieved_at <= timedelta(minutes=5)
        and calendar.pagination_complete
        and calendar.availability_complete
        and (not request.start or calendar.window_start <= request.start)
        and (not request.end or calendar.window_end >= request.end)
        and all(
            calendar.window_start <= w.start < w.end <= calendar.window_end
            for w in (request.plan.windows if request.plan else [])
        )
    )


def plan_request(request):
    plan = request.plan or PlanRequest()
    if calendar_ready(request):
        return PlanRequest.model_validate(
            {
                **plan.model_dump(),
                "busy_times": [*plan.busy_times, *request.calendar.busy_times],
                "availability_origin": "provided_via_conversation",
            }
        )
    return plan


async def workload(ctx, course, previous):
    return await ctx.bridge.workload(
        ctx.owner,
        ctx.ref,
        ctx.start,
        ctx.end,
        ctx.request.timezone,
        course_refs=ctx.courses,
        limit=100,
    )


async def changes(ctx, course, previous):
    if ctx.request.since is None:
        return unavailable(
            "Choose a comparison time to check observed changes; newness is unknown.",
            "BASELINE_NOT_REQUESTED",
        )
    # Existing change snapshots cover the current selection, not arbitrary subsets.
    if set(ctx.courses) != {c.id for c in ctx.bridge.selected(ctx.owner, ctx.ref)[1]}:
        return unavailable(
            "Change history does not cover this exact course scope.", "BASELINE_SCOPE_MISMATCH"
        )
    return ctx.bridge.changes(ctx.owner, ctx.ref, ctx.request.since)


async def calendar(ctx, course, previous):
    if not calendar_ready(ctx.request):
        return unavailable(
            "Calendar availability is unknown. Provide fresh, complete context from the existing authorized calendar connection.",
            "CALENDAR_UNAVAILABLE",
        )
    return Result(
        summary="Using calendar availability supplied through the existing client connection.",
        data={
            "availability_status": "provided_via_conversation",
            "retrieved_at": ctx.request.calendar.retrieved_at.isoformat(),
            "assumptions": [
                "The connector does not independently authenticate the external calendar response."
            ],
        },
    )


async def priorities(ctx, course, previous):
    result = ctx.bridge.study_plan(
        ctx.owner, ctx.ref, previous["obligations"].meta.snapshot_id, plan_request(ctx.request)
    )
    if recommendations := result.data.get("recommendations"):
        first = recommendations[0]
        source = next((s for s in result.sources if s.id == first["work_id"]), None)
        if source:
            result.summary = f"Suggested first step for {source.title}: {first['first_action']} Reason: {first['reason']}. This ranking is a heuristic."
    if not calendar_ready(ctx.request):
        result.status = "partial_data"
        result.data.setdefault("assumptions", []).append(
            "Calendar conflicts could not be checked; missing calendar data is not free time."
        )
        result.summary += " Calendar conflicts remain unchecked."
    return result


async def exam(ctx, course, previous):
    return await academic_request(
        ctx.bridge,
        ctx.owner,
        ctx.ref,
        course,
        "exam",
        work_id=ctx.request.assessment_id,
        material_ids=ctx.request.material_ids or None,
    )


async def exam_outline(ctx, course, previous):
    evidence = previous["assessment"]
    if not evidence.data.get("assessment"):
        return unavailable(
            "Choose a confirmed assessment before constructing a study outline.",
            "ASSESSMENT_UNKNOWN",
        )
    from canvas_bridge.planning import subtract

    outline_steps = [
        "Confirm the cited assessment scope and resolve missing requirements.",
        "Explain each confirmed objective from memory, then compare with its source.",
        "Practice interpreting the cited figures after inspecting their pixels.",
    ]
    blocks = []
    if ctx.request.plan:
        plan = plan_request(ctx.request)
        now = utcnow()
        windows = [
            [max(w.start, now, ctx.start), min(w.end, ctx.end)]
            for w in plan.windows
            if min(w.end, ctx.end) > max(w.start, now, ctx.start)
        ]
        for busy in [*plan.busy_times, *plan.pinned_blocks]:
            windows = subtract(
                windows,
                busy.start - timedelta(minutes=plan.buffer_minutes),
                busy.end + timedelta(minutes=plan.buffer_minutes),
            )
        remaining = plan.opportunity_minutes
        for start, end in windows:
            minutes = min(
                remaining, plan.max_block_minutes, int((end - start).total_seconds() // 60)
            )
            if minutes < plan.minimum_block_minutes:
                continue
            blocks.append(
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(minutes=minutes)).isoformat(),
                    "minutes": minutes,
                    "activity": "Work through the cited-scope review sequence; stop when the reserved time ends.",
                }
            )
            remaining -= minutes
            if remaining < plan.minimum_block_minutes:
                break
    # Time blocks fit supplied availability. Required effort and actual assessment
    # coverage remain unknown; fitting the window is not completing the syllabus.
    return Result(
        status="partial_data",
        summary="Review the confirmed scope, recall each learning objective, then check your answers against the cited passages.",
        data={
            "outline": outline_steps,
            "study_blocks": blocks,
            "assessment": evidence.data["assessment"],
            "availability": "user_supplied"
            if ctx.request.plan and ctx.request.plan.windows
            else "unknown",
            "limitations": [
                "This is a suggested study sequence, not verified assessment coverage or a guarantee of completion.",
                "Blocks fit only supplied availability; unknown calendar conflicts and required effort can change feasibility.",
            ],
        },
        sources=evidence.sources,
    )


async def grade_evidence(ctx, course, previous):
    evidence = await collect(ctx.bridge, ctx.owner, ctx.ref, course)
    ctx.private[course] = evidence
    return Result(
        status="ok" if evidence["complete"] else "partial_data",
        summary="Retrieved visible grading evidence once for current and scenario calculations.",
        data={
            "course_id": course,
            "complete": evidence["complete"],
            "policy": evidence["policy"].model_dump(mode="json"),
        },
        sources=evidence["sources"],
    )


def grade(ctx, course, scenario=False):
    from canvas_bridge.academic.services import calculate_grade
    from canvas_bridge.providers.canvas import AuthorizedCanvasProvider

    evidence = ctx.private[course]
    provider = AuthorizedCanvasProvider(ctx.bridge, ctx.owner, ctx.ref)
    calculation = calculate_grade(
        provider.gateway,
        provider.calculation_input(evidence, evidence["policy"]),
        mode=ctx.request.scenario_mode if scenario else "current_graded",
        scenario=ctx.request.scenario if scenario else None,
    )["calculation"]
    return Result(
        status="partial_data" if calculation["missing_information"] else "ok",
        summary=("Hypothetical grade scenario" if scenario else "Current visible grade calculation")
        + ": "
        + calculation["classification"].replace("_", " ")
        + ".",
        data={
            "course_id": course,
            "calculation": calculation,
            "assumptions": ["Visible-work arithmetic is not an official final grade."],
        },
        sources=evidence["sources"],
    )


async def current_grade(ctx, course, previous):
    return grade(ctx, course)


async def scenario(ctx, course, previous):
    if ctx.request.scenario is None:
        return Result(
            summary="No hypothetical scenario requested.", data={"scenario_status": "not_requested"}
        )
    return grade(ctx, course, True)


async def course_review(ctx, course, previous):
    return await academic_request(
        ctx.bridge,
        ctx.owner,
        ctx.ref,
        course,
        "audit",
        material_ids=ctx.request.material_ids or None,
    )


async def grading_review(ctx, course, previous):
    return await grading_request(
        ctx.bridge,
        ctx.owner,
        ctx.ref,
        course,
        "audit",
        material_ids=ctx.request.material_ids or None,
    )


async def materials(ctx, course, previous):
    if not ctx.request.material_ids:
        result = await outline(ctx.bridge, ctx.owner, ctx.ref, course)
        result.status = "partial_data"
        result.summary = "Choose up to three document references from this course outline for lecture comprehension."
        return result
    with ctx.bridge.store.transaction() as session:
        for ident in ctx.request.material_ids:
            row = ctx.bridge.store.owned(session, Material, ctx.owner, ctx.ref, ident)
            if row.course_id != course:
                raise DomainError(
                    "permission_denied", "Material does not belong to the chosen course."
                )
    return Result(
        summary="Requested materials belong to the selected course.",
        data={"course_id": course, "material_ids": ctx.request.material_ids},
    )


async def reading(ctx, course, previous):
    if not ctx.request.material_ids:
        return unavailable(
            "Choose documents from the course outline to continue.", "MATERIAL_SELECTION_REQUIRED"
        )
    results, sources, complete = [], [], True
    for ident in ctx.request.material_ids:
        ctx.check()
        try:
            result = await fetch_material(ctx.bridge, ctx.owner, ctx.ref, ident, length=6000)
            ctx.check_sources(result)
            sources.extend(result.sources)
            # The standalone reader retains the full scientific document model.
            # A workflow needs exact passages and continuations, not a duplicate
            # structure tree that would crowd the visual report out of the budget.
            compact = {
                key: value
                for key, value in result.data.items()
                if key
                in {
                    "id",
                    "file_id",
                    "title",
                    "course_id",
                    "content_hash",
                    "source_version",
                    "text",
                    "passages",
                    "coverage",
                    "limitations",
                    "next_offset",
                    "continuation",
                    "page_start",
                    "page_end",
                    "total_characters",
                    "content_boundary",
                }
            }
            results.append({"material_id": ident, "status": result.status, "data": compact})
            complete &= (
                result.status == "ok"
                and not result.data.get("continuation")
                and result.data.get("next_offset") is None
            )
        except DomainError as exc:
            if exc.status in {"permission_denied", "reconnect_required", "source_changed"}:
                raise
            complete = False
            results.append(
                {
                    "material_id": ident,
                    "status": exc.status,
                    "reason_code": exc.reason_code or "DOCUMENT_UNAVAILABLE",
                }
            )
        ctx.check()
    return Result(
        status="ok" if complete else "partial_data",
        summary="Retrieved source text; visual understanding still requires inspected pixels.",
        data={"documents": results},
        sources=sources,
    )


async def interpretation(ctx, course, previous):
    from canvas_bridge.figure_observations import record_observation

    if not ctx.request.visual_reports:
        return Result(
            status="partial_data",
            summary="Inspect the relevant rendered pages or slides, then provide the attributed visual report to continue.",
            data={
                "comprehension_status": "awaiting_client_inspection",
                "next_actions": [
                    "Use render_course_file_page or render_course_slide for each relevant figure; use inspect_course_figure when a crop is needed.",
                    "Return visual_reports with the render receipt and observations. Text extraction alone is not figure interpretation.",
                ],
            },
        )
    reports, sources = [], []
    for report in ctx.request.visual_reports:
        if report.file_id not in ctx.request.material_ids:
            raise DomainError(
                "permission_denied", "Visual report is outside this workflow's requested documents."
            )
        result = await record_observation(
            ctx.bridge, ctx.owner, ctx.ref, report.render_receipt, report.observation
        )
        if result.data.get("file_id") != report.file_id:
            raise DomainError("permission_denied", "Visual receipt and requested file differ.")
        ctx.check_sources(result)
        reports.append(result.data)
        sources.extend(result.sources)
    return Result(
        status="partial_data",
        summary="Source-bound visual reports are ready for discussion; scientific accuracy remains unverified.",
        data={"reports": reports},
        sources=sources,
    )


async def event_proposals(ctx, course, previous):
    return await propose_sync(
        ctx.bridge,
        ctx.owner,
        ctx.ref,
        previous["obligations"].meta.snapshot_id,
        ctx.request.calendar,
        ctx.request.plan,
    )


OPERATIONS = MappingProxyType(
    {
        fn.__name__: fn
        for fn in (
            workload,
            changes,
            calendar,
            priorities,
            exam,
            exam_outline,
            grade_evidence,
            current_grade,
            scenario,
            course_review,
            grading_review,
            materials,
            reading,
            interpretation,
            event_proposals,
        )
    }
)
