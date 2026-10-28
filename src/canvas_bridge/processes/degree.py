"""Unofficial catalog-scoped projections; never a graduation certification."""

from typing import Literal

from pydantic import AwareDatetime, Field

from canvas_bridge.processes.models import Model, Ref, SourceTag


class CourseCredit(Model):
    course: Ref
    credits: float = Field(ge=0, le=100, allow_inf_nan=False)
    completed: bool = False
    verified: bool = False
    planned_term: int | None = Field(default=None, ge=1, le=50)
    source: SourceTag


class CourseRule(Model):
    course: Ref
    prerequisites: tuple[Ref, ...] = ()
    corequisites: tuple[Ref, ...] = ()


class ElectiveBasket(Model):
    id: Ref
    eligible: frozenset[str] = Field(min_length=1, max_length=200)
    minimum_credits: float = Field(gt=0, le=200, allow_inf_nan=False)


class Substitution(Model):
    required: Ref
    replacement: Ref
    approval_source: SourceTag
    verified_approval: bool = False


class DegreeRules(Model):
    institution: Ref
    program: Ref
    concentration: Ref | None = None
    catalog_year: int | None = Field(default=None, ge=1900, le=2200)
    version: Ref
    minimum_credits: float = Field(gt=0, le=500, allow_inf_nan=False)
    required: frozenset[str] = frozenset()
    courses: tuple[CourseRule, ...] = Field(default=(), max_length=200)
    baskets: tuple[ElectiveBasket, ...] = Field(default=(), max_length=30)
    substitutions: tuple[Substitution, ...] = Field(default=(), max_length=30)
    source: SourceTag
    coverage: Literal["complete", "partial", "unknown"] = "unknown"


class OfficialAudit(Model):
    catalog_year: int
    program: Ref
    concentration: Ref | None = None
    observed_at: AwareDatetime
    source: SourceTag
    reported_status: Literal["requirements_remaining", "requirements_reported_satisfied", "unknown"]


def project_degree(rules, coursework, *, now, official_audit=None):
    by_course = {c.course: c for c in coursework}
    if len(by_course) != len(coursework) or len(coursework) > 200:
        raise ValueError("Duplicate coursework or projection budget exceeded.")
    if any(
        c.source.scope.principal != rules.source.scope.principal
        or c.source.scope.institution != rules.institution
        for c in coursework
    ):
        raise ValueError("Coursework is outside the degree scope.")
    limitations = []
    if rules.catalog_year is None:
        limitations.append("CATALOG_YEAR_MISSING")
    if rules.coverage != "complete" or rules.source.expires_at <= now:
        limitations.append("CATALOG_RULES_INCOMPLETE_OR_STALE")
    completed = {
        c.course for c in coursework if c.completed and c.verified and c.source.expires_at > now
    }
    if any(c.completed and c.course not in completed for c in coursework):
        limitations.append("COURSE_COMPLETION_UNVERIFIED")
    fulfilled = set(completed)
    for substitution in rules.substitutions:
        if substitution.replacement in completed:
            if (
                substitution.verified_approval
                and substitution.approval_source.expires_at > now
                and substitution.approval_source.origin in {"institutional", "synthetic"}
            ):
                fulfilled.add(substitution.required)
            else:
                limitations.append("SUBSTITUTION_APPROVAL_REQUIRED")
    blocked = []
    for rule in rules.courses:
        planned = by_course.get(rule.course)
        if not planned or planned.planned_term is None:
            continue
        for prerequisite in rule.prerequisites:
            other = by_course.get(prerequisite)
            if prerequisite not in fulfilled and not (
                other and other.planned_term and other.planned_term < planned.planned_term
            ):
                blocked.append(
                    {"course": rule.course, "requires": prerequisite, "kind": "prerequisite"}
                )
        for corequisite in rule.corequisites:
            other = by_course.get(corequisite)
            if corequisite not in fulfilled and not (
                other and other.planned_term and other.planned_term <= planned.planned_term
            ):
                blocked.append(
                    {"course": rule.course, "requires": corequisite, "kind": "corequisite"}
                )
    baskets, used = [], set()
    for basket in rules.baskets:
        candidates = basket.eligible & completed
        if candidates & used:
            limitations.append("ELECTIVE_ALLOCATION_REVIEW_REQUIRED")
        used |= candidates
        credits = sum(by_course[c].credits for c in candidates)
        baskets.append(
            {
                "id": basket.id,
                "credits": credits,
                "minimum": basket.minimum_credits,
                "remaining": max(0, basket.minimum_credits - credits),
                "courses": sorted(candidates),
            }
        )
    total = sum(by_course[c].credits for c in completed)
    assumed_credits = sum(
        c.credits for c in coursework if c.completed and c.course not in completed
    )
    audit = None
    if official_audit:
        if (
            official_audit.catalog_year == rules.catalog_year
            and official_audit.program == rules.program
            and official_audit.concentration == rules.concentration
            and official_audit.source.scope == rules.source.scope
            and official_audit.source.origin in {"institutional", "synthetic"}
            and official_audit.observed_at <= now < official_audit.source.expires_at
        ):
            audit = official_audit.model_dump(mode="json")
        else:
            limitations.append("OFFICIAL_AUDIT_SCOPE_OR_FRESHNESS_MISMATCH")
    return {
        "status": "provisional" if limitations else "projection",
        "unofficial": True,
        "certifies_graduation": False,
        "preferred_reference": "official_audit_snapshot" if audit else "catalog_projection",
        "official_audit": audit,
        "catalog_year": rules.catalog_year,
        "program": rules.program,
        "concentration": rules.concentration,
        "rule_version": rules.version,
        "credits": total,
        "unverified_completed_credits": assumed_credits,
        "what_if_credits_if_confirmed": total + assumed_credits,
        "credits_remaining": max(0, rules.minimum_credits - total),
        "required_remaining": sorted(rules.required - fulfilled),
        "elective_baskets": baskets,
        "blocked_plan": blocked,
        "limitations": sorted(set(limitations)),
        "source": rules.source.model_dump(mode="json"),
    }
