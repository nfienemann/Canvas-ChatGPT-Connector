"""Owner-bound receipts, source rechecks and the executable assistance boundary."""

import asyncio
import json
from datetime import timedelta

from sqlalchemy import delete, select

from canvas_bridge.domain import DomainError, Result, opaque_id
from canvas_bridge.evidence import fingerprint
from canvas_bridge.integrity.discovery import discover, minimal_sources
from canvas_bridge.integrity.engine import evaluate_academic_assistance
from canvas_bridge.integrity.guidance import safe_guidance
from canvas_bridge.integrity.models import VERSION, Activity, AssistanceRequest, Category, Scope
from canvas_bridge.storage import IndependentResource, aware

NOTICE = (
    "Academic AI-use permission could not be confirmed. Your instructor or institution may impose "
    "additional restrictions. Proceeding could carry academic-integrity consequences. "
    "Acknowledging this uncertainty is not instructor permission."
)


class IntegrityService:
    def __init__(self, bridge):
        self.bridge = bridge

    def read_record(self, owner, ident, kind):
        with self.bridge.store.transaction() as session:
            row = session.scalar(
                select(IndependentResource).where(
                    IndependentResource.id == ident,
                    IndependentResource.owner == owner,
                    IndependentResource.kind == kind,
                )
            )
            if not row or aware(row.expires_at) <= self.bridge.retention.clock():
                raise DomainError(
                    "permission_denied",
                    "This integrity reference is unavailable or expired.",
                    reason_code="INTEGRITY_REFERENCE_INVALID",
                )
            return row

    def write_record(self, owner, kind, content, *, expires=None, ident=None, generation=None):
        if len(json.dumps(content, ensure_ascii=False).encode("utf-8")) > 256 * 1024:
            raise DomainError(
                "retry_later",
                "The integrity receipt exceeds the bounded storage budget.",
                reason_code="INTEGRITY_RECEIPT_LIMIT",
            )
        now = self.bridge.retention.clock()
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            if generation is not None and principal.generation != generation:
                raise DomainError(
                    "source_changed", "The account state changed during this operation."
                )
            # Cap records and delete only expired integrity records; no silent eviction
            # of active restrictions to create room for a new workflow.
            session.execute(
                delete(IndependentResource).where(
                    IndependentResource.owner == owner,
                    IndependentResource.kind.in_(
                        {"integrity_decision", "integrity_ack", "integrity_context"}
                    ),
                    IndependentResource.expires_at <= now,
                )
            )
            rows = list(
                session.scalars(
                    select(IndependentResource.id).where(
                        IndependentResource.owner == owner,
                        IndependentResource.kind.in_(
                            {"integrity_decision", "integrity_ack", "integrity_context"}
                        ),
                    )
                )
            )
            existing = session.get(IndependentResource, ident) if ident else None
            if existing and (existing.owner != owner or existing.kind != kind):
                raise DomainError("permission_denied", "Integrity record ownership mismatch.")
            if not existing and len(rows) >= 200:
                raise DomainError(
                    "retry_later",
                    "The integrity receipt budget is full; wait for expiration.",
                    reason_code="INTEGRITY_RECEIPT_LIMIT",
                )
            row = existing or IndependentResource(id=ident or opaque_id(), owner=owner, kind=kind)
            row.version_hash, row.content = fingerprint(content), content
            row.provenance = {
                "owner": owner,
                "source_type": kind,
                "generation": principal.generation,
            }
            row.created_at, row.expires_at = now, expires or now + timedelta(hours=24)
            session.add(row)
            session.flush()
            return row.id

    def authorize_scope(self, owner, scope):
        if scope.connection_id:
            from canvas_bridge.approval_policy import CATEGORIES

            self.bridge.connection_policy(owner, scope.connection_id, CATEGORIES)
            self.bridge.selected(owner, scope.connection_id, [scope.course_id])
        for ident in scope.document_ids:
            self.bridge.independent.require(owner, ident)

    def scope_for_arguments(self, owner, arguments):
        request = arguments.get("request")
        if request:
            return (
                request.scope
                if isinstance(request, AssistanceRequest)
                else Scope.model_validate(request["scope"])
            )
        if arguments.get("scope"):
            return Scope.model_validate(arguments["scope"])
        for key, kind in (
            ("decision_id", "integrity_decision"),
            ("acknowledgment_id", "integrity_ack"),
        ):
            if arguments.get(key):
                return Scope.model_validate(
                    self.read_record(owner, arguments[key], kind).content["scope"]
                )
        return None

    def contexts(self, owner):
        with self.bridge.store.transaction() as session:
            return list(
                session.scalars(
                    select(IndependentResource).where(
                        IndependentResource.owner == owner,
                        IndependentResource.kind == "integrity_context",
                        IndependentResource.expires_at > self.bridge.retention.clock(),
                    )
                )
            )

    async def evaluate(self, owner, request, *, bundle=None, record=True):
        self.authorize_scope(owner, request.scope)
        with self.bridge.store.transaction() as session:
            generation = self.bridge.store.principal(session, owner).generation
        activity = request.effective_activity()
        if request.continuation_id:
            previous = self.read_record(owner, request.continuation_id, "integrity_decision")
            previous_scope = Scope.model_validate(previous.content["scope"])
            if previous_scope != request.scope:
                raise DomainError(
                    "permission_denied",
                    "A continuation cannot change its course, assessment or source scope.",
                    reason_code="INTEGRITY_SCOPE_CHANGED",
                )
        try:
            async with asyncio.timeout(90):
                evidence = await discover(self.bridge, owner, request.scope, bundle=bundle)
        except TimeoutError as exc:
            raise DomainError(
                "retry_later",
                "Policy discovery exceeded its bounded read budget.",
                reason_code="INTEGRITY_POLICY_COVERAGE_INCOMPLETE",
            ) from exc
        evidence["generation"] = generation
        assessed_source = bool(request.scope.assessment_id)
        from canvas_bridge.integrity.models import PolicySource

        # Known independent copies inherit already established source/course rules.
        # No client-provided provenance or renamed filename can erase those bindings.
        for context in self.contexts(owner):
            old = context.content
            same_course = request.scope.local_course and request.scope.local_course == old[
                "scope"
            ].get("local_course")
            overlap = set(evidence["hashes"].values()) & set(old.get("hashes", {}).values())
            if not (same_course or overlap):
                continue
            assessed_source |= bool(old.get("assessed_source") or old["scope"].get("assessment_id"))
            old_scope = Scope.model_validate(old["scope"])
            self.authorize_scope(owner, old_scope)
            current_ids = {s.id for s in evidence["sources"]}
            evidence["sources"].extend(
                PolicySource.model_validate(s)
                for s in old["policy_sources"]
                if s["id"] not in current_ids
            )
        ack = None
        if request.acknowledgment_id:
            row = self.read_record(owner, request.acknowledgment_id, "integrity_ack")
            ack = row.content
            if ack["scope"] != request.scope.model_dump(mode="json") or ack["activity"] != activity:
                raise DomainError(
                    "permission_denied",
                    "This acknowledgment covers a different activity or source scope.",
                    reason_code="INTEGRITY_ACKNOWLEDGMENT_SCOPE_MISMATCH",
                )
            ack = {**ack, "valid": True}
        decision = evaluate_academic_assistance(
            activity,
            evidence["sources"],
            assessment_id=request.scope.assessment_id,
            exam=evidence["exam"],
            now=self.bridge.retention.clock(),
            acknowledgment=ack,
        )
        evidence["assessed_source"] = assessed_source
        if ack and not decision.acknowledgment_valid:
            decision.allowed = False
            decision.reason_code = (
                "INTEGRITY_ACKNOWLEDGMENT_STALE"
                if decision.acknowledgment_eligible
                else decision.reason_code
            )
        self.authorize_scope(owner, request.scope)
        if record:
            scope = request.scope.model_dump(mode="json")
            context_id = fingerprint([owner, scope])
            self.write_record(
                owner,
                "integrity_context",
                {
                    "scope": scope,
                    "hashes": evidence["hashes"],
                    "policy_sources": [
                        s.model_dump(mode="json") for s in minimal_sources(evidence["sources"])
                    ],
                    "epoch": evidence["epoch"],
                    "latest_decision": decision.id,
                    "assessed_source": assessed_source,
                    "assessed_materials": [
                        link["material_id"]
                        for link in (evidence["bundle"] or {})
                        .get("assignments", {})
                        .get(request.scope.assessment_id, {})
                        .get("linked_materials", {})
                        .get("references", [])
                        if link.get("state") == "resolved" and link.get("material_id")
                    ],
                },
                ident=context_id,
                generation=generation,
            )
            # Decision audit contains no prompt, draft, answer or policy passage.
            safe = decision.model_dump(mode="json", exclude={"rules"})
            safe["evidence"] = [
                {
                    "source_id": r.source_id,
                    "version": r.source_version,
                    "locator": r.locator,
                    "effect": r.effect,
                }
                for r in decision.rules
            ]
            self.write_record(
                owner,
                "integrity_decision",
                {
                    "scope": scope,
                    "request": request.model_dump(mode="json"),
                    "decision": safe,
                    "policy_version": decision.policy_version,
                    "enforcement_outcome": "allowed" if decision.allowed else "withheld",
                },
                ident=decision.id,
                expires=decision.expires_at,
                generation=generation,
            )
        return decision, evidence

    def decision_result(self, decision, evidence, scope):
        return Result(
            summary="Academic permission is separate from source access and sharing permission.",
            data={
                **safe_guidance(),
                "decision": decision.model_dump(mode="json"),
                "scope": scope.model_dump(mode="json"),
                "public_policy_lookup": evidence["lookup"],
                "acknowledgment_notice": NOTICE if decision.acknowledgment_eligible else None,
                "source_coverage": [
                    s.model_dump(mode="json", exclude={"parts"}) for s in evidence["sources"]
                ],
            },
            sources=evidence["citations"],
        )

    async def check(self, owner, request):
        decision, evidence = await self.evaluate(owner, request)
        return self.decision_result(decision, evidence, request.scope)

    async def policy(self, owner, scope):
        # A substantive activity makes missing coverage and permission requirements
        # visible. Merely requesting policy information never releases assessed work.
        return await self.check(owner, AssistanceRequest(scope=scope, activity=Activity.DRAFT))

    async def acknowledge(self, owner, decision_id, confirmed):
        if confirmed is not True:
            raise DomainError(
                "needs_input",
                "Explicitly acknowledge the displayed uncertainty for this exact assistance.",
                reason_code="INTEGRITY_EXPLICIT_ACKNOWLEDGMENT_REQUIRED",
            )
        previous = self.read_record(owner, decision_id, "integrity_decision")
        request = AssistanceRequest.model_validate(previous.content["request"]).model_copy(
            update={"acknowledgment_id": None}
        )
        decision, evidence = await self.evaluate(owner, request)
        if (
            not decision.acknowledgment_eligible
            or decision.policy_version != previous.content["policy_version"]
        ):
            raise DomainError(
                "permission_denied",
                "This decision is ineligible for acknowledgment or its evidence changed. Review the current policy decision.",
                reason_code="INTEGRITY_ACKNOWLEDGMENT_INELIGIBLE",
            )
        result = self.decision_result(decision, evidence, request.scope)
        # An egress denial cannot be converted into an eligible risk acknowledgment.
        self.bridge.egress.release(
            result, owner, {"request": request}, tool_name="check_academic_assistance_permission"
        )
        ident = self.write_record(
            owner,
            "integrity_ack",
            {
                "scope": request.scope.model_dump(mode="json"),
                "activity": str(decision.activity),
                "policy_version": decision.policy_version,
                "decision_version": VERSION,
                "decision_id": decision.id,
                "acknowledged_at": self.bridge.retention.clock().isoformat(),
                "permission_established": False,
            },
            expires=decision.expires_at,
            generation=evidence["generation"],
        )
        result = self.decision_result(decision, evidence, request.scope)
        result.data.update(
            acknowledgment_id=ident, expires_at=decision.expires_at.isoformat(), notice=NOTICE
        )
        return result

    async def get_decision(self, owner, ident):
        previous = self.read_record(owner, ident, "integrity_decision")
        request = AssistanceRequest.model_validate(previous.content["request"])
        result = await self.check(owner, request)
        result.data["reevaluated_from"] = ident
        result.data["prior_policy_version_valid"] = (
            result.data["decision"]["policy_version"] == previous.content["policy_version"]
        )
        return result

    async def provide_evidence(self, owner, scope, document_id):
        self.bridge.independent.require(owner, document_id)
        expanded = Scope.model_validate(
            {**scope.model_dump(), "document_ids": sorted(set([*scope.document_ids, document_id]))}
        )
        result = await self.policy(owner, expanded)
        result.data["permission_evidence_status"] = "STUDENT_SUPPLIED_UNVERIFIED"
        return result

    async def prepare(self, owner, request):
        decision, evidence = await self.evaluate(owner, request)
        decision.require()
        result = self.decision_result(decision, evidence, request.scope)
        if decision.category in {Category.ADMINISTRATION, Category.PLANNING}:
            result.data["assistance_evidence"] = []
            result.data["allowed_activity_scope"] = [str(decision.activity)]
            result.data["content_boundary"] = (
                "Administrative metadata and planning do not release an assessed-work completion package."
            )
            return self.bridge.egress.release(
                result, owner, {"request": request}, tool_name="prepare_academic_assistance"
            )
        excerpts = []
        bundle = evidence["bundle"]
        if bundle:
            assignment = bundle["assignments"].get(request.scope.assessment_id)
            docs = (
                [assignment["instructions"], assignment["rubric"]]
                if assignment and decision.category != Category.LEARNING
                else []
            )
            docs += bundle["documents"]
            excerpts.extend(
                {
                    "source_id": doc["id"],
                    "version": doc["version"],
                    "locator": p["locator"],
                    "text": p["text"][:4000],
                }
                for doc in docs[:6]
                for p in doc.get("parts", [])[:2]
            )
        for ident in (
            request.scope.document_ids
            if not (evidence["assessed_source"] and decision.category == Category.LEARNING)
            else []
        ):
            row = self.bridge.independent.require(owner, ident)
            excerpts.extend(
                {
                    "source_id": ident,
                    "version": row.version_hash,
                    "locator": f"Part {i}",
                    "text": p.get("text", "")[:4000],
                }
                for i, p in enumerate(row.content["parsed"].get("pages", [])[:2], 1)
            )
        # The release gate separately verifies recipient, content classification and
        # source access. An integrity allow never overrides any of those controls.
        result.data["assistance_evidence"] = excerpts[:12]
        result.data["allowed_activity_scope"] = [str(decision.activity)]
        result.data["authorship_guidance"] = (
            "Do not claim unaided authorship. Verify citations and follow the cited disclosure rules."
        )
        if decision.conditions:
            result.data["editable_disclosure_template"] = (
                "I used [AI tool] for [permitted activity]. I reviewed and verified its output and sources. [Describe the extent of assistance and the required citation.]"
            )
        self.authorize_scope(owner, request.scope)
        return self.bridge.egress.release(
            result, owner, {"request": request}, tool_name="prepare_academic_assistance"
        )

    def acknowledgment_history(self, owner, revoke_id=None):
        if revoke_id:
            self.read_record(owner, revoke_id, "integrity_ack")
            with self.bridge.store.transaction() as session:
                session.execute(
                    delete(IndependentResource).where(
                        IndependentResource.id == revoke_id,
                        IndependentResource.owner == owner,
                        IndependentResource.kind == "integrity_ack",
                    )
                )
        with self.bridge.store.transaction() as session:
            rows = list(
                session.scalars(
                    select(IndependentResource).where(
                        IndependentResource.owner == owner,
                        IndependentResource.kind == "integrity_ack",
                        IndependentResource.expires_at > self.bridge.retention.clock(),
                    )
                )
            )
        # No course/source text or identifiers are exposed by this metadata-only path.
        return Result(
            summary="Scoped acknowledgment history; these records are not instructor permission.",
            data={
                "acknowledgments": [
                    {
                        "id": r.id,
                        "activity": r.content["activity"],
                        "expires_at": aware(r.expires_at).isoformat(),
                    }
                    for r in rows
                ],
                "revoked": bool(revoke_id),
            },
        )
