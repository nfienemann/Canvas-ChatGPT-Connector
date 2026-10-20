import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from canvas_bridge.domain import FactDate, Source, WorkItem, utcnow
from canvas_bridge.policy import source_id


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object"}:
            self.hidden += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(html: str, limit: int = 50_000) -> str:
    parser = PlainText()
    parser.feed(html[: limit * 4])
    return "".join(parser.parts).strip()[:limit]


def fact_date(payload: dict, field: str) -> FactDate:
    if field not in payload:
        return FactDate(kind="not_returned")
    raw = payload[field]
    if raw is None:
        return FactDate(kind="known_none")
    if not isinstance(raw, str):
        return FactDate(kind="not_returned")
    try:
        if len(raw) == 10:
            from datetime import date

            return FactDate(kind="local_date", local_date=date.fromisoformat(raw), raw=raw)
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return FactDate(kind="not_returned", raw=raw)
        return FactDate(kind="timestamp", timestamp=instant.astimezone(UTC), raw=raw)
    except ValueError:
        return FactDate(kind="not_returned", raw=raw[:100])


def canonical_id(owner: str, connection: str, kind: str, upstream: str) -> str:
    return hashlib.sha256(f"{owner}\0{connection}\0{kind}\0{upstream}".encode()).hexdigest()[:40]


def assignment_requirements(raw: dict) -> dict:
    """Describe the fetched assignment-description field, not all course requirements."""
    html = raw.get("description")
    text, truncated = "", False
    if "description" not in raw:
        state = "not_returned"
    elif html is None or isinstance(html, str) and not html.strip():
        state = "empty_in_canvas"
    elif not isinstance(html, str):
        state = "invalid"
    else:
        text = plain_text(html, 50_001)
        truncated = len(text) > 50_000 or len(html) > 200_004
        text = text[:50_000]
        state = "truncated" if truncated else "present" if text else "no_extractable_text"
    return {
        "text": text,
        "state": state,
        "retrieval": "succeeded",
        "field_returned": "description" in raw,
        "truncated": truncated,
        "scope": "canvas_assignment_description_only",
        "limitations": [
            "An empty assignment description does not mean there are no requirements.",
            "Quiz questions, external tools, linked files and other course instructions were not retrieved by this endpoint.",
        ],
    }


def normalize_assignment(
    raw: dict,
    *,
    owner: str,
    connection: str,
    institution: str,
    course: str,
    canvas_course: str,
    canvas_user: str,
    origin: str,
    now: datetime | None = None,
) -> WorkItem:
    now = now or utcnow()
    upstream = source_id(raw["id"])
    ref = canonical_id(owner, connection, "assignment", f"{canvas_course}:{upstream}")
    supplied = raw.get("submission")
    evidence = "not_returned" if supplied is None else "returned"
    sub = supplied if isinstance(supplied, dict) else {}
    if supplied is not None and not isinstance(supplied, dict):
        evidence = "invalid"
    elif sub and str(sub.get("user_id", "")) != canvas_user:
        evidence = "identity_mismatch"
        sub = {}
    elif not sub:
        evidence = "not_returned"
    types = raw.get("submission_types", [])
    if not isinstance(types, list) or any(not isinstance(t, str) for t in types):
        types = []
    submission, assessment, timeliness = "unknown", "unknown", "unknown"
    basis = "No verified current-user submission evidence; absence does not mean not submitted."
    state = sub.get("workflow_state")
    submitted_at = fact_date(sub, "submitted_at").timestamp
    if types and set(types) <= {"on_paper", "none", "not_graded"}:
        submission = "not_applicable"
        evidence = "not_applicable"
        basis = "This assignment does not require an online Canvas submission; completion is not established."
    elif state in {"submitted", "pending_review", "graded"} and submitted_at:
        attempt = sub.get("attempt")
        submission = "resubmitted" if type(attempt) is int and attempt > 1 else "submitted"
        basis = "Verified own Canvas submission workflow and submission timestamp."
    elif state == "unsubmitted":
        if sub.get("submitted_at"):
            evidence = "conflicting"
            basis = "Canvas returned unsubmitted workflow with a submission timestamp; status is unresolved."
        else:
            submission = "not_submitted"
            basis = "Canvas explicitly reports unsubmitted for this student's online record; offline completion is unknown."
    elif sub:
        basis = "Canvas returned own submission data, but it does not establish whether work was submitted."
    if sub.get("excused") is True:
        assessment = "excused"
    elif state == "graded" and sub.get("posted_at"):
        assessment = "graded"
    elif state in {"submitted", "pending_review", "graded"}:
        assessment = "pending"
    if sub.get("missing") is True:
        timeliness = "missing"
    elif sub.get("late") is True:
        timeliness = "late"
    elif sub.get("late") is False and submitted_at and evidence != "conflicting":
        timeliness = "on_time"
    due, opens, closes = (fact_date(raw, field) for field in ("due_at", "unlock_at", "lock_at"))
    availability = "unknown"
    if closes.timestamp and closes.timestamp <= now:
        availability = "closed"
    elif opens.timestamp and opens.timestamp > now:
        availability = "future_locked"
    elif raw.get("locked_for_user") is True or raw.get("published") is False:
        availability = "inaccessible"
    elif raw.get("locked_for_user") is False:
        availability = "available"
    kind = "assignment"
    if raw.get("discussion_topic", {}).get("id"):
        kind = "discussion"
    elif raw.get("quiz_id"):
        kind = "quiz"
    elif "external_tool" in types:
        kind = "external_tool"
    points = None
    try:
        if raw.get("points_possible") is not None:
            points = Decimal(str(raw["points_possible"]))
            if not points.is_finite() or points < 0:
                points = None
    except InvalidOperation:
        pass
    title = plain_text(str(raw.get("name") or "Untitled assignment"), 1000)
    updated = fact_date(raw, "updated_at").timestamp
    return WorkItem(
        id=ref,
        connection_id=connection,
        institution_id=institution,
        course_id=course,
        source_id=upstream,
        title=title,
        kind=kind,
        effective_due=due,
        available_from=opens,
        closes_at=closes,
        submission_state=submission,
        submission_evidence=evidence,
        submission_state_basis=basis,
        assessment_state=assessment,
        timeliness_state=timeliness,
        availability_state=availability,
        points_possible=points,
        submission_requirement=", ".join(types)[:500] if types else "unknown",
        source=Source(
            id=ref,
            url=f"{origin}/courses/{source_id(canvas_course)}/assignments/{upstream}",
            title=title,
            retrieved_at=now,
            source_updated_at=updated,
        ),
    )
