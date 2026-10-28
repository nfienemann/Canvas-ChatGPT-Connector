"""Concept relationships and separate exposure, practice and assessment evidence."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.processes.models import Model, Ref, SourceTag


class Concept(Model):
    id: Ref
    label: str = Field(min_length=1, max_length=200)
    sources: tuple[SourceTag, ...] = Field(min_length=1, max_length=100)


class ConceptRelationship(Model):
    left: Ref
    right: Ref
    kind: Literal["equivalent", "prerequisite", "related"]
    basis: Literal["explicit", "inferred", "user_corrected"]
    sources: tuple[SourceTag, ...] = Field(min_length=1, max_length=100)


class LearningEvidence(Model):
    concept_id: Ref
    kind: Literal["exposure", "practice", "assessed_performance"]
    source: SourceTag
    observed_at: AwareDatetime
    review_at: AwareDatetime
    score: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    possible: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    verified_assessment: bool = False

    @model_validator(mode="after")
    def valid(self):
        if (self.score is None) != (self.possible is None) or (
            self.score is not None and self.score > self.possible
        ):
            raise ValueError("Scores require a valid denominator.")
        if self.review_at <= self.observed_at:
            raise ValueError("Review date must follow observation.")
        if self.verified_assessment and (
            self.kind != "assessed_performance"
            or self.source.origin not in {"institutional", "synthetic"}
        ):
            raise ValueError("Assessment verification requires provider evidence.")
        return self


def competency(concept, evidence, *, now):
    rows = [e for e in evidence if e.concept_id == concept.id and e.observed_at <= now]
    current = [e for e in rows if now < min(e.review_at, e.source.expires_at)]
    assessed = [
        e
        for e in current
        if e.kind == "assessed_performance" and e.verified_assessment and e.score is not None
    ]
    practice = [e for e in current if e.kind == "practice"]
    category = (
        "assessed_evidence_available"
        if assessed
        else "practiced"
        if practice
        else "exposed"
        if current
        else "review_due"
        if rows
        else "unknown"
    )
    return {
        "concept_id": concept.id,
        "category": category,
        "mastery_certified": False,
        "evidence": [e.model_dump(mode="json") for e in rows],
        "next_step": "retrieval_practice"
        if category in {"unknown", "exposed", "practiced"}
        else "refresh_prerequisites"
        if category == "review_due"
        else "review_assessed_strengths_and_gaps",
        "grade_implication": "not_established",
    }


def related_concepts(concepts, relationships, concept_id):
    by_id = {c.id: c for c in concepts}
    if concept_id not in by_id:
        raise ValueError("Unknown concept.")
    result = []
    for edge in relationships:
        if edge.left not in by_id or edge.right not in by_id:
            raise ValueError("Unknown relationship endpoint.")
        if concept_id in {edge.left, edge.right}:
            result.append(edge.model_dump(mode="json"))
    return result
