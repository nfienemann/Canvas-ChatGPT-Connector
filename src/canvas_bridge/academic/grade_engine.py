"""Pure, versioned Decimal calculations. No network, persistence, or inferred scores."""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal

from pydantic import Field

from canvas_bridge.domain import Model

ENGINE = "grade-audit-1"
Mode = Literal["current_graded", "syllabus_current", "projected_final", "required_score"]


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def number(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and abs(result) <= 1_000_000_000 else None
    except InvalidOperation:
        return None


def display(value: Decimal | None):
    return (
        str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        if value is not None
        else None
    )


class GradeGroup(Model):
    id: str
    name: str
    weight: Decimal | None = None
    drop_lowest: int = Field(default=0, ge=0, le=100)
    drop_highest: int = Field(default=0, ge=0, le=100)
    drop_basis: Literal["equal_points", "percentage"] = "equal_points"
    never_drop: list[str] = Field(default_factory=list)


class GradePolicy(Model):
    basis: Literal["provider", "syllabus", "student_input", "canvas"] = "provider"
    method: Literal["points", "weighted", "unknown"] = "unknown"
    groups: list[GradeGroup] = Field(default_factory=list)
    empty_categories: Literal["refuse", "renormalize"] = "refuse"
    blockers: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    version: str = ""


class GradeAssessment(Model):
    id: str
    title: str
    group_id: str | None = None
    possible: Decimal | None = None
    score: Decimal | None = None
    score_state: Literal["posted", "ungraded", "unavailable", "excused", "conflicting"] = (
        "unavailable"
    )
    excluded_reason: str | None = None
    eligibility_verified: bool = True
    submission_state: str = "unknown"
    missing: bool | None = None
    late: bool | None = None
    source_url: str = ""
    source_version: str = ""


class GradeScenario(Model):
    # Opaque assessment references returned by the grading-policy tool.
    scores: dict[str, Decimal] = Field(default_factory=dict, max_length=100)
    target_percent: Decimal | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    acknowledge_visible_scope: bool = False


class PolicyReview(Model):
    """Explicit student interpretation, never an instructor verification."""

    policy_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_rule_ids: list[str] = Field(max_length=100)
    complete_policy_confirmed: bool = False
    applicability_confirmed: bool = False
    empty_categories: Literal["refuse", "renormalize"] = "refuse"


def calculate(
    policy: GradePolicy,
    assessments: list[GradeAssessment],
    mode: Mode = "current_graded",
    scenario: GradeScenario | None = None,
    *,
    evidence_complete: bool = True,
) -> dict:
    scenario = scenario or GradeScenario()
    basis = {
        "engine": ENGINE,
        "policy": policy.model_dump(mode="json"),
        "assessments": [a.model_dump(mode="json") for a in sorted(assessments, key=lambda a: a.id)],
        "mode": mode,
        "scenario": scenario.model_dump(mode="json"),
        "evidence_complete": evidence_complete,
    }
    result = {
        "engine_version": ENGINE,
        "calculation_id": digest(basis),
        "basis": basis,
        "mode": mode,
        "classification": "indeterminate",
        "calculated_percentage": None,
        "categories": [],
        "included_assessments": [],
        "excluded_assessments": [],
        "applied_rules": policy.rule_ids,
        "missing_information": list(policy.blockers),
        "assumptions": [],
        "limitations": [
            "Uses only visible student records; unpublished or hidden work may be absent.",
            "Posted scores are used as returned; late deductions are not applied a second time.",
            "An independent calculation is not an official grade or proof of an instructor error.",
        ],
    }
    missing = result["missing_information"]
    if not evidence_complete:
        missing.append("Grade evidence retrieval is incomplete or contradictory.")
    if policy.method == "unknown":
        missing.append("The grading method is unavailable.")
    if mode == "syllabus_current" and policy.basis != "syllabus":
        missing.append("This mode requires a source-backed syllabus policy.")
    groups = {g.id: g for g in policy.groups}
    if len(groups) != len(policy.groups):
        missing.append("Duplicate grading categories.")
    if len({a.id for a in assessments}) != len(assessments):
        missing.append("Duplicate assessment records.")
    if policy.method == "weighted" and (
        not groups
        or any(g.weight is None or g.weight < 0 for g in groups.values())
        or sum((g.weight or Decimal(0) for g in groups.values()), Decimal(0)) != 100
    ):
        missing.append(
            "Supported weighted policies require known nonnegative weights totaling 100%."
        )
    future = mode in {"projected_final", "required_score"}
    if future and not scenario.acknowledge_visible_scope:
        missing.append(
            "Acknowledge that this scenario covers only the currently visible assessment inventory, not an assured complete final grade."
        )
    if not future and (scenario.scores or scenario.target_percent is not None):
        missing.append("Hypothetical inputs require a scenario calculation mode.")
    by_id = {a.id: a for a in assessments}
    for key, value in scenario.scores.items():
        a = by_id.get(key)
        if (
            a is None
            or a.score_state != "ungraded"
            or a.excluded_reason
            or number(value) is None
            or value < 0
        ):
            missing.append(
                "A hypothetical score must reference an eligible, visible, ungraded assessment and be finite and nonnegative."
            )
    rows = []
    remaining = []
    for a in sorted(assessments, key=lambda a: a.id):
        if a.excluded_reason or a.score_state == "excused":
            result["excluded_assessments"].append(
                {"id": a.id, "reason": a.excluded_reason or "excused"}
            )
            if future and a.excluded_reason == "unpublished_or_restricted":
                missing.append("A restricted assessment cannot be included in a final scenario.")
            continue
        if not a.eligibility_verified:
            missing.append(f"{a.id}: inclusion in course grading has not been verified.")
            continue
        if a.score_state in {"unavailable", "conflicting"}:
            missing.append(
                f"{a.id}: score availability or consistency is unresolved; it is not zero."
            )
            result["excluded_assessments"].append({"id": a.id, "reason": a.score_state})
            continue
        if a.group_id not in groups:
            missing.append(f"{a.id}: assignment category is unknown or ambiguous.")
            continue
        if a.score_state == "ungraded" and not future:
            result["excluded_assessments"].append({"id": a.id, "reason": "ungraded_not_zero"})
            continue
        if a.possible is None or a.possible < 0:
            missing.append(f"{a.id}: possible points are unavailable.")
            continue
        score = a.score
        if a.score_state == "ungraded":
            score = scenario.scores.get(a.id)
            if score is None:
                if mode == "required_score" and a.possible > 0:
                    remaining.append(a)
                    score = Decimal(0)  # Solver endpoint only, never an assumed grade.
                else:
                    missing.append(f"{a.id}: a hypothetical score is required; no zero is assumed.")
                    continue
        if score is None or not score.is_finite():
            missing.append(f"{a.id}: a posted score is unavailable.")
            continue
        rows.append((a, score))
    if missing:
        result["missing_information"] = list(dict.fromkeys(missing))
        return result

    def evaluate(values):
        categories, included, dropped, errors = [], [], [], []
        total_earned, total_possible, contribution, active_weight = (Decimal(0),) * 4
        for group in policy.groups:
            members = [(a, s) for a, s in values if a.group_id == group.id]
            candidates = [(a, s) for a, s in members if a.id not in group.never_drop]
            if group.drop_highest:
                errors.append(f"{group.name}: drop-highest rules are not modeled.")
            if group.drop_lowest and candidates:
                # Default rules require equal denominators. A source-declared
                # percentage rule sorts exact ratios, not retained-grade impact.
                percentage = group.drop_basis == "percentage"
                if any(a.possible == 0 for a, _ in members) or (
                    not percentage and len({a.possible for a, _ in members}) != 1
                ):
                    errors.append(
                        f"{group.name}: drop rules with unequal/zero possible points require an unsupported optimization."
                    )
                else:
                    count = min(group.drop_lowest, len(candidates), max(0, len(members) - 1))
                    ids = {
                        a.id
                        for a, _ in sorted(
                            candidates,
                            key=lambda x: (
                                Fraction(x[1]) / Fraction(x[0].possible) if percentage else x[1],
                                x[0].id,
                            ),
                        )[:count]
                    }
                    dropped.extend(
                        {
                            "id": i,
                            "reason": "drop_lowest_percentage"
                            if percentage
                            else "drop_lowest_equal_points",
                        }
                        for i in sorted(ids)
                    )
                    members = [(a, s) for a, s in members if a.id not in ids]
            earned = sum((s for _, s in members), Decimal(0))
            possible = sum((a.possible for a, _ in members), Decimal(0))
            pct = earned / possible * 100 if possible > 0 else None
            weight = group.weight if policy.method == "weighted" else None
            part = pct * weight / 100 if pct is not None and weight is not None else None
            if policy.method == "weighted" and weight and possible == 0:
                if earned or policy.empty_categories == "refuse" or future:
                    errors.append(
                        f"{group.name}: positive-weight category has no usable denominator; no zero or redistribution assumed."
                    )
            if pct is not None and weight is not None:
                contribution += part
                active_weight += weight
            total_earned += earned
            total_possible += possible
            included.extend(a.id for a, _ in members)
            categories.append(
                {
                    "id": group.id,
                    "name": group.name,
                    "earned_points": str(earned),
                    "possible_points": str(possible),
                    "percentage": display(pct),
                    "configured_weight": str(weight) if weight is not None else None,
                    "contribution_before_normalization": display(part),
                    "status": "graded_or_hypothetical" if possible else "no_usable_denominator",
                }
            )
        if policy.method == "points":
            pct = total_earned / total_possible * 100 if total_possible > 0 else None
        else:
            pct = contribution * 100 / active_weight if active_weight else None
        if pct is None:
            errors.append("No eligible work has a usable denominator.")
        return pct, categories, included, dropped, errors, active_weight

    pct, categories, included, dropped, errors, active = evaluate(rows)
    result.update(categories=categories, included_assessments=included)
    result["excluded_assessments"].extend(dropped)
    if policy.method == "weighted" and active != 100 and not future:
        result["assumptions"].append(
            f"Explicit current-grade normalization uses {active}% active category weight; empty categories contribute neither zero nor weight."
        )
    if mode == "required_score":
        if scenario.target_percent is None:
            errors.append("A target percentage is required.")
        if any(g.drop_lowest or g.drop_highest for g in policy.groups):
            errors.append(
                "Required-score solving with drop rules is unsupported because the function may be nonlinear."
            )
        if not errors:
            remaining_ids = {a.id for a in remaining}
            upper, _, _, _, upper_errors, _ = evaluate(
                [(a, a.possible if a.id in remaining_ids else s) for a, s in rows]
            )
            errors.extend(upper_errors)
            if not errors:
                target = scenario.target_percent
                needed = (
                    Decimal(0)
                    if target <= pct
                    else (target - pct) / (upper - pct) * 100
                    if upper > pct
                    else None
                )
                result["required_score"] = {
                    "target_percentage": str(target),
                    "uniform_remaining_percent": display(needed),
                    "remaining_assessment_ids": sorted(remaining_ids),
                    "outcome_range_percent": [display(pct), display(upper)],
                    "status": "already_met"
                    if target <= pct
                    else "infeasible"
                    if needed is None or needed > 100
                    else "conditional",
                    "meaning": "The same percentage on every remaining eligible assessment; not a unique allocation or guarantee.",
                }
    result["missing_information"] = list(dict.fromkeys(errors))
    if not errors:
        result["classification"] = (
            "hypothetical_scenario"
            if future
            else "estimate"
            if policy.basis == "syllabus"
            else "verified_arithmetic"
        )
        if mode != "required_score":
            result["calculated_percentage"] = display(pct)
        result["assumptions"].append(
            "The supplied policy and visible assessment scope apply; arithmetic verification does not verify instructor policy completeness."
        )
    return result
