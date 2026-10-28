"""Transactional deletion hooks; no access grant or source content in receipts."""

from pydantic import ValidationError
from sqlalchemy import select

from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import ProcessState
from canvas_bridge.processes.state import KIND, descendants, indexed
from canvas_bridge.storage import IndependentResource


def purge_sources(session, owner, *, source_ids=(), connection=None, course_ids=None):
    """Caller owns its ordinary deletion transaction and lock order."""
    ids = set(source_ids)

    def matches(tag):
        return tag.id in ids or (
            connection
            and tag.connection == connection
            and (course_ids is None or tag.scope.course in course_ids)
        )

    rows = list(
        session.scalars(
            select(IndependentResource).where(
                IndependentResource.owner == owner,
                IndependentResource.kind.in_({KIND, "academic_process_preview"}),
            )
        )
    )
    removed = 0
    for row in rows:
        try:
            if fingerprint(row.content) != row.version_hash:
                raise ValueError("Invalid state hash")
            if row.kind == "academic_process_preview":
                from canvas_bridge.processes.models import ChangePreview

                change = ChangePreview.model_validate(row.content["change"])
                if any(
                    image and any(matches(s) for s in image.sources)
                    for image in (change.before, change.after)
                ):
                    session.delete(row)
                    removed += 1
                continue
            state = ProcessState.model_validate(row.content)
        except (ValidationError, ValueError, KeyError, TypeError):
            # Corruption cannot block a deletion or preserve an unverifiable copy.
            session.delete(row)
            removed += 1
            continue
        direct = {r.id for r in state.records.values() if any(matches(s) for s in r.sources)}
        affected = direct | {child for ident in direct for child in descendants(state, ident)}
        history = tuple(
            r
            for r in state.revisions
            if not any(
                image and (image.id in affected or any(matches(s) for s in image.sources))
                for image in (r.before, r.after)
            )
        )
        if affected or history != state.revisions:
            updated = indexed(
                {k: v for k, v in state.records.items() if k not in affected},
                version=state.version + 1,
                revisions=history,
                receipts=state.receipts,
            )
            row.content = updated.model_dump(mode="json")
            row.version_hash = fingerprint(row.content)
            removed += len(affected)
    return removed
