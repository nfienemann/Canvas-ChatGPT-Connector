import hashlib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRIDGE_", env_file=".env", extra="ignore")

    profile: Literal["synthetic", "personal", "hosted"] = "synthetic"
    database_url: str = "sqlite:///.local/bridge.db"
    resource_url: str = "http://127.0.0.1:8000"
    issuer_url: str = "https://synthetic.invalid"
    jwks_url: str | None = None
    local_jwks_file: Path | None = None
    vault_key_file: Path = Path(".local/vault.key")
    institutions_file: Path = Path("institutions.json")
    deletion_journal: Path = Path(".local/deletions.jsonl")
    browser_client_id: str | None = None
    browser_client_secret_file: Path | None = None
    browser_authorization_url: str | None = None
    browser_token_url: str | None = None
    browser_require_issuer_parameter: bool = True
    live_access_enabled: bool = False
    personal_subject: str | None = Field(default=None, min_length=1, max_length=256, repr=False)
    mcp_read_only: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    max_pages: int = Field(default=20, ge=1, le=100)
    max_response_bytes: int = Field(default=2_000_000, ge=1000, le=10_000_000)
    request_timeout_seconds: float = Field(default=8, gt=0, le=15)
    refresh_budget_seconds: float = Field(default=12, gt=0, le=15)
    authorization_lease_seconds: int = Field(default=300, ge=0, le=300)
    max_courses: int = Field(default=30, ge=1, le=100)
    file_reading_enabled: bool = False
    parser_root: Path | None = None
    parser_runtime_root: Path | None = None
    ocr_root: Path | None = None
    file_cache_hours: int = Field(default=24, ge=1, le=24)
    file_delivery_enabled: bool = True
    file_delivery_root: Path | None = None
    file_delivery_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)
    file_delivery_inline_bytes: int = Field(default=128 * 1024, ge=0, le=128 * 1024)
    file_delivery_ttl_seconds: int = Field(default=300, ge=1, le=900)
    file_delivery_staging_bytes: int = Field(default=512 * 1024 * 1024, ge=1, le=512 * 1024 * 1024)
    file_delivery_budget_seconds: float = Field(default=90, gt=0, le=90)

    @property
    def browser_callback_url(self) -> str:
        callback = self.resource_url.rstrip("/") + "/settings/callback"
        if not self.browser_require_issuer_parameter:
            # RFC 9700 section 4.4.2.2: a distinct redirect for each exact issuer.
            callback += "/" + hashlib.sha256(self.issuer_url.encode()).hexdigest()
        return callback

    @model_validator(mode="after")
    def safe_profile(self):
        if self.profile == "personal" and not self.personal_subject:
            raise ValueError("Personal testing requires one configured identity-provider subject.")
        if self.profile != "synthetic":
            if not self.live_access_enabled:
                raise ValueError("Live access requires an explicit operator enablement.")
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Live profiles require PostgreSQL.")
            for value in (self.resource_url, self.issuer_url, self.jwks_url):
                if not value or urlsplit(value).scheme != "https":
                    raise ValueError("Live profiles require HTTPS resource, issuer and JWKS URLs.")
            if self.local_jwks_file:
                raise ValueError("Local fixture keys are restricted to the synthetic profile.")
        if self.profile == "synthetic" and self.host not in {"127.0.0.1", "::1"}:
            raise ValueError("Synthetic services must bind only to loopback.")
        if urlsplit(self.resource_url).query or urlsplit(self.resource_url).fragment:
            raise ValueError("Resource identifier cannot contain a query or fragment.")
        return self
