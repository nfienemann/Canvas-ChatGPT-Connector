"""Validate grounding references, never claim to judge scientific correctness."""

import re
from typing import Literal

from pydantic import Field, model_validator

from canvas_bridge.domain import DomainError, Model


class ScientificClaim(Model):
    claim_id: str = Field(min_length=1, max_length=50)
    statement: str = Field(min_length=1, max_length=1500)
    basis: Literal["visual_observation", "source_text", "inference", "scientific_context"]
    # These identify the exact attributed observations or exact source quotation.
    visual_observation_indexes: list[int] = Field(default_factory=list, max_length=20)
    source_quote: str | None = Field(default=None, min_length=1, max_length=1500)
    based_on: list[str] = Field(default_factory=list, max_length=20)
    uncertainty: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def supported(self):
        if self.basis == "visual_observation":
            if not self.visual_observation_indexes or self.source_quote or self.based_on:
                raise ValueError("Visual claims reference actual visual observations only.")
        elif self.basis == "source_text":
            if not self.source_quote or self.visual_observation_indexes or self.based_on:
                raise ValueError("Text claims require an exact source quotation only.")
        else:
            if (
                not self.based_on
                or not self.uncertainty
                or self.source_quote
                or self.visual_observation_indexes
            ):
                raise ValueError(
                    "Inference/context needs earlier evidence and explicit uncertainty."
                )
        return self


class ScientificExplanation(Model):
    scientific_question: str | None = Field(default=None, max_length=1000)
    claims: list[ScientificClaim] = Field(min_length=1, max_length=20)
    conclusion_support: Literal[
        "supported_within_limits", "partially_supported", "not_supported", "indeterminate"
    ] = "indeterminate"
    conclusion_claim_ids: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def references(self):
        seen = set()
        for claim in self.claims:
            if claim.claim_id in seen or not set(claim.based_on) <= seen:
                raise ValueError(
                    "Claims need unique identifiers and preceding evidence references."
                )
            seen.add(claim.claim_id)
        if not set(self.conclusion_claim_ids) <= seen or (
            self.conclusion_support != "indeterminate" and not self.conclusion_claim_ids
        ):
            raise ValueError("Conclusion assessment requires existing supporting claims.")
        return self


def grounded_explanation(explanation, observation, source_text, locator):
    if explanation is None:
        return None
    if observation.visibility != "visible" or observation.delivery_mode == "unknown":
        raise DomainError(
            "needs_input",
            "Scientific visual explanation requires an attributed report of actual visible pixels.",
            reason_code="VISUAL_DATA_NOT_CONFIRMED",
        )
    for claim in explanation.claims:
        if any(
            type(i) is not int or i < 0 or i >= len(observation.direct_visual_observations)
            for i in claim.visual_observation_indexes
        ):
            raise DomainError(
                "needs_input",
                "A scientific claim references an unavailable visual observation.",
                reason_code="VISUAL_EVIDENCE_REFERENCE_INVALID",
            )
        if claim.source_quote and (source_text is None or claim.source_quote not in source_text):
            raise DomainError(
                "needs_input",
                "A scientific text claim is not anchored in the exact current page or slide text.",
                reason_code="SCIENTIFIC_TEXT_ANCHOR_MISMATCH",
            )

        def numbers(value):
            return set(re.findall(r"(?<![\w.])[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", value))

        if claim.basis in {"visual_observation", "source_text"}:
            readings = [n for p in observation.panels for n in p.numerical_readings]
            allowed = (
                numbers(claim.source_quote)
                if claim.source_quote
                else set().union(
                    *(numbers(n.value) for n in readings),
                    numbers(observation.figure_number.value or ""),
                    *(numbers(p.panel_label.value or "") for p in observation.panels),
                )
            )
            if not numbers(claim.statement) <= allowed:
                raise DomainError(
                    "needs_input",
                    "Numerical claims require matching structured visual readings or exact quoted source values.",
                    reason_code="SCIENTIFIC_NUMBER_UNGROUNDED",
                )
            if (
                claim.basis == "visual_observation"
                and numbers(claim.statement)
                and any(
                    n.precision == "visual_estimate" and numbers(n.value) & numbers(claim.statement)
                    for n in readings
                )
                and not claim.uncertainty
            ):
                raise DomainError(
                    "needs_input",
                    "A visual estimate must retain explicit uncertainty.",
                    reason_code="SCIENTIFIC_ESTIMATE_UNLABELED",
                )
    return {
        "schema_version": "scientific-explanation-3",
        "direct_explanation": "\n".join(c.statement for c in explanation.claims),
        "scientific_question": explanation.scientific_question,
        "observed_visual_evidence": list(observation.direct_visual_observations),
        "supporting_textual_evidence": [
            c.source_quote for c in explanation.claims if c.source_quote
        ],
        "scientific_context": [
            c.model_dump(mode="json") for c in explanation.claims if c.basis == "scientific_context"
        ],
        "claims": [c.model_dump(mode="json") for c in explanation.claims],
        "conclusion_support": explanation.conclusion_support,
        "conclusion_claim_ids": explanation.conclusion_claim_ids,
        "limitations": explanation.limitations,
        "source_locator": locator,
        "verification": "references_checked_scientific_interpretation_not_independently_verified",
        "model_visibility_confirmation": "attributed_assistant_report_not_server_proof",
    }
