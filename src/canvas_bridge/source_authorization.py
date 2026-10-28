"""Server-owned operation and source contracts; local storage is not authority."""

from enum import StrEnum

from pydantic import Field

from canvas_bridge.domain import DomainError, Model
from canvas_bridge.semester_models import SemesterPreferences


class OperationCategory(StrEnum):
    EXTERNAL_SOURCE_ACCESS = "EXTERNAL_SOURCE_ACCESS"
    INSTITUTIONAL_CACHE_ACCESS = "INSTITUTIONAL_CACHE_ACCESS"
    USER_PROVIDED_CONTENT = "USER_PROVIDED_CONTENT"
    SYNTHETIC_CONTENT = "SYNTHETIC_CONTENT"
    LOCAL_ONLY_PREFERENCES = "LOCAL_ONLY_PREFERENCES"
    DERIVED_ACADEMIC_ANALYSIS = "DERIVED_ACADEMIC_ANALYSIS"
    DATA_EXPORT_OR_MODEL_EGRESS = "DATA_EXPORT_OR_MODEL_EGRESS"


LOCAL_DOCUMENT_TOOLS = frozenset(
    {
        "list_local_documents",
        "read_local_document",
        "search_local_documents",
        "render_local_document_page",
        "get_local_document_status",
        "prepare_local_study_materials",
    }
)
PREFERENCE_TOOLS = frozenset({"get_local_study_preferences", "update_local_study_preferences"})
INDEPENDENT_INTELLIGENCE_TOOLS = frozenset({"run_independent_academic_workflow"})


class LocalPreferences(Model):
    timezone: str = Field(default="UTC", max_length=100)
    week_start: str = Field(default="monday", pattern=r"^(monday|sunday)$")
    break_minutes: int = Field(default=10, ge=0, le=60)
    buffer_minutes: int = Field(default=10, ge=0, le=120)
    semester: SemesterPreferences | None = None

    def validated(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise DomainError("needs_input", "Choose a valid IANA timezone.") from None
        return self.model_dump(mode="json", exclude_none=True)


def operation_contract(name, categories=(), *, write=False):
    if name in INDEPENDENT_INTELLIGENCE_TOOLS:
        return {
            "contract_version": "source-operation-1",
            "categories": [
                "USER_PROVIDED_CONTENT",
                "DERIVED_ACADEMIC_ANALYSIS",
                "DATA_EXPORT_OR_MODEL_EGRESS",
            ],
            "authentication": "verified_application_identity",
            "authorization": [
                "owned_independent_source",
                "content_rights",
                "recipient_review",
                "academic_integrity",
            ],
            "source_types": ["independent_import"],
            "data_dependencies": ["exact_source_versions"],
            "upstream_network": False,
            "read_only": True,
            "offline_supported": True,
            "data_classification": "inherited_from_authorized_sources; unknown_denied",
            "egress": "exact_source_recipient_and_modality_check",
            "academic_integrity": "B; known_assessed_source_requires_activity_decision",
            "conditional_institutional_dependencies": False,
        }
    from canvas_bridge.processes.surfaces import TOOLS as PROCESS_TOOLS
    from canvas_bridge.processes.surfaces import contract as process_contract

    if name in PROCESS_TOOLS:
        return process_contract(name, write=write)
    from canvas_bridge.integrity.surfaces import TOOLS as INTEGRITY_TOOLS
    from canvas_bridge.integrity.surfaces import contract

    integrity = name in INTEGRITY_TOOLS
    C = OperationCategory
    if integrity:
        from canvas_bridge.integrity.surfaces import HISTORY

        history = name in HISTORY
        return {
            "contract_version": "source-operation-1",
            "academic_integrity": contract(name),
            "categories": [str(C.DERIVED_ACADEMIC_ANALYSIS), str(C.DATA_EXPORT_OR_MODEL_EGRESS)],
            "authentication": "verified_application_identity",
            "authorization": ["owned_integrity_receipt"]
            if history
            else [
                "owned_scope",
                "current_source_authorization",
                "recipient_egress",
                "academic_integrity",
            ],
            "source_types": ["minimal_integrity_receipt"]
            if history
            else ["local_document", "institutional", "synthetic", "reviewed_public_policy"],
            "data_dependencies": [] if history else ["exact_request_sources"],
            "upstream_network": not history,
            "read_only": not write,
            "offline_supported": True,
            "data_classification": "schema_restricted_metadata"
            if history
            else "inherited_from_authorized_sources; unknown_denied",
            "egress": "schema_restricted_metadata"
            if history
            else "exact_source_recipient_and_modality_check",
            "conditional_institutional_dependencies": not history,
            "conditional_authorization": {}
            if history
            else {
                "institutional_scope": [
                    "provider",
                    "institution",
                    "selected_scope",
                    "recipient_egress",
                ],
                "local_scope": [
                    "owned_independent_source",
                    "content_rights",
                    "recipient_egress",
                    "no_upstream_network",
                ],
            },
        }
    local = name in LOCAL_DOCUMENT_TOOLS
    preference = name in PREFERENCE_TOOLS or name in {
        "update_study_preferences",
        "get_saved_study_state",
    }
    status = name == "get_connection_status"
    cached = name in {
        "get_changes",
        "get_saved_study_state",
        "propose_study_plan",
        "save_study_plan",
        "record_personal_progress",
        "propose_calendar_sync",
        "acknowledge_semester_findings",
    }
    derived = name == "get_semester_overview" or name.startswith(
        (
            "propose_",
            "audit_",
            "calculate_",
            "simulate_",
            "interpret_",
            "reconcile_",
            "review_",
            "prepare_",
        )
    )
    primary = [
        str(
            C.USER_PROVIDED_CONTENT
            if local
            else C.LOCAL_ONLY_PREFERENCES
            if preference
            else C.LOCAL_ONLY_PREFERENCES
            if status
            else C.INSTITUTIONAL_CACHE_ACCESS
            if cached
            else C.EXTERNAL_SOURCE_ACCESS
        )
    ]
    if derived:
        primary.append(str(C.DERIVED_ACADEMIC_ANALYSIS))
    if name == "get_saved_study_state":
        primary.append(str(C.INSTITUTIONAL_CACHE_ACCESS))
    return {
        "academic_integrity": contract(name),
        "contract_version": "source-operation-1",
        "categories": primary + [str(C.DATA_EXPORT_OR_MODEL_EGRESS)],
        "authentication": "verified_application_identity",
        "authorization": ["owned_independent_source", "content_rights", "recipient_review"]
        if local
        else ["owned_schema_restricted_preferences"]
        if preference
        else ["redacted_status"]
        if status
        else [
            "provider",
            "institution",
            "deployment",
            "upstream_identity",
            "selected_scope",
            "recipient_egress",
        ],
        "source_types": ["local_document"]
        if local
        else ["local_preferences"]
        if preference
        else ["safe_status"]
        if status
        else ["institutional", "synthetic"],
        "data_dependencies": sorted(categories),
        "upstream_network": not (local or preference or status or cached),
        "data_classification": "FIRST_PARTY_EDUCATIONAL_RECORD"
        if local
        else "schema_restricted_metadata"
        if preference or status
        else "inherited_from_authorized_sources; unknown_denied",
        "read_only": not write,
        "offline_supported": local or preference or status or integrity,
        "egress": "exact_source_recipient_and_modality_check"
        if local
        else "schema_restricted_metadata"
        if preference or status
        else "institutional_content_policy",
        "conditional_institutional_dependencies": name == "get_saved_study_state",
        "conditional_authorization": {
            "include_institutional=true": [
                "provider",
                "institution",
                "upstream_identity",
                "source_lineage",
                "recipient_egress",
            ]
        }
        if name == "get_saved_study_state"
        else {},
    }


def capability_inventory(mcp):
    """Inventory real registered definitions, including schema and widget metadata."""
    from canvas_bridge.policy_surfaces import OFFLINE_TOOLS, TOOL_CATEGORIES

    known = set(TOOL_CATEGORIES) | OFFLINE_TOOLS
    rows = []
    for tool in mcp._tool_manager.list_tools():
        if tool.name not in known:
            raise ValueError("Unclassified registered MCP tool")
        rows.append(
            {
                "name": tool.name,
                **operation_contract(
                    tool.name,
                    TOOL_CATEGORIES.get(tool.name, ()),
                    write=not tool.annotations.readOnlyHint,
                ),
                "input_schema": tool.parameters,
                "output_schema": tool.output_schema,
                "widget": tool.meta or {},
            }
        )
    return rows


def registered_inventory():
    """Build the actual MCP registry with an ephemeral fictional store and no environment."""
    import tempfile
    from pathlib import Path

    from canvas_bridge.app import create_app
    from canvas_bridge.config import Settings
    from canvas_bridge.policy import Registry
    from canvas_bridge.service import Bridge
    from canvas_bridge.storage import Store
    from canvas_bridge.synthetic import SyntheticProvider
    from canvas_bridge.vault import Vault

    with tempfile.TemporaryDirectory(prefix="bridge-contracts-") as directory:
        root = Path(directory)
        Vault.create(root / "vault.key")
        settings = Settings.model_construct(
            profile="synthetic",
            database_url="sqlite:///:memory:",
            vault_key_file=root / "vault.key",
            deletion_journal=root / "journal",
            mcp_read_only=False,
            resource_url="http://127.0.0.1:8000",
            issuer_url="https://synthetic.invalid",
            local_jwks_file=None,
        )
        store = Store(settings.database_url)
        store.create_fixture_schema()
        try:
            bridge = Bridge(
                settings,
                store,
                Vault(settings.vault_key_file),
                Registry(settings.institutions_file),
                SyntheticProvider(),
            )
            mcp = create_app(settings, bridge).state.mcp
            rows = capability_inventory(mcp)
            for row in rows:
                row["available_in_read_only_configuration"] = row["read_only"]
            return rows
        finally:
            store.close()
