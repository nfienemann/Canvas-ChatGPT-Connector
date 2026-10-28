"""Central content release policy, independent of technical access and sanitization."""

import html
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.egress_models import (
    Channel,
    EgressGovernance,
    Purpose,
    RecipientPolicy,
    SourceContext,
    Transfer,
)
from canvas_bridge.egress_models import (
    ContentClassification as CC,
)
from canvas_bridge.egress_models import (
    ReleaseDecision as RD,
)

POLICY_VERSION = "canvas-egress-1"
logger = logging.getLogger("canvas_bridge.data_egress")
FAILURE_MESSAGE = (
    "Content was not transmitted because its classification or permission for this "
    "recipient could not be established. Authorized local analysis remains available."
)
HARD_DENY = {CC.THIRD_PARTY_EDUCATIONAL_RECORD, CC.RESTRICTED_ASSESSMENT, CC.CONFIDENTIAL_RESEARCH}
OWNER_KINDS = {
    "feedback",
    "submission",
    "file",
    "page",
    "syllabus",
    "assignment_content",
    "research",
    "announcement",
    "discussion",
}


@dataclass(frozen=True)
class EgressDecision:
    decision: RD
    reason_code: str
    classifications: tuple[CC, ...]
    recipient_category: str

    @property
    def allowed(self):
        return self.decision in {RD.ALLOW, RD.ALLOW_MINIMIZED, RD.ALLOW_REDACTED}

    def public(self):
        return {
            "policy_version": POLICY_VERSION,
            "classifications": [str(c) for c in self.classifications],
            "recipient_category": self.recipient_category,
            "decision": str(self.decision),
            "reason_code": self.reason_code,
        }

    def require(self):
        if not self.allowed:
            raise DomainError(
                "permission_denied",
                FAILURE_MESSAGE,
                reason_code=self.reason_code,
                details={"egress": self.public(), "transmitted": False},
            )
        return self


def classify(source: SourceContext):
    # Source relationships and surrounding restrictions dominate any label. A
    # transformation does not reset any of these properties.
    if source.subject is not None and source.subject != source.owner:
        return CC.THIRD_PARTY_EDUCATIONAL_RECORD
    if source.restricted:
        return CC.RESTRICTED_ASSESSMENT
    if source.confidential:
        return CC.CONFIDENTIAL_RESEARCH
    return source.classification


def dangerous_reference(value):
    decoded = value
    for _ in range(4):
        decoded = html.unescape(unquote(decoded)).replace("\\/", "/")
    return bool(
        re.search(
            r"(?i)(?:/course-file-(?:download|original)/|/files/[^\s<>]+/download|"
            r"canvas-file:|data:[^\s]*;base64,|[?&](?:download|download_frd|verifier|"
            r"x-amz-signature|x-goog-signature|access_token|signature)=|bearer\s+[a-z0-9._-]{12,})",
            decoded,
        )
    )


PRIVATE_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "client_secret",
        "email",
        "student_email",
        "student_name",
        "teacher_email",
        "canvas_user",
        "user_id",
        "student_id",
        "owner",
        "grader_id",
        "author_id",
        "submission_comments",
        "submission_body",
    }
)


def privacy_filter(payload, *, own_canvas_user=None):
    from canvas_bridge.privacy.output import filter_output

    return filter_output(payload, own_canvas_user=own_canvas_user)


class DataEgressPolicyEngine:
    def __init__(self, bridge):
        self.bridge = bridge

    def decision(self, transfer, code, reason, classifications):
        category = transfer.recipient.recipient
        if category not in {
            "chatgpt",
            "external_ai",
            "document_processor",
            "user_download",
            "public",
            "synthetic",
        }:
            category = "unverified"
        result = EgressDecision(code, reason, tuple(sorted(set(classifications))), category)
        # Deliberately only these five fields: no source identifiers, excerpts,
        # environment/workspace identifiers, tokens, or arbitrary exception text.
        logger.info("data_egress_decision %s", json.dumps(result.public(), sort_keys=True))
        return result

    def governance(self, institution):
        if self.bridge.settings.profile == "synthetic":
            from canvas_bridge.synthetic import SyntheticProvider

            if (
                not isinstance(self.bridge.synthetic, SyntheticProvider)
                or institution != "synthetic"
            ):
                return None
            return EgressGovernance(
                policy_version="fictional-only-v1",
                max_retention_days=0,
                allow_training=False,
                allowed_processing={"inference"},
                recipients=[
                    RecipientPolicy(
                        policy_id="fictional-only",
                        recipient="chatgpt",
                        environment="synthetic",
                        workspace="synthetic",
                        plan="fictional",
                        issuer="synthetic",
                        client_id="synthetic",
                        classifications={CC.PUBLIC_OR_APPROVED, CC.FIRST_PARTY_EDUCATIONAL_RECORD},
                        purposes=set(Purpose.__args__),
                        channels=set(Channel.__args__),
                        retention_days=0,
                        training=False,
                        downstream_processing={"inference"},
                        max_output_bytes=100_000_000,
                    )
                ],
            )
        records, error = self.bridge.approval_gateway.store.load()
        if error:
            return None
        record = next(
            (r for r in records if r.authority == "sharing" and institution in r.institutions), None
        )
        return record.egress if record else None

    def evaluate(self, transfer: Transfer):
        classes = [classify(s) for s in transfer.sources] or [CC.UNKNOWN_OR_UNCLASSIFIED]

        def deny(code, reason):
            return self.decision(transfer, code, reason, classes)

        if not transfer.authorized or any(s.owner != transfer.principal for s in transfer.sources):
            return deny(RD.DENY, "EGRESS_USER_NOT_AUTHORIZED")
        if not transfer.privacy_filtered:
            return deny(RD.DENY, "EGRESS_PRIVACY_CHECK_REQUIRED")
        if set(classes) & HARD_DENY:
            return deny(RD.DENY, "EGRESS_RESTRICTED_CONTENT")
        if CC.UNKNOWN_OR_UNCLASSIFIED in classes:
            return deny(RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_CLASSIFICATION_UNKNOWN")
        if (
            not transfer.sources
            or transfer.amount < 0
            or transfer.channel not in Channel.__args__
            or transfer.purpose not in Purpose.__args__
        ):
            return deny(RD.DENY, "EGRESS_UNSUPPORTED_TRANSFER")
        for source, classification in zip(transfer.sources, classes, strict=True):
            if source.kind == "local_document":
                if self.bridge.independent.permits(source, transfer):
                    continue
                return deny(RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_REVIEW_REQUIRED")
            if source.kind in {"static_ui", "safe_error", "safe_status", "preferences"}:
                # These sources are reconstructed by trusted server code and contain
                # no academic record, attachment, opaque binary, or arbitrary error.
                if classification == CC.PUBLIC_OR_APPROVED and transfer.channel in {
                    "structured",
                    "metadata",
                    "error",
                }:
                    continue
                return deny(RD.DENY, "EGRESS_UNSUPPORTED_TRANSFER")
            governance = self.governance(source.institution)
            if governance is None:
                return deny(RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_GOVERNANCE_MISSING")
            synthetic = self.bridge.settings.profile == "synthetic"
            recipient = transfer.recipient
            if not synthetic:
                from canvas_bridge.approval_policy import PolicyRequest

                category = source.data_category or {
                    "grade": "grades",
                    "deadline": "assignments",
                    "assignment_content": "assignments",
                    "course": "courses",
                    "page": "pages",
                }.get(source.kind, "files")
                approval = self.bridge.approval_gateway.evaluate(
                    PolicyRequest(
                        source.institution,
                        self.bridge.settings.profile,
                        frozenset({category}),
                        recipient.recipient,
                        "share",
                        resource=source.authorization_resource,
                    )
                )
                if not approval.allowed:
                    return deny(RD.DENY, "EGRESS_INSTITUTIONAL_APPROVAL_DENIED")
            profiles = [
                p
                for p in governance.recipients
                if (
                    synthetic
                    or (
                        p.recipient == recipient.recipient
                        and p.issuer == recipient.issuer
                        and p.client_id == recipient.client_id
                        and p.environment == recipient.environment
                        and p.workspace == recipient.workspace
                    )
                )
            ]
            if len(profiles) != 1:
                return deny(RD.DENY, "EGRESS_RECIPIENT_UNVERIFIED")
            profile = profiles[0]
            if (
                classification not in profile.classifications
                or transfer.purpose not in profile.purposes
                or transfer.channel not in profile.channels
            ):
                return deny(RD.DENY, "EGRESS_RECIPIENT_SCOPE_DENIED")
            if (
                profile.retention_days > governance.max_retention_days
                or (
                    (profile.training or "training" in profile.downstream_processing)
                    and not governance.allow_training
                )
                or not profile.downstream_processing <= governance.allowed_processing
            ):
                return deny(RD.DENY, "EGRESS_PROCESSING_RESTRICTION")
            if transfer.amount > profile.max_output_bytes:
                return deny(RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_AMOUNT_EXCEEDED")
            if source.kind in OWNER_KINDS or classification == CC.INSTRUCTOR_OWNED_COURSE_CONTENT:
                review = next(
                    (
                        r
                        for r in governance.content_reviews
                        if r.source_id == source.source_id and r.version == source.version
                    ),
                    None,
                )
                if synthetic and classification == CC.PUBLIC_OR_APPROVED:
                    continue  # Locally generated, fictional fixture; no live entitlement.
                if review is None or review.classification != classification:
                    return deny(RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_SOURCE_REVIEW_REQUIRED")
                if (
                    transfer.channel not in review.reviewed_channels
                    or transfer.purpose not in review.purposes
                ):
                    return deny(RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_MODALITY_REVIEW_REQUIRED")
                if source.kind == "file" and transfer.channel in {
                    "text",
                    "visual",
                    "original",
                    "temporary_url",
                }:
                    if not review.content_sha256 or review.content_sha256 != source.content_sha256:
                        return deny(
                            RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_CONTENT_HASH_REVIEW_REQUIRED"
                        )
                if transfer.channel in {
                    "text",
                    "visual",
                    "original",
                    "temporary_url",
                    "structured",
                    "metadata",
                } and (
                    transfer.channel not in review.privacy_reviewed_channels
                    or not review.privacy_review_reference
                ):
                    return deny(
                        RD.REQUIRES_AUTHORIZED_REVIEW, "CONTENT_WITHHELD_PRIVACY_UNCERTAINTY"
                    )
                if (
                    classification != CC.PUBLIC_OR_APPROVED
                    and not review.content_owner_permission_reference
                ):
                    return deny(
                        RD.REQUIRES_AUTHORIZED_REVIEW, "EGRESS_CONTENT_OWNER_PERMISSION_REQUIRED"
                    )
        code = (
            RD.ALLOW_REDACTED
            if transfer.redacted
            else RD.ALLOW_MINIMIZED
            if transfer.minimized
            else RD.ALLOW
        )
        return deny(code, "EGRESS_RELEASE_PERMITTED")

    def release(self, result, owner, arguments, *, tool_name, channel="structured", opaque_bytes=0):
        from canvas_bridge.egress_sources import prepare_transfer
        from canvas_bridge.integrity.surfaces import guard_result

        result = guard_result(self.bridge, owner, tool_name, arguments, result)

        cleaned, transfer = prepare_transfer(
            self, result, owner, arguments, tool_name, channel, opaque_bytes
        )
        decision = self.evaluate(transfer).require()
        # A signed-link field is a transfer in its own right, even in summaries,
        # metadata, errors or an apparently harmless derived record.
        if dangerous_reference(cleaned.model_dump_json()):
            self.decision(
                transfer,
                RD.DENY,
                "EGRESS_HIDDEN_FILE_REFERENCE",
                [classify(s) for s in transfer.sources],
            ).require()
        cleaned.meta.egress = decision.public()
        from canvas_bridge.privacy.output import metadata

        cleaned.meta.privacy = metadata(
            transfer.redacted or transfer.minimized, content=cleaned.model_dump_json()
        )
        return cleaned

    def external_processing(self, transfer):
        # No external AI/document service is installed. Future adapters must first
        # implement an authenticated destination and this gate; no generic HTTP API.
        return self.decision(
            transfer,
            RD.DENY,
            "EGRESS_EXTERNAL_PROCESSOR_DISABLED",
            [classify(s) for s in transfer.sources],
        ).require()

    def download(self, item, *, bearer=False):
        from canvas_bridge.authorization import request_authorization
        from canvas_bridge.egress_models import RecipientIdentity
        from canvas_bridge.egress_sources import prepare_transfer

        context = request_authorization.get()
        if context and context.egress_identity is None:
            context.egress_identity = RecipientIdentity("user_download")
        result = Result(
            summary="Original file transfer.",
            data={"file_id": item.file, "bytes_sha256": item.data["bytes_sha256"]},
        )
        _, transfer = prepare_transfer(
            self,
            result,
            item.owner,
            {"connection_id": item.connection, "file_id": item.file},
            "download_original",
            "original",
            item.data["byte_size"],
        )
        if bearer and self.bridge.settings.profile != "synthetic":
            return self.decision(
                transfer,
                RD.DENY,
                "EGRESS_BEARER_RECIPIENT_UNVERIFIED",
                [classify(s) for s in transfer.sources],
            ).require()
        return self.evaluate(transfer).require()

    def safe_error(self, result):
        from canvas_bridge.egress_errors import safe_error_result
        from canvas_bridge.egress_models import RecipientIdentity

        clean = safe_error_result(result)
        transfer = Transfer(
            "system",
            RecipientIdentity("public"),
            "diagnostics",
            "error",
            (
                SourceContext(
                    "__public__", "system", "safe-error", "", "safe_error", CC.PUBLIC_OR_APPROVED
                ),
            ),
            len(clean.model_dump_json().encode()),
            True,
            True,
            redacted=True,
        )
        clean.meta.egress = self.evaluate(transfer).require().public()
        from canvas_bridge.privacy.output import metadata

        clean.meta.privacy = metadata(True)
        return clean

    def public_resource(self, text, resource_id):
        from canvas_bridge.egress_models import RecipientIdentity
        from canvas_bridge.file_delivery_ui import DOWNLOAD_URI
        from canvas_bridge.visual_ui import PAGE_URI

        source = SourceContext(
            "__public__", "system", resource_id, "", "static_ui", CC.PUBLIC_OR_APPROVED
        )
        transfer = Transfer(
            "system",
            RecipientIdentity("public"),
            "metadata",
            "metadata",
            (source,),
            len(text.encode()),
            resource_id in {DOWNLOAD_URI, PAGE_URI},
            True,
        )
        self.evaluate(transfer).require()
        return text

    def static_metadata(self, content, *, authorized=True):
        from canvas_bridge.egress_models import RecipientIdentity

        transfer = Transfer(
            "system",
            RecipientIdentity("public"),
            "metadata",
            "metadata",
            (
                SourceContext(
                    "__public__", "system", "fixed-catalog", "", "static_ui", CC.PUBLIC_OR_APPROVED
                ),
            ),
            len(content.encode()),
            authorized,
            True,
        )
        self.evaluate(transfer).require()

    def connection_export(self, owner, connection, recipient, exported):
        # An aggregate archive mixes cached documents, research and personal state.
        # It is not downgraded to a harmless first-party record by being JSON.
        with self.bridge.store.transaction() as session:
            conn = self.bridge.store.connection(session, owner, connection)
            classification = (
                CC.PUBLIC_OR_APPROVED
                if self.bridge.settings.profile == "synthetic"
                else CC.UNKNOWN_OR_UNCLASSIFIED
            )
            source = SourceContext(
                conn.institution, owner, connection, "", "archive", classification
            )
        clean, redacted, third_party, hidden = privacy_filter(
            exported, own_canvas_user=conn.canvas_user
        )
        if third_party:
            source = SourceContext(
                conn.institution,
                owner,
                connection,
                "",
                "archive",
                CC.THIRD_PARTY_EDUCATIONAL_RECORD,
            )
        transfer = Transfer(
            owner,
            recipient,
            "original_download",
            "original",
            (source,),
            len(json.dumps(clean).encode()),
            True,
            True,
            redacted=redacted,
        )
        if hidden:
            self.decision(
                transfer, RD.DENY, "EGRESS_HIDDEN_FILE_REFERENCE", [classify(source)]
            ).require()
        self.evaluate(transfer).require()
        return clean
