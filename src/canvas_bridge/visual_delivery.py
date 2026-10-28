"""Evidence-bounded image delivery. A prepared response is not a host receipt."""

import base64
from datetime import datetime, timedelta

from mcp.types import CallToolResult, ImageContent, TextContent

from canvas_bridge.domain import DomainError, utcnow

STAGES = (
    "source_authorized",
    "source_retrieved",
    "page_rendered",
    "image_delivered_to_host",
    "image_visible_to_model",
    "visual_interpretation_completed",
    "interpretation_verified",
)


def lifecycle(*, rendered=False, events=()):
    stages = {
        name: {
            "status": "established" if rendered and i < 3 else "unknown",
            "evidence": (
                ("fresh_file_authorization", "version_checked_source_bytes", "validated_png")[i]
                if rendered and i < 3
                else "no_host_acknowledgment"
                if i == 3
                else "not_observed_by_server"
            ),
        }
        for i, name in enumerate(STAGES)
    }
    # Only server-established stages are derived here. Response preparation,
    # conversion and rasterization never prove host/model delivery or reading.
    mapping = {
        "authorization": ("source_authorized", "fresh_file_authorization"),
        "source_fetch": ("source_retrieved", "version_checked_source_bytes"),
        "pdf_page_render": ("page_rendered", "validated_png"),
    }
    for event in events:
        if event.get("stage") not in mapping:
            continue
        stage, evidence = mapping[event["stage"]]
        if event.get("result") == "completed":
            if event["stage"] == "source_fetch" and event.get("resources", {}).get("cache_hit"):
                evidence = "version_checked_cached_derivative"
            stages[stage] = {"status": "established", "evidence": evidence}
        elif event.get("result") in {"failed", "unavailable"}:
            stages[stage] = {
                "status": event["result"],
                "evidence": event.get("error_classification", "server_stage_failed"),
            }
    return stages


def capability(settings, client_info=None):
    """Exact, operator-recorded client-build observations, never user-agent guesses.

    Optional malformed/expired evidence is ignored so it cannot break core tools.
    Client identity is only a delivery hint, never an authorization credential.
    """
    unknown = {"native_image": "unknown", "basis": "no_current_client_evidence"}
    if client_info is None or settings.visual_client_evidence_file is None:
        return unknown
    try:
        import json

        with settings.visual_client_evidence_file.open("rb") as stream:
            raw = stream.read(16_385)
        if len(raw) > 16_384:
            return unknown
        records = json.loads(raw)
        if not isinstance(records, list) or len(records) > 20:
            return unknown
        matches = []
        for record in records:
            if (record["client_name"], record["client_version"]) != (
                client_info.name,
                client_info.version,
            ):
                continue
            tested = datetime.fromisoformat(record["observed_at"])
            expires = datetime.fromisoformat(record["expires_at"])
            if not tested <= utcnow() < expires or expires - tested > timedelta(days=30):
                continue
            if record["native_image"] not in {"supported", "unsupported"}:
                continue
            if record["basis"] != "model_visible_probe" or not record.get("evidence_id"):
                continue
            if record.get("client_identity_unique_to_tested_surface") is not True:
                continue
            # Do not echo operator paths, evidence contents, or arbitrary strings.
            matches.append(
                {
                    "native_image": record["native_image"],
                    "basis": "operator_recorded_model_visible_probe",
                }
            )
        return matches[0] if len(matches) == 1 else unknown
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return unknown


def image_response(result, png, settings, client_info=None):
    """Keep legacy native+reader behavior; new inspect calls select a delivery mode."""
    cap = capability(settings, client_info)
    requested = result.data.pop("_visual_delivery_mode", "legacy")
    mode = requested
    fallback = None
    if mode == "auto":
        mode = "native" if cap["native_image"] == "supported" else "reader"
        if mode == "reader":
            fallback = (
                "HOST_IMAGE_UNSUPPORTED"
                if cap["native_image"] == "unsupported"
                else "HOST_IMAGE_CAPABILITY_UNKNOWN"
            )
    if not png:
        mode = "text"
        fallback = result.data.get("fallback_reason", "VISUAL_INSPECTION_UNAVAILABLE")
    if len(result.model_dump_json().encode()) > 240_000 or (png and len(png) > 1_733_336):
        raise DomainError(
            "partial_data",
            "Page image exceeds the response budget.",
            reason_code="IMAGE_RESPONSE_LIMIT",
        )
    result.data["image_delivery"] = {
        "schema_version": "1.0",
        "capability": cap,
        "mode": "native_mcp_image"
        if mode in {"legacy", "native"}
        else "native_page_reader"
        if mode == "reader"
        else "text_only",
        "status": "prepared" if png and mode != "text" else "not_attempted",
        "mime_type": "image/png" if png and mode != "text" else None,
        "image_bytes": len(base64.b64decode(png, validate=True)) if png and mode != "text" else 0,
        "fallback_reason": fallback,
        "model_visibility": "unknown",
        "visual_interpretation_established": False,
    }
    result.data.setdefault("visual_pipeline", lifecycle())
    contents = [TextContent(type="text", text=result.model_dump_json())]
    metadata = {}
    if png and mode != "text":
        # Legacy OpenAI widget globals need this private copy. Never put pixels
        # in structuredContent or JSON text. Standard Apps can read ImageContent.
        if mode in {"legacy", "reader"}:
            metadata = {"canvas_bridge_page": {"png": png}}
        if mode in {"legacy", "native"}:
            contents.append(ImageContent(type="image", data=png, mimeType="image/png"))
    return CallToolResult(
        structuredContent=result.model_dump(mode="json"), content=contents, _meta=metadata
    )
