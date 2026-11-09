"""MCP process workflows registered through the existing security wrapper."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from canvas_bridge.auth import request_identity
from canvas_bridge.domain import DomainError, Result
from canvas_bridge.planning import PlanRequest
from canvas_bridge.processes import (
    change_service,
    effort_service,
    handoff_models,
    handoff_outputs,
    handoff_service,
    readiness,
    resource_effects,
    resource_service,
    study_plan,
)
from canvas_bridge.processes.models import Ref
from canvas_bridge.processes.requests import EvaluationRequest, SaveRequest


def register_tools(register, bridge):
    @register(write=True, destructive=True)
    async def restore_group_handoff(request: handoff_models.Restore) -> Result:
        """Restore selected responsibility, action or presentation fields changed by an exact packet revision. Conflicting later edits must be resolved; original records and responses remain available."""
        return await handoff_service.restore(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def reconcile_handoff_output(request: handoff_models.OutputOperation) -> Result:
        """Reconcile an exact exported payload with a configured host file or delivery adapter. Requires resolved destination and current grant. Only explicitly confirmed new actions can create an output. Use reconcile_only for uncertain historical outcomes."""
        return await handoff_outputs.operate(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def record_handoff_delivery_receipt(request: handoff_models.SuppliedReceipt) -> Result:
        """Record a supplied delivery receipt against its exact exported hash and recipient set. This records a declaration independently of teammate responses."""
        return await handoff_outputs.observe(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def prepare_group_handoff(request: handoff_models.Prepare) -> Result:
        """Save or reconcile a private group handoff from an existing assignment, logical artifact, explicit member declarations and next action. Use the current journal revision and prior packet ID on replacement. Optionally bind an exact Phase E generation and step. Read back the packet for content and applicability."""
        return await handoff_service.prepare(bridge.processes, request_identity().owner, request)

    @register()
    async def get_group_handoff(
        record_id: Ref,
        handoff_id: Ref,
        packet_id: Ref | None = None,
        as_of: AwareDatetime | None = None,
        output_id: Ref | None = None,
    ) -> Result:
        """Retrieve a saved group handoff, criterion evidence, progress, responsibilities and current or historical response applicability. An as-of cutoff selects only packets, outputs and responses known by that time."""
        return await handoff_service.view(
            bridge.processes,
            request_identity().owner,
            record_id,
            handoff_id,
            packet_id,
            as_of,
            output_id,
        )

    @register(write=True)
    async def record_handoff_response(request: handoff_models.Response) -> Result:
        """Record an explicitly supplied response on the exact packet it referenced. Specify the actual responding scoped member and evidence. The authenticated owner is its recorder. Use observation revisions for corrections and retractions."""
        return await handoff_service.record_response(
            bridge.processes, request_identity().owner, request
        )

    @register(write=True)
    async def export_group_handoff(request: handoff_models.Export) -> Result:
        """Return the current private packet as JSON or Markdown with an exact UTF-8 payload hash. Retry a lost response with the original request and key. Local export has no external delivery effect."""
        return await handoff_service.export(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def check_resource_calendar(request: resource_effects.CalendarReadback) -> Result:
        """Use a fresh complete host calendar snapshot to reconcile one resource-study event. After explicit confirmation prepare a conditional host action; find the exact marker before retrying a create."""
        return await resource_effects.check_calendar(
            bridge.processes, request_identity().owner, request
        )

    @register(write=True, destructive=True)
    async def compensate_resource_effects(request: resource_effects.Compensation) -> Result:
        """Prepare conditional inverses of specified confirmed provider effects in the current generation. Preserve other study and resource operations; use the new operation IDs for explicit execution."""
        return await resource_effects.compensate(
            bridge.processes, request_identity().owner, request
        )

    @register(write=True)
    async def apply_resource_plan_operation(request: resource_effects.Apply) -> Result:
        """After explicit confirmation, reconcile or apply one eligible resource-plan operation through a configured provider. Uncertain effects require provider lookup. Observation-only resources require supplied confirmation."""
        return await resource_effects.apply(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def save_resource_plan(request: resource_service.Save) -> Result:
        """Plan or repair scoped resource work from a current forecast. Supply versioned resource calendars, equipment quantities, phases and waits. Bind active phase demand to the forecast. Persist the locally evaluated generation, then retrieve it to see attendance, occupancy, booking evidence and blockers."""
        return await resource_service.save(bridge.processes, request_identity().owner, request)

    @register()
    async def get_resource_plan(
        record_id: Ref, process_id: Ref, generation_id: Ref | None = None
    ) -> Result:
        """Recall the resource plan, attended sessions, passive waits, latest-start proof and outstanding booking requirements. Resource schedules do not establish artifact completion."""
        return await resource_service.view(
            bridge.processes, request_identity().owner, record_id, process_id, generation_id
        )

    @register(write=True)
    async def record_scoped_effort(request: effort_service.WorkLog) -> Result:
        """Record or correct measured active time for one work episode and scope. Use the saved journal and observation revisions."""
        return await effort_service.log_work(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def forecast_remaining_work(request: effort_service.ForecastRequest) -> Result:
        """Freeze a personalized estimate for an existing remediation work item. Supply comparable task family, baseline policy and whole or remaining scope."""
        return await effort_service.issue(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def save_study_replan(request: study_plan.SavePlan) -> Result:
        """Save a study plan using current forecasts and available windows. For a student-selected Canvas assignment, first read get_assignment_details and use its current effective timestamp. An unknown deadline can be omitted. Release a future protected block by ID only when the student explicitly requests it. Retrieve the saved generation for calendar proposals."""
        return await study_plan.save(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def check_study_calendar(request: study_plan.CalendarCheck) -> Result:
        """Reconcile a fresh complete existing-calendar search for the exact study markers. After explicit confirmation specify one operation ID to prepare for conditional host execution. Only execute pending newly issued actions once. Read back uncertain effects before retry."""
        return await study_plan.check(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def compensate_study_replan(request: study_plan.Undo) -> Result:
        """Explicitly reverse one saved generation, preserving later block edits. Read back any proposed calendar compensation before confirming it."""
        return await study_plan.undo(bridge.processes, request_identity().owner, request)

    @register()
    async def get_study_forecast_plan(record_id: Ref) -> Result:
        """Retrieve saved observations, forecast versions, journal revision and calendar operation readbacks."""
        return await study_plan.view(bridge.processes, request_identity().owner, record_id)

    @register(write=True)
    async def observe_assignment_change(request: change_service.Observation) -> Result:
        """Compare the selected replacement imports with a saved readiness record. Stage the observed source versions and criterion impacts, then retrieve the change before targeted reassessment."""
        return await change_service.observe(bridge.processes, request_identity().owner, request)

    @register()
    async def get_assignment_change(record_id: Ref) -> Result:
        """Retrieve the saved observation, pending criterion scope or applied work decisions for an assignment."""
        return await change_service.report(bridge.processes, request_identity().owner, record_id)

    @register(write=True)
    async def reconcile_assignment_change(request: change_service.Reassessment) -> Result:
        """Commit the staged transition. Supply grounded criterion assessments only for changed requirements; unchanged assessments carry from their proofs. Cite explicit removals. A material fulfillment change starts a new work episode. Use the observed revision and replay key."""
        return await change_service.apply_change(
            bridge.processes, request_identity().owner, request
        )

    @register(write=True, destructive=True)
    async def compensate_assignment_change(request: change_service.Compensation) -> Result:
        """Explicitly reverse one applied reconciliation at the current revision, preserving compatible later progress. Returns a new revision receipt."""
        return await change_service.compensate(bridge.processes, request_identity().owner, request)

    @register(write=True)
    async def save_assignment_readiness(review: readiness.Review) -> Result:
        """Remember the requested review of independent materials. For a changed saved assignment, observe_assignment_change and reconcile_assignment_change preserve its work episodes. Bind each source by logical ID, document ID and SHA-256. Cite exact passages for each criterion and finding. For absence/all_claims include inspected artifact parts. Use expected_revision=0 to create. Returns confirmed record ID and revision; read it to show the projection."""
        owner = request_identity().owner
        bridge.processes.enabled()
        await readiness.authorize_bindings(bridge, owner, review.bindings)
        return readiness.save(bridge.processes, owner, review)

    @register()
    async def get_assignment_readiness(
        record_id: Ref,
        revision: int | None = None,
        selection: readiness.Selection | None = None,
        plan: PlanRequest | None = None,
        plan_as_of: AwareDatetime | None = None,
    ) -> Result:
        """Recall a saved readiness review or historical revision. Supply selection for an explicit current-version comparison. Supply plan to propose work from the saved tasks."""
        owner = request_identity().owner
        bridge.processes.enabled()
        stored = readiness.snapshot(bridge.processes.repository, owner, record_id, revision)
        bindings = [readiness.Binding.model_validate(b) for b in stored.data["bindings"]]
        withheld = await readiness.authorize_bindings(
            bridge, owner, bindings, partial=True, planning=plan is not None
        )
        if selection:
            await readiness.authorize_bindings(bridge, owner, selection.bindings)
        return readiness.view(
            bridge.processes,
            owner,
            record_id,
            stored.revision,
            selection,
            plan,
            plan_as_of,
            withheld,
        )

    @register(write=True)
    async def record_readiness_progress(request: readiness.Progress) -> Result:
        """Save explicitly declared personal progress for one existing remediation item. Retrieve the record to see its assessment alongside task progress."""
        owner = request_identity().owner
        bridge.processes.enabled()
        stored = readiness.snapshot(bridge.processes.repository, owner, request.record_id)
        await readiness.authorize_bindings(
            bridge, owner, [readiness.Binding.model_validate(b) for b in stored.data["bindings"]]
        )
        return readiness.update_progress(bridge.processes, owner, request)

    @register()
    async def evaluate_academic_process(request: EvaluationRequest) -> Result:
        """Evaluate sourced evidence, conflicts, feasibility, lifecycle, identity, concepts, unofficial degree progress or portfolio review. Caller claims remain unverified. Does not save a plan, send a message, submit work or publish."""
        return await bridge.processes.evaluate(request_identity().owner, request)

    @register(write=True)
    async def preview_academic_process_change(request: SaveRequest) -> Result:
        """Prepare an expiring exact preview of an explicitly requested local record change. Review before confirmation. expected_revision=0 creates a record; corrections preserve source history and invalidate dependent records."""
        return await bridge.processes.propose(request_identity().owner, request)

    @register(write=True, destructive=True)
    async def confirm_academic_process_change(
        preview_id: Ref, confirmed: bool, idempotency_key: Ref
    ) -> Result:
        """Apply only the exact preview the student reviewed and explicitly confirmed, including deletions. Rechecks sources and policy. Retry with the same key after an uncertain response. No external services are changed."""
        return await bridge.processes.confirm(
            request_identity().owner, preview_id, confirmed, idempotency_key
        )

    @register()
    async def get_academic_process_records(
        record_ids: Annotated[list[Ref], Field(max_length=100)] = (),
    ) -> Result:
        """Inspect current local records or inventory. Revoked, expired or invalidated records disclose no academic contents."""
        return bridge.processes.inspect_records(request_identity().owner, record_ids)

    @register(write=True)
    async def preview_academic_process_recovery(
        record_id: Ref | None = None, revision_id: Ref | None = None
    ) -> Result:
        """Preview deletion of one local record and its dependent copies, or rollback of one revision. Choose exactly one reference. A rollback cannot restore revoked source access."""
        if bool(record_id) == bool(revision_id):
            raise DomainError(
                "needs_input", "Choose one record to delete or one revision to roll back."
            )
        return bridge.processes.recovery_preview(request_identity().owner, record_id, revision_id)

    @register()
    async def get_academic_process_impacts(record_id: Ref) -> Result:
        """Review deduplicated observed change impacts and repair needs for one saved record. Historical values are withheld when their source version cannot be released. Sends no notifications or calendar updates."""
        return bridge.processes.change_impacts(request_identity().owner, record_id)

    @register()
    async def export_academic_process_records(
        record_ids: Annotated[list[Ref], Field(min_length=1, max_length=100)],
        output_format: Literal["json", "markdown"] = "json",
    ) -> Result:
        """Return requested local records as portable versioned JSON or Markdown with provenance, subject to current source and recipient permissions. No external file or message is created."""
        return bridge.processes.export(request_identity().owner, record_ids, output_format)

    @register()
    async def get_academic_support_report(
        category: Literal[
            "connector", "parsing", "authorization", "state", "sync", "interpretation"
        ],
    ) -> Result:
        """Preview a minimal offline support report with opaque IDs and fixed troubleshooting steps. Includes no coursework, credentials or raw exception text and sends nothing to support."""
        from canvas_bridge.processes.diagnostics import preview_report, support_report

        bridge.processes.enabled()
        return Result(
            summary="Review this exact support report before sharing it yourself.",
            data=preview_report(support_report(category)),
        )
