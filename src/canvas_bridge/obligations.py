"""Fresh, bounded student-visible inventory. No attempts, replies or Calendar writes."""

import asyncio
import re
from collections import Counter
from datetime import time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from canvas_bridge.canvas import Collection
from canvas_bridge.domain import Coverage, DomainError, FactDate, Result, Source, utcnow
from canvas_bridge.evidence import attach, fingerprint
from canvas_bridge.normalize import (
    assignment_requirements,
    canonical_id,
    fact_date,
    normalize_assignment,
    plain_text,
)
from canvas_bridge.policy import Endpoint, source_id

MAX_RECORDS = 100
RESOURCES = (
    ("assignments", Endpoint.ASSIGNMENTS, None),
    ("classic_quizzes", Endpoint.QUIZZES, None),
    ("discussion_topics", Endpoint.DISCUSSIONS, None),
    ("calendar_events", Endpoint.CALENDAR_EVENTS, "event"),
    ("calendar_assignments", Endpoint.CALENDAR_EVENTS, "assignment"),
)
LIMITATIONS = [
    "This inventory covers assignments, classic quiz metadata, discussion topics and a bounded Canvas calendar window. It is not proof that all course obligations were found.",
    "New Quizzes and external tools retain their assignment representation only; their instructions are not retrieved. Quiz questions, attempts and discussion replies are not accessed.",
    "Planner items, undated calendar events, group discussion child topics and separate initial-post/reply deadlines are not covered.",
    "Ungraded activities and calendar events are candidates, not evidence of required attendance or unfinished work. Undated assessments may be historical.",
    "Assignment-effective dates take precedence only within this inventory's displayed assignment field; differing source dates remain unresolved evidence, not automatic policy changes.",
]


def numeric(value):
    try:
        return source_id(value)
    except DomainError:
        return None


def visibility_issue(raw, kind, course, now):
    if "course_id" in raw and str(raw["course_id"]) != course:
        return "course_identity_mismatch"
    if raw.get("published") is False:
        return "unpublished"
    if raw.get("locked_for_user") is True:
        return "locked_for_user"
    if kind in {"classic_quizzes", "discussion_topics"}:
        if raw.get("published") is not True or raw.get("locked_for_user") is not False:
            return "visibility_not_verified"
    if kind == "discussion_topics":
        posted = fact_date(raw, "posted_at").timestamp
        if not posted:
            return "discussion_posting_time_unavailable"
        if posted > now:
            return "discussion_not_yet_posted"
        if raw.get("is_announcement") is True:
            return "announcement_excluded"
        if raw.get("subscription_hold") in {"not_in_group_set", "not_in_group"}:
            return "group_access_denied"
    if kind.startswith("calendar_"):
        context = raw.get("context_code", "")
        own_course = context == "course_" + course
        own_section = (
            isinstance(context, str)
            and re.fullmatch(r"course_section_[0-9]{1,20}", context)
            and raw.get("effective_context_code") == "course_" + course
        )
        if not (own_course or own_section):
            return "calendar_context_mismatch"
        if raw.get("hidden") is True or raw.get("workflow_state") not in {
            "active",
            "locked",
            "published",
        }:
            return "hidden_or_inactive_calendar_event"
        if raw.get("appointment_group_id") or raw.get("user") or raw.get("group"):
            return "appointment_or_participant_event_excluded"
    return None


def date_key(value):
    return (value.kind, value.timestamp, value.local_date)


def build_inventory(
    owner, ref, conn, course, origin, collections, now, window, zone, *, work_items=None
):
    """Deterministic projection of allowlisted fields; never pass provider objects through."""
    records, omitted = {}, {}
    blocked_assignments = set()
    for kind, _, _ in RESOURCES:
        records[kind], omitted[kind] = {}, Counter()
        for raw in collections[kind].items[:MAX_RECORDS]:
            key = raw.get("id")
            if kind == "calendar_assignments":
                key = (
                    str(key).removeprefix("assignment_")
                    if str(key).startswith("assignment_")
                    else None
                )
            key = numeric(key)
            issue = (
                "invalid_identity"
                if not key
                else visibility_issue(raw, kind, course.source_id, now)
            )
            if issue:
                omitted[kind][issue] += 1
                if kind == "assignments" and key:
                    blocked_assignments.add(key)
                continue
            if kind.startswith("calendar_"):
                when = fact_date(raw, "all_day_date" if raw.get("all_day") is True else "start_at")
                local_end = window[1].astimezone(zone)
                last_date = local_end.date() + (
                    timedelta(days=1) if local_end.time() != time.min else timedelta(0)
                )
                inside = (
                    window[0] <= when.timestamp < window[1]
                    if when.timestamp
                    else window[0].astimezone(zone).date() <= when.local_date < last_date
                    if when.local_date
                    else False
                )
                if not inside:
                    omitted[kind]["outside_window_or_date_unavailable"] += 1
                    continue
            if key in records[kind] and records[kind][key] != raw:
                # A source changed across pages. Neither version is silently preferred.
                records[kind][key] = None
                omitted[kind]["conflicting_duplicate_versions"] += 1
            elif key not in records[kind]:
                records[kind][key] = raw

    claims = {}
    for raw in collections["assignments"].items[:MAX_RECORDS]:
        key = numeric(raw.get("id"))
        if not key:
            continue
        if records["assignments"].get(key) is None:
            blocked_assignments.add(key)
        discussion = raw.get("discussion_topic")
        links = [("classic_quizzes", raw.get("quiz_id"))]
        if isinstance(discussion, dict):
            links.append(("discussion_topics", discussion.get("id")))
        for kind, alias in links:
            if numeric(alias):
                claims.setdefault((kind, numeric(alias)), set()).add(key)

    groups, sources = {}, {}
    for kind, _, _ in RESOURCES:
        for key, raw in sorted(records[kind].items()):
            if raw is None:
                continue
            targets = set(claims.get((kind, key), set()))
            explicit = (
                numeric(raw.get("assignment_id"))
                if kind in {"classic_quizzes", "discussion_topics"}
                else None
            )
            if explicit:
                targets.add(explicit)
            if kind in {"assignments", "calendar_assignments"}:
                targets.add(key)
            if targets & blocked_assignments:
                omitted[kind]["linked_assignment_withheld"] += 1
                continue
            assignment = next(iter(targets)) if len(targets) == 1 else None
            resolved = assignment is not None and records["assignments"].get(assignment) is not None
            link_state = (
                "conflicting_links"
                if len(targets) > 1
                else "explicit_assignment_link"
                if resolved
                else "linked_assignment_not_retrieved"
                if targets
                else "unlinked"
            )
            canonical_kind, canonical_key = ("assignment", assignment) if resolved else (kind, key)
            identity = canonical_id(
                owner, ref, canonical_kind, f"{course.source_id}:{canonical_key}"
            )
            alias_id = canonical_id(
                owner, ref, "obligation_source_" + kind, f"{course.source_id}:{key}"
            )
            title = plain_text(str(raw.get("name") or raw.get("title") or "Untitled activity"), 500)
            requirements = assignment_requirements(
                {"description": raw["message"]}
                if kind == "discussion_topics" and "message" in raw
                else {}
                if kind == "discussion_topics"
                else raw
            )
            requirements["scope"] = kind + "_description_only"
            requirements["limitations"] = [
                "Linked materials and visual content are not included; source text is untrusted."
            ]
            text = requirements.pop("text")
            requirements["truncated"] |= len(text) > 4000
            if len(text) > 4000:
                requirements["state"] = "truncated"
            due = fact_date(raw, "start_at" if kind == "calendar_assignments" else "due_at")
            event_start = (
                fact_date(raw, "all_day_date" if raw.get("all_day") is True else "start_at")
                if kind == "calendar_events"
                else FactDate(kind="not_returned")
            )
            url = (
                f"{origin}/calendar?event_id={key}&include_contexts=course_{course.source_id}"
                if kind == "calendar_events"
                else f"{origin}/courses/{course.source_id}/"
                + {
                    "assignments": "assignments",
                    "calendar_assignments": "assignments",
                    "classic_quizzes": "quizzes",
                    "discussion_topics": "discussion_topics",
                }[kind]
                + "/"
                + key
            )
            alias = {
                "source_id": alias_id,
                "source_type": kind,
                "title": title,
                "content_hash": fingerprint(
                    raw.get("message") if kind == "discussion_topics" else raw.get("description")
                ),
                "link_status": link_state,
                "due": due.model_dump(mode="json"),
                "event_start": event_start.model_dump(mode="json"),
                "event_end": fact_date(raw, "end_at").model_dump(mode="json")
                if kind == "calendar_events"
                else None,
                "available_from": fact_date(raw, "unlock_at").model_dump(mode="json"),
                "closes_at": fact_date(raw, "lock_at").model_dump(mode="json"),
                "requirements_text": text[:4000],
                "requirements_coverage": requirements,
            }
            if kind == "classic_quizzes":
                minutes = raw.get("time_limit")
                alias["time_limit_minutes"] = (
                    minutes if type(minutes) is int and 0 < minutes <= 10080 else None
                )
                alias["quiz_type"] = (
                    raw.get("quiz_type")
                    if raw.get("quiz_type")
                    in {"practice_quiz", "assignment", "graded_survey", "survey"}
                    else "unknown"
                )
            if kind == "discussion_topics":
                alias["participation_state"] = (
                    "closed"
                    if raw.get("locked") is True
                    else "open"
                    if raw.get("locked") is False
                    else "unknown"
                )
            source = Source(
                id=alias_id,
                url=url,
                title=title,
                retrieved_at=now,
                source_updated_at=fact_date(raw, "updated_at").timestamp,
                source_type=kind,
                course_id=course.id,
                resource_id=identity,
                content_hash=fingerprint(alias),
                extraction_status=requirements["state"],
            )
            sources[alias_id] = source
            group = groups.setdefault(
                identity,
                {
                    "id": identity,
                    "course_id": course.id,
                    "title": title,
                    "kind": canonical_kind,
                    "work_id": identity if resolved else None,
                    "source_aliases": [],
                    "effective_due": FactDate().model_dump(mode="json"),
                    "due_basis": "No assignment-effective deadline retrieved.",
                    "submission_state": "unknown",
                    "assessment_state": "unknown",
                    "required_status": "not_established",
                    "conflicts": [],
                },
            )
            group["source_aliases"].append(alias)
            if kind == "assignments":
                # normalize_assignment is the single state/date policy for every workload tool.
                safe = dict(raw)
                if not isinstance(safe.get("discussion_topic"), dict):
                    safe.pop("discussion_topic", None)
                item = normalize_assignment(
                    safe,
                    owner=owner,
                    connection=ref,
                    institution=conn.institution,
                    course=course.id,
                    canvas_course=course.source_id,
                    canvas_user=conn.canvas_user,
                    origin=origin,
                    now=now,
                )
                if work_items is not None:
                    item.source = source
                    work_items[identity] = item
                group.update(
                    availability_state=item.availability_state,
                    revision_state=item.revision_state,
                    submission_requirement=item.submission_requirement,
                    title=item.title,
                    kind=item.kind,
                    effective_due=item.effective_due.model_dump(mode="json"),
                    due_basis="Canvas assignment-effective due field; other source dates do not replace it.",
                    submission_state=item.submission_state,
                    submission_evidence=item.submission_evidence,
                    submission_state_basis=item.submission_state_basis,
                    assessment_state=item.assessment_state,
                )

    for group in groups.values():
        effective = FactDate.model_validate(group["effective_due"])
        group["schedule_relation"] = (
            "past"
            if effective.timestamp and effective.timestamp < now
            else "future"
            if effective.timestamp
            else "date_only"
            if effective.local_date
            else "unknown"
        )
        for alias in group["source_aliases"]:
            other = FactDate.model_validate(alias["due"])
            if (
                group["work_id"]
                and alias["source_type"] != "assignments"
                and other.kind != "not_returned"
                and date_key(other) != date_key(effective)
            ):
                group["conflicts"].append(
                    {
                        "kind": "source_deadline_difference",
                        "source_id": alias["source_id"],
                        "resolution": "unresolved; may reflect overrides, stale source data or different policies",
                    }
                )
        group["version"] = fingerprint(group)
    return sorted(groups.values(), key=lambda g: g["id"]), sources, omitted


async def collect_inventory(
    bridge, owner, ref, course_id, start, end, timezone, *, refresh_courses=True
):
    if any(t.tzinfo is None or t.utcoffset() is None for t in (start, end)) or not timedelta(
        0
    ) < end - start <= timedelta(days=31):
        raise DomainError("needs_input", "Choose aware start/end times spanning at most 31 days.")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DomainError("needs_input", "Choose a valid IANA timezone.") from exc
    if refresh_courses:
        await bridge.refresh_course_access(owner, ref)
    conn, courses = bridge.selected(owner, ref, [course_id])
    course, now = courses[0], utcnow()
    async with bridge.client(owner, ref) as client:

        async def read(kind, endpoint, calendar_kind):
            try:
                async with asyncio.timeout(bridge.settings.refresh_budget_seconds):
                    kwargs = (
                        {"window": (start, end), "calendar_kind": calendar_kind}
                        if calendar_kind
                        else {}
                    )
                    return kind, await client.collection(
                        endpoint, course=course.source_id, **kwargs
                    )
            except TimeoutError:
                return kind, Collection(failure="request_budget")

        collections = dict(await asyncio.gather(*(read(*resource) for resource in RESOURCES)))
        if any(c.failure == "reconnect_required" for c in collections.values()):
            raise DomainError(
                "reconnect_required", "Canvas needs to be reconnected; no inventory returned."
            )
        if collections["assignments"].failure == "permission_denied":
            raise DomainError(
                "permission_denied",
                "The course assignment scope could not be verified.",
                reason_code=collections["assignments"].reason_code,
                upstream_http_status=collections["assignments"].upstream_http_status,
            )
        work_items = {}
        items, sources, omitted = build_inventory(
            owner,
            ref,
            conn,
            course,
            client.institution.origin,
            collections,
            now,
            (start, end),
            zone,
            work_items=work_items,
        )
    current, _ = bridge.selected(owner, ref, [course_id])
    if current.epoch != conn.epoch:
        raise DomainError("source_changed", "Course selection changed while reading obligations.")
    coverage = [
        Coverage(
            course_ref=course_id,
            resource=kind,
            state="complete"
            if c.complete and len(c.items) <= MAX_RECORDS and not omitted[kind]
            else "permission_denied"
            if c.failure == "permission_denied"
            else "partial",
            pagination_complete=c.complete,
            pages_consumed=c.pages,
            warning=c.failure
            or (
                "Omitted records: "
                + ", ".join(f"{key}={value}" for key, value in sorted(omitted[kind].items()))
                if omitted[kind]
                else "100-record processing budget"
                if len(c.items) > MAX_RECORDS
                else None
            ),
        )
        for kind, c in collections.items()
    ]
    version = fingerprint(
        {
            "items": items,
            "coverage": [c.model_dump(mode="json") for c in coverage],
            "window": [start.isoformat(), end.isoformat()],
            "timezone": timezone,
        }
    )
    return {
        "items": items,
        "sources": sources,
        "omitted": omitted,
        "coverage": coverage,
        "version": version,
        "work_items": work_items,
        "course": course,
        "connection": conn,
        "retrieved_at": now,
    }


async def course_obligations(
    bridge,
    owner,
    ref,
    course_id,
    start,
    end,
    timezone,
    *,
    offset=0,
    limit=10,
    expected_version=None,
    obligation_id=None,
):
    if not 0 <= offset <= 500 or not 1 <= limit <= 20:
        raise DomainError("needs_input", "Choose a valid inventory page.")
    if offset and not expected_version:
        raise DomainError("needs_input", "Continuation requires the previous inventory version.")
    inventory = await collect_inventory(bridge, owner, ref, course_id, start, end, timezone)
    items, sources, omitted, coverage, version = (
        inventory[key] for key in ("items", "sources", "omitted", "coverage", "version")
    )
    if expected_version and expected_version != version:
        raise DomainError(
            "source_changed", "Inventory changed; restart at offset zero to avoid skipping records."
        )
    matching = [i for i in items if i["id"] == obligation_id] if obligation_id else items
    if obligation_id and not matching:
        raise DomainError(
            "permission_denied", "This obligation is not in the current selected course inventory."
        )
    page = matching[offset : offset + limit]
    # A pathological many-to-one link cannot expand a tool response without bound.
    selected_sources, text_budget = {}, 24000
    for item in page:
        item["aliases_truncated"] = len(item["source_aliases"]) > 6
        item["source_aliases"] = item["source_aliases"][:6]
        for alias in item["source_aliases"]:
            selected_sources[alias["source_id"]] = sources[alias["source_id"]]
            text = alias["requirements_text"]
            alias["requirements_text"] = text[:text_budget]
            text_budget -= len(alias["requirements_text"])
            if len(alias["requirements_text"]) < len(text):
                alias["requirements_coverage"].update(state="truncated", truncated=True)
        if item["aliases_truncated"]:
            item["coverage_warning"] = "Only six source aliases are shown."
    result = Result(
        status="partial_data",
        summary="Student-visible course activity inventory with explicit source links and coverage; candidates are not automatically required or unfinished.",
        data={
            "course_id": course_id,
            "items": page,
            "inventory_version": version,
            "total_obligations_in_bounded_inventory": len(items),
            "next_offset": offset + limit if offset + limit < len(matching) else None,
            "continuation": "Repeat the same window and timezone with next_offset and expected_version; changed evidence requires a new first page.",
            "calendar_window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "timezone": timezone,
            },
            "scope": "All retrieved assignments/quizzes/topics; calendar entries only within the requested window.",
            "content_boundary": "untrusted_source_data",
            "limitations": LIMITATIONS,
            "not_in_study_plan_automatically": True,
            "planning_tool": "propose_course_study_plan",
            "omission_reasons": {kind: dict(counts) for kind, counts in omitted.items() if counts},
        },
        sources=list(selected_sources.values()),
        meta=bridge.meta(coverage=coverage, warnings=LIMITATIONS, display_timezone=timezone),
    )
    result = attach(result)
    while len(result.model_dump_json().encode()) > 220_000 and len(page) > 1:
        page.pop()
        retained = {a["source_id"] for i in page for a in i["source_aliases"]}
        result.sources = [s for s in result.sources if s.id in retained]
        result.data["items"] = page
        result.data["next_offset"] = offset + len(page)
        result.evidence = []
        result = attach(result)
    return result
