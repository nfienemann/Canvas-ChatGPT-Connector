"""Structured PPTX reading through existing file authorization and scoped cache."""

import asyncio
import hashlib
import json
from contextlib import nullcontext

from canvas_bridge.course_files import authorized, checked_row, read_file, source
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.file_download import download_file, file_metadata, file_version
from canvas_bridge.parser_sandbox import extract_isolated


async def read_presentation(
    bridge, owner, ref, file_id, slide=None, offset=0, max_objects=10, expected_hash=None
):
    if (
        not 0 <= offset <= 400
        or not 1 <= max_objects <= 30
        or (slide is not None and not 1 <= slide <= 200)
        or (offset and (not expected_hash or slide is None))
    ):
        raise DomainError(
            "needs_input",
            "Choose a slide (1–200); continuation needs its content hash and object offset.",
        )
    result = await read_file(bridge, owner, ref, file_id, length=1, expected_hash=expected_hash)
    if result.data.get("format") != "pptx":
        if result.status not in {"ok", "partial_data"}:
            return result
        raise DomainError("unsupported_feature", "This file is not an extracted PPTX presentation.")
    _, _, _, epoch = await authorized(bridge, owner, ref, file_id)
    with bridge.store.transaction() as session:
        row = checked_row(bridge, session, owner, ref, file_id, epoch)
        if row.version_hash != result.data["content_hash"]:
            raise DomainError("source_changed", "Presentation changed. Read a fresh overview.")
    data = {
        "file_id": file_id,
        "filename": row.title,
        "format": "pptx",
        "presentation": row.file_state["metadata"],
        "content_hash": row.version_hash,
        "source_version": row.file_state["version"],
        "coverage": row.file_state["coverage"],
        "limitations": row.limitations,
        "content_boundary": "untrusted_source_data",
        "continuation": None,
    }
    sources = []
    if slide is not None:
        page = next((p for p in row.locators if p["page"] == slide), None)
        if page is None:
            raise DomainError(
                "needs_input", "Slide not found. Read the presentation overview first."
            )
        # Notes use the same bounded continuation as objects; long notes cannot
        # consume every response or cause subsequent objects to be skipped.
        records = list(page["objects"]) + [
            {"kind": "speaker_note", "note_paragraph": i, **p}
            for i, p in enumerate(page["notes"], 1)
        ]
        if offset > len(records):
            raise DomainError("needs_input", "Offset exceeds the extracted slide records.")
        selected, size = [], 0
        for record in records[offset : offset + max_objects]:
            label = (
                f"speaker notes paragraph {record['note_paragraph']}"
                if record["kind"] == "speaker_note"
                else f"object {record['object_index']}"
            )
            citation = source(row, f"Slide {slide}, {label}")
            item = {**record, "source_reference": citation.model_dump(mode="json")}
            if "table" in item:
                item["table"] = {
                    **item["table"],
                    "cells": [
                        {**c, "locator": f"Slide {slide}, {label}, table R{c['row']}C{c['column']}"}
                        for c in item["table"]["cells"]
                    ],
                    "cell_citation_format": f"Slide {slide}, {label}, table R<row>C<column>",
                }
            if size + len(json.dumps(item, ensure_ascii=True)) > 60000:
                if not selected:
                    raise DomainError(
                        "unsupported_feature", "Slide record exceeds the response budget."
                    )
                break
            size += len(json.dumps(item, ensure_ascii=True))
            selected.append(item)
            sources.append(citation)
        data.update(
            {
                "slide": slide,
                "hidden": page["hidden"],
                "records": selected,
                "record_count": len(records),
                "notes_state": page["notes_state"],
                "slide_coverage": page["coverage"],
                "visual_review_required": page["visual_review_required"],
            }
        )
        next_offset = offset + len(selected)
        if next_offset < len(records):
            data["continuation"] = {
                "file_id": file_id,
                "slide": slide,
                "offset": next_offset,
                "max_objects": max_objects,
                "expected_hash": row.version_hash,
            }
    return Result(
        status=result.status,
        summary="PPTX source structure and notes. Pictures and charts require visual evidence; course context can guide explanation but cannot establish unseen content.",
        data=data,
        sources=sources or [source(row)],
        meta=bridge.meta(),
    )


async def read_picture(bridge, owner, ref, file_id, slide, object_index, expected_hash=None):
    if type(object_index) is not int or not 1 <= object_index <= 200:
        raise DomainError("needs_input", "Choose an embedded picture object index.")
    return await _read_visual(bridge, owner, ref, file_id, slide, object_index, expected_hash)


async def read_slide(bridge, owner, ref, file_id, slide, expected_hash=None):
    return await _read_visual(bridge, owner, ref, file_id, slide, None, expected_hash)


async def _read_visual(bridge, owner, ref, file_id, slide, object_index, expected_hash):
    whole_slide = object_index is None
    if type(slide) is not int or not 1 <= slide <= 200:
        raise DomainError(
            "needs_input", "Use a slide and picture object index from read_course_presentation."
        )
    if not bridge.settings.file_reading_enabled or bridge.settings.parser_root is None:
        raise DomainError(
            "unsupported_feature", "Isolated image reading is not enabled on this server."
        )
    async with bridge.lock("file:" + ref + ":" + file_id):
        row, course, _, epoch = await authorized(bridge, owner, ref, file_id)
        async with bridge.client(owner, ref) as client:
            async with bridge.synthetic.client() if bridge.synthetic else nullcontext(None) as http:
                download = await download_file(client, course.source_id, row.source_id, http=http)
        if download.kind != "pptx":
            raise DomainError("unsupported_feature", "Presentation image reading requires PPTX.")
        digest = hashlib.sha256(download.data).hexdigest()
        if expected_hash is not None and expected_hash != digest:
            raise DomainError("source_changed", "Presentation changed. Start a fresh review.")
        if whole_slide:
            from canvas_bridge.full_slides import render_slide

            image = await asyncio.to_thread(render_slide, download.data, bridge.settings, slide)
        else:
            image = await asyncio.to_thread(
                extract_isolated,
                download.data,
                "pptx",
                bridge.settings.parser_root,
                runtime_root=bridge.settings.parser_runtime_root,
                ocr_root=bridge.settings.ocr_root,
                visual={"kind": "pptx", "page": slide, "rotation": 0, "object_index": object_index},
            )
        async with bridge.client(owner, ref) as client:
            after = await file_metadata(client, course.source_id, row.source_id)
        if not download.revision or file_version(after) != download.revision:
            raise DomainError(
                "source_changed", "A stable presentation version could not be established."
            )
        with bridge.store.transaction() as session:
            checked_row(bridge, session, owner, ref, file_id, epoch)
        citation = source(row, image["image_locator"]).model_copy(
            update={
                "retrieved_at": utcnow(),
                "content_hash": digest,
                "extraction_status": "slide_rendered" if whole_slide else "picture_decoded",
                "uncertainty": [
                    "Static LibreOffice rendering; font substitution and PowerPoint compatibility may affect layout. Meaning requires visual interpretation."
                    if whole_slide
                    else "Original picture pixels, not the complete slide. Meaning requires visual interpretation."
                ],
            }
        )
        png = image.pop("png")
        return Result(
            summary=(
                "Authorized complete static PPTX slide. Inspect its labels, layout and pictures alongside separate speaker notes and course context."
                if whole_slide
                else "Authorized embedded PPTX picture. Inspect pixels with its slide text and notes before interpreting scientific content."
            ),
            data={
                **image,
                "file_id": file_id,
                "source_version": download.revision,
                "binary_retrieved": True,
                "ocr_performed": False,
                "content_boundary": "untrusted_source_data",
                "limitations": [
                    "Static LibreOffice rendering may differ from PowerPoint, including fonts, unsupported effects, charts and SmartArt. This is not a fidelity guarantee.",
                    "Animations and video are not played. Speaker notes are separate; use read_course_presentation. Tiny labels may need a closer source review.",
                    "No slide OCR or visual search indexing is performed. Rendered pixels alone are not a transcription or a scientific interpretation.",
                    "If pixels are unavailable, use Read slide in ChatGPT. Never infer unseen labels or findings from the course topic.",
                ]
                if whole_slide
                else [
                    "Original uncropped picture: slide cropping, rotation, masks, overlays, group transforms and surrounding text are not applied.",
                    "Transparency is shown on white. Large pictures may be downsampled; tiny labels may be unreadable.",
                    "No full slide renderer, chart/SmartArt rendering or image OCR. Text search cannot find unread picture text.",
                    "If ChatGPT cannot see pixels, use Read image in ChatGPT in the native reader. Do not infer image content from alt text or course context.",
                ],
                "retention": "No persistent image cache. Temporary worker files are deleted after each request.",
            },
            sources=[citation],
            meta=bridge.meta(),
        ), png
