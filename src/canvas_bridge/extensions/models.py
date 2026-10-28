"""A closed, loop-free numeric language, not a Python sandbox."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.academic.contracts import Contract, Version, compatible

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
Number = Annotated[
    Decimal,
    Field(
        allow_inf_nan=False, ge=-1_000_000_000, le=1_000_000_000, max_digits=20, decimal_places=8
    ),
]
INPUTS = {"earned_points", "possible_points", "future_possible_points", "future_score_percent"}


class NumericField(Contract):
    type: Literal["decimal"] = "decimal"
    minimum: Number
    maximum: Number

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum > self.maximum:
            raise ValueError("Invalid numeric field bounds.")
        return self


class Operand(Contract):
    ref: Name | None = None
    constant: Number | None = None

    @model_validator(mode="after")
    def one(self):
        if (self.ref is None) == (self.constant is None):
            raise ValueError("Exactly one operand kind is required.")
        return self


class Step(Contract):
    name: Name
    op: Literal["add", "subtract", "multiply", "divide", "min", "max"]
    left: Operand
    right: Operand


class Budget(Contract):
    max_steps: int = Field(default=64, ge=1, le=64)
    max_input_bytes: int = Field(default=4096, ge=128, le=4096)
    max_output_bytes: int = Field(default=4096, ge=128, le=4096)
    max_milliseconds: int = Field(default=100, ge=1, le=100)


class TestVector(Contract):
    inputs: dict[Name, Number] = Field(max_length=4)
    expected: dict[Name, Number] = Field(min_length=1, max_length=12)


class ExtensionManifest(Contract):
    sdk_version: Version
    module_id: Name
    module_version: Version
    normalized_schema: Literal["academic-1"] = "academic-1"
    language: Literal["bounded_decimal_graph_v1"] = "bounded_decimal_graph_v1"
    projection: Literal["grade_points_v1"] = "grade_points_v1"
    required_capabilities: tuple[Literal["get_grade_summary"], ...] = Field(
        min_length=1, max_length=1
    )
    permission_requirements: tuple[Literal["grade_planning"], ...] = Field(
        min_length=1, max_length=1
    )
    inputs: dict[Name, NumericField] = Field(min_length=4, max_length=4)
    outputs: dict[Name, NumericField] = Field(min_length=1, max_length=12)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=64)
    emit: dict[Name, Name] = Field(min_length=1, max_length=12)
    budget: Budget = Field(default_factory=Budget)
    tests: tuple[TestVector, ...] = Field(min_length=2, max_length=16)

    @model_validator(mode="after")
    def graph(self):
        compatible(self.sdk_version)
        if set(self.inputs) != INPUTS or set(self.outputs) != set(self.emit):
            raise ValueError("Schemas must match the v1 projection and emitted fields.")
        known = set(self.inputs)
        if len(self.steps) > self.budget.max_steps:
            raise ValueError("Program exceeds its declared step budget.")
        for step in self.steps:
            if step.name in known or any(
                o.ref is not None and o.ref not in known for o in (step.left, step.right)
            ):
                raise ValueError("Duplicate names, cycles and forward references are forbidden.")
            known.add(step.name)
        if set(self.emit.values()) - known:
            raise ValueError("Unknown output reference.")
        return self
