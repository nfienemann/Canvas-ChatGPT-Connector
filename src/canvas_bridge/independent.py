"""Owned independent sources. No Canvas IDs, network acquisition or caller source labels."""

import base64
import hashlib
import json
from datetime import timedelta
from pathlib import PurePath

from sqlalchemy import select

from canvas_bridge.document_policy import LOCAL_IMPORT_BYTES, local_import_limit
from canvas_bridge.domain import DomainError, Result, Source, opaque_id
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import RecipientPolicy, SourceContext
from canvas_bridge.file_download import FILE_TYPES, file_format
from canvas_bridge.source_authorization import LocalPreferences
from canvas_bridge.storage import IndependentResource, Material, aware
from canvas_bridge.worker_storage import processing


def deny(code="SOURCE_PROVENANCE_UNKNOWN"):
    raise DomainError(
        "permission_denied", "This source is unavailable for the requested use.", reason_code=code
    )


def bounded_table_structure(structure):
    """Expose already extracted table coordinates; never infer layout or headers."""
    result = {"tables": [], "limitations": [], "visual_inspection_status": "not_performed"}
    tables = structure.get("tables", [])
    for table in tables[:10]:
        candidate = {
            key: table[key]
            for key in ("locator", "cells", "row_count", "structure_complete", "header_semantics")
            if key in table
        }
        # Include complete table items only. A truncated structure is never a
        # complete table or an excuse to bypass ordinary source egress checks.
        if len(json.dumps([*result["tables"], candidate]).encode()) > 12000:
            result["limitations"].append(
                "Table output budget exhausted; inspect the original for omitted structure."
            )
            break
        result["tables"].append(candidate)
    if len(tables) > 10:
        result["limitations"].append("Table count limit reached.")
    result["limitations"].extend(structure.get("limitations", [])[:5])
    return result


class IndependentSources:
    def __init__(self, bridge):
        self.bridge = bridge

    def profile(self):
        path = self.bridge.settings.independent_egress_file
        if self.bridge.settings.profile == "synthetic" and self.bridge.synthetic:
            # Fictional test identity only; this is never applied to a live service.
            return RecipientPolicy(
                policy_id="fictional-independent",
                recipient="chatgpt",
                environment="synthetic",
                workspace="synthetic",
                plan="fictional",
                issuer="synthetic",
                client_id="synthetic",
                classifications={CC.FIRST_PARTY_EDUCATIONAL_RECORD},
                purposes={
                    "metadata",
                    "document_reading",
                    "study",
                    "visual_analysis",
                    "grade_planning",
                    "schedule",
                },
                channels={"metadata", "structured", "text", "visual"},
                retention_days=0,
                training=False,
                downstream_processing={"inference"},
                max_output_bytes=2_000_000,
            )
        return self._read_profile(path, "chatgpt")

    def external_profile(self):
        policy = self._read_profile(
            self.bridge.settings.independent_external_egress_file, "external_ai"
        )
        if policy and policy.client_id not in self.bridge.settings.mcp_chatgpt_client_ids:
            return policy
        return None

    @staticmethod
    def _read_profile(path, recipient):
        if not path:
            return None
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_000:
                return None
            profile = RecipientPolicy.model_validate_json(path.read_text(encoding="utf-8"))
            if (
                profile.recipient != recipient
                or profile.training
                or "training" in profile.downstream_processing
            ):
                return None
            return profile
        except (OSError, ValueError):
            return None

    def require(self, owner, ident, *, kind="local_document"):
        if ident.startswith("lib_") and kind == "local_document":
            return self.bridge.library.adapter(owner, ident)
        with self.bridge.store.transaction() as session:
            row = session.scalar(
                select(IndependentResource).where(
                    IndependentResource.id == ident, IndependentResource.owner == owner
                )
            )
            return self.require_row(session, owner, row, kind=kind)

    def require_row(self, session, owner, row, *, kind="local_document"):
        if (
            not row
            or row.owner != owner
            or row.kind != kind
            or aware(row.expires_at) <= self.bridge.retention.clock()
        ):
            deny("RESOURCE_AUTHORIZATION_REVOKED")
        if row.content.get("portable_origin"):
            from canvas_bridge.usefulness.workspace_authority import verify_restored_source

            verify_restored_source(self.bridge, session, row)
        if row.content.get("packet"):
            self.reject_institutional_copy(session, owner, row.version_hash)
        p = row.provenance
        if (
            p.get("source_type") != kind
            or p.get("schema_version") != "source-provenance-1"
            or p.get("origin") != "authenticated_browser_upload"
            or p.get("mechanism") != "bounded_browser_upload"
            or p.get("owner") != owner
            or p.get("content_identity") != row.version_hash
            or p.get("institutional_connection") is not None
            or p.get("parents")
            or p.get("source_category", "independent_import") != "independent_import"
            or p.get("privacy_classification") != str(CC.FIRST_PARTY_EDUCATIONAL_RECORD)
        ):
            deny()
        if p.get("authorization") != "explicit_user_permission":
            deny("SOURCE_IDENTITY_UNVERIFIED")
        return row

    def reject_institutional_copy(self, session, owner, digest):
        # Known institutional bytes stay institutional regardless of a new filename.
        match = session.scalar(
            select(Material.id)
            .where(Material.owner == owner, Material.version_hash == digest)
            .execution_options(retention_admin=True)
            .limit(1)
        )
        lineage = session.scalar(
            select(IndependentResource.id)
            .where(
                IndependentResource.owner == owner,
                IndependentResource.kind == "institutional_lineage",
                IndependentResource.version_hash == digest,
            )
            .limit(1)
        )
        if match or lineage:
            deny("INSTITUTION_APPROVAL_REQUIRED")

    async def ingest(
        self,
        owner,
        data,
        filename,
        mime,
        *,
        own_material=False,
        share_text=False,
        share_visual=False,
        allow_academic_analysis=False,
        validate_session=lambda: None,
        course="independent",
        purpose="material",
        replace_id=None,
        expected_hash=None,
        packet_member=None,
    ):
        if not own_material or not data or len(data) > LOCAL_IMPORT_BYTES:
            deny("SOURCE_IDENTITY_UNVERIFIED")
        if (
            PurePath(filename).name != filename
            or any(c in filename for c in "/\\:\x00")
            or len(filename) > 180
        ):
            deny()
        kind = file_format({"filename": filename, "content-type": mime})
        if kind is None and mime in {"application/octet-stream", "text/markdown"}:
            # Browsers may omit an Office/text MIME. Parser signature and archive
            # checks still apply; this never enables HTML or a URL fetch.
            kind = (
                "md"
                if filename.lower().endswith(".md")
                else next(
                    (
                        fmt
                        for fmt, extension in FILE_TYPES.values()
                        if filename.lower().endswith(extension) and fmt != "html"
                    ),
                    None,
                )
            )
        if kind not in {"pdf", "docx", "pptx", "txt", "md", "xlsx"}:
            raise DomainError(
                "unsupported_feature",
                "Use PDF, DOCX, PPTX, TXT, Markdown or XLSX with a matching content type.",
            )
        if len(data) > local_import_limit(kind):
            raise DomainError(
                "unsupported_feature",
                f"The import exceeds the {local_import_limit(kind) // 1_000_000} MB limit for this format.",
            )
        if (
            (kind == "pdf" and not data.startswith(b"%PDF-"))
            or (kind in {"docx", "pptx", "xlsx"} and not data.startswith(b"PK"))
            or (
                kind in {"txt", "md"}
                and (data.startswith((b"%PDF-", b"PK", b"\x89PNG")) or b"\x00" in data)
            )
        ):
            deny()
        digest, ident = hashlib.sha256(data).hexdigest(), opaque_id()
        if not isinstance(course, str) or not 1 <= len(course) <= 100:
            raise DomainError("needs_input", "Choose a course label of at most 100 characters.")
        if purpose not in {
            "material",
            "syllabus",
            "schedule",
            "lecture",
            "reading",
            "instructions",
            "own_feedback",
        }:
            raise DomainError("needs_input", "Choose a supported document purpose.")
        if packet_member:
            if packet_member.digest != digest:
                deny()
            replace_id = packet_member.target
        if replace_id:
            previous = self.require(owner, replace_id)
            if (
                not packet_member and previous.version_hash != expected_hash
            ) or previous.content.get("course", "independent") != course:
                raise DomainError(
                    "source_changed", "Refresh the explicit replacement target and course."
                )
            if previous.content.get("portable_origin") and previous.version_hash != digest:
                deny("PORT_ORIGINAL_VERSION_REQUIRED")
            ident = replace_id
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            generation = principal.generation
            self.reject_institutional_copy(session, owner, digest)
            if packet_member:
                current = packet_member.check(
                    session, owner, course, purpose, self.bridge.retention.clock()
                )
                if current and current.version_hash == digest:
                    self.require_row(session, owner, current)
                    current.content = current.content | {
                        "packet": packet_member.metadata(current, self.bridge.retention.clock())
                    }
                    packet_member.publish(session, owner, current, self.bridge.retention.clock())
                    return current.id
                if current:
                    expected_hash = current.version_hash
            elif not replace_id:
                for existing in session.scalars(
                    select(IndependentResource).where(
                        IndependentResource.owner == owner,
                        IndependentResource.kind == "local_document",
                        IndependentResource.version_hash == digest,
                        IndependentResource.expires_at > self.bridge.retention.clock(),
                    )
                ):
                    if (
                        existing.content.get("course", "independent") == course
                        and existing.content.get("purpose", "material") == purpose
                        and existing.content.get("packet", {}).get("term", "unspecified")
                        == "unspecified"
                    ):
                        # A retry never upgrades sharing, course membership or provenance.
                        return self.require_row(session, owner, existing).id
            if (
                len(
                    list(
                        session.scalars(
                            select(IndependentResource.id).where(
                                IndependentResource.owner == owner,
                                IndependentResource.kind == "local_document",
                            )
                        )
                    )
                )
                >= 20
                and not replace_id
            ):
                raise DomainError(
                    "retry_later", "Delete an older import before adding another document."
                )
        lease = self.bridge.request_limits.acquire(owner)
        try:
            from canvas_bridge.parser_sandbox import extract_document

            with processing(owner, ident, namespace=self.bridge.processing_namespace):
                parsed = await extract_document(data, kind, self.bridge.settings)
        finally:
            lease.close()
        validate_session()
        if (
            parsed.get("privacy", {}).get("content_status")
            == "content_withheld_privacy_uncertainty"
        ):
            deny("EGRESS_REVIEW_REQUIRED")
        if share_visual and parsed.get("privacy", {}).get("page_content_filtered"):
            deny("EGRESS_REVIEW_REQUIRED")
        from canvas_bridge.privacy_text import inspect_text

        for page in parsed.get("pages", []):
            if inspect_text(page.get("text", ""))[1]:
                deny("EGRESS_REVIEW_REQUIRED")
        now = self.bridge.retention.clock()
        profile = self.profile()
        provenance = {
            "schema_version": "source-provenance-1",
            "source_category": "independent_import",
            "source_type": "local_document",
            "origin": "authenticated_browser_upload",
            "owner": owner,
            "mechanism": "bounded_browser_upload",
            "institutional_connection": None,
            "authorization": "explicit_user_permission",
            "scope": ["document_reading", "study", "visual_analysis"]
            + (["grade_planning", "schedule"] if allow_academic_analysis else []),
            "content_identity": digest,
            "retention_class": "restricted_raw_records",
            "privacy_classification": str(CC.FIRST_PARTY_EDUCATIONAL_RECORD),
            "egress_policy": profile.model_dump(mode="json") if profile and share_text else None,
            "share_text": bool(share_text),
            "share_visual": bool(share_text and share_visual),
            "revocation_dependency": ident,
            "parents": [],
            "copyright": "owner_attested",
            "original_authority": None,
            "acquired_at": now.isoformat(),
        }
        with self.bridge.store.transaction() as session:
            if self.bridge.store.principal(session, owner).generation != generation:
                deny("RESOURCE_AUTHORIZATION_REVOKED")
            self.reject_institutional_copy(session, owner, digest)
            if packet_member:
                packet_member.check(session, owner, course, purpose, now)
            if not replace_id:
                current = list(
                    session.scalars(
                        select(IndependentResource).where(
                            IndependentResource.owner == owner,
                            IndependentResource.kind == "local_document",
                        )
                    )
                )
                for existing in current:
                    if (
                        not packet_member
                        and existing.version_hash == digest
                        and existing.content.get("purpose", "material") == purpose
                        and existing.content.get("packet", {}).get("term", "unspecified")
                        == "unspecified"
                        and existing.content.get("course", "independent") == course
                        and aware(existing.expires_at) > now
                    ):
                        return self.require_row(session, owner, existing).id
                if len(current) >= 20:
                    raise DomainError(
                        "retry_later", "Delete an older import before adding another document."
                    )
            else:
                existing = session.get(IndependentResource, replace_id)
                if (
                    not existing
                    or existing.owner != owner
                    or aware(existing.expires_at) <= now
                    or existing.version_hash != expected_hash
                ):
                    raise DomainError(
                        "source_changed", "The replacement target changed during parsing."
                    )
                # Retain bounded reviewed evidence, not another copy of the original bytes.
                history = list(existing.content.get("version_history", []))
                history.append(
                    {
                        "hash": existing.version_hash,
                        "review": existing.content.get("review"),
                        "parser_version": existing.content["parsed"].get("parser_version"),
                        "coverage": existing.content["parsed"].get("coverage"),
                    }
                )
                packet = existing.content.get("packet")
                if packet_member:
                    packet = packet_member.metadata(existing, now)
                if packet:
                    history[-1].update(
                        original_bytes=existing.content["bytes"],
                        privacy=existing.content["parsed"].get("privacy", {}),
                        acquired_at=existing.provenance.get("acquired_at"),
                        logical_path=existing.content.get("packet", {}).get(
                            "current_path", existing.content["filename"]
                        ),
                    )
                    if (
                        len(history) > 10
                        or sum(len(v.get("original_bytes", "")) for v in history) > 28_000_000
                    ):
                        raise DomainError(
                            "needs_input", "This source reached its retained version limit."
                        )
                    from canvas_bridge.usefulness.packet import invalidate_version

                    invalidate_version(self.bridge, session, owner, existing.id, expected_hash, now)
                existing.content = {
                    **({"packet": packet} if packet else {}),
                    "bytes": base64.b64encode(data).decode(),
                    "format": kind,
                    "parsed": parsed,
                    "filename": filename,
                    "course": course,
                    "purpose": purpose,
                    "version_history": history[-10:],
                }
                existing.version_hash = digest
                # Replacement can only narrow existing rights. Review new consent separately.
                provenance["share_text"] &= bool(existing.provenance.get("share_text"))
                provenance["share_visual"] &= bool(existing.provenance.get("share_visual"))
                provenance["scope"] = list(
                    set(provenance["scope"]) & set(existing.provenance.get("scope", []))
                )
                provenance["egress_policy"] = (
                    existing.provenance.get("egress_policy") if provenance["share_text"] else None
                )
                existing.provenance = provenance
                if packet_member:
                    packet_member.publish(session, owner, existing, now)
                return ident
            session.add(
                IndependentResource(
                    id=ident,
                    owner=owner,
                    kind="local_document",
                    version_hash=digest,
                    provenance=provenance,
                    content={
                        **({"packet": packet_member.metadata(None, now)} if packet_member else {}),
                        "bytes": base64.b64encode(data).decode(),
                        "format": kind,
                        "parsed": parsed,
                        "filename": filename,
                        "course": course,
                        "purpose": purpose,
                    },
                    created_at=now,
                    expires_at=now
                    + timedelta(hours=self.bridge.settings.independent_retention_hours),
                )
            )
            if packet_member:
                session.flush()
                packet_member.publish(session, owner, session.get(IndependentResource, ident), now)
        return ident

    def list(self, owner):
        with self.bridge.store.transaction() as session:
            ids = list(
                session.scalars(
                    select(IndependentResource.id)
                    .where(
                        IndependentResource.owner == owner,
                        IndependentResource.kind == "local_document",
                        IndependentResource.expires_at > self.bridge.retention.clock(),
                    )
                    .limit(20)
                )
            )
        rows = []
        for ident in ids:
            try:
                rows.append(self.require(owner, ident))
            except DomainError:
                continue
        return Result(
            summary="Independently imported documents; no institution was contacted.",
            data={
                **({"unavailable_count": len(ids) - len(rows)} if len(ids) != len(rows) else {}),
                "documents": [
                    {
                        "document_id": r.id,
                        "content_hash": r.version_hash,
                        "expires_at": aware(r.expires_at).isoformat(),
                        "format": r.content["format"],
                        "course": r.content.get("course", "independent"),
                        "filename": r.content.get("filename", "Imported document"),
                    }
                    for r in rows
                ],
            },
        )

    def evidence(self, row, locator=None):
        if row.id.startswith("lib_"):
            return self.bridge.library.evidence(row.owner, row.id[4:], locator)
        from canvas_bridge.evidence import fingerprint

        return Source(
            id=row.id,
            resource_id=row.id,
            url="",
            title="Independently supplied document",
            retrieved_at=aware(row.created_at),
            locator=locator,
            classification="student_input",
            source_type="local_document",
            content_hash=row.version_hash,
            semantic_hash=fingerprint(
                [
                    row.version_hash,
                    row.content.get("course", "independent"),
                    row.content.get("metadata_revision", 0),
                    row.content.get("purpose"),
                    row.content.get("review"),
                    row.content["parsed"],
                ]
            ),
            hash_basis="source_bytes_and_current_reviewed_representation",
            extraction_status=row.content["parsed"].get("coverage", "partial"),
            uncertainty=[
                "Ownership and intended sharing are user attested; not institutional verification."
            ],
        )

    def read(
        self,
        owner,
        ident,
        *,
        start=1,
        limit=3,
        query=None,
        status=False,
        study=False,
        offset=0,
        characters=18000,
    ):
        row = self.require(owner, ident)
        parsed = row.content["parsed"]
        pages = parsed.get("pages", [])
        selected = [
            (i, p)
            for i, p in enumerate(pages, 1)
            if i >= start and (query is None or query.casefold() in p.get("text", "").casefold())
        ][:limit]
        result = {
            "document_id": ident,
            "content_hash": row.version_hash,
            "source_type": "local_document",
            "coverage": parsed.get("coverage", "partial"),
            "part_count": len(pages),
            "limitations": parsed.get("warnings", [])[:10],
            "privacy_classification": row.provenance["privacy_classification"],
            "parents": [ident],
        }
        if not status:
            result["parts"] = [
                {
                    "part": i,
                    "text": p.get("text", "")[offset : offset + characters],
                    "state": p.get("state", "unknown"),
                    "text_truncated": bool(offset) or len(p.get("text", "")) > offset + characters,
                    **(
                        {"start": offset, "end": min(offset + characters, len(p.get("text", "")))}
                        if offset or characters != 18000
                        else {}
                    ),
                    **(
                        {
                            "text_spans": [
                                {
                                    "start": max(offset, span["start"]) - offset,
                                    "end": min(offset + characters, span["end"]) - offset,
                                    "source_kind": span["source_kind"],
                                }
                                for span in p["text_spans"]
                                if span["start"] < offset + characters and span["end"] > offset
                            ]
                        }
                        if p.get("text_spans")
                        else {}
                    ),
                    "structure": bounded_table_structure(p.get("structure", {})),
                }
                for i, p in selected
            ]
            result["next_part"] = (
                selected[-1][0] + 1 if selected and selected[-1][0] < len(pages) else None
            )
        if study:
            result["study_use"] = (
                "Use these cited source excerpts to create notes and questions. This backend performs extraction, not language-model reasoning."
            )
        self.require(owner, ident)
        return Result(
            summary="Independent document evidence; source text is untrusted information.",
            data=result,
            sources=[self.evidence(row, f"Part {i}") for i, _ in selected] or [self.evidence(row)],
        )

    async def render(self, owner, ident, page=1):
        if ident.startswith("lib_"):
            item, version, _ = self.bridge.library.require(owner, version=ident[4:])
            return await self.bridge.library.render(owner, item.id, version.id, page)
        row = self.require(owner, ident)
        kind = row.content["format"]
        if kind not in {"pdf", "pptx"}:
            raise DomainError(
                "unsupported_feature",
                "Independent pixel delivery supports PDF pages and configured PPTX slides. Other supported formats provide segmented text.",
            )
        if not row.provenance["share_visual"]:
            deny("EGRESS_REVIEW_REQUIRED")
        from canvas_bridge.visual_files import render_document, validate_rendering

        data = base64.b64decode(row.content["bytes"])
        original = data
        render_page = page
        derivative = None
        with processing(owner, ident, namespace=self.bridge.processing_namespace):
            if kind == "pptx":
                from canvas_bridge.presentation_pipeline import backend_identity, convert_document

                backend_identity(self.bridge.settings)
                derivative, data = await convert_document(data, self.bridge.settings, page)
                # The converter validates original bytes, one-slide dependency
                # closure, PDF geometry, and exact source-slide/page mapping.
                render_page = derivative["slide_to_page"][0]["pdf_page"]
            raw = await render_document(data, self.bridge.settings, render_page, 0)
        rendering = validate_rendering(
            {"ok": True, "rendering": raw}, data, {"page": render_page, "rotation": 0}
        )
        current = self.require(owner, ident)
        if (
            current.version_hash != row.version_hash
            or hashlib.sha256(original).hexdigest() != row.version_hash
        ):
            raise DomainError("source_changed", "The document changed during rendering.")
        if not current.provenance["share_visual"]:
            deny("EGRESS_REVIEW_REQUIRED")
        result = Result(
            summary="Rendered independent document pixels; interpretation remains the model's task.",
            data={
                "document_id": ident,
                "content_hash": row.version_hash,
                "page": page,
                "visual_render_status": "rendered_not_interpreted",
                "assistant_pixels_delivered": False,
                **(
                    {
                        "source_slide": page,
                        "derivative_content_hash": derivative["derivative_content_hash"],
                        "slide_to_page": derivative["slide_to_page"],
                        "source_slide_count": derivative["source_slide_count"],
                    }
                    if derivative
                    else {}
                ),
            },
            sources=[self.evidence(row, f"{'Slide' if kind == 'pptx' else 'PDF page'} {page}")],
        )
        result.data["_visual_delivery_mode"] = "native"
        return result, rendering["png"]

    def sources(self, owner, arguments, result):
        ids = {arguments["document_id"]} if arguments.get("document_id") else set()
        ids |= set(arguments.get("document_ids") or ())
        ids |= {s.id for s in result.sources if s.source_type == "local_document"}
        ids |= {r["document_id"] for r in result.data.get("documents", [])}
        if not ids:
            return (
                SourceContext(
                    "__public__",
                    owner,
                    "empty-independent-inventory",
                    "",
                    "safe_status",
                    CC.PUBLIC_OR_APPROVED,
                ),
            )
        rows = [self.require(owner, ident) for ident in ids]
        expected = {s.id: s.content_hash for s in result.sources if s.content_hash}
        expected.update(
            {
                d["document_id"]: d["content_hash"]
                for d in result.data.get("documents", [])
                if d.get("content_hash")
            }
        )
        if any(r.id in expected and expected[r.id] != r.version_hash for r in rows):
            raise DomainError(
                "source_changed", "The document changed before output; read its current version."
            )
        semantic = {s.id: s.semantic_hash for s in result.sources if s.semantic_hash}
        if any(r.id in semantic and semantic[r.id] != self.evidence(r).semantic_hash for r in rows):
            raise DomainError(
                "source_changed",
                "The source representation or reviewed scope changed before output.",
            )
        return tuple(
            SourceContext(
                "__independent__",
                owner,
                r.id,
                r.version_hash,
                "local_document",
                CC.FIRST_PARTY_EDUCATIONAL_RECORD,
                derived=True,
                content_sha256=r.version_hash,
            )
            for r in rows
        )

    def permits(self, source, transfer):
        if source.source_id.startswith("lib_"):
            channel = (
                "metadata"
                if transfer.purpose == "metadata"
                else "text"
                if transfer.channel == "structured"
                else transfer.channel
            )
            return (
                self.bridge.library.permitted(
                    transfer.principal,
                    source.source_id[4:],
                    channel,
                    transfer=transfer,
                    purpose=transfer.purpose,
                )
                and source.version
                == self.bridge.library.require(transfer.principal, version=source.source_id[4:])[
                    1
                ].digest
            )
        row = self.require(transfer.principal, source.source_id)
        recipient = transfer.recipient
        external = recipient.recipient == "external_ai"
        profile = self.external_profile() if external else self.profile()
        bound = row.provenance.get("external_egress_policy" if external else "egress_policy")
        if (
            not profile
            or not bound
            or RecipientPolicy.model_validate(bound) != profile
            or (external and transfer.channel not in {"metadata", "structured", "text"})
            or not row.provenance.get("share_text")
        ):
            return False
        if (
            external or self.bridge.settings.profile != "synthetic"
        ) and recipient != profile.identity():
            return False
        return (
            recipient.recipient == profile.recipient
            and source.classification in profile.classifications
            and source.version == row.version_hash
            and transfer.purpose in profile.purposes
            and (
                transfer.purpose == "metadata"
                or transfer.purpose in row.provenance.get("scope", [])
            )
            and transfer.channel in profile.channels
            and transfer.amount <= profile.max_output_bytes
            and (transfer.channel != "visual" or row.provenance.get("share_visual"))
        )

    def preferences(self, owner, value=None, expected_version=0):
        ident = hashlib.sha256((owner + ":preferences").encode()).hexdigest()
        now = self.bridge.retention.clock()
        with self.bridge.store.transaction() as session:
            self.bridge.store.principal(session, owner)
            row = session.get(IndependentResource, ident)
            if row and (row.owner != owner or row.kind != "local_preferences"):
                deny()
            old = (
                row.content
                if row and aware(row.expires_at) > now
                else {"version": 0, "value": LocalPreferences().validated()}
            )
            if row and aware(row.expires_at) > now:
                p = row.provenance
                if (
                    p.get("source_type") != "local_preferences"
                    or p.get("owner") != owner
                    or p.get("authorization") != "explicit_user_permission"
                    or p.get("institutional_connection") is not None
                    or p.get("parents")
                    or p.get("source_category", "user_manual") != "user_manual"
                    or p.get("origin") != "authenticated_explicit_preferences"
                    or type(old.get("version")) is not int
                    or old["version"] < 0
                    or row.version_hash
                    != hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
                    or (
                        p.get("content_identity") is not None
                        and p["content_identity"] != row.version_hash
                    )
                ):
                    deny()
                old = {
                    "version": old["version"],
                    "value": LocalPreferences.model_validate(old["value"]).validated(),
                }
            if value is not None:
                if expected_version != old["version"]:
                    raise DomainError("source_changed", "Read current preferences before saving.")
                content = {
                    "version": expected_version + 1,
                    "value": LocalPreferences.model_validate(value).validated(),
                }
                if row:
                    session.delete(row)
                    session.flush()
                session.add(
                    IndependentResource(
                        id=ident,
                        owner=owner,
                        kind="local_preferences",
                        version_hash=hashlib.sha256(
                            json.dumps(content, sort_keys=True).encode()
                        ).hexdigest(),
                        provenance={
                            "source_type": "local_preferences",
                            "source_category": "user_manual",
                            "content_identity": hashlib.sha256(
                                json.dumps(content, sort_keys=True).encode()
                            ).hexdigest(),
                            "scope": ["preferences"],
                            "origin": "authenticated_explicit_preferences",
                            "owner": owner,
                            "parents": [],
                            "institutional_connection": None,
                            "retention_class": "sanitized_analysis_results",
                            "authorization": "explicit_user_permission",
                        },
                        content=content,
                        created_at=now,
                        expires_at=now + timedelta(days=30),
                    )
                )
                old = content
        return Result(
            summary="Local-only study preferences; institutional approval is not required.",
            data=old,
        )

    def delete(self, owner, ident):
        with self.bridge.store.transaction() as session:
            self.bridge.store.principal(session, owner)
            row = session.scalar(
                select(IndependentResource)
                .where(IndependentResource.id == ident, IndependentResource.owner == owner)
                .with_for_update()
            )
            if not row or row.kind != "local_document":
                deny()
            from canvas_bridge.processes.purge import purge_sources
            from canvas_bridge.usefulness.packet import fence_deletion

            fence_deletion(session, row, self.bridge.retention.clock())
            purge_sources(session, owner, source_ids=(ident,))
            session.delete(row)
        from canvas_bridge.worker_storage import invalidate

        invalidate(owner, ident, namespace=self.bridge.processing_namespace)
        return {
            "local_deletion": "completed",
            "derivatives": "deleted_or_inflight_output_fenced",
            "external_copies": "outside_bridge_control",
        }

    def sweep(self):
        with self.bridge.store.transaction() as session:
            rows = list(
                session.scalars(
                    select(IndependentResource).where(
                        IndependentResource.expires_at <= self.bridge.retention.clock()
                    )
                )
            )
            from canvas_bridge.worker_storage import invalidate

            # Match local process commits' principal-first order, including when
            # expiring one source invalidates shared mixed-origin state.
            for owner in sorted({row.owner for row in rows}):
                self.bridge.store.principal(session, owner)
            for row in rows:
                if row.kind == "local_document":
                    from canvas_bridge.processes.purge import purge_sources

                    purge_sources(session, row.owner, source_ids=(row.id,))
                invalidate(row.owner, row.id, namespace=self.bridge.processing_namespace)
                session.delete(row)
