"""User-owned local bytes, explicitly permitted for local processing only.

No pathname/URL is accepted here. The trusted upload/CLI host supplies bytes and
an ownership attestation bound to their hash. This is not vendor authorization.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from canvas_bridge.academic.gateway import denied
from canvas_bridge.academic.models import (
    AcademicDataset,
    AcademicDocument,
    DocumentPart,
    PermissionContext,
    Provenance,
    Restrictions,
    SourceReference,
)
from canvas_bridge.document_policy import local_import_limit
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.privacy_text import inspect_text
from canvas_bridge.providers.base import AcademicProvider


@dataclass(frozen=True)
class LocalImportPermit:
    principal: str
    source_id: str
    content_sha256: str
    expires_at: datetime
    ownership_attestation: str
    purpose: str = "document_reading"


@dataclass(frozen=True)
class LocalExtractionSettings:
    parser_root: Path
    file_reading_enabled: bool = True
    parser_runtime_root: Path | None = None
    ocr_root: Path | None = None


def require_local_import(data, permit, request, now, purpose):
    if (
        permit is None
        or not permit.ownership_attestation
        or permit.expires_at.tzinfo is None
        or permit.expires_at <= now
        or request.principal != permit.principal
        or request.resource != permit.source_id
        or request.tenant != "local"
        or request.connection != "local-import"
        or request.recipient != "local"
        or request.purpose != permit.purpose
        or permit.purpose != purpose
        or hashlib.sha256(data).hexdigest() != permit.content_sha256
    ):
        denied()


class LocalDocumentProvider(AcademicProvider):
    provider_id = "local-document"
    api_version = "1.0.0"
    supported = frozenset({"get_authorized_document"})
    capability_fields = {"get_authorized_document": ("documents", "documents.parts")}
    permission_requirements = ("expiring_hash_bound_ownership_attestation", "local_recipient")
    freshness = "user_supplied_unverified"
    downstream_model_sharing = "local_only"

    def __init__(
        self, data: bytes, kind, permit: LocalImportPermit | None, *, settings=None, clock=utcnow
    ):
        self._data, self.kind, self.permit, self.settings = bytes(data), kind, permit, settings
        self._records = {}
        super().__init__(clock=clock)

    def require(self, request, *, phase):
        require_local_import(
            self._data, self.permit, request, self.gateway.clock(), "document_reading"
        )
        if len(self._data) > local_import_limit(self.kind) or self.kind not in {
            "txt",
            "md",
            "pdf",
            "docx",
            "pptx",
            "xlsx",
        }:
            raise DomainError(
                "unsupported_feature", "The local document exceeds supported format or size limits."
            )

    def revoke(self):
        self.permit = None
        self._data = b""
        self._records.clear()

    def verify_record(self, record, request):
        if self._records.get(record.id) != record:
            denied()

    async def retrieve(self, operation, request):
        self.require(request, phase="retrieve")
        if operation != "get_authorized_document":
            raise DomainError(
                "unsupported_feature", "This source only provides authorized document text."
            )
        if self.kind in {"txt", "md"}:
            try:
                text = self._data.decode("utf-8")
            except UnicodeError as exc:
                raise DomainError("unsupported_feature", "Local text must use UTF-8.") from exc
            if len(text) > 250_000:
                raise DomainError("unsupported_feature", "Local text exceeds the extraction limit.")
            complete = bool(text.strip())
            pages = [{"page": 1, "text": text, "state": "extracted" if complete else "no_text"}]
            warnings = [] if complete else ["No readable text was supplied."]
        else:
            if self.settings is None:
                raise DomainError("unsupported_feature", "An isolated document worker is required.")
            from canvas_bridge.parser_sandbox import extract_document

            parsed = await extract_document(self._data, self.kind, self.settings)
            if (
                parsed.get("privacy", {}).get("content_status")
                == "content_withheld_privacy_uncertainty"
            ):
                denied()
            pages = parsed["pages"]
            complete = parsed.get("coverage") == "text_only"
            warnings = parsed.get("warnings", [])
        self.require(request, phase="analysis")
        now, permit = self.gateway.clock(), self.permit
        restrictions = Restrictions(
            classifications={CC.FIRST_PARTY_EDUCATIONAL_RECORD},
            purposes={permit.purpose},
            recipients={"local"},
            copyright="owner_attested",
            permission_reference=permit.ownership_attestation,
        )
        permission = PermissionContext(
            principal=permit.principal,
            tenant="local",
            connection="local-import",
            scope={permit.purpose},
            decision_reference="local-user-attestation",
            expires_at=permit.expires_at,
        )
        provenance = Provenance(
            source_type="local_" + self.kind,
            source=SourceReference(
                provider=self.provider_id, id=permit.source_id, version=permit.content_sha256
            ),
            observed_at=now,
            basis="user_supplied",
            complete=complete,
            uncertainty=(
                "User-supplied ownership attestation; no institutional verification or external sharing grant.",
            ),
        )
        parts = []
        for index, page in enumerate(pages, 1):
            text, changed = inspect_text(page["text"])
            if changed:
                denied()  # Local ownership is not permission to expose third parties.
            part_kind = (
                "slide"
                if self.kind == "pptx"
                else "section"
                if self.kind in {"txt", "md", "docx"}
                else "sheet"
                if self.kind == "xlsx"
                else "page"
            )
            number = page.get("page", index)
            part_provenance = provenance.model_copy(
                update={
                    "source": provenance.source.model_copy(
                        update={"locator": f"{part_kind} {number}"}
                    )
                }
            )
            parts.append(
                DocumentPart(
                    id=f"{permit.source_id}-part-{index}",
                    provenance=part_provenance,
                    permission=permission,
                    restrictions=restrictions,
                    document_id=permit.source_id,
                    kind=part_kind,
                    number=number,
                    text=text,
                    structure=page.get("structure"),
                    extraction_status=(
                        "unavailable"
                        if not text.strip()
                        else "complete_text"
                        if page.get("state") == "extracted"
                        else "partial_text"
                    ),
                )
            )
        document = AcademicDocument(
            id=permit.source_id,
            provenance=provenance,
            permission=permission,
            restrictions=restrictions,
            title="User-supplied academic document",
            format=self.kind,
            content_sha256=permit.content_sha256,
            parts=tuple(parts),
        )
        dataset = AcademicDataset(
            provider=self.provider_id,
            documents=(document,),
            complete=complete,
            limitations=(
                "Text extraction only; no claim of visual interpretation, grading policy completeness, or external sharing permission.",
                *(inspect_text(warning)[0] for warning in warnings[:48]),
                *(
                    ("Additional parser limitations were omitted from this bounded response.",)
                    if len(warnings) > 48
                    else ()
                ),
            ),
        )
        self._records = {r.id: r for r in dataset.records()}
        return dataset
