"""Planning bounds are calculations, never replacements for source dates."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from canvas_bridge.domain import WorkItem


def instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Planning times must include an explicit UTC offset.")
    result = value.astimezone(UTC)
    if result.astimezone(value.tzinfo).replace(tzinfo=None) != value.replace(tzinfo=None):
        raise ValueError("A planning time does not exist in its supplied timezone.")
    return result


def day_boundary(day, zone):
    wall = datetime.combine(day, time.min)
    choices = []
    for fold in (0, 1):
        candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == wall:
            choices.append(candidate)
    if not choices:
        raise ValueError("The local date boundary cannot be established.")
    # At a repeated midnight, finish before the earliest possible start of day.
    return min(choices)


@dataclass
class Timing:
    opens: datetime | None = None
    deadline: datetime | None = None
    overdue: bool = False
    blocked: str | None = None
    assumptions: list[str] = field(default_factory=list)
    timezone: str | None = None

    def evidence(self, item):
        return {
            "classification": "deterministic_calculation",
            "source_id": item.source.id,
            "source_due": item.effective_due.model_dump(mode="json"),
            "source_opens": item.available_from.model_dump(mode="json"),
            "source_closes": item.closes_at.model_dump(mode="json"),
            "planning_not_before": self.opens.isoformat() if self.opens else None,
            "planning_finish_by": self.deadline.isoformat() if self.deadline else None,
            "blocked_reason": self.blocked,
            "overdue_recovery": self.overdue,
            "date_only_timezone": self.timezone,
            "timezone_basis": "student_or_conversation_input" if self.timezone else None,
            "assumptions": self.assumptions,
        }


def resolve_timing(item: WorkItem, now: datetime, timezone: str | None = None) -> Timing:
    result = Timing()
    facts = (item.effective_due, item.available_from, item.closes_at)
    date_only = any(f.local_date for f in facts)
    if date_only and timezone is None:
        result.blocked = "date_only_timezone_required"
        result.assumptions.append(
            "A source date has no time or timezone. Supply its applicable IANA timezone; the display timezone is not assumed to be the course timezone."
        )
        return result
    zone = ZoneInfo(timezone) if timezone and date_only else None
    result.timezone = timezone if date_only else None
    values = []
    try:
        for index, fact in enumerate(facts):
            value = instant(fact.timestamp) if fact.timestamp else None
            if fact.local_date:
                # Allow work only after an entire opening day, but finish before
                # a due/closing day starts. No invented source clock time.
                day = fact.local_date + timedelta(days=1 if index == 1 else 0)
                value = day_boundary(day, zone)
                result.assumptions.append(
                    "Date-only opening: conservatively wait until after that local calendar day; this is not a reported unlock time."
                    if index == 1
                    else "Date-only due/close: conservatively finish before that local calendar day starts; this is not a reported deadline time."
                )
            values.append(value)
    except (ValueError, OverflowError):
        result.blocked = "source_date_boundary_unresolved"
        return result
    due, result.opens, close = values
    now = instant(now)
    if close and close <= now:
        result.blocked = "source_closing_bound_passed"
    if item.effective_due.local_date and due <= now:
        result.blocked = result.blocked or "date_only_deadline_needs_clarification"
        result.assumptions.append(
            "The date-only planning cutoff has passed. Confirm the actual due time or a supported recovery deadline before scheduling work."
        )
    result.overdue = bool(item.effective_due.timestamp and due < now)
    if result.overdue:
        due = None  # Existing overdue recovery is bounded by the close, not an invented extension.
    result.deadline = min(t for t in (due, close) if t) if due or close else None
    if result.opens and result.deadline and result.opens >= result.deadline:
        result.blocked = result.blocked or "source_timing_bounds_conflict"
    return result
