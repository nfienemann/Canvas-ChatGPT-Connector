"""Bounded browser-byte imports and local-only candidate review; no acquisition API."""

import hashlib
import io
import mimetypes
import re
import stat
import unicodedata
import zipfile
from copy import deepcopy
from datetime import timedelta
from pathlib import PurePosixPath

from sqlalchemy import select

from canvas_bridge.academic.independent_models import IndependentAcademicInput, IndependentWork
from canvas_bridge.domain import DomainError, opaque_id
from canvas_bridge.evidence import fingerprint
from canvas_bridge.storage import IndependentResource, aware
from canvas_bridge.usefulness.search import locator

ZIP_BYTES = 50_000_000
DOCUMENT_BYTES = 10_000_000
SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md"}


def unpack(data, filename, mime, *, logical_paths=False):
    if not filename.lower().endswith(".zip"):
        if len(data) > DOCUMENT_BYTES:
            raise DomainError("needs_input", "Batch imports allow 10 MB per document.")
        return [(filename, data, mime)], []
    if len(data) > ZIP_BYTES or mime not in {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    }:
        raise DomainError("needs_input", "Choose a ZIP no larger than 50 MB with a matching type.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 100:
                raise ValueError
            names, accepted, excluded, total = set(), [], [], 0
            for entry in entries:
                path = PurePosixPath(entry.filename)
                folded = unicodedata.normalize("NFC", entry.filename).casefold().rstrip("/")
                if (
                    path.is_absolute()
                    or entry.orig_filename != entry.filename
                    or len(entry.filename) > 2048
                    or any(not part for part in entry.filename.rstrip("/").split("/"))
                    or any(ord(c) < 32 for c in entry.filename)
                    or any(p in {"..", "."} for p in entry.filename.split("/"))
                    or any(c in entry.filename for c in "\\:\x00")
                    or folded in names
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.flag_bits & 1
                ):
                    raise ValueError
                names.add(folded)
                total += entry.file_size
                if (
                    total > 200_000_000
                    or entry.file_size > max(1, entry.compress_size) * 50
                    or entry.file_size > DOCUMENT_BYTES
                ):
                    raise ValueError
                if entry.is_dir():
                    continue
                if path.suffix.lower() in {".zip", ".tar", ".gz", ".7z", ".rar"}:
                    raise ValueError
                if path.suffix.lower() not in SUPPORTED:
                    excluded.append(entry.filename)
                    continue
                if len(accepted) >= 20:
                    raise ValueError
                # Streamed reads enforce actual counts, not just ZIP directory metadata.
                with archive.open(entry) as stream:
                    body = stream.read(DOCUMENT_BYTES + 1)
                if len(body) != entry.file_size or len(body) > DOCUMENT_BYTES:
                    raise ValueError
                accepted.append(
                    (
                        entry.filename if logical_paths else path.name,
                        body,
                        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    )
                )
            if not accepted and not logical_paths:
                raise DomainError("needs_input", "This ZIP has no supported documents.")
            return accepted, excluded
    except (ValueError, OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
        raise DomainError(
            "needs_input",
            "ZIP rejected: check paths, encryption, nested archives, collisions and expansion limits.",
        ) from None


class Imports:
    def __init__(self, bridge):
        self.bridge = bridge

    def status(self, owner, ident):
        with self.bridge.store.transaction() as session:
            row = session.get(IndependentResource, ident)
            if (
                not row
                or row.owner != owner
                or row.kind != "import_batch"
                or aware(row.expires_at) <= self.bridge.retention.clock()
            ):
                raise DomainError("permission_denied", "This import batch is unavailable.")
            return dict(row.content)

    def update(self, owner, ident, update, *, attempt=None):
        with self.bridge.store.transaction() as session:
            self.bridge.store.principal(session, owner)
            row = session.get(IndependentResource, ident)
            if (
                not row
                or row.owner != owner
                or row.kind != "import_batch"
                or aware(row.expires_at) <= self.bridge.retention.clock()
            ):
                raise DomainError("permission_denied", "This import batch is unavailable.")
            content = deepcopy(row.content)
            if attempt and content.get("attempt") != attempt:
                raise DomainError("source_changed", "Another attempt owns this receipt.")
            update(content)
            row.content, row.version_hash = content, fingerprint(content)

    def cancel(self, owner, ident):
        def cancel(content):
            content["state"] = "cancelled"
            content["items"] = [
                i if i["state"] == "ready" else i | {"state": "cancelled"} for i in content["items"]
            ]

        self.update(owner, ident, cancel)

    async def run(
        self,
        owner,
        data,
        filename,
        mime,
        *,
        course,
        purpose,
        key,
        permissions,
        validate_session,
        term="unspecified",
        preview_only=False,
        confirmation=None,
        decisions=None,
        expected=None,
    ):
        if not 1 <= len(key) <= 100:
            raise DomainError("needs_input", "A bounded import retry key is required.")
        from canvas_bridge.usefulness import packet

        attempt = opaque_id()
        is_packet = filename.lower().endswith(".zip")
        if not permissions.get("own_material"):
            raise DomainError(
                "permission_denied", "Confirm permission to process the selected materials."
            )
        try:
            files, excluded = unpack(data, filename, mime, logical_paths=is_packet)
        except DomainError:
            if not (is_packet and preview_only):
                raise
            # Never decompress rejected archives. Account for the bounded central
            # directory only where it can safely be read.
            members = []
            if len(data) <= ZIP_BYTES:
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        for entry in archive.infolist()[:100]:
                            members.append(
                                {
                                    "logical_path": entry.orig_filename[:2048],
                                    "disposition": "rejected",
                                    "state": "rejected",
                                }
                            )
                except (zipfile.BadZipFile, ValueError, OSError):
                    pass
            return {
                "state": "rejected",
                "items": members,
                "excluded": [],
                "reason": "PORT_ARCHIVE_REJECTED",
                "coverage": {"missing": [], "mode": "rejected"},
            }
        decisions = decisions or {}
        expected = expected or {}
        if not isinstance(decisions, dict) or len(decisions) > 20:
            raise DomainError("needs_input", "Review the bounded packet mapping.")
        packet_hash = hashlib.sha256(data).hexdigest()
        ident = fingerprint([owner, "import-batch", key])
        signature = fingerprint(
            [packet_hash, filename, mime, course, purpose, permissions]
            + (
                [term, decisions, expected]
                if is_packet and (term != "unspecified" or decisions or expected)
                else []
            )
        )
        now = self.bridge.retention.clock()
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            prior = session.get(IndependentResource, ident)
            proposed = None
            if is_packet and (preview_only or not prior):
                current = packet.eligible_documents(
                    self.bridge, session, owner, course, purpose, term, now
                )
                proposed = packet.plan(
                    session, owner, course, purpose, term, files, decisions, now, current
                )
                observation = packet.coverage(
                    session, owner, course, purpose, term, proposed, expected, now, current
                )
                review_id = fingerprint(
                    [signature, principal.generation, proposed, observation, excluded]
                )
                if preview_only or (
                    confirmation != review_id
                    and (
                        confirmation
                        or any(
                            i["disposition"]
                            in {
                                "ambiguous",
                                "new_version",
                                "conflicting_mapping",
                                "unexpected_version",
                            }
                            for i in proposed
                        )
                    )
                ):
                    return {
                        "state": "review_required",
                        "preview_id": review_id,
                        "items": proposed,
                        "excluded": excluded,
                        "coverage": observation,
                        "packet_hash": packet_hash,
                    }
            if prior:
                if aware(prior.expires_at) <= now:
                    raise DomainError(
                        "source_changed",
                        "This import receipt expired; select the files for a new import.",
                    )
                if (
                    prior.owner != owner
                    or prior.kind != "import_batch"
                    or prior.provenance.get("generation", principal.generation)
                    != principal.generation
                    or prior.content["signature"] != signature
                ):
                    raise DomainError(
                        "source_changed", "Retry the original selection or use a new batch."
                    )
                if prior.content["state"] in {"ready", "cancelled"}:
                    return prior.content
                if (
                    prior.content["state"] == "extracting"
                    and aware(prior.created_at) + timedelta(minutes=10) > now
                ):
                    raise DomainError(
                        "retry_later", "This batch is still processing; inspect its status."
                    )
                content = dict(prior.content)
                content["state"] = "extracting"
                content["attempt"] = attempt
                content["items"] = [
                    i if i["state"] == "ready" else i | {"state": "staged"}
                    for i in content["items"]
                ]
                prior.content = content
                prior.created_at = now
            else:
                active = list(
                    session.scalars(
                        select(IndependentResource).where(
                            IndependentResource.owner == owner,
                            IndependentResource.kind == "import_batch",
                            IndependentResource.expires_at > now,
                        )
                    )
                )
                if any(
                    r.content["state"] == "extracting"
                    and aware(r.created_at) + timedelta(minutes=10) > now
                    for r in active
                ):
                    raise DomainError(
                        "retry_later", "Finish or cancel the active import batch first."
                    )
                if len(active) >= 40:
                    raise DomainError(
                        "retry_later",
                        "Import receipt capacity reached; allow old batches to expire.",
                    )
                content = {
                    "batch_id": ident,
                    "attempt": attempt,
                    "signature": signature,
                    **(
                        {
                            "preview_id": review_id,
                            "packet_hash": packet_hash,
                            "coverage": observation,
                        }
                        if proposed is not None
                        else {}
                    ),
                    "state": "extracting",
                    "course": course,
                    "term": term,
                    "purpose": purpose,
                    "excluded": excluded,
                    "items": [
                        {
                            "filename": name,
                            "size": len(body),
                            "state": "staged",
                            **(proposed[n] if proposed else {}),
                        }
                        for n, (name, body, _) in enumerate(files)
                    ],
                }
                session.add(
                    IndependentResource(
                        id=ident,
                        owner=owner,
                        kind="import_batch",
                        version_hash=fingerprint(content),
                        content=content,
                        provenance={
                            "owner": owner,
                            "retention_class": "restricted_raw_records",
                            "generation": principal.generation,
                        },
                        created_at=now,
                        expires_at=now + timedelta(hours=24),
                    )
                )

        def recheck():
            validate_session()
            status = self.status(owner, ident)
            if status["state"] == "cancelled" or status.get("attempt") != attempt:
                raise DomainError(
                    "needs_input", "The batch was cancelled; completed imports were retained."
                )

        for index, (name, body, content_type) in enumerate(files):
            if self.status(owner, ident)["items"][index]["state"] == "ready":
                continue
            if self.status(owner, ident)["state"] == "cancelled":
                break
            self.update(
                owner,
                ident,
                lambda c, index=index: c["items"][index].update(state="extracting"),
                attempt=attempt,
            )
            try:
                item = self.status(owner, ident)["items"][index]
                selection = (
                    packet.member(item, ident, index, attempt)
                    if is_packet and "binding" in item
                    else None
                )
                if selection:
                    recheck()
                    if selection.disposition in {
                        "ambiguous",
                        "conflicting_mapping",
                        "unexpected_version",
                    }:
                        raise DomainError(
                            "needs_input", "Review this source mapping or expected version."
                        )
                basename = PurePosixPath(name).name if is_packet else name
                if selection and len(basename) > 180:
                    basename = selection.digest + PurePosixPath(basename).suffix
                doc = await self.bridge.independent.ingest(
                    owner,
                    body,
                    basename,
                    content_type,
                    course=course,
                    purpose=purpose,
                    validate_session=recheck,
                    packet_member=selection,
                    **permissions,
                )
                if selection:
                    continue
                saved = self.bridge.independent.require(owner, doc)
                extraction = saved.content["parsed"].get("coverage", "unknown")
                self.update(
                    owner,
                    ident,
                    lambda c, index=index, doc=doc, extraction=extraction: c["items"][index].update(
                        state="ready", document_id=doc, extraction=extraction
                    ),
                )
            except DomainError as exc:
                reason = exc.reason_code or exc.status
                next_action = (
                    "Local file processing is not configured; ask the operator to enable the reviewed local parser."
                    if reason == "EXTRACTION_RUNTIME_UNCONFIGURED"
                    else "Review this file's ownership, privacy and sharing permissions."
                    if exc.status == "permission_denied"
                    else "Wait for local processing capacity, then retry this batch."
                    if exc.status == "retry_later"
                    else "Review the supported file format and size, then retry this file."
                )
                self.update(
                    owner,
                    ident,
                    lambda c, index=index, reason=reason, next_action=next_action: c["items"][
                        index
                    ].update(
                        state="cancelled" if c["state"] == "cancelled" else "failed",
                        reason=reason,
                        next_action=next_action,
                    ),
                    attempt=attempt,
                )

        def finish(content):
            if content["state"] != "cancelled":
                ready = sum(i["state"] == "ready" for i in content["items"])
                content["state"] = (
                    "partial"
                    if not content["items"] and content["excluded"]
                    else "ready"
                    if ready == len(content["items"])
                    else "partial"
                    if ready
                    else "failed"
                )

        self.update(owner, ident, finish, attempt=attempt)
        return self.status(owner, ident)


def candidates(row):
    from canvas_bridge.academic_dates import DATES, parse_candidate

    values = []
    for part, page in enumerate(row.content["parsed"].get("pages", [])[:200], 1):
        text = page.get("text", "")
        for m in re.finditer(r"[^\n]+", text[:200_000]):
            quote = m.group()[:1500]
            if not re.search(
                r"\b(due|TBD|must|required|words?|weight|repl(?:y|ies)|revise|submit)\b|\d\s*%",
                quote,
                re.I,
            ):
                continue
            dates = list(DATES.finditer(quote))
            value = {"kind": "not_returned"}
            if len(dates) == 1:
                parsed = parse_candidate(dates[0])
                if parsed.get("date") and parsed["precision"] == "date":
                    value = {"kind": "local_date", "local_date": parsed["date"]}
                elif parsed.get("date") and parsed["precision"] == "timestamp":
                    value = {"kind": "timestamp", "timestamp": parsed["date"]}
            values.append(
                {
                    "id": fingerprint([row.id, row.version_hash, part, m.start(), quote]),
                    "document_id": row.id,
                    "content_hash": row.version_hash,
                    "part": part,
                    "locator": locator(page, part, row.content["format"]),
                    "start": m.start(),
                    "end": m.start() + len(quote),
                    "quote": quote,
                    "title": re.split(r"\b(?:due|must|requires?|submit)\b", quote, flags=re.I)[
                        0
                    ].strip(" :-")[:500]
                    or "Reviewed activity",
                    "due": value,
                    "precision": {"local_date": "date_only", "timestamp": "explicit_instant"}.get(
                        value["kind"], "unknown"
                    ),
                    "fields": [
                        {
                            "kind": kind,
                            "value": match.group(1),
                            "start": m.start() + match.start(),
                            "end": m.start() + match.end(),
                            "quote": match.group(),
                        }
                        for kind, pattern in (
                            ("word_count", r"\b(\d{1,6})\s+words?\b"),
                            ("weight_percent_candidate", r"\b(\d{1,3}(?:\.\d{1,2})?)\s*%"),
                        )
                        for match in re.finditer(pattern, quote, re.I)
                    ][:8],
                    "interpretation_status": "deterministic_candidate_requires_review",
                }
            )
            if len(values) >= 50:
                return values
    return values


def compile_review(row, decisions, *, timezone=None):
    """Every accepted/edit item cites the exact original candidate; omissions remain recorded."""
    original = {c["id"]: c for c in candidates(row)}
    work, reviewed = [], []
    for ident, choice in decisions.items():
        if ident not in original or choice["action"] not in {"accept", "edit", "omit"}:
            raise DomainError("source_changed", "Review the current candidate selection.")
        candidate = original[ident]
        reviewed.append(
            {"candidate": candidate, "action": choice["action"], "correction": choice.get("work")}
        )
        if choice["action"] == "omit":
            continue
        value = choice.get("work") or {
            "key": ident[:32],
            "title": candidate["title"],
            "due": candidate["due"],
            "requirement": "unresolved",
        }
        value = dict(value)
        value["evidence"] = [
            {
                k: candidate[k]
                for k in ("document_id", "content_hash", "part", "locator", "start", "end", "quote")
            }
        ]
        value["requirement_basis"] = (
            "Authenticated student review of the cited passage; not an instructor amendment."
        )
        work.append(IndependentWork.model_validate(value))
    dataset = IndependentAcademicInput(
        schema_version="independent-academic-1", work=work, timezone=timezone, complete=False
    )
    return {
        "dataset": dataset.model_dump(mode="json"),
        "decisions": reviewed,
        "source_hash": row.version_hash,
        "coverage": "reviewed_selection_only",
        "grade_policy": "not_inferred",
    }
