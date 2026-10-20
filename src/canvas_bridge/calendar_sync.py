"""Native ChatGPT Calendar composition: proposal generation, never provider writes.

Provider-held description markers maintain assignment/event mappings. Google
credentials remain with the student's existing Google Calendar connection.
"""

from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import DomainError, Model, Result, WorkItem, utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.planning import Window, is_actionable, propose
from canvas_bridge.storage import Snapshot, aware


class CalendarEvent(Model):
    id: str = Field(min_length=1, max_length=256)
    title: str = Field(max_length=500)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    all_day_date: date | None = None
    bridge_marker: str | None = Field(default=None, max_length=100)
    canvas_source_url: str | None = Field(default=None, max_length=500)
    status: Literal["confirmed", "tentative", "cancelled", "unknown"] = "unknown"
    version: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def interval(self):
        if self.start and self.all_day_date:
            raise ValueError("An event cannot be timed and all-day simultaneously.")
        if self.end and (not self.start or self.end <= self.start):
            raise ValueError("Calendar interval is invalid.")
        return self


class CalendarContext(Model):
    calendar_id: str = Field(min_length=1, max_length=256)
    timezone: str = Field(max_length=100)
    retrieved_at: AwareDatetime
    window_start: AwareDatetime
    window_end: AwareDatetime
    pagination_complete: bool
    mapping_search_complete: bool = False
    events: list[CalendarEvent] = Field(max_length=200)
    busy_times: list[Window] = Field(default_factory=list, max_length=100)
    availability_complete: bool = False
    origin: Literal["existing_google_calendar_connection"] = "existing_google_calendar_connection"

    @model_validator(mode="after")
    def validate_window(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Use a valid IANA calendar timezone.") from exc
        if not timedelta(0) < self.window_end - self.window_start <= timedelta(days=31):
            raise ValueError("Calendar window must be positive and at most 31 days.")
        if len({e.id for e in self.events}) != len(self.events):
            raise ValueError("Calendar event IDs must be unique.")
        return self


def marker(owner, ref, item):
    return "canvas-bridge:" + fingerprint([owner, ref, item.course_id, item.id])[:40]


def calendar_proposal(items, context, owner, ref, now):
    limitations = [
        "Calendar evidence was supplied through ChatGPT's existing connection; this server has no Google credentials.",
        "A proposal is not an executed action. Ask for explicit confirmation of the concrete events before calling Google Calendar write tools.",
        "After approval, reread Canvas and Calendar versions, apply only the confirmed proposal, and read back the resulting events.",
        "After an uncertain create result, search the exact mapping marker before retrying. Never blindly retry.",
    ]
    freshness = now - context.retrieved_at
    if (
        freshness > timedelta(minutes=5)
        or freshness < -timedelta(seconds=30)
        or not context.pagination_complete
        or not context.mapping_search_complete
    ):
        return {
            "status": "needs_input",
            "proposals": [],
            "reason": "Fresh complete event listing and marker/source searches are required. Changed events may lie outside the current date window.",
            "limitations": limitations,
        }
    proposals, mappings, uncertain, ignored = [], [], [], []
    active = [e for e in context.events if e.status != "cancelled"]
    for item in sorted(items, key=lambda i: i.id):
        if not is_actionable(item):
            ignored.append({"work_id": item.id, "reason": "not_actionable"})
            continue
        due = item.effective_due
        if due.timestamp:
            if (
                not context.window_start <= due.timestamp < context.window_end
                or due.timestamp < now
            ):
                ignored.append({"work_id": item.id, "reason": "past_or_outside_requested_window"})
                continue
            event_date = due.timestamp.astimezone(ZoneInfo(context.timezone)).date()
            timing = {
                "start": due.timestamp.astimezone(ZoneInfo(context.timezone)).isoformat(),
                "end": (due.timestamp + timedelta(minutes=15))
                .astimezone(ZoneInfo(context.timezone))
                .isoformat(),
                "timezone": context.timezone,
                "duration_basis": "15-minute reminder, not an effort estimate",
            }
        elif due.local_date:
            event_date = due.local_date
            if (
                not context.window_start.astimezone(ZoneInfo(context.timezone)).date()
                <= event_date
                < context.window_end.astimezone(ZoneInfo(context.timezone)).date()
                or event_date < now.astimezone(ZoneInfo(context.timezone)).date()
            ):
                continue
            timing = {
                "start_date": event_date.isoformat(),
                "end_date": (event_date + timedelta(days=1)).isoformat(),
                "timezone": context.timezone,
            }
        else:
            ignored.append({"work_id": item.id, "reason": "date_unknown_no_event_invented"})
            continue
        tag = marker(owner, ref, item)
        matches = [
            e for e in active if e.bridge_marker == tag or e.canvas_source_url == item.source.url
        ]
        if len(matches) > 1:
            uncertain.append(
                {
                    "work_id": item.id,
                    "reason": "multiple_matching_events",
                    "event_ids": [e.id for e in matches],
                }
            )
            continue
        if not matches:
            possible = [
                e
                for e in active
                if item.title.casefold() in e.title.casefold()
                or e.title.casefold() in item.title.casefold()
            ]
            if possible:
                uncertain.append(
                    {
                        "work_id": item.id,
                        "reason": "possible_untagged_match; confirm before creating",
                        "event_ids": [e.id for e in possible],
                    }
                )
                continue
        candidate = {
            "work_id": item.id,
            "title": item.title + " — Canvas deadline",
            "calendar_id": context.calendar_id,
            "timing": timing,
            "source": item.source.model_dump(mode="json"),
            "description": tag + "\n" + item.source.url,
            "bridge_marker": tag,
            "requires_explicit_confirmation": True,
        }
        if matches:
            event = matches[0]
            mappings.append(
                {
                    "work_id": item.id,
                    "event_id": event.id,
                    "calendar_id": context.calendar_id,
                    "bridge_marker": tag,
                    "storage": "provider_event_description",
                    "evidence_origin": context.origin,
                }
            )
            equal = (
                event.start == due.timestamp if due.timestamp else event.all_day_date == event_date
            )
            if equal:
                continue
            if event.status == "unknown" or not event.version:
                uncertain.append(
                    {
                        "work_id": item.id,
                        "reason": "reread_existing_event_status_and_version_before_update",
                        "event_id": event.id,
                    }
                )
                continue
            candidate.update(
                action="update",
                event_id=event.id,
                expected_event_version=event.version,
                previous_timing={
                    "start": event.start.isoformat() if event.start else None,
                    "all_day_date": event.all_day_date.isoformat() if event.all_day_date else None,
                },
            )
        else:
            candidate["action"] = "create"
        candidate["proposal_id"] = fingerprint(candidate)
        proposals.append(candidate)
    return {
        "status": "proposal_only",
        "proposals": proposals,
        "mappings": mappings,
        "ambiguous_matches": uncertain,
        "ignored": ignored,
        "limitations": limitations,
        "deletions": [],
        "provider_writes_executed": False,
        "mapping_retention": "Stored only in confirmed Google event descriptions; remove that marker or event to remove the provider mapping. No Calendar data is persisted by Canvas Bridge.",
    }


async def propose_sync(bridge, owner, ref, snapshot_id, context, study_request=None):
    await bridge.list_courses(owner, ref)
    conn, courses = bridge.selected(owner, ref)
    with bridge.store.transaction() as session:
        snapshot = bridge.store.owned(session, Snapshot, owner, ref, snapshot_id)
    if set(snapshot.course_ids) - {c.id for c in courses}:
        raise DomainError(
            "permission_denied", "Snapshot contains courses outside the current selection."
        )
    if not snapshot.complete or utcnow() - aware(snapshot.created_at) > timedelta(minutes=5):
        raise DomainError(
            "needs_input",
            "Refresh a complete workload snapshot before proposing calendar synchronization.",
        )
    items = [WorkItem.model_validate(i) for i in snapshot.items]
    result = calendar_proposal(items, context, owner, ref, utcnow())
    if study_request:
        if not context.availability_complete or result["status"] == "needs_input":
            result["study_plan"] = {
                "status": "needs_input",
                "reason": "Fresh complete Calendar availability is required.",
            }
        else:
            if any(
                w.start < context.window_start or w.end > context.window_end
                for w in study_request.windows
            ):
                raise DomainError(
                    "needs_input", "Study windows exceed the verified Calendar window."
                )
            request = study_request.model_copy(
                update={
                    "busy_times": [*study_request.busy_times, *context.busy_times],
                    "availability_origin": "provided_via_conversation",
                }
            )
            result["study_plan"] = propose(items, request, utcnow())
    current, _ = bridge.selected(owner, ref, snapshot.course_ids)
    if current.epoch != conn.epoch:
        raise DomainError("source_changed", "Connection scope changed during Calendar planning.")
    return Result(
        status="needs_input" if result["status"] == "needs_input" else "ok",
        summary="Calendar proposals only. Confirm specific events in ChatGPT before its Google Calendar connection makes any changes.",
        data=result,
        sources=[i.source for i in items],
        meta=bridge.meta(snapshot_id=snapshot.id),
    )
