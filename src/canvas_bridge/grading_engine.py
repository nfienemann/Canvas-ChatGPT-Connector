"""Legacy grade-tool vocabulary; arithmetic lives in the provider-neutral core."""

from decimal import Decimal
from typing import Literal

from canvas_bridge.academic.grade_engine import ENGINE as ENGINE
from canvas_bridge.academic.grade_engine import GradeAssessment as GradeAssessment
from canvas_bridge.academic.grade_engine import GradeGroup as GradeGroup
from canvas_bridge.academic.grade_engine import GradePolicy as _GradePolicy
from canvas_bridge.academic.grade_engine import GradeScenario as GradeScenario
from canvas_bridge.academic.grade_engine import Mode as Mode
from canvas_bridge.academic.grade_engine import PolicyReview as PolicyReview
from canvas_bridge.academic.grade_engine import calculate as calculate
from canvas_bridge.academic.grade_engine import digest as digest
from canvas_bridge.academic.grade_engine import display as display
from canvas_bridge.academic.grade_engine import number as number


class GradePolicy(_GradePolicy):
    basis: Literal["canvas", "syllabus"] = "canvas"


def reconcile(
    reported: dict,
    canvas: dict,
    syllabus: dict | None,
    canvas_policy: GradePolicy,
    syllabus_policy: GradePolicy | None,
    *,
    reported_comparable: bool,
) -> dict:
    """Never promote student interpretation or a numerical gap to confirmed error."""
    reported_pct = number(reported.get("current_score"))
    estimate = number(syllabus.get("calculated_percentage")) if syllabus else None
    reproduced = number(canvas.get("calculated_percentage"))
    result = {
        "outcome": "insufficient_evidence",
        "canvas_reported_percentage": reported.get("current_score"),
        "canvas_reproduced_percentage": display(reproduced),
        "syllabus_estimate_percentage": display(estimate),
        "difference_percentage_points": display(estimate - reported_pct)
        if estimate is not None and reported_pct is not None
        else None,
        "configuration_differences": [],
        "explanations": [],
        "verification": "indeterminate",
        "statement": "A difference does not establish a grading error. Syllabus applicability and unseen adjustments require confirmation.",
    }
    if syllabus_policy and syllabus_policy.method != "unknown":
        if canvas_policy.method != syllabus_policy.method:
            result["configuration_differences"].append(
                {
                    "field": "grading_method",
                    "canvas": canvas_policy.method,
                    "syllabus": syllabus_policy.method,
                }
            )
        expected = {g.id: g for g in syllabus_policy.groups}
        for g in canvas_policy.groups:
            if g.id in expected and g.weight != expected[g.id].weight:
                result["configuration_differences"].append(
                    {
                        "category": g.name,
                        "canvas_weight": str(g.weight),
                        "syllabus_weight": str(expected[g.id].weight),
                    }
                )
    if not reported_comparable or reported_pct is None or estimate is None or reproduced is None:
        result["explanations"].append(
            "Comparable reported grade, reproducible Canvas configuration, or reviewed syllabus policy is missing."
        )
        return result
    delta = abs(estimate - reported_pct)
    canvas_delta = abs(reproduced - reported_pct)
    result["verification"] = "estimated_policy_comparison"
    if delta <= Decimal("0.01") and canvas_delta <= Decimal("0.01"):
        result["outcome"] = "consistent"
        result["explanations"].append(
            "Visible arithmetic agrees within 0.01 percentage point; display rounding is possible, not proven."
        )
    elif canvas_delta <= Decimal("0.01") and result["configuration_differences"]:
        result["outcome"] = "explainable_difference"
        result["explanations"].append(
            "Canvas arithmetic reproduces the reported value; using the reviewed syllabus configuration produces the different estimate."
        )
    else:
        result["outcome"] = "potential_discrepancy"
        result["explanations"].append(
            "The available calculation does not explain the difference. Check policy amendments, periods, visibility, and manual adjustments."
        )
    return result
