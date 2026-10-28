"""Authorized PPTX -> private PDF -> existing PDFium -> native image response."""

import asyncio
import hashlib
import logging
import os
import time
from contextlib import nullcontext
from datetime import timedelta

from canvas_bridge.course_files import authorized, checked_row, fresh_cache, source
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.file_download import download_file, file_format, file_metadata, file_version
from canvas_bridge.parser_sandbox import extract_isolated
from canvas_bridge.parser_worker import PARSER
from canvas_bridge.presentation_render_worker import CONVERTER
from canvas_bridge.visual_delivery import lifecycle

logger = logging.getLogger(__name__)
STAGES = (
    "authorization",
    "source_fetch",
    "pptx_conversion",
    "derivative_registration",
    "pdf_page_render",
    "image_response_preparation",
    "image_delivery",
    "model_visibility",
    "visual_interpretation",
)


class Trace:
    def __init__(self):
        self.events = {
            stage: {"stage": stage, "result": "not_attempted", "duration_ms": 0, "resources": {}}
            for stage in STAGES
        }
        self.started = time.monotonic()

    def record(self, stage, result, *, started=None, resources=None, error=None):
        event = {
            "stage": stage,
            "result": result,
            "duration_ms": round(1000 * (time.monotonic() - started)) if started is not None else 0,
            "resources": resources or {},
        }
        if error:
            event["error_classification"] = error
        self.events[stage] = event
        # Only allowlisted stages/results and numeric resource values, no IDs,
        # document text, paths, URLs, native stderr or credentials.
        logger.info("presentation_stage %s", event)

    def result(self):
        return list(self.events.values())


def backend_identity(settings):
    if not (
        settings.pptx_rendering_enabled
        and settings.pptx_renderer_root
        and settings.file_reading_enabled
        and settings.parser_root
        and os.name == "nt"
    ):
        raise DomainError(
            "unsupported_feature",
            "PPTX conversion is unavailable on this server.",
            reason_code="PPTX_RENDERER_UNAVAILABLE",
            processing_stage="pptx_conversion",
            details={
                "retryable": False,
                "visual_render_status": "unavailable",
                "assistant_pixels_delivered": False,
            },
        )
    try:
        root = settings.pptx_renderer_root.resolve(strict=True)
        values = [CONVERTER, str(root)]
        for name in ("soffice.bin", "mergedlo.dll", "version.ini"):
            path = root / "program" / name
            stat = path.stat()
            values.append(f"{name}:{stat.st_size}:{stat.st_mtime_ns}")
        return hashlib.sha256("|".join(values).encode()).hexdigest()
    except OSError as exc:
        raise DomainError(
            "unsupported_feature",
            "The configured PPTX conversion backend is missing.",
            reason_code="PPTX_RENDERER_UNAVAILABLE",
            processing_stage="pptx_conversion",
        ) from exc


async def convert_document(data, settings, slide):
    return await asyncio.to_thread(
        extract_isolated,
        data,
        "pptx",
        settings.parser_root,
        presentation_root=settings.pptx_renderer_root,
        visual={"page": slide, "rotation": 0, "conversion_only": True},
    )


def text_fallback(row, metadata, settings, slide, *, now=None):
    """Read existing version-bound evidence; never trigger another extraction."""
    state = row.file_state
    result = {
        "status": "not_checked",
        "source_version": file_version(metadata),
        "source_slide": slide,
        "scope": "requested_slide_text_only",
    }
    if state.get("version") != result["source_version"] or state.get("parser") != PARSER:
        return result
    if state.get("stage") in {"failed", "unsupported"}:
        return {
            **result,
            "status": "failed",
            "reason_code": state.get("reason_code") or "TEXT_EXTRACTION_FAILED",
            "processing_stage": state.get("processing_stage"),
        }
    if not fresh_cache(row, metadata, settings, now=now):
        return result
    page = next((p for p in row.locators if p["page"] == slide), None)
    if page is None or page["state"] in {"unreadable", "resource_limit"}:
        return {**result, "status": "failed", "reason_code": "SLIDE_TEXT_INCOMPLETE"}
    if not page["text"].strip():
        return {**result, "status": "failed", "reason_code": "NO_USABLE_SLIDE_TEXT"}
    return {
        **result,
        "status": "available",
        "content_hash": row.version_hash,
        "extraction_state": page["state"],
        "tool": "read_course_file",
        "arguments": {
            "file_id": row.id,
            "page_start": slide,
            "page_end": slide,
            "expected_hash": row.version_hash,
        },
    }


async def render_slide(
    bridge,
    owner,
    ref,
    file_id,
    slide=1,
    expected_source_hash=None,
    resolution="standard",
    *,
    rotation=0,
):
    if type(slide) is not int or not 1 <= slide <= 200 or resolution not in {"standard", "high"}:
        raise DomainError(
            "needs_input",
            "Choose a slide from 1–200 and standard or high resolution.",
            reason_code="INVALID_SLIDE",
            processing_stage="input_validation",
        )
    trace, stage = Trace(), "authorization"
    fallback = None
    started = trace.started
    async with bridge.lock("file:" + ref + ":" + file_id):
        try:
            row, course, metadata, epoch = await authorized(bridge, owner, ref, file_id)
            trace.record(stage, "completed", started=started)
            if file_format(metadata) != "pptx":
                raise DomainError(
                    "unsupported_feature",
                    "render_course_slide requires a PPTX. Use render_course_file_page for PDF.",
                    reason_code="PPTX_REQUIRED",
                )
            version = file_version(metadata)
            if not version:
                raise DomainError("source_changed", "A stable source version is required.")
            fallback = text_fallback(
                row, metadata, bridge.settings, slide, now=bridge.retention.clock()
            )
            if fallback["status"] == "available":
                fallback["arguments"]["connection_id"] = ref
            stage, started = "pptx_conversion", time.monotonic()
            engine = backend_identity(bridge.settings)
            key = (owner, ref, file_id, epoch, version, engine, slide)
            cached = bridge.presentation_derivatives.get(key)
            cache_hit = cached is not None
            if cached:
                derivative, pdf = cached
                digest = derivative["source_content_hash"]
                if expected_source_hash and expected_source_hash != digest:
                    raise DomainError(
                        "source_changed", "The presentation changed; begin a fresh visual review."
                    )
                trace.record("source_fetch", "completed", resources={"cache_hit": 1})
                trace.record("pptx_conversion", "completed", resources={"cache_hit": 1})
                trace.record(
                    "derivative_registration",
                    "completed",
                    resources={"cache_hit": 1, "pdf_bytes": len(pdf)},
                )
            else:
                stage, started = "source_fetch", time.monotonic()
                async with bridge.client(owner, ref) as client:
                    async with (
                        bridge.synthetic.client() if bridge.synthetic else nullcontext(None) as http
                    ):
                        download = await download_file(
                            client, course.source_id, row.source_id, http=http
                        )
                if download.kind != "pptx" or download.revision != version:
                    raise DomainError(
                        "source_changed", "The presentation changed while downloading."
                    )
                digest = hashlib.sha256(download.data).hexdigest()
                if expected_source_hash and expected_source_hash != digest:
                    raise DomainError(
                        "source_changed", "The presentation changed; begin a fresh visual review."
                    )
                trace.record(
                    stage,
                    "completed",
                    started=started,
                    resources={"source_bytes": len(download.data)},
                )
                stage, started = "pptx_conversion", time.monotonic()
                from canvas_bridge.worker_storage import processing

                with processing(owner, ref, namespace=bridge.processing_namespace):
                    derivative, pdf = await convert_document(download.data, bridge.settings, slide)
                trace.record(
                    stage,
                    "completed",
                    started=started,
                    resources={
                        **derivative.get("resource_usage", {}),
                        "pdf_bytes": len(pdf),
                        "pages": derivative["pdf_page_count"],
                        **{
                            k: derivative[k]
                            for k in ("subset_bytes", "subset_members")
                            if k in derivative
                        },
                    },
                )
            if slide > derivative["source_slide_count"]:
                raise DomainError(
                    "needs_input",
                    "The requested slide is absent from this presentation.",
                    reason_code="INVALID_SLIDE",
                    processing_stage="slide_mapping",
                )
            mapping = derivative["slide_to_page"][0]
            if mapping["source_slide"] != slide or mapping["pdf_page"] != 1:
                raise DomainError(
                    "unsupported_feature",
                    "Slide mapping could not be verified.",
                    reason_code="PPTX_SLIDE_MAPPING_UNCERTAIN",
                    processing_stage="slide_mapping",
                )
            stage, started = "pdf_page_render", time.monotonic()
            from canvas_bridge.visual_files import render_document
            from canvas_bridge.worker_storage import processing

            with processing(owner, ref, namespace=bridge.processing_namespace):
                rendering = await render_document(
                    pdf,
                    bridge.settings,
                    mapping["pdf_page"],
                    rotation,
                    max_edge=2400 if resolution == "high" else 1600,
                )
            if (
                rendering["content_hash"] != derivative["derivative_content_hash"]
                or rendering["page_count"] != derivative["pdf_page_count"]
            ):
                raise DomainError(
                    "unsupported_feature",
                    "The PDF derivative is inconsistent.",
                    reason_code="PPTX_DERIVATIVE_INVALID",
                    processing_stage=stage,
                )
            trace.record(
                stage,
                "completed",
                started=started,
                resources={
                    "width_pixels": rendering["pixels"][0],
                    "height_pixels": rendering["pixels"][1],
                },
            )
            # Both hit and miss recheck current metadata and epoch after rendering.
            stage, started = "authorization", time.monotonic()
            async with bridge.client(owner, ref) as client:
                after = await file_metadata(client, course.source_id, row.source_id)
            if file_version(after) != version:
                raise DomainError("source_changed", "The source changed during rendering.")
            with bridge.store.transaction() as session:
                checked_row(bridge, session, owner, ref, file_id, epoch)
            if not cache_hit:
                bridge.presentation_derivatives.put(key, derivative, pdf)
                trace.record(
                    "derivative_registration",
                    "completed",
                    resources={"cache_hit": 0, "pdf_bytes": len(pdf)},
                )
            now = utcnow()
            receipt = bridge.vault.seal(
                {
                    "purpose": "visual_slide",
                    "file_id": file_id,
                    "epoch": epoch,
                    "version": version,
                    "hash": digest,
                    "page": slide,
                    "derivative_hash": derivative["derivative_content_hash"],
                    "image_hash": rendering["image_hash"],
                    "retrieved_at": now.isoformat(),
                    "expires": (now + timedelta(hours=1)).isoformat(),
                },
                owner,
                ref,
            )
            png = rendering.pop("png")
            trace.record(
                "image_response_preparation",
                "completed",
                resources={"png_bytes": len(png) * 3 // 4},
            )
            return Result(
                summary="Authorized rendered slide. Inspect the image before describing it; a render is not visual interpretation.",
                data={
                    **rendering,
                    "file_id": file_id,
                    "format": "pptx",
                    "source_format": "pptx",
                    "source_locator": f"Slide {slide}",
                    "source_slide": slide,
                    "slide_number": slide,
                    "page": slide,
                    "page_count": derivative["source_slide_count"],
                    "derivative_page_count": derivative["pdf_page_count"],
                    "source_slide_image_references": derivative.get(
                        "source_slide_image_references"
                    ),
                    "source_version": version,
                    "content_hash": digest,
                    "source_content_hash": digest,
                    "rendered_page": mapping["pdf_page"],
                    "derivative_content_hash": derivative["derivative_content_hash"],
                    "converter": derivative["converter"],
                    "engine_build": derivative["engine_build"],
                    "slide_to_page": derivative["slide_to_page"],
                    "mapping_validation": derivative["mapping_validation"],
                    "hidden_slide": mapping["hidden"],
                    "render_status": "rendered",
                    "visual_render_status": "rendered_not_interpreted",
                    "visual_delivery": "mcp_image_and_native_reader",
                    "image_delivery_status": "response_prepared_host_visibility_unconfirmed",
                    "assistant_pixel_visibility": "not_confirmed_by_server",
                    "visual_observation": "not_yet_inspected",
                    "visually_inspected": [],
                    "render_receipt": receipt,
                    "resolution": resolution,
                    "cache_hit": cache_hit,
                    "next_slide": slide + 1 if slide < derivative["source_slide_count"] else None,
                    "continuation_expected_hash": digest,
                    "warnings": derivative["warnings"],
                    "pipeline_events": trace.result(),
                    "visual_pipeline": lifecycle(events=trace.result()),
                    "retention": "Private process-memory PDF cache: ten minutes, four derivatives / 40 MB total; fresh source access required on every render. No Canvas writes.",
                },
                sources=[
                    source(row, f"Slide {slide}").model_copy(
                        update={
                            "content_hash": digest,
                            "retrieved_at": now,
                            "extraction_status": "slide_rendered",
                            "uncertainty": ["Interpretation requires actual model-visible pixels."],
                        }
                    )
                ],
                meta=bridge.meta(),
            ), png
        except DomainError as exc:
            if exc.status in {"permission_denied", "reconnect_required", "source_changed"}:
                bridge.presentation_derivatives.invalidate(owner, ref, file_id)
            trace.record(
                stage,
                "unavailable" if exc.reason_code == "PPTX_RENDERER_UNAVAILABLE" else "failed",
                started=started,
                resources=exc.details.get("resource_usage", {}),
                error=exc.reason_code or exc.status,
            )
            exc.details["pipeline_events"] = trace.result()
            exc.details["visual_pipeline"] = lifecycle(events=trace.result())
            if fallback is not None and exc.status in {"unsupported_feature", "retry_later"}:
                exc.details["text_fallback"] = fallback
                exc.message += {
                    "available": " Previously extracted text is available for this slide; it is not a visual review.",
                    "failed": f" Text fallback failed for this source: {fallback.get('reason_code')}.",
                    "not_checked": " Text fallback has not been checked for this source version.",
                }[fallback["status"]]
            raise
