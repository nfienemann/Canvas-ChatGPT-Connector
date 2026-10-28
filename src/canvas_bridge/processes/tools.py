"""MCP process workflows registered through the existing security wrapper."""

from typing import Annotated, Literal

from pydantic import Field

from canvas_bridge.auth import request_identity
from canvas_bridge.domain import DomainError, Result
from canvas_bridge.processes.models import Ref
from canvas_bridge.processes.requests import EvaluationRequest, SaveRequest


def register_tools(register, bridge):
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
