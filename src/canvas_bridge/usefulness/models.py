"""Bounded proposals; none of these inputs grants permission or records consent."""

from typing import Literal

from pydantic import Field, model_validator

from canvas_bridge.academic.independent_models import DocumentSelection, IndependentWork, Ref
from canvas_bridge.domain import Model
from canvas_bridge.planning import PlanRequest


class Passage(Model):
    document_id: Ref
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    part: int = Field(ge=1, le=200)
    start: int = Field(ge=0, le=200_000)
    end: int = Field(ge=1, le=200_000)
    quote: str = Field(min_length=1, max_length=2000)


class Improvement(Model):
    feedback: Passage
    work_key: Ref
    kind: Literal["required_correction", "suggestion", "praise", "unclear"]
    action: str = Field(min_length=1, max_length=1000)
    reference: Passage | None = None
    practice: Literal[
        "control_purpose", "result_implication", "claim_evidence", "axis_units", "clarify"
    ]


class UsefulnessRequest(Model):
    operation: Literal["obligations", "feedback", "resume", "changes"]
    course: str = Field(default="independent", min_length=1, max_length=100)
    documents: list[DocumentSelection] = Field(default_factory=list, max_length=5)
    improvements: list[Improvement] = Field(default_factory=list, max_length=3)
    goal_id: Ref | None = None
    baseline_revision: Ref | None = None
    plan: PlanRequest | None = None
    minutes: int | None = Field(default=None, ge=1, le=180)
    cursor: str | None = Field(default=None, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def bounded(self):
        if len({d.document_id for d in self.documents}) != len(self.documents):
            raise ValueError("Select each source once.")
        if len(self.model_dump_json().encode()) > 40_000:
            raise ValueError("Narrow the request to 40 KB.")
        return self


class Attempt(Model):
    goal_id: Ref
    session_id: Ref
    concept: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=1500)
    response: str = Field(default="", max_length=3000)
    evidence_kind: Literal[
        "self_report", "practice_response", "deterministic_check", "host_interpretation"
    ]
    observation: str = Field(default="", max_length=1000)
    next_exercise: str = Field(default="", max_length=1000)
    rejected: bool = False
    check: Literal["control_purpose", "none"] = "none"

    @model_validator(mode="after")
    def bounded(self):
        if len(self.model_dump_json().encode()) > 8000:
            raise ValueError("Save at most 8 KB per attempt.")
        if self.evidence_kind in {"practice_response", "deterministic_check"} and not self.response:
            raise ValueError("An attempted response is required.")
        if self.evidence_kind == "deterministic_check" and self.check == "none":
            raise ValueError("Select a supported deterministic check.")
        return self


class PersonalTask(Model):
    work: IndependentWork
    # No field for official submissions, identity, rights or instructor authority.
