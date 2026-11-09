"""Browser-only mutation inputs. No model assertion is an authorization action."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.domain import DomainError, Model, opaque_id

POLICY = "private-library-1"
CHUNK = 8 * 1024 * 1024
TERMINAL = {"published", "cancelled", "expired", "rejected", "failed"}
TOOLS = frozenset(
    {
        "get_library_status",
        "list_library_items",
        "get_library_item",
        "search_library",
        "read_library_item",
        "render_library_item",
        "prepare_library_download",
    }
)


def fail(reason, status="permission_denied", *, retryable=False):
    actions = {
        "HOST_TRANSFER_UNAVAILABLE": "Open Add files, choose the file on your device, and save it to your private library.",
        "SOURCE_CHANGED": "Refresh the selection and review its current version and permissions.",
        "QUOTA_EXCEEDED": "Delete an unwanted file or reduce this selection.",
        "CAPACITY_UNAVAILABLE": "This operation is busy. Retry after the current transfer completes.",
        "SCAN_UNAVAILABLE": "Retry when the local safety worker is available.",
        "RESTORE_ON_HOLD": "The operator must verify storage keys and deletion history.",
        "PROCESSING_UNSUPPORTED": "Use the owner original download; extraction is unavailable for this file.",
    }
    action = actions.get(
        reason, "Open the signed-in library to inspect this operation and retry if available."
    )
    raise DomainError(
        status,
        action,
        reason_code=reason,
        details={"retryable": retryable, "next_action": action, "correlation_id": opaque_id()},
    )


class Retention(Model):
    mode: Literal["until_deleted", "expires_at"] = "until_deleted"
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if (self.mode == "expires_at") != (self.expires_at is not None):
            raise ValueError("An expiry date is required only for expiring retention.")
        return self


class RecipientGrant(Model):
    recipient_profile_id: str = Field(min_length=1, max_length=128)
    channels: list[Literal["metadata", "text", "visual", "original", "audio"]] = Field(max_length=5)


class FileSelection(Model):
    selection_id: str = Field(min_length=1, max_length=128)
    file_name: str = Field(min_length=1, max_length=180)
    declared_bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    maximum_bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class IntakeRequest(Model):
    schema_version: Literal["library-intake-request-1"] = "library-intake-request-1"
    authorization_action_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=16, max_length=128)
    transfer_mode: Literal["browser_bytes"] = "browser_bytes"
    files: list[FileSelection] = Field(min_length=1, max_length=20)
    collection_id: str | None = Field(default=None, max_length=100)
    retention: Retention = Field(default_factory=Retention)
    allow_processing: bool = False
    purpose: Literal["document_reading", "study", "grade_planning", "schedule"] = "document_reading"
    recipient_grants: list[RecipientGrant] = Field(default_factory=list, max_length=5)


class MetadataChange(Model):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=180)
    tags: list[str] = Field(default_factory=list, max_length=20)
    collection_id: str | None = Field(default=None, max_length=100)


class PermissionChange(Model):
    expected_version_id: str
    expected_permission_revision: int = Field(ge=1)
    allow_processing: bool
    purpose: Literal["document_reading", "study", "grade_planning", "schedule"]
    recipient_grants: list[RecipientGrant] = Field(max_length=5)


class VersionExpectation(Model):
    expected_version_id: str
    expected_revision: int = Field(ge=1)
    expected_permission_revision: int = Field(ge=1)


class Replacement(VersionExpectation):
    selection: IntakeRequest


class ExportRequest(Model):
    idempotency_key: str = Field(min_length=16, max_length=128)
    versions: list[str] = Field(min_length=1, max_length=20)
