"""Authorized independent acquisition and egress around source-neutral reasoning."""

import base64
import hashlib

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from canvas_bridge.academic.independent_engine import analyze
from canvas_bridge.academic.independent_models import IndependentAcademicInput
from canvas_bridge.domain import DomainError, Result, opaque_id, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import SourceContext
from canvas_bridge.integrity.surfaces import before_tool
from canvas_bridge.storage import aware

TOOL = "run_independent_academic_workflow"
PURPOSES = {
    "grades": "grade_planning",
    "planning": "schedule",
    "calendar": "schedule",
    "deadlines": "schedule",
    "consistency": "schedule",
    "requirements": "study",
    "assessment": "study",
}


def require_use(bridge, row, capability):
    purposes = {PURPOSES[capability]} | ({"study"} if capability == "consistency" else set())
    profile = bridge.independent.profile()
    if not purposes <= set(row.provenance.get("scope", [])):
        raise DomainError(
            "permission_denied",
            "This source is not permitted for the requested analysis.",
            reason_code="INDEPENDENT_SOURCE_OPERATION_NOT_PERMITTED",
        )
    if not profile or not purposes <= profile.purposes:
        raise DomainError(
            "permission_denied",
            "The recipient has not been reviewed for this use.",
            reason_code="EGRESS_REVIEW_REQUIRED",
        )


def require(bridge, owner, selected, *, check_version=True):
    row = bridge.independent.require(owner, selected.document_id)
    if check_version and row.version_hash != selected.expected_hash:
        raise DomainError(
            "source_changed",
            "Independent source version changed; reread its status.",
            reason_code="INDEPENDENT_SOURCE_CHANGED",
        )
    # A registered institutional policy context must not cause hidden acquisition
    # from this adapter. It needs its separately authorized institutional route.
    for context in bridge.integrity.contexts(owner):
        if row.id in context.content.get("hashes", {}) and context.content.get("scope", {}).get(
            "connection_id"
        ):
            raise DomainError(
                "permission_denied",
                "This source retains an institutional dependency.",
                reason_code="INDEPENDENT_SOURCE_HAS_INSTITUTIONAL_LINEAGE",
            )
    return row


def provenance(row):
    p = row.provenance
    return {
        "source_id": row.id,
        "source_category": p.get("source_category", "independent_import"),
        "acquisition_mechanism": p.get("mechanism", "bounded_browser_upload"),
        "original_authority": None,
        "authorization_basis": p["authorization"],
        "privacy_classification": p["privacy_classification"],
        "content_hash": row.version_hash,
        "source_version": row.version_hash,
        "acquired_at": aware(row.created_at).isoformat(),
        "parents": p.get("parents", []),
        "permitted_operations": p.get("scope", []),
        "restrictions": {
            "copyright": p.get("copyright", "unknown"),
            "share_text": p.get("share_text", False),
            "share_visual": p.get("share_visual", False),
        },
        "uncertainty": [
            "Ownership is user attested; institutional origin cannot be inferred from possession."
        ],
    }


def resolve_sources(bridge, owner, arguments, result):
    request = arguments.get("request")
    request = request.model_dump(mode="json") if hasattr(request, "model_dump") else request or {}
    selected = {d["document_id"]: d["expected_hash"] for d in request.get("documents", [])}
    if request.get("dataset"):
        d = request["dataset"]
        selected[d["document_id"]] = d["expected_hash"]
    if not result.sources:
        raise DomainError(
            "permission_denied", "Independent output has no authorized source lineage."
        )
    sources = {}
    for source in result.sources:
        row = bridge.independent.require(owner, source.id)
        require_use(bridge, row, request["capability"])
        if selected.get(row.id) != row.version_hash or source.content_hash != row.version_hash:
            raise DomainError(
                "source_changed",
                "Independent output source identity changed.",
                reason_code="INDEPENDENT_SOURCE_CHANGED",
            )
        sources[row.id] = SourceContext(
            "__independent__",
            owner,
            row.id,
            row.version_hash,
            "local_document",
            CC.FIRST_PARTY_EDUCATIONAL_RECORD,
            derived=True,
            content_sha256=row.version_hash,
        )
    return tuple(sources.values())


async def run(bridge, owner, request):
    try:
        return await _run(bridge, owner, request)
    except SQLAlchemyError as exc:
        raise DomainError(
            "retry_later",
            "Independent local storage is unavailable; retry local access. Reconnecting an LMS will not repair this.",
            reason_code="LOCAL_STORAGE_UNAVAILABLE",
        ) from exc
    except ValueError as exc:
        raise DomainError(
            "needs_input",
            "Independent input or planning constraints are invalid; review the documented bounded schema.",
            reason_code="INDEPENDENT_INPUT_INVALID",
        ) from exc


async def _run(bridge, owner, request):
    dataset, dataset_source = None, None
    documents, sources, lineage, coverage, excluded = [], [], [], [], []
    accepted = []
    selections = ([request.dataset] if request.dataset else []) + request.documents
    for position, selected in enumerate(selections, 1):
        try:
            row = require(bridge, owner, selected, check_version=False)
            require_use(bridge, row, request.capability)
            await before_tool(bridge, owner, "read_local_document", {"document_id": row.id})
            # Establish current sharing before revealing whether a supplied hash
            # matches. Unknown, non-owned and restricted IDs must look alike.
            bridge.egress.release(
                bridge.independent.read(owner, row.id, status=True),
                owner,
                {"document_id": row.id},
                tool_name="get_local_document_status",
            )
            require(bridge, owner, selected)
            evidence = bridge.independent.read(
                owner, row.id, start=selected.start_part, limit=selected.limit, study=True
            )
            # Every source is checked before reasoning as well as before release.
            evidence = bridge.egress.release(evidence, owner, {"request": request}, tool_name=TOOL)
        except DomainError as exc:
            if exc.status in {
                "source_changed",
                "reconnect_required",
            }:
                raise
            if selected is request.dataset:
                raise DomainError(
                    "permission_denied",
                    "This selection is unavailable for independent use.",
                    reason_code="INDEPENDENT_SOURCE_UNAVAILABLE",
                ) from exc
            excluded.append(
                {"selection": position, "reason_code": "INDEPENDENT_SOURCE_UNAVAILABLE"}
            )
            continue
        accepted.append(selected)
        lineage.append(provenance(row))
        sources.extend(evidence.sources)
        if selected is request.dataset:
            if row.content.get("format") not in {"txt", "md"}:
                raise DomainError(
                    "unsupported_feature",
                    "Structured academic records require a permitted TXT or Markdown import.",
                    reason_code="INDEPENDENT_SCHEMA_UNSUPPORTED",
                )
            raw = base64.b64decode(row.content["bytes"], validate=True)
            if len(raw) > 80_000 or hashlib.sha256(raw).hexdigest() != row.version_hash:
                raise DomainError(
                    "source_changed",
                    "Academic input bytes do not match their version.",
                    reason_code="INDEPENDENT_SOURCE_CHANGED",
                )
            try:
                dataset = IndependentAcademicInput.model_validate_json(raw)
            except ValidationError as exc:
                unsupported = any(
                    e["loc"] == ("schema_version",)
                    for e in exc.errors(include_input=False, include_context=False)
                )
                raise DomainError(
                    "unsupported_feature" if unsupported else "needs_input",
                    "Academic records require the supported native schema.",
                    reason_code="INDEPENDENT_SCHEMA_UNSUPPORTED"
                    if unsupported
                    else "INDEPENDENT_INPUT_INVALID",
                ) from exc
            dataset_source = bridge.independent.evidence(row, "Independent academic records")
            # Child references are backed by this validated document, not by LMS
            # identifiers. This also preserves exact timing/override maps through
            # the existing owner-source privacy projection.
            sources.extend(
                dataset_source.model_copy(update={"resource_id": w.key, "locator": "Work " + w.key})
                for w in dataset.work
            )
            continue
        parts = [
            {"locator": f"Part {p['part']}", "text": p["text"][:4000]}
            for p in evidence.data["parts"]
        ]
        complete = (
            selected.start_part == 1
            and evidence.data.get("next_part") is None
            and evidence.data["coverage"] == "complete"
            and all(
                not p["text_truncated"] and len(p["text"]) <= 4000 for p in evidence.data["parts"]
            )
        )
        documents.append(
            {
                "id": row.id,
                "title": "Independently supplied document",
                "url": "",
                "course_id": None,
                "source_type": "local_document",
                "role": selected.role,
                "version": row.version_hash,
                "retrieved_at": evidence.sources[0].retrieved_at.isoformat(),
                "complete": complete,
                "parts": parts,
            }
        )
        coverage.append(
            {
                "document_id": row.id,
                "role": selected.role,
                "start_part": selected.start_part,
                "parts_read": len(parts),
                "part_count": evidence.data["part_count"],
                "next_part": evidence.data.get("next_part"),
                "complete": complete,
                "limitations": evidence.data["limitations"],
            }
        )
    if not sources or (request.capability in {"assessment", "requirements"} and not documents):
        if excluded:
            raise DomainError(
                "permission_denied",
                "This selection is unavailable for independent use.",
                reason_code="INDEPENDENT_SOURCE_UNAVAILABLE",
            )
        raise DomainError(
            "needs_input",
            "No permitted independent evidence could be processed.",
            reason_code="INDEPENDENT_INPUT_MISSING",
            requested_capability=request.capability,
        )
    data, partial = analyze(request, dataset, dataset_source, documents, owner=owner, now=utcnow())
    data.update(
        source_provenance=lineage,
        coverage=coverage,
        excluded_sources=excluded,
        diagnostics={
            "requested_capability": request.capability,
            "source_adapter": "independent_import",
            "institutional_authorization_required": False,
            "institutional_network_attempted": False,
            "policy_decision": "owned_source_and_current_recipient_checked",
            "included_source_classes": ["independent_import"],
            "excluded_source_classes": ["unknown_or_disallowed"] if excluded else [],
            "correlation_id": opaque_id(),
        },
        source_versions=[
            {"source_id": p["source_id"], "content_hash": p["content_hash"]} for p in lineage
        ],
        derived_restrictions="All output retains every included source's current processing and sharing restrictions.",
        institutional_coverage="not_requested_not_accessed",
    )
    result = Result(
        status="partial_data"
        if partial or excluded or any(not c["complete"] for c in coverage)
        else "ok",
        summary="Independent academic analysis from the cited permitted inputs. No LMS was accessed or calendar changed.",
        data=data,
        sources=sources,
    )
    if len(result.model_dump_json().encode()) > 120_000:
        raise DomainError(
            "needs_input",
            "Independent analysis exceeds its output limit; select fewer records or source parts.",
        )
    for selected in accepted:
        require(bridge, owner, selected)
    # The normal MCP wrapper applies privacy filtering again. Direct callers also
    # get the same current source, academic-integrity and recipient boundary.
    return bridge.egress.release(result, owner, {"request": request}, tool_name=TOOL)
