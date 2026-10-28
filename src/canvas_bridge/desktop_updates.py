"""Signed offline update packages; no network, unsigned fallback or approval changes."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, Field

from canvas_bridge.domain import Model
from canvas_bridge.onboarding import DESKTOP_VERSION, SetupError, trust_configuration

MAX_PACKAGE = 512 * 1024 * 1024
MINIMUM_ACCESS_PRESERVING_VERSION = (0, 2, 0)


class Release(Model):
    schema_version: str = "desktop-release-1"
    product: str = "canvas-bridge-local"
    version: str = Field(pattern=r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
    platform: str = "windows-x64"
    editions: list[str] = Field(min_length=1, max_length=2)
    key_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    installer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    installer_bytes: int = Field(gt=0, le=MAX_PACKAGE)
    publisher_thumbprint: str = Field(pattern=r"^[A-Fa-f0-9]{40}$")
    compatible_database_revisions: list[str] = Field(default_factory=list, max_length=100)
    release_notes: str = Field(min_length=1, max_length=12000)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def verify_release(raw, signature, *, trust=None, now=None):
    trust = trust if trust is not None else trust_configuration()
    now = now or datetime.now(UTC)
    try:
        if len(raw) > 65536 or len(signature) > 256:
            raise ValueError()
        data = json.loads(raw)
        release = Release.model_validate(data)
        public = trust.get("release_keys", {}).get(release.key_id)
        if not public:
            raise SetupError(
                "UPDATE_SIGNER_NOT_CONFIGURED",
                "No trusted release signer matches this package. Obtain an approved release; no update was installed.",
            )
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True)).verify(
            base64.b64decode(signature, validate=True), canonical(data)
        )
        if (
            release.schema_version != "desktop-release-1"
            or release.product != "canvas-bridge-local"
            or release.platform != "windows-x64"
            or set(release.editions) - {"offline", "synthetic"}
            or release.publisher_thumbprint.upper()
            not in {p.upper() for p in trust.get("publisher_thumbprints", [])}
        ):
            raise ValueError()
        if not release.issued_at <= now < release.expires_at:
            raise SetupError(
                "UPDATE_EXPIRED_OR_CLOCK_INCORRECT",
                "This update is outside its validity period. Check automatic date/time and obtain a current signed package; verification cannot be bypassed.",
            )
        return release
    except (ValueError, TypeError, KeyError, InvalidSignature) as exc:
        raise SetupError(
            "UPDATE_SIGNATURE_INVALID",
            "The update signature or release information is invalid. Nothing was installed.",
        ) from exc


def authenticode(path, expected):
    if sys.platform != "win32":
        raise SetupError(
            "UPDATE_PLATFORM_UNSUPPORTED",
            "Automatic installation is currently verified only for Windows x64.",
        )
    system = (
        Path(os.environ.get("SystemRoot", "C:/Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    script = "$s=Get-AuthenticodeSignature -LiteralPath $env:CB_VERIFY_FILE; [pscustomobject]@{valid=($s.Status -eq 'Valid'); thumbprint=$s.SignerCertificate.Thumbprint} | ConvertTo-Json -Compress"
    env = os.environ.copy()
    env["CB_VERIFY_FILE"] = str(path)
    try:
        result = subprocess.run(  # noqa: S603 - fixed signature query, no executable supplied by the package
            [str(system), "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            capture_output=True,
            timeout=30,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )  # noqa: S603 - fixed PowerShell signature query, path only via environment
        state = json.loads(result.stdout)
        if (
            state.get("valid") is not True
            or state.get("thumbprint", "").upper() != expected.upper()
        ):
            raise ValueError()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise SetupError(
            "INSTALLER_PUBLISHER_UNVERIFIED",
            "Windows could not verify the expected installer publisher. Nothing was launched.",
        ) from exc


def prepare_update(
    package,
    staging,
    *,
    edition,
    database_revision=None,
    rollback=False,
    trust=None,
    current_version=DESKTOP_VERSION,
    signature_check=authenticode,
):
    package, staging = Path(package), Path(staging)
    if package.is_symlink() or not package.is_file() or package.stat().st_size > MAX_PACKAGE:
        raise SetupError(
            "UPDATE_PACKAGE_INVALID",
            "Choose a regular signed update package within the supported size limit.",
        )
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if sorted(names) != ["installer.exe", "release.json", "release.sig"]:
                raise ValueError()
            if (
                archive.getinfo("release.json").file_size > 65536
                or archive.getinfo("release.sig").file_size > 256
            ):
                raise ValueError()
            release = verify_release(
                archive.read("release.json"), archive.read("release.sig"), trust=trust
            )
            if edition not in release.editions:
                raise SetupError(
                    "UPDATE_EDITION_MISMATCH",
                    "This update does not support the selected local edition.",
                )
            if database_revision and database_revision not in release.compatible_database_revisions:
                raise SetupError(
                    "ROLLBACK_SCHEMA_INCOMPATIBLE",
                    "This release cannot safely use the current database. Keep the current application or obtain an approved compatible release; data will not be downgraded.",
                )

            def version(v):
                return tuple(int(n) for n in v.split("."))

            if version(release.version) < MINIMUM_ACCESS_PRESERVING_VERSION:
                raise SetupError(
                    "ROLLBACK_SECURITY_INCOMPATIBLE",
                    "This release predates required access-preservation controls. Obtain a compatible signed release at version 0.2.0 or later; legacy rollback is blocked.",
                )
            if (not rollback and version(release.version) <= version(current_version)) or (
                rollback and version(release.version) >= version(current_version)
            ):
                raise SetupError(
                    "UPDATE_VERSION_DIRECTION",
                    "Choose a newer release for Update or a compatible previous release for Roll back.",
                )
            if archive.getinfo("installer.exe").file_size != release.installer_bytes:
                raise ValueError()
            staging.mkdir(parents=True, exist_ok=False)
            path = staging / "installer.exe"
            digest = hashlib.sha256()
            count = 0
            with archive.open("installer.exe") as source, path.open("xb") as target:
                while block := source.read(1024 * 1024):
                    count += len(block)
                    if count > release.installer_bytes:
                        raise ValueError()
                    digest.update(block)
                    target.write(block)
            if count != release.installer_bytes or digest.hexdigest() != release.installer_sha256:
                raise ValueError()
            signature_check(path, release.publisher_thumbprint)
            return {
                "release": release,
                "installer": path,
                "sha256": digest.hexdigest(),
                "rollback": rollback,
                "preserves_data": True,
            }
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, SetupError):
            raise
        raise SetupError(
            "UPDATE_INTEGRITY_FAILED",
            "Update contents failed verification. Obtain a fresh approved package; nothing was installed.",
        ) from exc


def launch_update(prepared, *, confirmed=False):
    if not confirmed:
        raise SetupError(
            "UPDATE_CONFIRMATION_REQUIRED",
            "Review the release notes and explicitly choose Install.",
        )
    installer = prepared["installer"]
    if installer.is_symlink():
        raise SetupError(
            "UPDATE_INTEGRITY_FAILED", "The staged installer changed. Prepare it again."
        )
    with installer.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != prepared["sha256"]:
            raise SetupError(
                "UPDATE_INTEGRITY_FAILED", "The staged installer changed. Prepare it again."
            )
    authenticode(installer, prepared["release"].publisher_thumbprint)
    # Fixed installer path and fixed arguments; the caller stops the runtime and
    # exits the launcher. No credentials/configuration are passed to the installer.
    return subprocess.Popen(  # noqa: S603 - signed, hash-verified executable after explicit approval
        [str(installer), "/NORESTART"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )  # noqa: S603 - signed and hash-verified executable after explicit approval
