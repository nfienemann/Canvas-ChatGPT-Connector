"""Bounded, source-authorized comparisons for explicitly selected readiness versions."""

import base64
import hashlib
import io
import re
import unicodedata
import zlib
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.readiness import Binding
from canvas_bridge.processes.requests import ProcessScope
from canvas_bridge.processes.state import failure


def source_entries(service, owner, record, selected):
    ids = tuple(b.document_id for b in selected if b.document_id)
    if not ids:
        failure("READINESS_SOURCE_UNAVAILABLE")
    entries = service.load(
        owner,
        ProcessScope(document_ids=ids, local_course=record.scope.course, term=record.scope.term),
    )
    from canvas_bridge.processes.readiness import bind

    bind(entries, selected)
    if any(entry["tag"].scope != record.scope for entry in entries.values()):
        failure("PROCESS_SCOPE_MISMATCH")
    return entries


def native_manifest(raw):
    """Compare every canonical part; ambiguous or oversized packages cannot prove equivalence."""
    parts = {}
    try:
        with ZipFile(io.BytesIO(raw)) as package:
            members = package.infolist()
            if len(members) > 4096 or sum(i.file_size for i in members) > 64 * 1024 * 1024:
                return None
            for item in members:
                name = item.filename
                path = PurePosixPath(name)
                if (
                    item.orig_filename != name
                    or not name
                    or name.startswith("/")
                    or ":" in name
                    or "\x00" in name
                    or "\\" in name
                    or "%" in name
                    or unicodedata.normalize("NFC", name) != name
                    or path.as_posix() != name
                    or ".." in path.parts
                    or name.casefold() in parts
                    or item.flag_bits & 1
                ):
                    return None
                parts[name.casefold()] = (name, hashlib.sha256(package.read(item)).hexdigest())
    except (BadZipFile, RuntimeError, ValueError, NotImplementedError, OSError, zlib.error):
        return None
    if "[content_types].xml" not in parts or "ppt/presentation.xml" not in parts:
        return None
    return parts


def sections(text):
    chunks = re.split(r"(?m)^## (.+?)\s*$", text)
    result = {"": chunks[0]}
    for label, body in zip(chunks[1::2], chunks[2::2], strict=True):
        if label in result:
            return {}
        result[label] = body
    return result


def compare(service, owner, before, after):
    """Use the imported bytes. An extracted quote never proves native package equivalence."""
    row = service.bridge.independent.require
    result = dict(
        logical_id=after.logical_id,
        role=after.role,
        before_hash=before.content_hash if before else None,
        after_hash=after.content_hash,
        comparison_coverage="complete",
        changed_sections=[],
    )
    if not after.document_id or not before or not before.document_id:
        return result | dict(
            change_class="unavailable" if not after.document_id else "content_changed",
            comparison_coverage="unavailable",
        )
    if before.role != after.role:
        return result | dict(change_class="incomparable", comparison_coverage="unavailable")
    left, right = row(owner, before.document_id), row(owner, after.document_id)
    if (left.version_hash, right.version_hash) != (before.content_hash, after.content_hash):
        failure("READINESS_VERSION_MISMATCH")
    if left.version_hash == right.version_hash:
        return result | dict(change_class="alias_only", proof_id=left.version_hash)
    lraw, rraw = (base64.b64decode(r.content["bytes"], validate=True) for r in (left, right))
    if (
        hashlib.sha256(lraw).hexdigest() != before.content_hash
        or hashlib.sha256(rraw).hexdigest() != after.content_hash
    ):
        failure("READINESS_VERSION_MISMATCH")
    if left.content["format"] == right.content["format"] == "pptx":
        a, b = native_manifest(lraw), native_manifest(rraw)
        if a is not None and a == b:
            return result | dict(
                change_class="content_equivalent",
                proof_kind="all_native_parts",
                proof_id=fingerprint(a),
                part_count=len(a),
            )
        return result | dict(
            change_class="content_changed" if a and b else "incomparable",
            comparison_coverage="complete" if a and b else "partial",
        )
    try:
        texts = [raw.decode("utf-8-sig").replace("\r\n", "\n") for raw in (lraw, rraw)]
    except UnicodeDecodeError:
        return result | dict(change_class="incomparable", comparison_coverage="partial")

    # Preserve punctuation, case and word boundaries; allow blank-line-only remapping.
    def clean(t):
        return tuple(line for line in t.splitlines() if line.strip())

    if (
        all(len(t) <= 200_000 for t in texts)
        and not any(
            re.search(
                r"(?m)^(?:    |\t| {0,3}(?:`{3}|~{3}|[<>|]|[-=*+_]+[ \t]*$|[-*+]|\d+[.)] ))", t
            )
            for t in texts
        )
        and clean(texts[0]) == clean(texts[1])
    ):
        return result | dict(
            change_class="content_equivalent",
            proof_kind="nonblank_lines",
            proof_id=fingerprint(clean(texts[0])),
        )
    if any(len(t) > 200_000 for t in texts):
        return result | dict(change_class="content_changed", comparison_coverage="partial")
    a, b = map(sections, texts)
    changes = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    return result | dict(
        change_class="content_changed",
        changed_sections=changes if a and b else [],
        proof_id=fingerprint([left.version_hash, right.version_hash]),
    )


def bindings(data):
    return [Binding.model_validate(b) for b in data["bindings"]]
