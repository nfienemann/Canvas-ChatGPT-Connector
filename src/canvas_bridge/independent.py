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
        if not path or not path.is_file() or path.is_symlink() or path.stat().st_size > 16_000:
            return None
        try:
            profile = RecipientPolicy.model_validate_json(path.read_text(encoding="utf-8"))
            if (
                profile.recipient != "chatgpt"
                or profile.training
                or "training" in profile.downstream_processing
            ):
                return None
            return profile
        except (OSError, ValueError):
            return None

    def require(self, owner, ident, *, kind="local_document"):
        with self.bridge.store.transaction() as session:
            row = session.scalar(
                select(IndependentResource).where(
                    IndependentResource.id == ident, IndependentResource.owner == owner
                )
            )
            if (
                not row
                or row.kind != kind
                or aware(row.expires_at) <= self.bridge.retention.clock()
            ):
                deny("RESOURCE_AUTHORIZATION_REVOKED")
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
        if (kind == "pdf" and not data.startswith(b"%PDF-")) or (
            kind in {"docx", "pptx", "xlsx"} and not data.startswith(b"PK")
        ):
            deny()
        digest, ident = hashlib.sha256(data).hexdigest(), opaque_id()
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            generation = principal.generation
            self.reject_institutional_copy(session, owner, digest)
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
            session.add(
                IndependentResource(
                    id=ident,
                    owner=owner,
                    kind="local_document",
                    version_hash=digest,
                    provenance=provenance,
                    content={
                        "bytes": base64.b64encode(data).decode(),
                        "format": kind,
                        "parsed": parsed,
                    },
                    created_at=now,
                    expires_at=now
                    + timedelta(hours=self.bridge.settings.independent_retention_hours),
                )
            )
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
        rows = [self.require(owner, ident) for ident in ids]
        return Result(
            summary="Independently imported documents; no institution was contacted.",
            data={
                "documents": [
                    {
                        "document_id": r.id,
                        "content_hash": r.version_hash,
                        "expires_at": aware(r.expires_at).isoformat(),
                        "format": r.content["format"],
                    }
                    for r in rows
                ]
            },
        )

    def evidence(self, row, locator=None):
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
            extraction_status=row.content["parsed"].get("coverage", "partial"),
            uncertainty=[
                "Ownership and intended sharing are user attested; not institutional verification."
            ],
        )

    def read(self, owner, ident, *, start=1, limit=3, query=None, status=False, study=False):
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
                    "text": p.get("text", "")[:18000],
                    "state": p.get("state", "unknown"),
                    "text_truncated": len(p.get("text", "")) > 18000,
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
        row = self.require(owner, ident)
        if row.content["format"] != "pdf":
            raise DomainError(
                "unsupported_feature",
                "Independent pixel delivery currently supports PDF pages. Other supported formats provide segmented text.",
            )
        if not row.provenance["share_visual"]:
            deny("EGRESS_REVIEW_REQUIRED")
        from canvas_bridge.visual_files import render_document, validate_rendering

        data = base64.b64decode(row.content["bytes"])
        with processing(owner, ident, namespace=self.bridge.processing_namespace):
            raw = await render_document(data, self.bridge.settings, page, 0)
        rendering = validate_rendering(
            {"ok": True, "rendering": raw}, data, {"page": page, "rotation": 0}
        )
        self.require(owner, ident)
        result = Result(
            summary="Rendered independent PDF page; interpretation remains the model's task.",
            data={
                "document_id": ident,
                "content_hash": row.version_hash,
                "page": page,
                "visual_render_status": "rendered_not_interpreted",
                "assistant_pixels_delivered": False,
            },
            sources=[self.evidence(row, f"PDF page {page}")],
        )
        result.data["_visual_delivery_mode"] = "native"
        return result, rendering["png"]

    def sources(self, owner, arguments, result):
        ids = (
            {arguments["document_id"]}
            if arguments.get("document_id")
            else {r["document_id"] for r in result.data.get("documents", [])}
        )
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
        row = self.require(transfer.principal, source.source_id)
        profile = self.profile()
        if (
            not profile
            or not row.provenance.get("egress_policy")
            or RecipientPolicy.model_validate(row.provenance["egress_policy"]) != profile
            or not row.provenance.get("share_text")
        ):
            return False
        recipient = transfer.recipient
        if self.bridge.settings.profile != "synthetic" and (
            recipient.recipient,
            recipient.issuer,
            recipient.client_id,
            recipient.environment,
            recipient.workspace,
        ) != (
            profile.recipient,
            profile.issuer,
            profile.client_id,
            profile.environment,
            profile.workspace,
        ):
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
