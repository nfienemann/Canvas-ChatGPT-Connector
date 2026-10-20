"""Fresh selected-activity planning. Source visibility is not an obligation or completion claim."""

import asyncio
from typing import Annotated, Literal

from pydantic import Field, model_validator
from sqlalchemy import select

from canvas_bridge.domain import DomainError, Effort, FactDate, Model, Result, WorkItem, utcnow
from canvas_bridge.evidence import attach
from canvas_bridge.obligations import LIMITATIONS, collect_inventory
from canvas_bridge.planning import PlanRequest, is_actionable, propose
from canvas_bridge.storage import LocalRecord

Ref = Annotated[str, Field(min_length=1, max_length=100)]


class CoursePlanningScope(Model):
    course_id: Ref
    inventory_version: str = Field(pattern=r"^[a-f0-9]{64}$")


class ActivitySelection(Model):
    obligation_id: Ref
    intent: Literal["remaining_work", "event_preparation"]
    basis: Literal["student_request", "suggested_review"] = "suggested_review"


class ActivityPlanRequest(PlanRequest):
    activities: list[ActivitySelection] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_activities(self):
        if len({a.obligation_id for a in self.activities}) != len(self.activities):
            raise ValueError("Choose each canonical activity only once.")
        return self


def project_activity(bundle, group, choice, now):
    """Only allowlisted inventory facts enter the existing deterministic planner."""
    aliases = group["source_aliases"]
    if group["conflicts"] or any(
        a["link_status"] in {"conflicting_links", "linked_assignment_not_retrieved"}
        for a in aliases
    ):
        return None, None, "unresolved_source_relationship_or_deadline"
    if choice.basis != "student_request":
        return None, None, "activity_relevance_needs_student_choice"
    if group["work_id"]:
        if choice.intent != "remaining_work":
            return None, None, "event_preparation_requires_calendar_event"
        return bundle["work_items"][group["id"]].model_copy(deep=True), None, None
    if len(aliases) != 1:
        return None, None, "ambiguous_activity_sources"
    alias = aliases[0]
    kind = alias["source_type"]
    if kind not in {"classic_quizzes", "discussion_topics", "calendar_events"}:
        return None, None, "unsupported_activity_source"
    event = kind == "calendar_events"
    if event != (choice.intent == "event_preparation"):
        return None, None, "calendar_events_require_preparation_intent"
    opens, closes = (FactDate.model_validate(alias[k]) for k in ("available_from", "closes_at"))
    availability = (
        "closed"
        if (closes.timestamp and closes.timestamp <= now)
        or alias.get("participation_state") == "closed"
        else "future_locked"
        if opens.timestamp and opens.timestamp > now
        else "unknown"
        if kind == "discussion_topics" and alias.get("participation_state") == "unknown"
        else "available"
    )
    item = WorkItem(
        id=group["id"],
        connection_id=bundle["connection"].id,
        institution_id=bundle["connection"].institution,
        course_id=group["course_id"],
        source_id=alias["source_id"],
        title=group["title"],
        kind=kind,
        effective_due=FactDate() if event else FactDate.model_validate(alias["due"]),
        available_from=opens,
        closes_at=closes,
        availability_state=availability,
        source=bundle["sources"][alias["source_id"]],
        instruction_state=alias["requirements_coverage"]["state"],
        instruction_hash=alias["content_hash"],
    )
    return item, FactDate.model_validate(alias["event_start"]) if event else None, None


async def propose_course_plan(bridge, owner, ref, scopes, start, end, timezone, request):
    ids = [s.course_id for s in scopes]
    if not 1 <= len(ids) <= 10 or len(set(ids)) != len(ids):
        raise DomainError("needs_input", "Choose one to ten distinct selected courses.")
    await bridge.list_courses(owner, ref)
    connection, _ = bridge.selected(owner, ref, ids)
    try:
        async with asyncio.timeout(bridge.settings.refresh_budget_seconds):
            bundles = await asyncio.gather(
                *(
                    collect_inventory(
                        bridge,
                        owner,
                        ref,
                        scope.course_id,
                        start,
                        end,
                        timezone,
                        refresh_courses=False,
                    )
                    for scope in scopes
                ),
                return_exceptions=True,
            )
    except TimeoutError as exc:
        raise DomainError(
            "retry_later",
            "Course planning exceeded the refresh budget. No plan was produced; narrow the course scope.",
        ) from exc
    for bundle in bundles:
        if isinstance(bundle, BaseException):
            raise bundle
    for scope, bundle in zip(scopes, bundles, strict=True):
        if scope.inventory_version != bundle["version"]:
            raise DomainError(
                "source_changed",
                "Course activity evidence changed. Refresh get_course_obligations with the same window and timezone before planning.",
            )
    inventory = {g["id"]: (b, g) for b in bundles for g in b["items"]}
    choices = {c.obligation_id for c in request.activities}
    if choices - inventory.keys():
        raise DomainError(
            "permission_denied", "An activity is outside the current authorized course inventory."
        )
    supplied = (
        set(request.effort_overrides)
        | set(request.priority_overrides)
        | set(request.importance)
        | set(request.date_only_timezones)
        | {p.work_id for p in request.pinned_blocks}
    )
    if supplied - choices:
        raise DomainError(
            "needs_input", "Planning input references an activity outside the chosen set."
        )
    now = utcnow()
    items, targets, selected, review, excluded = [], {}, [], [], []
    with bridge.store.transaction() as session:
        progress = {
            r.key: r
            for r in session.scalars(
                select(LocalRecord).where(
                    LocalRecord.owner == owner,
                    LocalRecord.connection_id == ref,
                    LocalRecord.kind == "progress",
                    LocalRecord.key.in_(choices),
                )
            )
        }
    sources = {}
    for choice in request.activities:
        bundle, group = inventory[choice.obligation_id]
        item, target, problem = project_activity(bundle, group, choice, now)
        primary = next(
            (a for a in group["source_aliases"] if a["source_type"] == "assignments"),
            group["source_aliases"][0],
        )
        source = bundle["sources"][primary["source_id"]]
        sources[source.id] = source
        record = {
            "work_id": group["id"],
            "course_id": group["course_id"],
            "title": group["title"],
            "source_id": source.id,
            "intent": choice.intent,
            "selection_basis": choice.basis,
            "required_status": group["required_status"],
            "submission_state": group["submission_state"],
            "assessment_state": group["assessment_state"],
            "source_alias_count": len(group["source_aliases"]),
            "selection_classification": "student_input"
            if choice.basis == "student_request"
            else "assistant_inference",
        }
        if problem:
            aliases = group["source_aliases"][:6]
            for alias in aliases:
                sources[alias["source_id"]] = bundle["sources"][alias["source_id"]]
            review.append(
                {
                    **record,
                    "reason": problem,
                    "source_relationships": [
                        {key: a[key] for key in ("source_id", "source_type", "link_status", "due")}
                        for a in aliases
                    ],
                    "source_relationships_complete": len(aliases) == len(group["source_aliases"]),
                    "planning_inputs_not_applied": True,
                }
            )
            continue
        local = progress.get(item.id)
        if local:
            item.personal_progress = local.payload["status"]
            if local.payload.get("remaining_effort"):
                item.effort_remaining = Effort.model_validate(local.payload["remaining_effort"])
            record["personal_progress"] = {
                "status": item.personal_progress,
                "version": local.version,
                "classification": "student_input",
            }
        if not is_actionable(item):
            excluded.append(
                {
                    **record,
                    "reason": "completed_excused_or_currently_unavailable",
                    "planning_inputs_not_applied": True,
                }
            )
            continue
        items.append(item)
        if target is not None:
            targets[item.id] = target
        selected.append(record)
    eligible = {i.id for i in items}
    inputs = request.model_dump(exclude={"activities"})
    for field in ("effort_overrides", "priority_overrides", "importance", "date_only_timezones"):
        inputs[field] = {key: value for key, value in inputs[field].items() if key in eligible}
    inputs["pinned_blocks"] = [p for p in inputs["pinned_blocks"] if p["work_id"] in eligible]
    try:
        result = propose(
            items, PlanRequest.model_validate(inputs), now, preparation_targets=targets
        )
    except ValueError as exc:
        raise DomainError("needs_input", str(exc)) from exc
    if result["feasibility"] == "feasible":
        result["feasibility"] = "provisional"
    if not items:
        result["feasibility"] = (
            "selection_needs_review" if review else "no_actionable_selected_activities"
        )
    current, _ = bridge.selected(owner, ref, ids)
    if current.epoch != connection.epoch or any(
        b["connection"].epoch != connection.epoch for b in bundles
    ):
        raise DomainError("source_changed", "Course selection changed during activity planning.")
    limitations = [
        "This plan covers only the chosen activities, not the student's complete workload or timetable.",
        "Choosing an activity expresses planning intent, not proof of required participation or unfinished work. No quiz duration or assignment points are converted to effort.",
        "Event starts bound preparation only; they are not assignment deadlines or verified attendance commitments. Provide known commitments as busy_times.",
        "No plan is saved. New activity progress persistence and direct Calendar synchronization are not provided by this tool.",
        *LIMITATIONS,
    ]
    response = Result(
        status="needs_input" if review and not items else "partial_data",
        summary="Draft plan for selected authorized course activities, with current evidence and explicit limits. Nothing was saved or changed in Canvas or Calendar.",
        data={
            **result,
            "selected_activities": selected,
            "needs_review": review,
            "excluded_activities": excluded,
            "inventory_versions": {
                s.course_id: b["version"] for s, b in zip(scopes, bundles, strict=True)
            },
            "scope": "explicitly_selected_activities_only",
            "limitations": limitations,
            "provider_writes_executed": False,
        },
        sources=list(sources.values()),
        meta=bridge.meta(
            coverage=[c for b in bundles for c in b["coverage"]],
            warnings=limitations,
            display_timezone=timezone,
        ),
    )
    attach(response)
    if len(response.model_dump_json().encode()) > 200_000:
        raise DomainError(
            "needs_input",
            "The proposed plan exceeds the response budget. Choose fewer activities or study windows.",
        )
    return response
