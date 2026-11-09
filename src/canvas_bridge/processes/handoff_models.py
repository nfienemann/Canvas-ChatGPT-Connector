"""Local, explicitly declared group identities and immutable packet operations."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from canvas_bridge.analytics.effort_history import Instant
from canvas_bridge.processes import effort_service as effort
from canvas_bridge.processes import readiness as rd
from canvas_bridge.processes.models import Model, Ref

MemberId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1200)]
ResponseKind = Literal["received", "accepted_for_next_step", "changes_requested"]
ConditionScope = Literal["transfer", "requested_action", "downstream_execution"]


class Member(Model):
    member_id: MemberId
    label: Annotated[str, Field(min_length=1, max_length=100)]


class Responsibility(Model):
    assignment_ref: Ref
    revision: Ref
    members: tuple[Member, ...] = Field(max_length=24)
    responsible_actor: MemberId | None = None
    recipient_ids: tuple[MemberId, ...] = Field(default=(), max_length=24)
    identity_basis: Literal["explicit_declaration", "source_assignment", "proposed", "unresolved"]
    source_ref: Ref
    evidence: rd.Anchor | None = None

    @model_validator(mode="after")
    def identities(self):
        ids = [m.member_id for m in self.members]
        if len(set(ids)) != len(ids) or len(set(self.recipient_ids)) != len(self.recipient_ids):
            raise ValueError("Use one entry per scoped member.")
        if self.identity_basis == "source_assignment" and not self.evidence:
            raise ValueError("A sourced assignment requires its exact passage.")
        return self


class InputRef(Model):
    logical_id: Ref
    expected_hash: rd.Digest | None = None


class Action(Model):
    required_inputs: tuple[InputRef, ...] = Field(default=(), max_length=6)
    action_id: Ref
    revision: Ref
    owner_id: MemberId | None = None
    description: Text
    expected_output: Text
    prerequisite_ids: tuple[Ref, ...] = Field(default=(), max_length=40)
    requires_process_context: bool = False
    acknowledgment_policy: Literal["optional", "any", "all"] = "optional"
    acknowledgment_members: tuple[MemberId, ...] = Field(default=(), max_length=24)
    required_response: ResponseKind = "accepted_for_next_step"
    due_at: Instant | None = None


class ProcessLink(Model):
    process_id: Ref
    generation_id: Ref
    step_id: Ref
    # Only these named blockers govern transfer or the requested action.
    transfer_blockers: tuple[Ref, ...] = Field(default=(), max_length=40)
    action_blockers: tuple[Ref, ...] = Field(default=(), max_length=40)


class Condition(Model):
    blocker_id: Ref
    revision: Ref
    scope: ConditionScope
    state: Literal["blocked", "unknown", "conditional", "ready"]
    next_action: Text
    source_ref: Ref
    expires_at: Instant | None = None
    evidence: rd.Anchor | None = None


class Prepare(effort.Mutation):
    conditions: tuple[Condition, ...] = Field(default=(), max_length=24)
    handoff_id: Ref
    expected_packet: Ref | None = None
    work_id: Ref | None = None
    expected_artifact_hash: rd.Digest | None = None
    expected_requirement_revision: Ref | None = None
    expected_episode_id: Ref | None = None
    artifact_logical_id: Ref
    criterion_ids: tuple[Ref, ...] = Field(default=(), max_length=40)
    responsibility: Responsibility
    action: Action
    process: ProcessLink | None = None
    presentation_note: Text | None = None

    @model_validator(mode="after")
    def scope(self):
        if len({c.blocker_id for c in self.conditions}) != len(self.conditions):
            raise ValueError("Duplicate condition identity.")
        if len({v.logical_id for v in self.action.required_inputs}) != len(
            self.action.required_inputs
        ):
            raise ValueError("Duplicate action input.")
        if len(set(self.criterion_ids)) != len(self.criterion_ids):
            raise ValueError("Duplicate requirement scope.")
        if self.criterion_ids and not set(self.action.prerequisite_ids) <= set(self.criterion_ids):
            raise ValueError("Action prerequisites must belong to the selected packet scope.")
        if not set(self.action.acknowledgment_members) <= set(self.responsibility.recipient_ids):
            raise ValueError("Acknowledgment applies only to named recipients.")
        if self.process and set(self.process.action_blockers) & set(self.process.transfer_blockers):
            raise ValueError("Choose one governing scope for each blocker.")
        return self


class Response(effort.Mutation):
    handoff_id: Ref
    packet_id: Ref
    observation_id: Ref
    expected_observation_revision: int = Field(ge=0)
    acknowledged_by: MemberId
    state: ResponseKind
    evidence_basis: Literal[
        "supplied_direct_response", "supplied_relayed_response", "supplied_member_declaration"
    ]
    evidence_ref: Ref
    evidence: rd.Anchor | None = None
    observed_at: Instant
    retracted: bool = False
    supersedes: Ref | None = None

    @model_validator(mode="after")
    def direct_source(self):
        if self.evidence_basis == "supplied_direct_response" and not self.evidence:
            raise ValueError(
                "A supplied direct response requires a bound passage. A relayed declaration can use its supplied reference."
            )
        return self


class Export(effort.Mutation):
    handoff_id: Ref
    packet_id: Ref
    output_format: Literal["json", "markdown"] = "json"


class OutputOperation(effort.Mutation):
    handoff_id: Ref
    packet_id: Ref
    output_id: Ref
    kind: Literal["downloadable_artifact", "delivery"]
    destination_ref: Ref
    recipient_ids: tuple[MemberId, ...] = Field(default=(), max_length=24)
    confirmed: bool
    expected_destination_revision: Ref | None = None
    reconcile_only: bool = False


class SuppliedReceipt(effort.Mutation):
    handoff_id: Ref
    packet_id: Ref
    output_id: Ref
    receipt_ref: Ref
    destination_ref: Ref
    recipient_ids: tuple[MemberId, ...] = Field(min_length=1, max_length=24)
    content_hash: rd.Digest
    observed_at: Instant
    evidence: rd.Anchor | None = None


class Restore(effort.Mutation):
    handoff_id: Ref
    packet_id: Ref
    expected_packet: Ref
    fields: tuple[Literal["responsibility", "action", "presentation_note"], ...] = Field(
        min_length=1, max_length=3
    )
