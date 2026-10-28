"""Reviewed process tool inventory and exact-source output authorization."""

from sqlalchemy import select

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import SourceContext
from canvas_bridge.storage import IndependentResource, Material, Work

TOOLS = frozenset(
    {
        "evaluate_academic_process",
        "preview_academic_process_change",
        "confirm_academic_process_change",
        "get_academic_process_records",
        "preview_academic_process_recovery",
        "export_academic_process_records",
        "get_academic_support_report",
        "get_academic_process_impacts",
    }
)
SAFE_RECEIPTS = frozenset(
    {
        "confirm_academic_process_change",
        "get_academic_support_report",
        "preview_academic_process_recovery",
        "get_academic_process_records",
    }
)


def contract(name, *, write):
    return {
        "contract_version": "source-operation-1",
        "categories": ["DERIVED_ACADEMIC_ANALYSIS", "DATA_EXPORT_OR_MODEL_EGRESS"],
        "authentication": "verified_application_identity",
        "authorization": ["exact_source_recheck", "recipient_egress", "academic_integrity"],
        "source_types": ["local_document", "institutional"],
        "data_dependencies": ["exact_request_sources"],
        "upstream_network": name
        in {
            "evaluate_academic_process",
            "preview_academic_process_change",
            "confirm_academic_process_change",
        },
        "data_classification": "inherited_from_authorized_sources; unknown_denied",
        "read_only": not write,
        "offline_supported": True,
        "egress": "exact_source_recipient_and_modality_check",
        "conditional_institutional_dependencies": True,
        "academic_integrity": "administrative_or_planning; explicit_activity_checked_for_lifecycle",
    }


def resolve_process_sources(engine, owner, arguments, result, tool):
    from canvas_bridge.egress_sources import resolve_sources

    bridge = engine.bridge
    bridge.processes.enabled()
    resolved = []
    if not result.sources:
        if tool not in SAFE_RECEIPTS:
            raise DomainError(
                "permission_denied",
                "Process output has no bound sources.",
                reason_code="PROCESS_SOURCE_UNAVAILABLE",
            )
        return (
            SourceContext(
                "__public__", owner, "process-receipt", "", "safe_status", CC.PUBLIC_OR_APPROVED
            ),
        ), None
    seen = set()
    for source in result.sources:
        if source.id in seen:
            continue
        seen.add(source.id)
        with bridge.store.transaction() as session:
            local = session.scalar(
                select(IndependentResource).where(
                    IndependentResource.id == source.id,
                    IndependentResource.owner == owner,
                    IndependentResource.kind == "local_document",
                )
            )
            if local:
                bridge.independent.require(owner, source.id)
                if local.version_hash != source.content_hash:
                    raise DomainError(
                        "source_changed",
                        "Process source changed.",
                        reason_code="PROCESS_SOURCE_CHANGED",
                    )
                resolved.extend(
                    bridge.independent.sources(owner, {"document_id": source.id}, result)
                )
                continue
            row = session.scalar(select(Work).where(Work.owner == owner, Work.id == source.id))
            row = (
                row
                if row is not None
                else session.scalar(
                    select(Material).where(Material.owner == owner, Material.id == source.id)
                )
            )
            if row is None:
                raise DomainError(
                    "permission_denied",
                    "Process source is unavailable.",
                    reason_code="PROCESS_SOURCE_UNAVAILABLE",
                )
            version = (
                row.payload.get("source", {}).get("content_hash")
                if isinstance(row, Work)
                else row.version_hash
            )
            if version != source.content_hash:
                raise DomainError(
                    "source_changed",
                    "Process source changed.",
                    reason_code="PROCESS_SOURCE_CHANGED",
                )
            ref, course = row.connection_id, row.course_id
        subset = Result(summary="Bound process source.", sources=[source])
        sources, _ = resolve_sources(
            engine,
            owner,
            {"connection_id": ref, "course_id": course},
            subset,
            "prepare_for_assessment",
        )
        resolved.extend(sources)
    return tuple(resolved), None
