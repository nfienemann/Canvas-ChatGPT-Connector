"""Pure activity-specific decisions. No network, operator bypass or model approval."""

from datetime import timedelta

from canvas_bridge.domain import opaque_id, utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.integrity.models import (
    CATEGORIES,
    SUBSTANTIVE,
    VERSION,
    Activity,
    Category,
    Coverage,
    Decision,
    PolicySource,
    State,
)
from canvas_bridge.integrity.parser import parse


def policy_version(sources):
    return fingerprint(
        [
            s.model_dump(mode="json", exclude={"retrieved_at"})
            for s in sorted(sources, key=lambda s: s.id)
        ]
    )


def evaluate_academic_assistance(
    activity,
    sources: list[PolicySource],
    *,
    assessment_id=None,
    exam=False,
    now=None,
    acknowledgment=None,
):
    now = now or utcnow()
    version = policy_version(sources)
    decision = Decision(
        id=opaque_id(),
        policy_version=version,
        activity=activity,
        category=CATEGORIES[activity],
        state=State.NO_POLICY_FOUND,
        allowed=False,
        reason_code="INTEGRITY_ACKNOWLEDGMENT_REQUIRED",
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        limitations=[
            "Enforces Bridge-controlled operations only; independent host conversations are outside this boundary.",
            "Discovery is bounded and interpretation recognizes a reviewed subset of English clauses; unread sources and unfamiliar wording may require instructor clarification.",
        ],
    )

    def outcome(state, allowed, code, *, permission=False, eligible=False):
        decision.state, decision.allowed, decision.reason_code = state, allowed, code
        decision.permission_established, decision.acknowledgment_eligible = permission, eligible
        if (
            eligible
            and acknowledgment
            and (
                acknowledgment.get("policy_version") == version
                and acknowledgment.get("decision_version") == VERSION
                and acknowledgment.get("activity") == activity
                and acknowledgment.get("valid") is True
            )
        ):
            decision.allowed, decision.acknowledgment_valid = True, True
            decision.reason_code = "INTEGRITY_UNCERTAINTY_ACKNOWLEDGED"
            decision.limitations.append(
                "Permission remains unconfirmed. Risk acknowledgment is not instructor authorization."
            )
        return decision

    if activity == Activity.FALSE_DECLARATION:
        return outcome(State.PROHIBITED_CONFIRMED, False, "INTEGRITY_FALSE_AUTHORSHIP_CLAIM")
    if CATEGORIES[activity] in {Category.ADMINISTRATION, Category.PLANNING}:
        return outcome(State.PERMITTED_CONDITIONAL, True, "INTEGRITY_ADMINISTRATIVE_SCOPE")

    applicable = [s for s in sources if s.assessment_id is None or s.assessment_id == assessment_id]
    # Supersession is only accepted from reviewed source lineage, same issuer and
    # authority, matching scope, a later effective date, and complete extraction.
    superseded = set()
    for newer in applicable:
        for older in applicable:
            if (
                older.id + "@" + older.version in newer.supersedes
                and newer.authoritative
                and older.authoritative
                and newer.authority == older.authority
                and newer.issuer
                and newer.issuer == older.issuer
                and newer.course_id == older.course_id
                and newer.assessment_id == older.assessment_id
                and newer.coverage == Coverage.READ_COMPLETE
                and newer.effective_at
                and older.effective_at
                and older.effective_at < newer.effective_at <= now
                and (newer.expires_at is None or newer.expires_at > now)
            ):
                superseded.add(older.id)
    applicable = [s for s in applicable if s.id not in superseded]
    by_id = {s.id: s for s in applicable}
    all_rules = [r for s in applicable for r in parse(s)]
    rules = [
        r
        for r in all_rules
        if activity in r.activities and (not r.exam_only or exam or activity == Activity.ANSWER)
    ]
    decision.rules = rules
    authoritative = [r for r in rules if by_id[r.source_id].authoritative]
    denials = [r for r in authoritative if r.effect == "deny"]
    allows = [r for r in authoritative if r.effect == "allow"]
    uncertain = any(
        s.coverage not in {Coverage.READ_COMPLETE, Coverage.NOT_FOUND} for s in applicable
    )
    stale = any(
        (s.expires_at and s.expires_at <= now) or (s.effective_at and s.effective_at > now)
        for s in applicable
    )
    if denials:
        if allows:
            # A general positive statement cannot override a specific prohibition.
            specific_deny = all(by_id[r.source_id].assessment_id or r.exam_only for r in denials)
            general_allow = all(
                not by_id[r.source_id].assessment_id and not r.exam_only for r in allows
            )
            if not (specific_deny and general_allow):
                return outcome(State.CONFLICTING, False, "INTEGRITY_POLICY_CONFLICT")
        if stale or any(by_id[r.source_id].coverage != Coverage.READ_COMPLETE for r in denials):
            return outcome(State.REVIEW_REQUIRED, False, "INTEGRITY_PROHIBITION_REVIEW_REQUIRED")
        return outcome(State.PROHIBITED_CONFIRMED, False, "INTEGRITY_EXPLICIT_PROHIBITION")
    if any(r.effect == "deny" for r in rules):
        return outcome(State.REVIEW_REQUIRED, False, "INTEGRITY_UNVERIFIED_RESTRICTION")
    mandatory = [r for r in authoritative if r.effect == "permission_required"]
    instructor_permission = any(by_id[r.source_id].authority == "instructor" for r in allows)
    if mandatory and not instructor_permission:
        return outcome(State.PERMISSION_REQUIRED, False, "INTEGRITY_INSTRUCTOR_PERMISSION_REQUIRED")
    if any(r.effect == "approved_tool_required" for r in authoritative):
        return outcome(State.PERMISSION_REQUIRED, False, "INTEGRITY_TOOL_APPROVAL_REQUIRED")
    if (
        activity in SUBSTANTIVE
        and not allows
        and any(
            r.effect == "allow"
            and r.activities < SUBSTANTIVE
            and by_id[r.source_id].authoritative
            and r.activities & SUBSTANTIVE
            for r in all_rules
        )
    ):
        return outcome(State.PERMISSION_REQUIRED, False, "INTEGRITY_ACTIVITY_OUTSIDE_PERMISSION")
    if stale:
        return outcome(State.REVIEW_REQUIRED, False, "INTEGRITY_POLICY_VERSION_REVIEW_REQUIRED")
    if activity not in SUBSTANTIVE and not any(r.effect == "ambiguous" for r in rules):
        return outcome(State.PERMITTED_CONDITIONAL, True, "INTEGRITY_LEARNING_ONLY")
    if uncertain or not applicable:
        return outcome(State.POLICY_UNAVAILABLE, False, "INTEGRITY_POLICY_COVERAGE_INCOMPLETE")
    if (
        any(r.effect in {"permission_required", "approved_tool_required"} for r in rules)
        and not mandatory
    ):
        return outcome(State.REVIEW_REQUIRED, False, "INTEGRITY_UNVERIFIED_REQUIREMENT")
    if any(r.condition for r in rules if r.effect == "ambiguous"):
        return outcome(State.REVIEW_REQUIRED, False, "INTEGRITY_POLICY_VERSION_REVIEW_REQUIRED")
    if any(r.effect == "ambiguous" for r in authoritative):
        return outcome(
            State.AMBIGUOUS, False, "INTEGRITY_ACKNOWLEDGMENT_REQUIRED", eligible=not allows
        )
    if allows:
        decision.conditions = sorted(
            {r.condition for r in rules if r.condition and r.effect in {"allow", "disclosure"}}
        )
        return outcome(
            State.PERMITTED_CONDITIONAL if decision.conditions else State.PERMITTED_EXPLICIT,
            True,
            "INTEGRITY_ACTIVITY_PERMITTED",
            permission=True,
        )
    if rules:
        return outcome(State.AMBIGUOUS, False, "INTEGRITY_ACKNOWLEDGMENT_REQUIRED", eligible=True)
    return outcome(State.NO_POLICY_FOUND, False, "INTEGRITY_ACKNOWLEDGMENT_REQUIRED", eligible=True)
