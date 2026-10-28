"""Private, bounded, process-local PDF derivatives. Never a download endpoint.

Callers MUST authorize the original source before lookup and fence it again
before serving pixels. Cache keys bind owner, connection, file, authorization
epoch, source version, converter configuration and selected slide. Validated
source and PDF hashes remain distinct; expected-source-hash checks apply on hits.
"""

import copy
import hashlib
import time
from dataclasses import dataclass

from canvas_bridge.document_policy import PPTX_MEMBERS, PPTX_SOURCE_BYTES
from canvas_bridge.domain import DomainError
from canvas_bridge.presentation_render_worker import CONVERTER, MAX_PDF
from canvas_bridge.retention_policy import DERIVATIVE_SECONDS


def validate_derivative(result, source, pdf, selected_slide=1):
    if not result.get("ok"):
        reason = result.get("reason")
        codes = {
            "page_limit_or_range": "INVALID_SLIDE",
            "render_timeout": "PPTX_CONVERSION_TIMEOUT",
            "memory_limit": "SLIDE_RENDER_RESOURCE_LIMIT",
            "pptx_expansion_limit": "PPTX_EXPANSION_LIMIT",
            "conversion_page_mismatch": "PPTX_SLIDE_MAPPING_UNCERTAIN",
            "conversion_invalid_pdf": "PPTX_DERIVATIVE_INVALID",
            "image_output_limit": "PPTX_DERIVATIVE_LIMIT",
            "active_or_external_content": "PPTX_UNSAFE_CONTENT",
            "unsupported_slide_media": "PPTX_UNSUPPORTED_MEDIA",
            "image_resource_limit": "SLIDE_RENDER_RESOURCE_LIMIT",
            "invalid_slide_reference": "PPTX_INVALID_SLIDE_REFERENCE",
            "invalid_pptx_archive": "PPTX_INVALID_ARCHIVE",
            "active_office_content": "PPTX_UNSAFE_CONTENT",
        }
        raise DomainError(
            "needs_input"
            if reason == "page_limit_or_range"
            else "retry_later"
            if reason == "render_timeout"
            else "unsupported_feature",
            "PPTX conversion did not produce a verified PDF derivative.",
            reason_code=codes.get(reason, "PPTX_CONVERSION_FAILED"),
            processing_stage="pptx_conversion",
            details={
                "retryable": reason == "render_timeout",
                "visual_observation": "not_yet_inspected",
                **(
                    {"unsupported_media_format": result["media_format"]}
                    if result.get("media_format")
                    in {"emf", "wmf", "svg", "wdp", "mp4", "wav", "other"}
                    else {}
                ),
            },
        )
    d = result["derivative"]
    count = d.get("pdf_page_count")
    if (
        d.get("converter") != CONVERTER
        or d.get("source_content_hash") != hashlib.sha256(source).hexdigest()
        or not 0 < len(pdf) <= MAX_PDF
        or not pdf.startswith(b"%PDF-")
        or d.get("pdf_bytes") != len(pdf)
        or d.get("derivative_content_hash") != hashlib.sha256(pdf).hexdigest()
        or type(count) is not int
        or count != 1
        or type(d.get("source_slide_count")) is not int
        or not selected_slide <= d["source_slide_count"] <= 200
        or d.get("selected_slide") != selected_slide
        or type(d.get("selected_slide")) is not int
        or type(d.get("normalized_emf_bitmaps", 0)) is not int
        or not 0 <= d.get("normalized_emf_bitmaps", 0) <= PPTX_MEMBERS
        or any(
            type(d.get(key)) is not int or not 0 <= d[key] <= maximum
            for key, maximum in (
                ("subset_bytes", PPTX_SOURCE_BYTES),
                ("subset_members", PPTX_MEMBERS),
                ("source_slide_image_references", 200_000),
            )
        )
        or len(d.get("slide_to_page", [])) != count
        or d.get("mapping_validation")
        != "single_source_slide_hidden_included_one_pdf_page_and_geometry"
        or not isinstance(d.get("engine_build"), str)
        or len(d["engine_build"]) > 64
        or type(d.get("conversion_ms")) is not int
        or not 0 <= d["conversion_ms"] <= 75_000
        or not isinstance(d.get("warnings"), list)
        or len(d["warnings"]) > 10
        or any(not isinstance(w, str) or len(w) > 1000 for w in d["warnings"])
    ):
        raise ValueError("Invalid derivative manifest")
    for entry in d["slide_to_page"]:
        if (
            entry != {"source_slide": selected_slide, "pdf_page": 1, "hidden": entry.get("hidden")}
            or type(entry.get("hidden")) is not bool
        ):
            raise ValueError("Invalid slide mapping")
    return d


@dataclass(frozen=True)
class Derivative:
    metadata: dict
    pdf: bytes
    created: float


class Derivatives:
    """At most four PDFs / 40 MB total, ten minutes, no binary disk cache.

    Entries are lost on restart, omitted from backups and never exposed by ID.
    Access checks remain outside this cache on *every* request, including hits.
    """

    ttl = DERIVATIVE_SECONDS
    maximum_bytes = 40_000_000

    def __init__(self):
        self.records = {}

    def cleanup(self):
        now = time.monotonic()
        for key, item in list(self.records.items()):
            if not 0 <= now - item.created < self.ttl:
                self.records.pop(key, None)

    def invalidate(self, owner, connection, file=None):
        for key in list(self.records):
            if key[:2] == (owner, connection) and (file is None or key[2] == file):
                del self.records[key]

    def get(self, key):
        self.cleanup()
        # A new source version, epoch or converter invalidates older entries.
        for other in list(self.records):
            if other[:3] == key[:3] and other[3:6] != key[3:6]:
                del self.records[other]
        item = self.records.get(key)
        return (copy.deepcopy(item.metadata), item.pdf) if item else None

    def put(self, key, metadata, pdf):
        if len(pdf) > MAX_PDF:
            raise ValueError("Derivative cache input limit")
        self.get(key)
        while self.records and (
            len(self.records) >= 4
            or sum(len(i.pdf) for i in self.records.values()) + len(pdf) > self.maximum_bytes
        ):
            del self.records[next(iter(self.records))]
        self.records[key] = Derivative(copy.deepcopy(metadata), pdf, time.monotonic())

    def close(self):
        self.records.clear()
