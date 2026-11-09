"""Current independent work keys, reviewed aliases and explicitly declared historical states."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.analytics.observations import Declaration, Due, History, Outcome, Ref
from canvas_bridge.domain import FactDate, Model


class DeclaredRevision(Model):
    work_key: Ref
    version: int = Field(ge=1)
    recorded_at: AwareDatetime
    effective_at: AwareDatetime | None = None
    due: FactDate | None = None
    progress: Literal["student_marked_done", "not_started", "in_progress", "unknown"] | None = None
    timeliness: Literal["on_time", "late", "missing", "unknown", "not_applicable"] | None = None

    @model_validator(mode="after")
    def single_field(self):
        if sum(v is not None for v in (self.due, self.progress, self.timeliness)) != 1:
            raise ValueError("Specify one academic field per dated declaration.")
        return self


def independent_review(dataset, source, request, owner, now):
    from canvas_bridge.academic.study_steps import step_parents
    from canvas_bridge.analytics.report import build
    from canvas_bridge.domain import DomainError

    if request.course_ids != [source.id] or request.restates or request.evidence_cutoff > now:
        raise DomainError(
            "needs_input",
            "Select the current owned dataset ID as the course scope and use a past or current cutoff.",
        )
    captured = source.retrieved_at
    h = History()
    aliases = {alias: w.key for w in dataset.work for alias in [w.key, *w.aliases]}
    children = step_parents(dataset)
    base = {"course_ids": [source.id], "observed_at": captured, "basis": "student_declaration"}
    historical = set()
    work = {w.key: w for w in dataset.work}
    for r in dataset.declarations:
        key = aliases[r.work_key]
        if key in children:
            continue
        stamp = base | {
            "key": key,
            "version": r.version,
            "observed_at": max(captured, r.recorded_at),
            "source_recorded_at": r.recorded_at,
            "effective_at": r.effective_at,
            "event_time_known": r.effective_at is not None,
            "source_ref": source.content_hash + "/" + key,
        }
        if r.due:
            h.dues.append(Due(**stamp, due=r.due))
            historical.add((key, "due"))
        elif r.progress:
            h.progress.append(
                Declaration(
                    **stamp,
                    status=r.progress,
                    revision_state="requested" if work[key].revision_requested else "unknown",
                )
            )
            historical.add((key, "progress"))
        else:
            h.outcomes.append(Outcome(**stamp, state=r.timeliness))
    for w in dataset.work:
        # The inventory records one parent even when steps or aliases have been imported.
        stamp = base | {"key": w.key, "source_ref": source.content_hash + "/" + w.key}
        exclusion = (
            "child_step"
            if w.key in children
            else "requirement_unresolved"
            if w.requirement == "unresolved"
            else "optional"
            if w.requirement == "optional"
            else "excused"
            if w.reported_status == "excused"
            else None
        )
        if (w.key, "due") not in historical:
            h.dues.append(Due(**stamp, due=w.due, exclusion=exclusion))
        else:
            for due in h.dues:
                if due.key == w.key:
                    due.exclusion = exclusion
        if (w.key, "progress") not in historical:
            h.progress.append(
                Declaration(
                    **stamp,
                    status=w.progress,
                    revision_state="requested" if w.revision_requested else "unknown",
                )
            )
    # The current document can assert individual earlier effective states. Its current
    # inventory completeness cannot be backdated before acquisition.
    covered = captured <= request.as_of and captured <= request.evidence_cutoff
    h.coverage.append(
        {
            "course_id": source.id,
            "snapshot_id": source.content_hash,
            "state": "complete"
            if covered and dataset.complete
            else "partial"
            if h.dues and captured <= request.evidence_cutoff
            else "unavailable",
            "captured_at": captured.isoformat(),
            "retrieved": len({v.key for v in h.dues if v.eligible(request)}),
        }
    )
    data, _ = build(
        h, request, scope_binding=[owner, source.id, source.content_hash], synthetic=False, now=now
    )
    data["source_selection"] = "owned_dataset_student_declarations"
    return data, any(
        f["availability"] != "available" for p in data["periods"] for f in p["families"]
    )
