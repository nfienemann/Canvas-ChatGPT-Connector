"""Attributed visual reports, not a server-side scientific interpretation engine."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.course_files import authorized, checked_row, fresh_cache, source
from canvas_bridge.domain import DomainError, Model, Result, utcnow
from canvas_bridge.file_download import file_format, file_version
from canvas_bridge.scientific_explanations import ScientificExplanation, grounded_explanation
from canvas_bridge.visual_delivery import lifecycle

Short = Annotated[str, Field(min_length=1, max_length=1000)]
Box = Annotated[list[Annotated[float, Field(ge=0, le=1)]], Field(min_length=4, max_length=4)]


def valid_box(box):
    if box is not None and (box[0] >= box[2] or box[1] >= box[3]):
        raise ValueError("Use normalized left, top, right, bottom image coordinates.")


class VisualField(Model):
    status: Literal["observed", "unknown", "not_readable"] = "unknown"
    value: Short | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.status == "observed") != (self.value is not None):
            raise ValueError("Only an observed field can contain a value.")
        return self


class NumericalReading(Model):
    value: Short
    units: VisualField = Field(default_factory=VisualField)
    precision: Literal["explicit_label", "reliably_read", "visual_estimate"]
    evidence: Short
    region: Box

    @model_validator(mode="after")
    def geometry(self):
        valid_box(self.region)
        return self


class GraphPanel(Model):
    panel_label: VisualField = Field(default_factory=VisualField)
    region: Box
    graph_type: VisualField = Field(default_factory=VisualField)
    x_axis_label: VisualField = Field(default_factory=VisualField)
    x_axis_units: VisualField = Field(default_factory=VisualField)
    y_axis_label: VisualField = Field(default_factory=VisualField)
    y_axis_units: VisualField = Field(default_factory=VisualField)
    legend_and_groups: VisualField = Field(default_factory=VisualField)
    visible_trends: VisualField = Field(default_factory=VisualField)
    experimental_variables: VisualField = Field(default_factory=VisualField)
    controls_and_treatments: VisualField = Field(default_factory=VisualField)
    panel_relationships: VisualField = Field(default_factory=VisualField)
    uncertainty_indicators: VisualField = Field(default_factory=VisualField)
    statistical_annotations: VisualField = Field(default_factory=VisualField)
    numerical_readings: list[NumericalReading] = Field(default_factory=list, max_length=20)
    limitations: list[Short] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def geometry(self):
        valid_box(self.region)
        return self


class Reconciliation(Model):
    kind: Literal[
        "misassigned_table_cells",
        "reading_order",
        "column_interleaving",
        "missing_figure_labels",
        "misread_numbers",
        "lost_superscripts_subscripts",
        "missing_units",
        "caption_figure_mismatch",
    ]
    # Optional exact anchor into authorized extracted text. Missing text need not
    # have an anchor, but then the record cannot claim a checked text comparison.
    extracted_text: Short | None = None
    visual_observation: Short
    proposed_interpretation: Short
    region: Box
    confidence: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def geometry(self):
        valid_box(self.region)
        return self


class FigureObservation(Model):
    visibility: Literal["visible", "unavailable"]
    delivery_mode: Literal["native_mcp_image", "native_page_reader", "unknown"]
    figure_status: Literal[
        "figure_confirmed", "figure_not_found", "figure_ambiguous", "visual_inspection_unavailable"
    ]
    visible_feature: Short | None = None
    region: Box | None = None
    figure_number: VisualField = Field(default_factory=VisualField)
    caption: VisualField = Field(default_factory=VisualField)
    panels: list[GraphPanel] = Field(default_factory=list, max_length=12)
    direct_visual_observations: list[Short] = Field(default_factory=list, max_length=20)
    source_interpretation: VisualField = Field(default_factory=VisualField)
    source_interpretation_quote: Short | None = None
    assistant_inference: VisualField = Field(default_factory=VisualField)
    limitations: list[Short] = Field(default_factory=list, max_length=20)
    reconciliation: list[Reconciliation] = Field(default_factory=list, max_length=12)
    image_quality: Literal[
        "not_assessed",
        "sufficient_for_claims",
        "partially_readable",
        "insufficient_resolution",
        "important_details_unreadable",
    ] = "not_assessed"
    scientific_explanation: ScientificExplanation | None = None

    @model_validator(mode="after")
    def coherent(self):
        valid_box(self.region)
        if self.scientific_explanation and (
            self.visibility != "visible"
            or self.delivery_mode == "unknown"
            or self.image_quality not in {"sufficient_for_claims", "partially_readable"}
            or self.figure_status != "figure_confirmed"
        ):
            raise ValueError(
                "Scientific explanation requires a confirmed visible figure with adequate stated readability."
            )
        if self.image_quality in {"insufficient_resolution", "important_details_unreadable"} and (
            self.panels or self.direct_visual_observations or self.scientific_explanation
        ):
            raise ValueError(
                "Unreadable details cannot support scientific observations; report the limitation and request a better view."
            )
        if self.visibility == "unavailable":
            if (
                self.figure_status != "visual_inspection_unavailable"
                or self.visible_feature
                or self.region
                or self.panels
                or self.direct_visual_observations
                or self.reconciliation
                or any(
                    f.status != "unknown"
                    for f in (
                        self.figure_number,
                        self.caption,
                        self.source_interpretation,
                        self.assistant_inference,
                    )
                )
                or self.source_interpretation_quote
                or self.image_quality != "not_assessed"
            ):
                raise ValueError(
                    "Unavailable pixels cannot support visual observations or interpretations."
                )
        elif not self.visible_feature or self.figure_status == "visual_inspection_unavailable":
            raise ValueError(
                "Visible reports require an actual image feature, not a render receipt."
            )
        if self.figure_status == "figure_confirmed" and self.region is None:
            raise ValueError("A confirmed figure needs its visible image region.")
        if self.panels and self.figure_status != "figure_confirmed":
            raise ValueError("Do not manufacture graph panels on an unconfirmed page.")
        if self.source_interpretation.status == "observed" and not self.source_interpretation_quote:
            raise ValueError("Author interpretation needs an attributed source passage.")
        for panel in self.panels:
            if self.region and not (
                self.region[0] <= panel.region[0] < panel.region[2] <= self.region[2]
                and self.region[1] <= panel.region[1] < panel.region[3] <= self.region[3]
            ):
                raise ValueError("Keep each panel inside its figure region.")
            for number in panel.numerical_readings:
                if not (
                    panel.region[0] <= number.region[0] < number.region[2] <= panel.region[2]
                    and panel.region[1] <= number.region[1] < number.region[3] <= panel.region[3]
                ):
                    raise ValueError("Keep numerical evidence inside its own panel.")
        return self


async def record_observation(bridge, owner, ref, receipt, observation):
    try:
        proof = bridge.vault.open(receipt, owner, ref)
        if (
            proof["purpose"] not in {"visual_page", "visual_slide"}
            or datetime.fromisoformat(proof["expires"]) <= utcnow()
            or not proof.get("retrieved_at")
        ):
            raise ValueError("Invalid receipt")
    except Exception as exc:
        raise DomainError(
            "needs_input",
            "Render the page or slide again; this receipt is invalid, incomplete or expired.",
            reason_code="VISUAL_RECEIPT_INVALID",
        ) from exc
    row, _, metadata, epoch = await authorized(bridge, owner, ref, proof["file_id"])
    source_format = file_format(metadata)
    if (proof["purpose"], source_format) not in {("visual_page", "pdf"), ("visual_slide", "pptx")}:
        raise DomainError(
            "source_changed", "The render receipt does not identify this source format."
        )
    if epoch != proof["epoch"] or file_version(metadata) != proof["version"]:
        raise DomainError(
            "source_changed", "The source or scope changed. Render and inspect the page again."
        )
    compared_text = None
    if (
        fresh_cache(row, metadata, bridge.settings, now=bridge.retention.clock())
        and row.version_hash == proof["hash"]
    ):
        compared_text = next((p["text"] for p in row.locators if p["page"] == proof["page"]), None)
    comparisons = []
    for correction in observation.reconciliation:
        anchor = correction.extracted_text
        matches = compared_text is not None and anchor is not None and anchor in compared_text
        if compared_text is not None and anchor is not None and not matches:
            raise DomainError(
                "needs_input",
                "A reconciliation anchor is not present in this page's current extracted text.",
                reason_code="RECONCILIATION_ANCHOR_MISMATCH",
            )
        comparisons.append(
            {
                **correction.model_dump(mode="json"),
                "text_comparison": "exact_anchor_found" if matches else "unavailable",
                "classification": "assistant_inference",
                "verified": False,
            }
        )
    stages = lifecycle(rendered=True)
    if observation.visibility == "visible":
        for name in (
            "image_delivered_to_host",
            "image_visible_to_model",
            "visual_interpretation_completed",
        ):
            stages[name] = {
                "status": "reported",
                "evidence": "assistant_visual_report_not_independently_verified",
            }
    else:
        stages["image_visible_to_model"] = {
            "status": "reported_unavailable",
            "evidence": "assistant_report",
        }
    unavailable_reason = (
        "VISUAL_DATA_NOT_CONFIRMED"
        if observation.visibility == "unavailable"
        else {
            "insufficient_resolution": "IMAGE_RESOLUTION_INSUFFICIENT",
            "important_details_unreadable": "FIGURE_DETAILS_UNREADABLE",
        }.get(observation.image_quality)
    )
    if unavailable_reason:
        stages["visual_interpretation_completed"] = {
            "status": "reported_unavailable",
            "evidence": unavailable_reason,
        }
    locator = f"Slide {proof['page']}" if source_format == "pptx" else f"PDF page {proof['page']}"
    explanation = grounded_explanation(
        observation.scientific_explanation, observation, compared_text, locator
    )
    citation = source(row, f"{locator}, image region {observation.region}").model_copy(
        update={
            "content_hash": proof["hash"],
            "retrieved_at": datetime.fromisoformat(proof["retrieved_at"]),
            "classification": "assistant_inference",
            "extraction_status": "visual_interpretation_unverified",
            "uncertainty": [
                "The server validates provenance and structure, not visual or scientific accuracy."
            ],
        }
    )
    with bridge.store.transaction() as session:
        checked_row(bridge, session, owner, ref, row.id, epoch)
    return Result(
        status="partial_data",
        summary="Visual interpretation is unavailable; inspect a supported readable image before making scientific claims."
        if unavailable_reason
        else "Attributed visual report with checked source provenance; scientific accuracy is not independently verified.",
        data={
            "inspection_schema_version": "1.0",
            "comprehension_schema_version": "scientific-document-3",
            "source_locator": locator,
            "source_format": source_format,
            "scientific_explanation": explanation,
            "comprehension_status": "unavailable"
            if unavailable_reason
            else "reported_not_verified"
            if explanation
            else "not_established",
            "fallback_reason": unavailable_reason,
            "file_id": row.id,
            "page": proof["page"],
            "source_version": proof["version"],
            "content_hash": proof["hash"],
            "image_hash": proof["image_hash"],
            "visual_pipeline": stages,
            "figure_identification_status": observation.figure_status,
            "identification_basis": "assistant_visual_report_unverified",
            "observation": observation.model_dump(
                mode="json", exclude={"reconciliation", "scientific_explanation"}
            ),
            "reconciliation": comparisons,
            "source_interpretation_evidence": (
                "exact_page_text_match"
                if compared_text is not None
                and observation.source_interpretation_quote
                and observation.source_interpretation_quote in compared_text
                else "assistant_attribution_unverified"
                if observation.source_interpretation_quote
                else "not_supplied"
            ),
            "interpretation_verified": False,
            "retention": "Attributed record returned to this conversation only; extracted text is never overwritten.",
            "limitations": [
                "Exact values require explicit labels or reliable reading; visual estimates must be marked.",
                "Do not infer significance from bar heights or assign SD, SE or CI to unexplained error bars.",
                "Panels retain separate axes, units and legends. Author statements and assistant inferences are separately attributed.",
                "A receipt or a claimed visible feature cannot independently prove model visibility or scientific accuracy.",
            ],
        },
        sources=[citation],
        meta=bridge.meta(),
    )
