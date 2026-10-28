"""Authorized bounded discovery. Text is evidence, never executable instructions."""

import json
import re
from datetime import timedelta
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import DomainError, Model, utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.integrity.models import Coverage, PolicySource, Verification
from canvas_bridge.integrity.parser import AI, parse
from canvas_bridge.storage import aware

POLICY_NAMES = re.compile(
    r"syllabus|course[ _-]*(?:outline|information)|academic[ _-]*integrity|ai[ _-]*(?:use|usage|policy)",
    re.I,
)


class InstitutionalReview(Model):
    """Private operator-reviewed public source, not a student permission toggle.

    Reviewed text is hash bound; the same conservative parser interprets it. This
    profile cannot suppress a source prohibition or assert tool approval. No public
    lookup is attempted unless a separately implemented authorized adapter exists.
    """

    institution: str = Field(min_length=1, max_length=100)
    official_hosts: frozenset[str] = Field(min_length=1, max_length=8)
    checked_at: AwareDatetime
    review_due_at: AwareDatetime
    sources: list[PolicySource] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def evidence_bound(self):
        if not timedelta(0) < self.review_due_at - self.checked_at <= timedelta(days=30):
            raise ValueError("Public policy review must expire within 30 days.")
        for s in self.sources:
            url = urlsplit(s.uri)
            if (
                url.scheme != "https"
                or url.hostname not in self.official_hosts
                or url.username
                or url.password
                or url.port not in {None, 443}
                or s.authority not in {"institution", "department", "illustrative"}
                or s.supersedes
                or s.course_id
                or s.assessment_id
                or s.verification != Verification.OFFICIAL_SOURCE_CONFIRMED
            ):
                raise ValueError("Public review must identify a scoped official policy source.")
            if s.version != fingerprint(s.parts):
                raise ValueError("Policy content hash does not match its reviewed passages.")
        return self


def gap(ident, kind, coverage, *, course=None, limitation=None):
    return PolicySource(
        id=ident,
        version=fingerprint([kind, str(coverage), limitation]),
        kind=kind,
        authority="unknown",
        course_id=course,
        retrieved_at=utcnow(),
        coverage=coverage,
        limitation=limitation,
    )


def public_policy_sources(bridge, institution):
    """Offline public-policy adapter; never sends private queries or follows URLs."""
    path = bridge.settings.integrity_policy_reviews_file
    if path:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 500_000:
                raise ValueError("Invalid review file")
            rows = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list) or len(rows) > 30:
                raise ValueError("Invalid review list")
            reviews = [InstitutionalReview.model_validate(r) for r in rows]
            matches = [r for r in reviews if r.institution == institution]
            if len(matches) == 1:
                review = matches[0]
                stale = not review.checked_at <= bridge.retention.clock() < review.review_due_at
                return [
                    s.model_copy(
                        update={
                            "coverage": Coverage.STALE if stale else s.coverage,
                            "expires_at": review.review_due_at,
                        }
                    )
                    for s in review.sources
                ], "STALE" if stale else "REVIEWED_OFFLINE_REFERENCE"
        except (OSError, ValueError, TypeError):
            return [
                gap(
                    "institution-review",
                    "institution_policy",
                    Coverage.UNREADABLE,
                    limitation="Public policy review could not be validated.",
                )
            ], "REVIEW_REQUIRED"
    if institution == "synthetic" and bridge.synthetic and bridge.settings.profile == "synthetic":
        return [
            gap(
                "fictional-institution",
                "institution_policy",
                Coverage.NOT_FOUND,
                limitation="Fictional test institution has no higher-level requirement.",
            )
        ], "SYNTHETIC_FIXTURE"
    return [
        gap(
            "institution-policy",
            "institution_policy",
            Coverage.NOT_CHECKED,
            limitation="LOOKUP_UNAVAILABLE: no supported public lookup or current reviewed reference is configured.",
        )
    ], "LOOKUP_UNAVAILABLE"


def from_document(doc, *, assessment=None):
    kind = doc.get("source_type", "unknown")
    official = kind in {"syllabus", "assignment_description", "assignment_rubric"}
    # Announcement authorship and arbitrary course-file authorship are not inferred
    # from location or filename. They may restrict pending review, never grant use.
    parts = doc.get("parts", [])
    return PolicySource(
        id=doc["id"],
        version=fingerprint([doc.get("version"), parts]),
        kind=kind,
        authority="instructor" if official else "unknown",
        verification=Verification.OFFICIAL_SOURCE_CONFIRMED
        if official
        else Verification.NO_EVIDENCE,
        course_id=doc.get("course_id"),
        assessment_id=assessment,
        uri=doc.get("url", ""),
        retrieved_at=doc["retrieved_at"],
        coverage=Coverage.READ_COMPLETE if doc.get("complete") else Coverage.READ_PARTIAL,
        parts=parts,
        issuer="course:" + str(doc.get("course_id")),
        limitation=None
        if official
        else "Authorship and adoption of this source are not independently established.",
    )


def bundle_sources(bundle, assessment_id):
    sources = [from_document(doc) for doc in bundle["documents"]]
    assignment = bundle["assignments"].get(assessment_id)
    if assessment_id and not assignment:
        raise DomainError(
            "permission_denied",
            "The assessment is not available in this course.",
            reason_code="INTEGRITY_ASSESSMENT_UNAVAILABLE",
        )
    if assignment:
        sources.extend(
            from_document(assignment[k], assessment=assessment_id)
            for k in ("instructions", "rubric")
            if assignment[k].get("parts")
            and any(p.get("text", "").strip() for p in assignment[k]["parts"])
        )
    if not any(s.kind == "syllabus" for s in sources):
        status = next(
            (p["state"] for p in bundle.get("policy_discovery", []) if p["kind"] == "syllabus"),
            "NOT_CHECKED",
        )
        sources.append(
            gap(
                "syllabus",
                "syllabus",
                Coverage(status),
                course=bundle["course"].id,
                limitation="Syllabus HTML discovery status; file and institutional coverage is separate.",
            )
        )
    for record in bundle.get("material_discovery", {}).get("documents", []):
        if record.get("state") in {"reviewed", "partially_reviewed"}:
            continue
        state = {"skipped": Coverage.NOT_CHECKED, "unreadable": Coverage.UNREADABLE}.get(
            record.get("state"), Coverage.UNREADABLE
        )
        if record.get("status") == "permission_denied":
            state = Coverage.ACCESS_DENIED
        sources.append(
            gap(
                record["material_id"],
                "policy_candidate",
                state,
                course=bundle["course"].id,
                limitation=record.get("reason_code"),
            )
        )
    for entry in bundle["coverage"]:
        if entry.state not in {"complete", "not_applicable"}:
            sources.append(
                gap(
                    "coverage-" + entry.resource,
                    entry.resource,
                    Coverage.READ_PARTIAL,
                    course=bundle["course"].id,
                    limitation=entry.warning,
                )
            )
    return sources


def local_sources(bridge, owner, scope):
    sources, citations, hashes = [], [], {}
    for ident in scope.document_ids:
        row = bridge.independent.require(owner, ident)
        parsed = row.content["parsed"]
        parts = [
            {"text": p.get("text", ""), "locator": f"Part {i}"}
            for i, p in enumerate(parsed.get("pages", []), 1)
        ]
        complete = parsed.get("coverage") in {"text_only", "complete"} and all(
            p.get("state") not in {"failed", "unreadable", "partial", "unknown"}
            for p in parsed.get("pages", [])
        )
        sources.append(
            PolicySource(
                id=ident,
                version=row.version_hash,
                kind="local_document",
                authority="student",
                verification=Verification.STUDENT_SUPPLIED_UNVERIFIED,
                course_id=scope.course_id or scope.local_course,
                retrieved_at=aware(row.created_at),
                expires_at=aware(row.expires_at),
                coverage=Coverage.READ_COMPLETE if complete else Coverage.READ_PARTIAL,
                parts=parts,
                limitation="Student-supplied evidence is not instructor verification.",
            )
        )
        citations.append(bridge.independent.evidence(row))
        hashes[ident] = row.version_hash
    return sources, citations, hashes


async def discover(bridge, owner, scope, *, bundle=None):
    sources, citations, hashes = local_sources(bridge, owner, scope)
    epoch = None
    exam = False
    if scope.connection_id:
        from canvas_bridge.academic_intelligence import collect_course
        from canvas_bridge.approval_policy import CATEGORIES

        bridge.connection_policy(owner, scope.connection_id, CATEGORIES)
        bundle = bundle or await collect_course(
            bridge,
            owner,
            scope.connection_id,
            scope.course_id,
            purpose="integrity",
            work_id=scope.assessment_id,
        )
        conn, _ = bridge.selected(owner, scope.connection_id, [scope.course_id])
        if conn.epoch != bundle["connection"].epoch:
            raise DomainError(
                "source_changed", "Course selection changed during integrity discovery."
            )
        epoch, institution = conn.epoch, conn.institution
        sources.extend(bundle_sources(bundle, scope.assessment_id))
        citations.extend(bundle["sources"])
        for item in bundle["items"]:
            if item["id"] == scope.assessment_id:
                exam = item.get("kind") in {"quiz", "exam"} or bool(
                    re.search(r"\bquiz|\bexam", item.get("title", ""), re.I)
                )
    else:
        institution = scope.institution
        # Independent fictional fixtures explicitly choose the fictional profile;
        # real local imports never inherit it from the service deployment mode.
    public, lookup = public_policy_sources(bridge, institution)
    sources.extend(public)
    return {
        "sources": sources,
        "citations": citations,
        "hashes": hashes,
        "epoch": epoch,
        "institution": institution,
        "lookup": lookup,
        "exam": exam,
        "bundle": bundle,
    }


def minimal_sources(sources):
    """Retain relevant passages only, not full assignments or uploaded drafts."""
    result = []
    for source in sources:
        exceeded = len(source.parts) > 200 or any(
            len(p.get("text", "")) > 100_000 for p in source.parts
        )
        parts = [{"locator": r.locator, "text": r.passage} for r in parse(source)]
        for part in source.parts:
            for paragraph in re.split(r"\n\s*\n", part.get("text", "")):
                if AI.search(paragraph) and not parts:
                    parts.append({"locator": part.get("locator", "Text"), "text": paragraph[:2500]})
        parts = list({fingerprint(p): p for p in parts}.values())
        result.append(
            source.model_copy(
                update={
                    "parts": parts[:200],
                    "coverage": Coverage.READ_PARTIAL
                    if exceeded or len(parts) > 200
                    else source.coverage,
                }
            )
        )
    return result
