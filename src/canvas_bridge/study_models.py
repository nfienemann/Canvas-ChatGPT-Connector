"""Bounded voluntary study inputs. No health, disability or inferred personality profile."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.domain import Model
from canvas_bridge.planning import Window
from canvas_bridge.workflow_registry import Ref, VisualReport

Term = Annotated[str, Field(min_length=2, max_length=100, pattern=r"^[\w ()/,-]+$")]


class StudyPreferences(Model):
    difficulty: Literal["introductory", "standard", "advanced"] = "standard"
    session_minutes: int = Field(default=20, ge=5, le=120)
    focus: list[Term] = Field(default_factory=list, max_length=12)
    question_format: Literal["recall", "multiple_choice", "open_ended"] = "recall"
    explanation_depth: Literal["brief", "standard", "detailed"] = "standard"
    practice_frequency_days: int = Field(default=1, ge=1, le=30)
    recommend_reviews: bool = False
    availability: list[Window] = Field(default_factory=list, max_length=14)


class StudyRequest(Model):
    mode: Literal[
        "concept_explanation",
        "active_recall",
        "practice_assessment",
        "figure_practice",
        "concept_comparison",
        "focused_review",
    ]
    material_ids: list[Ref] = Field(min_length=1, max_length=6)
    concept_names: list[Term] = Field(default_factory=list, max_length=20)
    preferences: StudyPreferences = Field(default_factory=StudyPreferences)
    visual_reports: list[VisualReport] = Field(default_factory=list, max_length=2)
    include_history: bool = False

    @model_validator(mode="after")
    def bounded(self):
        self.material_ids = list(dict.fromkeys(self.material_ids))
        self.concept_names = list(dict.fromkeys(self.concept_names))
        if len(self.model_dump_json().encode()) > 48_000:
            raise ValueError("Study inputs exceed the bounded session size.")
        if self.visual_reports and self.mode != "figure_practice":
            raise ValueError("Visual reports are used only for figure practice.")
        return self


class PracticeResponse(Model):
    question_id: Ref
    response: str = Field(min_length=1, max_length=2000)
    assistance_used: bool
    self_reported_confidence: int | None = Field(default=None, ge=0, le=4)


class PracticeSubmission(Model):
    study_receipt: str = Field(min_length=1, max_length=100_000)
    responses: list[PracticeResponse] = Field(min_length=1, max_length=10)
    record_results: bool = False

    @model_validator(mode="after")
    def unique(self):
        if len({r.question_id for r in self.responses}) != len(self.responses):
            raise ValueError("Provide one response per question.")
        if len(self.model_dump_json().encode()) > 120_000:
            raise ValueError("Response batch exceeds the session size limit.")
        return self
