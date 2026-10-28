"""Bridge adapters for process evaluation and preview/confirm persistence.

No caller supplies source authority, review approvals or a stored before image.
Institutional sources are existing authorized cache records and are rechecked
through the same gateway on every read, commit and egress.
"""

from datetime import timedelta

from pydantic import BaseModel
from sqlalchemy import select

from canvas_bridge.domain import DomainError, Result, Source
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import (
    AcademicRecord,
    AcademicScope,
    ChangePreview,
    EvidenceClaim,
    EvidenceCoverage,
    SourceTag,
)
from canvas_bridge.processes.requests import EvaluationRequest
from canvas_bridge.processes.state import ProcessRepository, failure
from canvas_bridge.storage import IndependentResource, Material, Work, aware


def plain(value, *, public=False):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            k: plain(v, public=public)
            for k, v in value.items()
            if not public or k not in {"principal", "actor", "issuer", "instructor"}
        }
    if isinstance(value, (list, tuple)):
        return [plain(v, public=public) for v in value]
    return value


class ProcessService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.repository = ProcessRepository(
            bridge.store, clock=lambda: bridge.retention.clock(), authorize=self.authorize_source
        )

    def enabled(self):
        if not self.bridge.settings.process_features_enabled:
            raise DomainError(
                "unsupported_feature",
                "Academic process features are disabled in this deployment.",
                reason_code="PROCESS_FEATURE_DISABLED",
            )

    def authorize_source(self, session, owner, tag, purpose):
        if tag.scope.principal != owner:
            failure("PROCESS_SCOPE_MISMATCH")
        if tag.origin == "local_document":
            row = session.scalar(
                select(IndependentResource)
                .where(IndependentResource.id == tag.id, IndependentResource.owner == owner)
                .with_for_update()
            )
            if (
                not row
                or row.kind != "local_document"
                or aware(row.expires_at) <= self.bridge.retention.clock()
            ):
                failure("PROCESS_SOURCE_UNAVAILABLE")
            p = row.provenance
            if (
                row.version_hash != tag.version
                or p.get("source_type") != "local_document"
                or p.get("owner") != owner
                or p.get("content_identity") != row.version_hash
                or p.get("institutional_connection") is not None
                or p.get("parents")
                or p.get("authorization") != "explicit_user_permission"
            ):
                failure("PROCESS_SOURCE_CHANGED")
            return row
        if tag.origin != "institutional":
            failure("PROCESS_SOURCE_UNAVAILABLE")
        conn = self.bridge.store.connection(session, owner, tag.connection, lock=True)
        if conn.institution != tag.scope.institution:
            failure("PROCESS_SCOPE_MISMATCH")
        row = session.scalar(
            select(Work).where(
                Work.owner == owner, Work.connection_id == tag.connection, Work.id == tag.id
            )
        )
        resource = "assignments"
        if row is None:
            row = session.scalar(
                select(Material).where(
                    Material.owner == owner,
                    Material.connection_id == tag.connection,
                    Material.id == tag.id,
                )
            )
            resource = "files" if row and row.kind == "file" else "pages"
        if row is None or row.course_id != tag.scope.course:
            failure("PROCESS_SOURCE_UNAVAILABLE")
        self.bridge.authorize(
            owner, tag.connection, row.course_id, resource, session=session
        ).require()
        version = (
            row.payload.get("source", {}).get("content_hash")
            if isinstance(row, Work)
            else row.version_hash
        )
        if tag.version != version and purpose != "history":
            failure("PROCESS_SOURCE_CHANGED")
        if isinstance(row, Work):
            self.bridge.authorize(
                owner, tag.connection, row.course_id, "submissions", session=session
            ).require()
        return row

    def load(self, owner, scope):
        self.enabled()
        now = self.bridge.retention.clock()
        entries = {}
        for ident in scope.document_ids:
            row = self.bridge.independent.require(owner, ident)
            parsed = row.content["parsed"]
            tag = SourceTag(
                id=ident,
                version=row.version_hash,
                origin="local_document",
                scope=AcademicScope(
                    principal=owner,
                    institution="independent",
                    term=scope.term,
                    course=scope.local_course,
                ),
                locator="Imported document",
                observed_at=aware(row.created_at),
                expires_at=aware(row.expires_at),
            )
            entries[ident] = self.document_entry(tag, parsed, self.bridge.independent.evidence(row))
        if scope.connection_id:
            self.bridge.connection_policy(
                owner,
                scope.connection_id,
                {"courses", "files", "pages", "assignments", "submissions"},
            )
            with self.bridge.store.transaction() as session:
                conn = self.bridge.store.connection(session, owner, scope.connection_id)
                for ident in scope.resource_ids:
                    row = session.scalar(
                        select(Work).where(
                            Work.owner == owner, Work.connection_id == conn.id, Work.id == ident
                        )
                    )
                    if row:
                        citation = Source.model_validate(row.payload["source"])
                        version, observed = citation.content_hash, aware(row.observed_at)
                    else:
                        row = session.scalar(
                            select(Material).where(
                                Material.owner == owner,
                                Material.connection_id == conn.id,
                                Material.id == ident,
                            )
                        )
                        if not row:
                            failure(
                                "PROCESS_SOURCE_UNAVAILABLE",
                                "Read the selected resource through the existing course tools first.",
                            )
                        version, observed = row.version_hash, aware(row.retrieved_at)
                        citation = Source(
                            id=row.id,
                            resource_id=row.id,
                            course_id=row.course_id,
                            url=row.url,
                            title=row.title,
                            retrieved_at=observed,
                            content_hash=version,
                            source_type="course_file" if row.kind == "file" else "page",
                        )
                    tag = SourceTag(
                        id=ident,
                        version=version or "missing",
                        origin="institutional",
                        connection=conn.id,
                        scope=AcademicScope(
                            principal=owner,
                            institution=conn.institution,
                            term=scope.term,
                            course=row.course_id,
                        ),
                        locator=citation.locator or "Authorized cached record",
                        observed_at=observed,
                        expires_at=observed + timedelta(minutes=15),
                        sensitivity="course",
                    )
                    if row.course_id != scope.course_id:
                        failure("PROCESS_SCOPE_MISMATCH")
                    self.authorize_source(session, owner, tag, "read")
                    if isinstance(row, Work):
                        cover = EvidenceCoverage(
                            source=tag,
                            unit="record",
                            total=1,
                            seen=frozenset({1}),
                            extraction="complete",
                        )
                        entries[ident] = {
                            "tag": tag,
                            "coverage": cover,
                            "citation": citation,
                            "work": row.payload,
                            "text": "",
                        }
                    else:
                        pages = row.locators
                        parsed = {
                            "pages": pages,
                            "coverage": row.file_state.get("coverage", "partial"),
                            "page_count": row.file_state.get("page_count"),
                        }
                        entries[ident] = self.document_entry(tag, parsed, citation)
        if not entries or len(entries) > 36:
            failure("PROCESS_SOURCE_UNAVAILABLE")
        for entry in entries.values():
            if entry["tag"].expires_at <= now:
                failure(
                    "PROCESS_SOURCE_STALE",
                    "Refresh source evidence before evaluating this process.",
                )
        return entries

    @staticmethod
    def document_entry(tag, parsed, citation):
        pages = parsed.get("pages", [])
        seen, unreadable = set(), set()
        for index, page in enumerate(pages, 1):
            number = page.get("page", page.get("slide", index))
            if not isinstance(number, int) or number < 1:
                continue
            (seen if page.get("state") == "extracted" else unreadable).add(number)
        total = parsed.get("page_count")
        if not isinstance(total, int) or total < 1:
            total = None
        complete = (
            total is not None
            and len(seen) == total
            and not unreadable
            and parsed.get("coverage") in {"text_only", "complete"}
        )
        cover = EvidenceCoverage(
            source=tag,
            unit="page",
            total=total,
            seen=frozenset(seen),
            unreadable=frozenset(unreadable),
            extraction="complete" if complete else "partial" if seen else "unreadable",
        )
        return {
            "tag": tag,
            "coverage": cover,
            "citation": citation,
            "work": None,
            "text": "\n".join(p.get("text", "") for p in pages)[:200_000],
        }

    @staticmethod
    def claims(inputs, entries):
        result = []
        for index, item in enumerate(inputs):
            entry = entries.get(item.source_id)
            if not entry or item.unit not in entry["coverage"].seen:
                failure("PROCESS_CITATION_UNAVAILABLE")
            # Client extraction remains user-declared, even if it cites an official document.
            result.append(
                EvidenceClaim(
                    id=fingerprint([item.model_dump(), index]),
                    entity=item.entity,
                    field=item.field,
                    value=item.value,
                    coverage=entry["coverage"],
                    basis="user_declared",
                )
            )
        return result

    async def compute(self, owner, request):
        entries = self.load(owner, request.scope)
        payload, now = request.payload, self.bridge.retention.clock()
        tags = tuple(e["tag"] for e in entries.values())

        def entry(ident):
            if ident not in entries:
                failure("PROCESS_CITATION_UNAVAILABLE")
            return entries[ident]

        if payload.operation in {"evidence", "clarification"}:
            from canvas_bridge.processes.evidence import assess_coverage, reconcile
            from canvas_bridge.processes.trust import inspect_content

            claims = self.claims(payload.claims, entries)
            # Canonical provider fields are observed facts. Caller-authored
            # interpretations remain separate unverified candidates.
            requested = {(c.entity, c.field) for c in claims}
            for ident, item in entries.items():
                work = item["work"]
                if not work or requested and (ident, "deadline") not in requested:
                    continue
                due = work.get("effective_due", {})
                value = (
                    due.get("timestamp")
                    if due.get("kind") == "timestamp"
                    else due.get("local_date")
                    if due.get("kind") == "local_date"
                    else None
                )
                if value is not None:
                    claims.append(
                        EvidenceClaim(
                            id=fingerprint([ident, item["tag"].version, "deadline"]),
                            entity=ident,
                            field="deadline",
                            value=value,
                            coverage=item["coverage"],
                            basis="observed",
                            authority="official",
                        )
                    )
            groups = {}
            for claim in claims:
                groups.setdefault(
                    (claim.coverage.source.scope, claim.entity, claim.field), []
                ).append(claim)
            resolutions = [reconcile(group, now=now) for group in groups.values()]
            decision = resolutions[0] if len(resolutions) == 1 else reconcile((), now=now)
            data = {
                "resolution": decision,
                "resolutions": resolutions,
                "uncertainty_assessment": assess_coverage(
                    [e["coverage"] for e in entries.values()],
                    getattr(payload, "decision_class", "deadline"),
                    now=now,
                    contested=any("CONTESTED_CLAIMS" in r.reasons for r in resolutions),
                ),
                "document_trust": [inspect_content(e["text"], "text") for e in entries.values()],
                "canonical_fields": {
                    c.field: c.value for c in decision.candidates if c.id == decision.selected
                },
            }
            if payload.operation == "clarification":
                from canvas_bridge.processes.clarification import draft_clarification

                if len(resolutions) != 1:
                    raise DomainError(
                        "needs_input", "Clarify one exact entity, field and source scope at a time."
                    )
                data["clarification"] = draft_clarification(decision)
        elif payload.operation == "feasibility":
            from canvas_bridge.processes.feasibility import simulate

            data = simulate(
                payload.work,
                payload.availability,
                payload.commitments,
                now=now,
                buffer_minutes=payload.buffer_minutes,
                break_minutes=payload.break_minutes,
            )
        elif payload.operation == "identity":
            from canvas_bridge.processes.identity import (
                ExternalEntityKey,
                canonical_link,
                match_entities,
            )

            def external(item):
                tag = entry(item.source_id)["tag"]
                return ExternalEntityKey(
                    provider=item.provider,
                    external_id=item.external_id,
                    scope=tag.scope.model_copy(
                        update={"institution": item.institution, "term": item.term}
                    ),
                    kind=item.kind,
                    course_code=item.course_code,
                    section=item.section,
                    instructor=item.instructor,
                    start_date=item.start_date,
                    content_hash=tag.version if item.kind == "document" else None,
                    sources=(tag,),
                )

            left, right = external(payload.left), external(payload.right)
            data = match_entities(left, right)
            if data["merge_allowed"]:
                # This is an unsaved proposal. The generic exact-preview flow
                # creates the link only after the student's explicit confirmation.
                data["canonical_link_proposal"] = canonical_link(left, right, confirmed=True)
            data["identity_signal_basis"] = (
                "user_supplied_candidates; source_permissions_remain_separate"
            )
        elif payload.operation == "lifecycle":
            from canvas_bridge.integrity.models import AssistanceRequest, Scope
            from canvas_bridge.processes.lifecycle import (
                AssignmentState,
                TransitionEvidence,
                transition,
            )

            integrity_scope = Scope(
                connection_id=request.scope.connection_id,
                course_id=request.scope.course_id,
                assessment_id=payload.assignment_id if request.scope.connection_id else None,
                document_ids=list(request.scope.document_ids),
                local_course=request.scope.local_course
                if not request.scope.connection_id
                else None,
            )
            decision, policies = await self.bridge.integrity.evaluate(
                owner,
                AssistanceRequest(scope=integrity_scope, activity=payload.activity),
                record=False,
            )
            decision.require()
            found = entries.get(payload.assignment_id)
            work = found["work"] if found else None
            state_value = work.get("submission_state", "unknown") if work else "unknown"
            kind = (
                "grade_record"
                if state_value == "graded"
                else "submission_receipt"
                if state_value in {"submitted", "resubmitted"}
                else "user_declaration"
            )
            if (
                payload.current in {"submitted_confirmed", "graded", "feedback_reviewed"}
                and kind == "user_declaration"
            ):
                failure("PROCESS_SUBMISSION_UNCONFIRMED")
            if payload.current in {"graded", "feedback_reviewed"} and state_value != "graded":
                failure("PROCESS_GRADE_UNCONFIRMED")
            evidence = TransitionEvidence(
                source=found["tag"] if found else tags[0],
                kind=kind,
                assignment_id=payload.assignment_id,
                observed=bool(work),
                value=state_value
                if state_value in {"submitted", "resubmitted", "graded"}
                else "unknown",
            )
            data = (
                {
                    "state": AssignmentState(
                        assignment_id=payload.assignment_id,
                        stage=payload.current,
                        archived=True,
                        evidence=(evidence.source,),
                        basis="observed" if evidence.observed else "user_declared",
                    ),
                    "integrity_decision": decision,
                    "external_action": False,
                    "next_step": "start_new_term_with_separate_scope",
                }
                if payload.archive
                else transition(
                    AssignmentState(assignment_id=payload.assignment_id, stage=payload.current),
                    payload.target,
                    evidence,
                    policy_sources=policies["sources"],
                    activity=payload.activity,
                    now=now,
                )
            )
        elif payload.operation == "knowledge":
            from canvas_bridge.processes.knowledge import Concept, LearningEvidence, competency

            tag = entry(payload.source_id)["tag"]
            evidence = LearningEvidence(
                concept_id=payload.concept_id,
                kind=payload.kind,
                source=tag,
                observed_at=now,
                review_at=payload.review_at,
                score=payload.score,
                possible=payload.possible,
            )
            data = competency(
                Concept(id=payload.concept_id, label=payload.label, sources=(tag,)),
                [evidence],
                now=now,
            )
            data["related_concept_candidate"] = payload.related_concept
            data["relationship_basis"] = "user_declared"
            from canvas_bridge.processes.knowledge import ConceptRelationship

            data["relationships"] = (
                [
                    ConceptRelationship(
                        left=payload.concept_id,
                        right=payload.related_concept,
                        kind=payload.relationship_kind,
                        basis="user_corrected",
                        sources=tuple(tags),
                    )
                ]
                if payload.related_concept
                else []
            )
        elif payload.operation == "degree":
            from canvas_bridge.processes.degree import (
                CourseCredit,
                CourseRule,
                DegreeRules,
                ElectiveBasket,
                Substitution,
                project_degree,
            )

            tag = tags[0]
            rules = DegreeRules(
                institution=tag.scope.institution,
                program=payload.program,
                concentration=payload.concentration,
                catalog_year=payload.catalog_year,
                version=tag.version,
                minimum_credits=payload.minimum_credits,
                required=payload.required,
                source=tag,
                courses=tuple(
                    CourseRule(
                        course=c.course, prerequisites=c.prerequisites, corequisites=c.corequisites
                    )
                    for c in payload.coursework
                ),
                baskets=tuple(ElectiveBasket(**b.model_dump()) for b in payload.baskets),
                substitutions=tuple(
                    Substitution(
                        required=s.required,
                        replacement=s.replacement,
                        approval_source=entry(s.source_id)["tag"],
                    )
                    for s in payload.substitutions
                ),
            )
            credits = [
                CourseCredit(
                    course=c.course,
                    credits=c.credits,
                    completed=c.completed,
                    planned_term=c.planned_term,
                    source=tag,
                )
                for c in payload.coursework
            ]
            data = project_degree(rules, credits, now=now)
        elif payload.operation == "clarification_update":
            from canvas_bridge.processes.clarification import (
                ClarificationRequest,
                confirm_status,
                response_candidate,
            )

            record = self.repository.read(owner, payload.record_id)
            if record.kind != "clarification" or not {s.key for s in record.sources} <= {
                s.key for s in tags
            }:
                failure("PROCESS_SCOPE_MISMATCH")
            previous = ClarificationRequest.model_validate(record.data["clarification"]["request"])
            updated = confirm_status(previous, payload.event, confirmed=payload.confirmed_event)
            data = {
                "clarification": {"request": updated, "message_sent": False},
                "communication_status_basis": "user_confirmed",
            }
            if payload.response:
                data["response_candidate"] = response_candidate(
                    updated, self.claims((payload.response,), entries)[0]
                )
        elif payload.operation == "annotation":
            entry(payload.source_id)
            data = {
                "entity": payload.entity,
                "field": payload.field,
                "note": payload.note,
                "basis": "user_declared",
                "source_edited": False,
                "authority": "unverified",
            }
        elif payload.operation == "portfolio":
            from canvas_bridge.processes.portfolio import PortfolioPart, publication_clearance

            parts = [
                PortfolioPart(
                    id=p.source_id,
                    source=entry(p.source_id)["tag"],
                    origin=p.origin,
                    content_hash=entry(p.source_id)["tag"].version,
                )
                for p in payload.parts
            ]
            # No public tool may install a human publication-rights review.
            data = publication_clearance(parts, (), now=now)
        else:
            raise ValueError("Unsupported process operation.")
        # Recheck final source state after any awaited policy discovery.
        with self.bridge.store.transaction() as session:
            for tag in tags:
                self.authorize_source(session, owner, tag, "read")
        return plain(data), entries

    async def evaluate(self, owner, request):
        data, entries = await self.compute(owner, request)
        return Result(
            summary="Evidence-bound process evaluation; proposals do not perform external actions.",
            data=plain(data, public=True),
            sources=[e["citation"] for e in entries.values()],
        )

    def citations(self, owner, tags):
        result = []
        with self.bridge.store.transaction() as session:
            for tag in tags:
                row = self.authorize_source(session, owner, tag, "read")
                if tag.origin == "local_document":
                    result.append(self.bridge.independent.evidence(row))
                elif isinstance(row, Work):
                    result.append(Source.model_validate(row.payload["source"]))
                else:
                    result.append(
                        Source(
                            id=row.id,
                            resource_id=row.id,
                            course_id=row.course_id,
                            title=row.title,
                            url=row.url,
                            retrieved_at=row.retrieved_at,
                            content_hash=row.version_hash,
                            source_type="course_file" if row.kind == "file" else "page",
                        )
                    )
        return result

    def save_preview(self, owner, change, evaluation=None):
        now = self.bridge.retention.clock()
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            rows = list(
                session.scalars(
                    select(IndependentResource.id).where(
                        IndependentResource.owner == owner,
                        IndependentResource.kind == "academic_process_preview",
                        IndependentResource.expires_at > now,
                    )
                )
            )
            ident = fingerprint([owner, change.id])
            existing = session.get(IndependentResource, ident)
            if not existing and len(rows) >= 30:
                failure("PROCESS_PREVIEW_LIMIT")
            content = {
                "change": change.model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
            }
            if len(str(content)) > 200_000:
                failure("PROCESS_STORAGE_BUDGET")
            row = existing or IndependentResource(
                id=ident, owner=owner, kind="academic_process_preview", created_at=now
            )
            row.content, row.version_hash = content, fingerprint(content)
            row.expires_at = change.expires_at
            row.provenance = {
                "owner": owner,
                "generation": principal.generation,
                "source_type": "academic_process_preview",
            }
            session.add(row)
        return ident

    def public_preview(self, owner, change):
        """Old versions require their own current release proof; never borrow the
        new source's permission for an old before image.
        """
        data = plain(change, public=True)
        sources = self.citations(owner, change.after.sources) if change.after else []
        if change.before:
            try:
                old_sources = self.citations(owner, change.before.sources)
            except DomainError:
                data["before"] = {
                    "id": change.before.id,
                    "revision": change.before.revision,
                    "state": "stale",
                    "historical_content": "withheld_pending_version_review",
                }
            else:
                sources.extend(old_sources)
        data["repair_plan"] = [
            {"record_id": ident, "next_step": "recompute_before_reuse"} for ident in change.affected
        ]
        return data, sources

    async def propose(self, owner, request):
        data, entries = await self.compute(owner, request.evaluation)
        tags = {e["tag"].key: e["tag"] for e in entries.values()}
        for parent in request.depends_on:
            for tag in self.repository.read(owner, parent).sources:
                tags[tag.key] = tag
        kind = {
            "evidence": "claim",
            "feasibility": "plan",
            "identity": "identity",
            "lifecycle": "assignment",
            "knowledge": "concept",
            "degree": "projection",
            "clarification": "clarification",
            "clarification_update": "clarification",
            "annotation": "annotation",
            "portfolio": "portfolio",
        }[request.evaluation.payload.operation]
        after = AcademicRecord(
            id=request.record_id,
            kind=kind,
            scope=next(iter(tags.values())).scope,
            revision=request.expected_revision + 1,
            data=data,
            sources=tuple(tags.values()),
            depends_on=request.depends_on,
            updated_at=self.bridge.retention.clock(),
        )
        change = self.repository.propose(
            owner,
            request.record_id,
            after,
            "create" if request.expected_revision == 0 else "correction",
        )
        if (
            request.evaluation.payload.operation == "clarification_update"
            and request.record_id != request.evaluation.payload.record_id
        ):
            failure("PROCESS_SCOPE_MISMATCH")
        ident = self.save_preview(owner, change, request.evaluation)
        public_change, sources = self.public_preview(owner, change)
        return Result(
            summary="Review the exact local change before confirming it.",
            data={"preview_id": ident, "change": public_change},
            sources=sources,
        )

    async def confirm(self, owner, preview_id, confirmed, idempotency_key):
        self.enabled()
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            row = session.scalar(
                select(IndependentResource).where(
                    IndependentResource.id == preview_id,
                    IndependentResource.owner == owner,
                    IndependentResource.kind == "academic_process_preview",
                )
            )
            if (
                not row
                or aware(row.expires_at) <= self.bridge.retention.clock()
                or row.provenance.get("generation") != principal.generation
            ):
                failure("PROCESS_PREVIEW_STALE")
            if fingerprint(row.content) != row.version_hash:
                failure("PROCESS_STATE_CORRUPT")
            change = ChangePreview.model_validate(row.content["change"])
            evaluation = (
                EvaluationRequest.model_validate(row.content["evaluation"])
                if row.content["evaluation"]
                else None
            )
            generation = principal.generation
        if evaluation:
            # Re-run current policy/access checks; never substitute newly computed
            # output for the exact preview that the user reviewed.
            await self.compute(owner, evaluation)
        receipt = self.repository.commit(
            owner,
            change,
            confirmed=confirmed,
            idempotency_key=idempotency_key,
            expected_generation=generation,
        )
        return Result(
            summary="Local process change committed. External services are unchanged.", data=receipt
        )

    def inspect_records(self, owner, record_ids):
        self.enabled()
        if not record_ids:
            inventory = self.repository.inventory(owner)
            valid = [r["id"] for r in inventory["records"] if r["state"] == "valid"]
            tags = {s.key: s for ident in valid for s in self.repository.read(owner, ident).sources}
            return Result(
                summary="Local process inventory with source and retention state.",
                data=inventory,
                sources=self.citations(owner, tags.values()),
            )
        records = [self.repository.read(owner, ident) for ident in record_ids]
        tags = {s.key: s for r in records for s in r.sources}
        return Result(
            summary="Current source-authorized process records.",
            data={"records": plain(records, public=True)},
            sources=self.citations(owner, tags.values()),
        )

    def recovery_preview(self, owner, record_id=None, revision_id=None):
        self.enabled()
        change = (
            self.repository.rollback_preview(owner, revision_id)
            if revision_id
            else self.repository.propose(owner, record_id, None, "delete")
        )
        ident = self.save_preview(owner, change)
        # Destructive previews disclose identifiers and counts, not revoked data.
        data = {
            "preview_id": ident,
            "operation": change.reason,
            "affected_count": len(change.affected) + 1,
        }
        citations = []
        if change.after:
            data["change"], citations = self.public_preview(owner, change)
        return Result(
            summary="Review the local recovery operation before confirmation.",
            data=data,
            sources=citations,
        )

    def change_impacts(self, owner, record_id):
        self.enabled()
        current = self.repository.read(owner, record_id)
        sources = self.citations(owner, current.sources)
        with self.bridge.store.transaction() as session:
            _, state = self.repository._load(session, owner)
            revisions = [
                r for r in state.revisions if r.after and r.after.id == record_id and r.impacts
            ][-20:]
        proposals = []
        for revision in revisions:
            readable = {}
            for side, image in (("before", revision.before), ("after", revision.after)):
                try:
                    citations = self.citations(owner, image.sources) if image else []
                except DomainError:
                    readable[side] = False
                else:
                    readable[side] = True
                    sources.extend(citations)
            for proposal in revision.impacts:
                diff = {
                    field: {
                        side: value if readable.get(side) else "withheld_historical_version"
                        for side, value in values.items()
                    }
                    for field, values in proposal["diff"].items()
                }
                proposals.append(proposal | {"diff": diff})
        return Result(
            summary="Observed canonical change impacts. Review proposals before any external action.",
            data={"impacts": proposals, "external_writes": False, "history_limit": 20},
            sources=sources,
        )

    def export(self, owner, record_ids, output_format="json"):
        self.enabled()
        payload = self.repository.export(owner, record_ids)
        tags = {
            s.key: s for ident in record_ids for s in self.repository.read(owner, ident).sources
        }
        data = plain(payload, public=True)
        if output_format == "markdown":
            import json
            import re

            serialized = json.dumps(data, indent=2)
            fence = "`" * max(
                3, max((len(part) for part in re.findall(r"`+", serialized)), default=0) + 1
            )
            data = {
                "schema_version": "academic-process-export-1",
                "markdown": "# Academic process export\n\n"
                + fence
                + "json\n"
                + serialized
                + "\n"
                + fence
                + "\n",
                "authority": "portable_evidence_only",
                "external_transfer": False,
            }
        return Result(
            summary="Portable local records; provenance remains evidence, not permission.",
            data=data,
            sources=self.citations(owner, tags.values()),
        )
