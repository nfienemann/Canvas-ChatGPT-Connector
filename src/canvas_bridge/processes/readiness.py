"""Version-bound assignment readiness stored in the existing scoped process journal."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.domain import Effort
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import Model, Ref
from canvas_bridge.processes.state import failure

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=1200)]
Key = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


class Binding(Model):
    logical_id: Key
    role: Literal["brief", "artifact", "reference", "measurement", "other"]
    document_id: Ref | None = None
    content_hash: Digest | None = None

    @model_validator(mode="after")
    def verified_pair(self):
        if bool(self.document_id) != bool(self.content_hash):
            raise ValueError(
                "Supply the imported document and hash together, or leave both absent."
            )
        return self


def record_key(scope, assignment):
    return fingerprint(["assignment_readiness", scope.model_dump(mode="json"), assignment])


def bind(entries, bindings):
    tags = [e["tag"] for e in entries.values()]
    if any(t.scope != tags[0].scope or t.origin != "local_document" for t in tags):
        failure("PROCESS_SCOPE_MISMATCH")
    by_key = {b.logical_id: b for b in bindings}
    if len(by_key) != len(bindings) or {b.document_id for b in bindings if b.document_id} != set(
        entries
    ):
        failure("READINESS_SELECTION_INVALID", "Bind each selected import to its logical source.")
    for b in bindings:
        if b.document_id and b.content_hash != entries[b.document_id]["tag"].version:
            failure(
                "READINESS_VERSION_MISMATCH",
                "Read the current document status and review that version.",
            )
    return by_key


def snapshot(repository, owner, record_id, revision=None):
    """Select one immutable image; the caller authorizes each returned field before release."""
    with repository.store.transaction() as session:
        _, state = repository._load(session, owner)
        record = state.records.get(record_id)
        if record and record.state != "valid":
            failure("PROCESS_RECORD_NOT_VALID")
        if record and revision is not None and record.revision != revision:
            record = next(
                (
                    image
                    for change in reversed(state.revisions)
                    for image in (change.after, change.before)
                    if image and image.id == record_id and image.revision == revision
                ),
                None,
            )
        if (
            not record
            or record.scope.principal != owner
            or record.state != "valid"
            or record.data.get("payload_type") != "assignment_readiness"
        ):
            failure("PROCESS_RECORD_UNAVAILABLE")
        # Older records could approve empty quotes or prove a bounded claim
        # against just one of several artifacts. Re-evaluate their usability
        # on read without rewriting the immutable assessment.
        artifact_count = sum(b["role"] == "artifact" for b in record.data["bindings"])
        rows = [validated_snapshot_row(r, artifact_count) for r in record.data["requirements"]]
        return record.model_copy(update={"data": record.data | {"requirements": rows}})


def validated_snapshot_row(row, artifact_count):
    anchors = [
        row["governing"],
        *row["evidence"],
        *(a for c in row.get("candidate_assessments", []) for a in c["evidence"]),
    ]
    unsupported = any(not a["quote"].strip() for a in anchors) or (
        artifact_count > 1
        and row["coverage_rule"] in {"absence", "all_claims"}
        and not row.get("all_artifact_extents_verified")
    )
    if not unsupported:
        return row
    projected = row | dict(
        assessment_status="unknown", coverage="partial", followup="review_artifact"
    )
    if (projected.get("work_item") or {}).get("work_basis") != "explicit_user_request":
        projected.pop("work_item", None)
    return projected


class Anchor(Model):
    source: Key
    part: int = Field(ge=1, le=200)
    surface: Literal["text", "slide", "notes"] = "text"
    quote: Text


class Extent(Model):
    source: Key
    parts: tuple[Annotated[int, Field(ge=1, le=200)], ...] = Field(min_length=1, max_length=200)


class Candidate(Model):
    candidate_id: Key
    assessment_status: Literal["satisfied", "needs_work", "unknown"]
    claim: Text
    evidence: tuple[Anchor, ...] = Field(min_length=1, max_length=16)


class Criterion(Model):
    requirement_id: Key
    criterion: Text
    governing: Anchor
    required: bool = True
    applicability: Literal["applicable", "not_applicable", "unknown"] = "applicable"
    applicability_basis_kind: Literal[
        "governing_source", "host_interpretation", "user_declaration"
    ] = "governing_source"
    applicability_basis: Text
    assessment_status: Literal["satisfied", "needs_work", "unknown", "conflict"] = "unknown"
    rationale: Text
    evidence: tuple[Anchor, ...] = Field(default=(), max_length=16)
    coverage_rule: Literal["passage", "absence", "all_claims", "recorded_run"] = "passage"
    reviewed_extent: tuple[Extent, ...] = Field(default=(), max_length=6)
    coverage: Literal["complete", "partial", "unavailable"] = "unavailable"
    followup: Key | None = None
    gap_kind: Key | None = None
    action: Text | None = None
    completion_condition: Text | None = None
    measured_artifact_hash: Digest | None = None
    candidate_assessments: tuple[Candidate, ...] = Field(default=(), max_length=6)


class Review(Model):
    assignment_id: Key
    course: Key
    term: Key
    expected_revision: int = Field(ge=0)
    idempotency_key: Ref
    membership_complete: bool
    review_scope: Text
    bindings: tuple[Binding, ...] = Field(min_length=1, max_length=6)
    requested_work: tuple[Key, ...] = Field(
        default=(),
        max_length=40,
        description="Requirement IDs the user explicitly asked to turn into optional or review tasks.",
    )
    requirements: tuple[Criterion, ...] = Field(max_length=40)


def check_anchor(anchor, bindings, entries):
    binding = bindings.get(anchor.source)
    if not binding or not binding.document_id:
        failure("READINESS_SOURCE_UNAVAILABLE")
    pages = entries[binding.document_id]["pages"]
    if anchor.part > len(pages):
        failure(
            "READINESS_LOCATOR_INVALID", "Choose a returned part number in the selected source."
        )
    page = pages[anchor.part - 1]
    text = page.get("text", "")
    spans = [text]
    if anchor.surface != "text":
        kind = {"notes": "speaker_notes", "slide": "slide_shapes_and_tables"}[anchor.surface]
        spans = [
            text[s["start"] : s["end"]]
            for s in page.get("text_spans", [])
            if s["source_kind"] == kind
        ]
    quote = " ".join(anchor.quote.split())
    if not quote or not any(quote in " ".join(span.split()) for span in spans):
        failure(
            "READINESS_QUOTE_MISMATCH", "Read the indicated source part and use its exact passage."
        )


def assess(row, bindings, entries, *, equivalent_payloads=()):
    if row.governing.source not in bindings or bindings[row.governing.source].role != "brief":
        failure("READINESS_REQUIREMENT_SOURCE_REQUIRED")
    check_anchor(row.governing, bindings, entries)
    for anchor in row.evidence:
        check_anchor(anchor, bindings, entries)
    if row.assessment_status != "unknown" and (not row.evidence or row.coverage == "unavailable"):
        failure("READINESS_EVIDENCE_REQUIRED")
    candidates = row.candidate_assessments
    if row.assessment_status == "conflict":
        if (
            len({c.candidate_id for c in candidates}) != len(candidates)
            or len({c.assessment_status for c in candidates}) < 2
        ):
            failure(
                "READINESS_CONFLICT_EVIDENCE_REQUIRED",
                "Retain both conflicting interpretations and their source passages.",
            )
    elif candidates:
        failure("READINESS_CONFLICT_STATUS_REQUIRED")
    for candidate in candidates:
        for anchor in candidate.evidence:
            check_anchor(anchor, bindings, entries)
    if row.assessment_status == "needs_work" and not (
        row.gap_kind and row.action and row.completion_condition
    ):
        failure("READINESS_ACTION_REQUIRED")
    bounded = row.coverage_rule in ("absence", "all_claims")
    inspected = {}
    for extent in row.reviewed_extent:
        source = bindings.get(extent.source)
        if not source or not source.document_id:
            failure("READINESS_EXTENT_INVALID")
        entry = entries[source.document_id]
        if not set(extent.parts) <= entry["coverage"].seen:
            failure("READINESS_EXTENT_INVALID")
        inspected.setdefault(extent.source, set()).update(extent.parts)
    status = row.assessment_status
    reason = row.followup
    if bounded and (
        row.coverage != "complete"
        or not (artifacts := [b for b in bindings.values() if b.role == "artifact"])
        or not all(
            b.document_id
            and entries[b.document_id]["coverage"].complete
            and inspected.get(b.logical_id) == entries[b.document_id]["coverage"].seen
            for b in artifacts
        )
    ):
        status, reason = "unknown", reason or "review_artifact"
    version_match = "current"
    coverage = row.coverage
    if row.coverage_rule == "recorded_run" and (status != "unknown" or row.measured_artifact_hash):
        measurement = [a for a in row.evidence if bindings[a.source].role == "measurement"]
        if not row.measured_artifact_hash or not any(
            row.measured_artifact_hash in entries[bindings[a.source].document_id]["text"]
            for a in measurement
        ):
            failure("READINESS_MEASUREMENT_UNBOUND")
        if any(
            b.role == "artifact"
            and b.content_hash
            and b.content_hash != row.measured_artifact_hash
            and (row.measured_artifact_hash, b.content_hash) not in equivalent_payloads
            for b in bindings.values()
        ):
            status, reason = "unknown", "supporting_artifact_version_mismatch"
            version_match, coverage = "mismatch", "unavailable"
    return row.model_dump(mode="json") | {
        "assessment_status": status,
        "coverage": coverage,
        "version_match": version_match,
        "followup": reason,
        "basis": "host_interpretation",
        "reference_validation": "quotes_and_parts_resolved",
        **({"all_artifact_extents_verified": True} if bounded and status != "unknown" else {}),
    }


def summarize(rows, membership_complete):
    from collections import Counter

    required = [r for r in rows if r["required"]]
    applicable = [r for r in required if r["applicability"] == "applicable"]
    counts = Counter(r["assessment_status"] for r in applicable)
    unknown = sum(r["applicability"] == "unknown" for r in required)
    summary = "ready"
    if not rows or not membership_complete or unknown or counts["unknown"]:
        summary = "unknown"
    if counts["needs_work"]:
        summary = "needs_work"
    if counts["conflict"]:
        summary = "conflict"
    return dict(
        summary_status=summary,
        counts=dict(
            requirements=len(rows),
            required=len(required),
            applicable_required=len(applicable),
            optional=len(rows) - len(required),
            not_applicable_required=sum(r["applicability"] == "not_applicable" for r in required),
            unknown_applicability_required=unknown,
            **{k: counts[k] for k in ("satisfied", "needs_work", "unknown", "conflict")},
        ),
    )


def dependencies(row, bindings):
    names = {
        row["governing"]["source"],
        *(a["source"] for a in row["evidence"]),
        *(e["source"] for e in row["reviewed_extent"]),
        *(a["source"] for c in row.get("candidate_assessments", []) for a in c["evidence"]),
    }
    if row["coverage_rule"] in {"all_claims", "absence", "recorded_run"}:
        names.update(b.logical_id for b in bindings if b.role == "artifact")
    return names


def project(data, rows):
    output = summarize(rows, data["membership_complete"])
    work, followups = [], {}
    for row in rows:
        ident = row["requirement_id"]
        if row["applicability"] == "not_applicable":
            continue
        status = row["assessment_status"]
        if status in {"unknown", "conflict"} or row["applicability"] == "unknown":
            reason = row.get("followup") or (
                "resolve_applicability"
                if row["applicability"] == "unknown"
                else "resolve_conflict"
                if status == "conflict"
                else "review_criterion"
            )
            followups.setdefault(reason, []).append(ident)
        if "work_item" in row:
            work.append(
                {
                    **row["work_item"],
                    **data.get("personal_fields", {}).get(row["work_item"]["work_id"], {}),
                    "rereview_needed": data["progress"].get(row["work_item"]["work_id"])
                    == "student_marked_done"
                    and status == "needs_work",
                    "progress_state": data["progress"].get(row["work_item"]["work_id"], "unknown"),
                }
            )
    return output | dict(
        definition_version="readiness-1",
        requirements=rows,
        remaining_work=work,
        review_followups=[
            {"reason": key, "requirement_ids": ids} for key, ids in sorted(followups.items())
        ],
    )


async def authorize_bindings(bridge, owner, bindings, *, partial=False, planning=False):
    """Use the ordinary independent workflow's source, integrity and release gates."""
    from canvas_bridge.academic.independent_models import DocumentSelection, IndependentRequest
    from canvas_bridge.domain import DomainError
    from canvas_bridge.independent_intelligence import TOOL, require, require_use
    from canvas_bridge.integrity.surfaces import before_tool

    unavailable = set()
    for binding in bindings:
        if not binding.document_id:
            continue
        selected = DocumentSelection(
            document_id=binding.document_id, expected_hash=binding.content_hash
        )
        payload = (
            IndependentRequest(capability="planning", dataset=selected)
            if planning
            else IndependentRequest(capability="requirements", documents=[selected])
        )
        try:
            row = require(bridge, owner, selected, check_version=False)
            require_use(bridge, row, payload.capability)
            await before_tool(bridge, owner, "read_local_document", {"document_id": row.id})
            bridge.egress.release(
                bridge.independent.read(owner, row.id, status=True),
                owner,
                {"document_id": row.id},
                tool_name="get_local_document_status",
            )
            require(bridge, owner, selected)
            bridge.egress.release(
                bridge.independent.read(owner, row.id, limit=1, study=True),
                owner,
                {"request": payload},
                tool_name=TOOL,
            )
        except DomainError:
            if not partial:
                raise
            unavailable.add(binding.logical_id)
    return unavailable


def prepare_review(service, owner, review, *, equivalent_payloads=()):
    """Validate outside the transaction and return the existing journal record builder."""
    from canvas_bridge.processes.models import AcademicRecord
    from canvas_bridge.processes.requests import ProcessScope

    selected = [b.document_id for b in review.bindings if b.document_id]
    if not selected:
        failure("READINESS_SOURCE_UNAVAILABLE")
    entries = service.load(
        owner,
        ProcessScope(document_ids=tuple(selected), local_course=review.course, term=review.term),
    )
    bindings = bind(entries, review.bindings)
    if not any(b.role == "brief" and b.document_id for b in review.bindings):
        failure("READINESS_REQUIREMENT_SOURCE_REQUIRED")
    tags = tuple(e["tag"] for e in entries.values())
    scope = tags[0].scope
    if scope.course != review.course or scope.term != review.term:
        failure("PROCESS_SCOPE_MISMATCH")
    key = record_key(scope, review.assignment_id)
    rows = sorted(
        [
            assess(r, bindings, entries, equivalent_payloads=equivalent_payloads)
            for r in review.requirements
        ],
        key=lambda r: r["requirement_id"],
    )
    if len({r["requirement_id"] for r in rows}) != len(rows):
        failure("READINESS_DUPLICATE_REQUIREMENT")
    criteria = [
        "requirement_id",
        "criterion",
        "governing",
        "required",
        "applicability",
    ]
    revision = fingerprint(
        [
            key,
            sorted((b.logical_id, b.content_hash) for b in review.bindings if b.role == "brief"),
            [{k: r[k] for k in criteria} for r in rows],
        ]
    )
    versions = sorted((b.logical_id, b.role, b.content_hash) for b in review.bindings)
    if not set(review.requested_work) <= {r["requirement_id"] for r in rows}:
        failure("READINESS_WORK_UNAVAILABLE")
    for row in rows:
        requested = row["requirement_id"] in review.requested_work
        if requested and (
            not row["action"]
            or not row["completion_condition"]
            or not row["gap_kind"]
            or row["applicability"] == "not_applicable"
        ):
            failure("READINESS_ACTION_REQUIRED")
        if requested or (
            row["assessment_status"] == "needs_work"
            and row["required"]
            and row["applicability"] == "applicable"
        ):
            work_id = fingerprint([key, revision, versions, row["requirement_id"], row["gap_kind"]])
            row["work_item"] = dict(
                work_id=work_id,
                work_basis="explicit_user_request" if requested else "supported_required_gap",
                requirement_id=row["requirement_id"],
                action=row["action"],
                completion_condition=row["completion_condition"],
                gap_kind=row["gap_kind"],
            )

    def build(before, now):
        work_ids = {r["work_item"]["work_id"] for r in rows if "work_item" in r}
        progress = (
            {i: s for i, s in before.data["progress"].items() if i in work_ids} if before else {}
        )
        data = dict(
            payload_type="assignment_readiness",
            assignment_id=review.assignment_id,
            requirement_set_revision=revision,
            review_scope=review.review_scope,
            assessed_at=now.isoformat(),
            assessment_revision=review.expected_revision + 1,
            membership_complete=review.membership_complete,
            bindings=[b.model_dump(mode="json") for b in review.bindings],
            requirements=rows,
            progress=progress,
            personal_fields={
                k: v for k, v in before.data.get("personal_fields", {}).items() if k in work_ids
            }
            if before
            else {},
        )
        return AcademicRecord(
            id=key,
            kind="assignment",
            scope=scope,
            revision=review.expected_revision + 1,
            data=data,
            sources=tags,
            updated_at=now,
        )

    return key, build


def save(service, owner, review):
    from canvas_bridge.domain import Result

    key, build = prepare_review(service, owner, review)
    receipt = service.repository.save_readiness(
        owner,
        key,
        review.expected_revision,
        review.idempotency_key,
        fingerprint(review.model_dump(mode="json")),
        build,
    )
    return Result(summary="Assignment readiness saved.", data=receipt)


class Selection(Model):
    requirement_set_revision: Ref
    bindings: tuple[Binding, ...] = Field(min_length=1, max_length=6)


def view(
    service, owner, ident, revision=None, selection=None, plan=None, plan_as_of=None, withheld=()
):
    from canvas_bridge.domain import DomainError, Result, WorkItem
    from canvas_bridge.planning import propose

    service.enabled()
    record = snapshot(service.repository, owner, ident, revision)
    data = record.data
    bindings = [Binding.model_validate(b) for b in data["bindings"]]
    available = {}
    changed = set()
    unverified = set()
    if selection:
        selected = {b.logical_id: b for b in selection.bindings}
        if len(selected) != len(selection.bindings):
            failure("READINESS_SELECTION_INVALID")
        for b in selected.values():
            if (
                b.document_id
                and service.bridge.independent.require(owner, b.document_id).version_hash
                != b.content_hash
            ):
                failure("READINESS_VERSION_MISMATCH")
        changed = {
            b.logical_id
            for b in bindings
            if b.logical_id not in selected
            or (selected[b.logical_id].role, selected[b.logical_id].content_hash)
            != (b.role, b.content_hash)
        }
        unverified = {
            b.logical_id
            for b in bindings
            if b.logical_id not in selected or not selected[b.logical_id].content_hash
        }
        if set(selected) - {b.logical_id for b in bindings}:
            # The saved inventory cannot attest new sources in the requested review scope.
            changed.update(b.logical_id for b in bindings)
        if selection.requirement_set_revision != data["requirement_set_revision"]:
            changed.update(b.logical_id for b in bindings)
    unavailable = set(withheld)
    for b in bindings:
        if not b.document_id or b.logical_id in unavailable:
            continue
        try:
            tag = next(t for t in record.sources if t.id == b.document_id)
            with service.bridge.store.transaction() as session:
                row = service.authorize_source(session, owner, tag, "read")
                if not row.provenance.get(
                    "share_text"
                ) or "grade_planning" not in row.provenance.get("scope", []):
                    failure("READINESS_SOURCE_UNAVAILABLE")
                available[b.logical_id] = service.bridge.independent.evidence(row)
        except DomainError:
            unavailable.add(b.logical_id)
    if not available:
        failure("READINESS_SOURCE_UNAVAILABLE")
    rows = []
    for original in data["requirements"]:
        affected = dependencies(original, bindings) & (unavailable | changed)
        if affected:
            # Withhold free text derived from a source whose release is no longer authorized.
            rows.append(
                dict(
                    requirement_id=original["requirement_id"],
                    required=original["required"],
                    applicability="unknown"
                    if original["governing"]["source"] in (changed | unavailable)
                    else original["applicability"],
                    assessment_status="unknown",
                    coverage="unavailable",
                    version_match="unverified"
                    if affected & unverified
                    else "mismatch"
                    if affected & changed
                    else original.get("version_match", "current"),
                    availability="unavailable" if affected & unavailable else "available",
                    affected_sources=sorted(affected),
                    followup="review_selected_version" if affected & changed else "refresh_source",
                )
            )
        else:
            rows.append(
                original
                | {
                    "version_match": original.get("version_match", "current"),
                    "availability": "available",
                }
            )
    output = project(data, rows)
    output["selected_bindings"] = (
        [b.model_dump(mode="json") for b in selection.bindings] if selection else None
    )
    output.update(
        record_id=ident,
        revision=record.revision,
        assessment_revision=data["assessment_revision"],
        assessed_at=data["assessed_at"],
        assignment_id=data["assignment_id"],
        requirement_set_revision=data["requirement_set_revision"],
        membership_complete=data["membership_complete"],
        view_mode="current_selection" if selection else "saved_snapshot",
        bindings=[
            dict(
                logical_id=b.logical_id,
                role=b.role,
                content_hash=b.content_hash,
                availability="unavailable"
                if b.logical_id in unavailable or not b.document_id
                else "available",
            )
            for b in bindings
        ],
    )
    if pending := data.get("pending_change"):
        output["pending_observation"] = {
            "change_id": pending["change_id"],
            "processing_state": "pending",
            "next_step": "get_assignment_change",
        }
    if plan is not None:
        items = [
            WorkItem(
                id=w["work_id"],
                connection_id="independent",
                institution_id="independent",
                course_id=record.scope.course,
                source_id=ident,
                title=w.get("personal_title") or w["action"],
                effort_remaining=Effort.model_validate(w["effort"]) if w.get("effort") else None,
                source=next(iter(available.values())),
                personal_progress=w["progress_state"],
                independent_personal_work=True,
            )
            for w in output["remaining_work"]
        ]
        clock = plan_as_of or service.bridge.retention.clock()
        try:
            output["plan"] = propose(items, plan, clock)
        except ValueError:
            failure(
                "READINESS_PLAN_INVALID", "Use current remediation IDs and a valid planning window."
            )
        output["plan_as_of"] = clock.isoformat()
    return Result(
        summary="Version-bound assignment readiness.", data=output, sources=list(available.values())
    )


class Progress(Model):
    record_id: Ref
    work_id: Ref
    expected_revision: int = Field(ge=1)
    idempotency_key: Ref
    progress_state: Literal["not_started", "in_progress", "student_marked_done"] | None = None
    personal_title: Text | None = None
    personal_note: Text | None = None
    effort: Effort | None = None

    @model_validator(mode="after")
    def declares_change(self):
        if not any((self.progress_state, self.personal_title, self.personal_note, self.effort)):
            raise ValueError("Supply personal progress, a task edit, or a scoped effort estimate.")
        return self


def update_progress(service, owner, request):
    from canvas_bridge.domain import Result

    service.enabled()

    def build(before, now):
        if not before or request.work_id not in {
            r["work_item"]["work_id"] for r in before.data["requirements"] if "work_item" in r
        }:
            failure("READINESS_WORK_UNAVAILABLE")
        data = dict(before.data)
        fields = dict(data.get("personal_fields", {}))
        personal = dict(fields.get(request.work_id, {}))
        personal.update(
            request.model_dump(
                mode="json",
                include={"personal_title", "personal_note", "effort"},
                exclude_none=True,
            )
        )
        if request.progress_state:
            data["progress"] = data["progress"] | {request.work_id: request.progress_state}
            personal.update(
                declaration_id=fingerprint(
                    [owner, request.record_id, request.work_id, request.idempotency_key]
                ),
                progress_basis="user_declaration",
            )
        fields[request.work_id] = personal
        data["personal_fields"] = fields
        return before.model_copy(
            update=dict(data=data, revision=before.revision + 1, updated_at=now)
        )

    receipt = service.repository.save_readiness(
        owner,
        request.record_id,
        request.expected_revision,
        request.idempotency_key,
        fingerprint(request.model_dump(mode="json")),
        build,
    )
    return Result(
        summary="Personal progress saved. The artifact retains its assessed result.", data=receipt
    )
