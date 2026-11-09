"""Use the academic process repository for explicitly reviewed local state."""

from datetime import timedelta

from canvas_bridge.domain import DomainError, Source, opaque_id
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import AcademicRecord, AcademicScope, SourceTag
from canvas_bridge.processes.state import preview
from canvas_bridge.storage import PrincipalState, aware


def declaration(owner, generation, course, now):
    return SourceTag(
        id=fingerprint(["local-declaration", owner]),
        version=str(generation),
        origin="user_declaration",
        scope=AcademicScope(
            principal=owner, institution="independent", term="unspecified", course=course
        ),
        locator="Explicit authenticated local review",
        observed_at=now,
        expires_at=now + timedelta(days=30),
    )


def authorize_declaration(session, owner, tag):
    principal = session.get(PrincipalState, owner)
    if (
        tag.id != fingerprint(["local-declaration", owner])
        or not principal
        or tag.version != str(principal.generation)
        or tag.scope.principal != owner
        or tag.scope.institution != "independent"
    ):
        raise DomainError("permission_denied", "Local study evidence is unavailable.")


class Records:
    def __init__(self, bridge):
        self.bridge = bridge
        self.repo = bridge.processes.repository

    def state(self, owner):
        with self.bridge.store.transaction() as session:
            return self.repo._load(session, owner)[1]

    def rows(self, owner, course=None, subtype=None, *, include_unavailable=False):
        state = self.state(owner)
        rows = []
        for record in state.records.values():
            if record.data.get("schema") != "usefulness-1":
                continue
            if course is not None and record.scope.course != course:
                continue
            if subtype is not None and record.data.get("subtype") != subtype:
                continue
            try:
                self.repo.read(owner, record.id)
            except DomainError:
                if not include_unavailable:
                    continue
            rows.append(record)
        return rows

    def save(
        self,
        owner,
        course,
        subtype,
        value,
        *,
        record_id=None,
        expected_revision=0,
        idempotency_key,
        share=False,
        sources=(),
        depends_on=(),
        validate_session=lambda: None,
        publish=lambda session, record: None,
        identity_hint=None,
    ):
        """Only called by CSRF-protected browser actions, never model confirmations."""
        now = self.bridge.retention.clock()
        key = fingerprint([owner, "usefulness", idempotency_key])

        def retry_value(value):
            if isinstance(value, dict):
                return {k: retry_value(v) for k, v in value.items() if k != "as_of"}
            if isinstance(value, list):
                return [retry_value(v) for v in value]
            return value

        request_hash = fingerprint(
            [
                course,
                subtype,
                retry_value(value),
                identity_hint or record_id,
                expected_revision,
                share,
                [s.model_dump(mode="json") for s in sources],
                depends_on,
            ]
        )
        generation = validate_session()
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            if generation is not None and generation != principal.generation:
                raise DomainError(
                    "permission_denied", "The settings session changed before saving."
                )
            _, state = self.repo._load(session, owner)
            prior = state.receipts.get(key)
            if prior:
                if prior.get("request_hash") != request_hash:
                    raise DomainError(
                        "source_changed", "This retry key already identifies another change."
                    )
                return prior
            existing = state.records.get(record_id) if record_id else None
            if (
                subtype == "collection"
                and record_id is None
                and any(
                    r.scope.course == course
                    and r.data.get("schema") == "usefulness-1"
                    and r.data.get("subtype") == "collection"
                    for r in state.records.values()
                )
            ):
                raise DomainError(
                    "source_changed", "Refresh the current collection preference before saving."
                )
            if (existing.revision if existing else 0) != expected_revision or (
                record_id and not existing
            ):
                raise DomainError("source_changed", "Refresh the review before saving.")
            if existing and (
                existing.scope.course != course or existing.data.get("subtype") != subtype
            ):
                raise DomainError(
                    "permission_denied", "This record is unavailable for this action."
                )
            tag = declaration(owner, principal.generation, course, now)
            profile = self.bridge.independent.profile()
            after = AcademicRecord(
                id=record_id or opaque_id(),
                kind="annotation",
                scope=tag.scope,
                revision=expected_revision + 1,
                data={
                    "schema": "usefulness-1",
                    "subtype": subtype,
                    "value": value,
                    "share": bool(share),
                    "recipient_policy": profile.model_dump(mode="json")
                    if share and profile
                    else None,
                },
                sources=tuple(sources) or (tag,),
                depends_on=tuple(depends_on),
                updated_at=now,
            )
            self.repo._require(session, owner, after, "write")
            for parent in after.depends_on:
                dependency = state.records.get(parent)
                if not dependency:
                    raise DomainError(
                        "source_changed", "A selected dependency changed before saving."
                    )
                self.repo._require(session, owner, dependency)
            change = preview(
                state, owner, after.id, after, "correction" if existing else "create", now=now
            )
            from canvas_bridge.processes.models import ProcessState
            from canvas_bridge.processes.state import apply

            updated = apply(state, change, now=now)
            receipt = {
                "request_hash": request_hash,
                "record_id": after.id,
                "revision": after.revision,
                "revision_id": change.id,
                "version": updated.version,
                "external_writes": False,
            }
            receipts = dict(list((state.receipts | {key: receipt}).items())[-500:])
            updated = ProcessState.model_validate(updated.model_dump() | {"receipts": receipts})
            publish(session, after)
            row, _ = self.repo._load(session, owner)
            self.repo._save(session, owner, row, updated)
            return receipt

    def delete(self, owner, ident, revision, *, validate_session=lambda: None):
        generation = validate_session()
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            if generation is not None and generation != principal.generation:
                raise DomainError(
                    "permission_denied", "The settings session changed before deletion."
                )
            row, state = self.repo._load(session, owner)
            record = state.records.get(ident)
            if (
                not record
                or record.data.get("schema") != "usefulness-1"
                or record.revision != revision
            ):
                raise DomainError("source_changed", "Refresh the record before deleting it.")
            change = preview(state, owner, ident, None, "delete", now=self.bridge.retention.clock())
            from canvas_bridge.processes.state import apply

            self.repo._save(
                session, owner, row, apply(state, change, now=self.bridge.retention.clock())
            )
        return {"deleted": True, "external_writes": False}

    def document_tag(self, owner, row):
        return SourceTag(
            id=row.id,
            version=row.version_hash,
            origin="local_document",
            scope=AcademicScope(
                principal=owner,
                institution="independent",
                term=row.content.get("packet", {}).get("term", "unspecified"),
                course=row.content.get("course", "independent"),
            ),
            locator="Reviewed imported evidence",
            observed_at=aware(row.created_at),
            expires_at=aware(row.expires_at),
        )

    def citation(self, record):
        return Source(
            id=record.id,
            resource_id=record.id,
            url="",
            title="Selected local study record",
            retrieved_at=record.updated_at,
            content_hash=fingerprint(record.model_dump(mode="json")),
            source_type="local_study_record",
            course_id=record.scope.course,
            classification="student_input",
            locator=f"Revision {record.revision}",
        )
