from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import Field

from canvas_bridge.domain import Model


class PointsScenario(Model):
    earned_points: Decimal = Field(ge=0, allow_inf_nan=False)
    completed_possible: Decimal = Field(ge=0, allow_inf_nan=False)
    remaining_possible: Decimal = Field(ge=0, allow_inf_nan=False)
    target_percent: Decimal = Field(ge=0, le=100, allow_inf_nan=False)
    policy: Literal["simple_points", "unknown", "unsupported"] = "unknown"
    assumptions: list[str] = Field(default_factory=list, max_length=20)


def points_scenario(request: PointsScenario) -> dict:
    if request.policy != "simple_points":
        return {
            "supported": False,
            "reason": "Exact scenarios require a verified simple-points policy.",
        }
    if request.earned_points > request.completed_possible:
        return {"supported": False, "reason": "Extra credit is outside this policy subset."}
    final = request.completed_possible + request.remaining_possible
    if final == 0:
        return {"supported": False, "reason": "No known possible points."}
    required = max(Decimal(0), request.target_percent / 100 * final - request.earned_points)
    if request.remaining_possible == 0:
        status = "already_met" if required == 0 else "infeasible"
        fraction = None
    else:
        status = (
            "already_met"
            if required == 0
            else ("infeasible" if required > request.remaining_possible else "conditional")
        )
        fraction = required / request.remaining_possible * 100
    return {
        "supported": True,
        "classification": "hypothetical_scenario",
        "status": status,
        "required_remaining_points": str(required),
        "required_remaining_percent": (
            str(fraction.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
            if fraction is not None
            else None
        ),
        "basis": request.model_dump(mode="json"),
        "limitations": [
            "Conditional on the stated published-work totals and simple-points assumptions.",
            "No weighted groups, drops, extra credit, late penalties, overrides or hidden work modeled.",
            "This is not a guaranteed final grade or a reconstruction of unknown Canvas policy.",
        ],
    }
