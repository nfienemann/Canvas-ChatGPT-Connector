"""Validate model-interpreted table rows against an authorized rendered page version."""

from datetime import date as CalendarDate
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.calendar_sync import calendar_proposal
from canvas_bridge.course_files import authorized, checked_row, source
from canvas_bridge.domain import DomainError, FactDate, Model, Result, WorkItem, utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.file_download import file_version


class ScheduleRow(Model):
    row_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=300)
    date: CalendarDate | None = None
    date_basis: Literal["explicit", "assumed", "ambiguous", "tbd"]
    original_date: str = Field(max_length=150)
    time_text: str | None = Field(default=None, max_length=150)
    kind: Literal["reading", "presentation", "exam", "quiz", "no_class", "deadline", "other"]
    passage: str = Field(min_length=1, max_length=2000)
    bbox: list[Annotated[float, Field(ge=0, le=1)]] = Field(min_length=4, max_length=4)
    paper: str | None = Field(default=None, max_length=150)
    motivation_methods: str | None = Field(default=None, max_length=200)
    results_impact: str | None = Field(default=None, max_length=200)
    qa_leaders: str | None = Field(default=None, max_length=300)
    color_description: str | None = Field(default=None, max_length=200)
    uncertainties: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=10
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.bbox[0] >= self.bbox[2] or self.bbox[1] >= self.bbox[3]:
            raise ValueError("Use normalized left, top, right, bottom image coordinates.")
        if self.date_basis == "tbd" and self.date is not None:
            raise ValueError("TBD cannot have a fabricated date.")
        if self.date_basis == "explicit" and self.date is None:
            raise ValueError("Explicit dates need a full date visibly supported by the source.")
        return self


async def interpret_schedule(bridge, owner, ref, receipt, rows, calendar=None):
    try:
        proof = bridge.vault.open(receipt, owner, ref)
        if proof["purpose"] != "visual_page" or datetime.fromisoformat(proof["expires"]) < utcnow():
            raise ValueError("Expired")
    except Exception as exc:
        raise DomainError(
            "needs_input",
            "Render the authorized PDF page again; the review receipt is invalid or expired.",
        ) from exc
    if not 1 <= len(rows) <= 50 or len({r.row_key for r in rows}) != len(rows):
        raise DomainError(
            "needs_input", "Provide 1â€“50 uniquely keyed schedule entries from one rendered page."
        )
    row, course, metadata, epoch = await authorized(bridge, owner, ref, proof["file_id"])
    if proof["epoch"] != epoch or proof["version"] != file_version(metadata):
        raise DomainError(
            "source_changed",
            "This page interpretation is superseded by a source or scope change. Render and review again.",
        )
    entries, items, sources = [], [], []
    seen = set()
    for entry in rows:
        key = fingerprint([entry.title.casefold(), entry.date, entry.original_date, entry.kind])
        if key in seen:
            raise DomainError(
                "needs_input",
                "Duplicate interpreted entries require review before calendar proposals.",
            )
        seen.add(key)
        citation = source(
            row, f"PDF page {proof['page']}, row {entry.row_key}, image region {entry.bbox}"
        ).model_copy(
            update={
                "content_hash": proof["hash"],
                "retrieved_at": datetime.fromisoformat(proof["retrieved_at"]),
                "classification": "assistant_inference",
                "extraction_status": "visual_interpretation_unverified",
                "uncertainty": entry.uncertainties,
                "url": row.url + f"#page={proof['page']}&schedule_entry={entry.row_key}",
            }
        )
        record = {
            **entry.model_dump(mode="json"),
            "source": citation.model_dump(mode="json"),
            "source_version": proof["version"],
            "extraction_method": "assistant_visual_interpretation",
            "verified": False,
            "page": proof["page"],
            "image_hash": proof["image_hash"],
            "rotation": proof["rotation"],
            "student_confirmation_needed": True,
        }
        entries.append(record)
        sources.append(citation)
        # Explicit date-only proposals: preserve any printed clock as evidence,
        # never invent its timezone or duration. An unresolved time blocks a proposal.
        if entry.date_basis != "explicit" or entry.uncertainties or entry.time_text:
            continue
        items.append(
            WorkItem(
                id=row.id + ":" + entry.row_key,
                connection_id=ref,
                institution_id="source_course",
                course_id=course.id,
                source_id=row.source_id,
                title=entry.title,
                kind="schedule_entry",
                effective_due=FactDate(
                    kind="local_date", local_date=entry.date, raw=entry.original_date
                ),
                source=citation,
            )
        )
    proposal = calendar_proposal(items, calendar, owner, ref, utcnow()) if calendar else None
    if proposal:
        for candidate in proposal["proposals"]:
            candidate["title"] = (
                candidate["title"].removesuffix(" â€” Canvas deadline") + " â€” Course schedule"
            )
            candidate["source_version"] = proof["version"]
            candidate["interpretation_status"] = "unverified_visual_interpretation"
            candidate["proposal_id"] = fingerprint(
                {k: v for k, v in candidate.items() if k != "proposal_id"}
            )
    with bridge.store.transaction() as session:
        checked_row(bridge, session, owner, ref, row.id, epoch)
    return Result(
        status="partial_data",
        summary="Structured visual interpretations with citations; source meaning has not been independently verified. No calendar changes were made.",
        data={
            "entries": entries,
            "calendar": proposal,
            "coverage": "only the submitted rows on one page",
            "limitations": [
                "The receipt proves which authorized image was rendered, not the correctness of an interpretation.",
                "Do not infer year, timezone, color meaning or merged-cell inheritance without visible evidence.",
                "Reuse stable row keys for the same obligations across versions. A replacement file is not automatically a superseding policy.",
                "TBD, assumptions, uncertain entries and unresolved times are excluded from calendar proposals.",
            ],
        },
        sources=sources,
        meta=bridge.meta(),
    )
