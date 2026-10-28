"""Local setup checks, explicit editions and privacy-safe progress evidence."""

import asyncio
import hashlib
import json
import os
import platform
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from canvas_bridge.document_policy import LOCAL_IMPORT_BYTES, SOURCE_BYTES

DESKTOP_VERSION = "0.2.0"
EDITIONS = {
    "offline": (
        "Offline academic intelligence",
        "Your permitted local materials and fictional examples. No account, server or network connection.",
    ),
    "synthetic": (
        "Synthetic demonstration",
        "Fictional courses and a local authenticated tool check. No university account is contacted.",
    ),
    "institutional": (
        "Authorized institutional integration",
        "Use an independently approved hosted service and its secure sign-in. This installer cannot grant approval.",
    ),
}
STAGES = (
    "source_retrieved",
    "document_converted",
    "content_extracted",
    "pixels_rendered",
    "visual_content_delivered",
    "analysis_completed",
)


class SetupError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def trust_configuration():
    """Only packaged operator-reviewed public configuration, never shell/.env settings."""
    path = Path(__file__).with_name("assets") / "onboarding-trust.json"
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if value.get("schema") == "onboarding-trust-1" else {}
    except (OSError, ValueError, AttributeError):
        return {}


def authorized_services(now=None):
    """This catalog is a navigation allowlist, not an authorization decision."""
    now = now or datetime.now(UTC)
    output = []
    for service in trust_configuration().get("institution_services", [])[:20]:
        try:
            url = urlsplit(service["settings_url"])
            expiry = datetime.fromisoformat(service["expires_at"])
            if (
                service.get("enabled") is not True
                or expiry.tzinfo is None
                or expiry <= now
                or url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path != "/settings"
            ):
                continue
            output.append(
                {
                    "name": str(service["name"])[:100],
                    "settings_url": service["settings_url"],
                    "authorization": "must_be_verified_by_host_at_sign_in",
                }
            )
        except (ValueError, KeyError, TypeError):
            continue
    return output


def compatibility():
    windows = sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}
    supported = (
        windows and sys.getwindowsversion().major >= 10 if sys.platform == "win32" else False
    )
    return {
        "platform": "Windows x64" if supported else "unsupported_release_platform",
        "supported_release": supported,
        "administrator_required": False,
        "runtime_bundled": bool(getattr(sys, "frozen", False)),
        "other_platforms": "experimental_only_not_released",
    }


def verify_bundle(root=None):
    if root is None and not getattr(sys, "frozen", False):
        return {"state": "source_checkout", "publisher": "not_verified"}
    root = root or Path(sys.executable).parent
    manifest = root / "bundle-manifest.json"
    try:
        if manifest.is_symlink() or manifest.stat().st_size > 2_000_000:
            raise ValueError()
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if value.get("schema") != "desktop-bundle-1" or not value.get("files"):
            raise ValueError()
        for name, expected in value["files"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
                raise ValueError()
            target = root / relative
            if (
                target.is_symlink()
                or target.is_junction()
                or not target.resolve().is_relative_to(root.resolve())
                or any(
                    p.is_symlink() or p.is_junction()
                    for p in target.parents
                    if p != root and p.is_relative_to(root)
                )
            ):
                raise ValueError()
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError()
        return {
            "state": "integrity_verified",
            "publisher": "separate_signature_required",
            "files_verified": len(value["files"]),
        }
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise SetupError(
            "BUNDLE_INTEGRITY_FAILED",
            "Application files are missing or changed. Reinstall a verified release; your separate data folder is kept.",
        ) from exc


def converter_status(candidates=None):
    candidates = (
        candidates
        if candidates is not None
        else [
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "LibreOffice",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "LibreOffice",
        ]
    )
    for root in candidates:
        version_file = root / "program/version.ini"
        if (
            not version_file.is_file()
            or version_file.is_symlink()
            or version_file.stat().st_size > 32768
        ):
            continue
        text = version_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(
            r"(?im)^(?:ProductVersion|Version)\s*=\s*(\d+\.\d+(?:\.\d+){0,2})\s*$", text
        )
        version = match[1] if match else "unknown"
        verified = version in trust_configuration().get("supported_converter_versions", [])
        return {
            "state": "compatible_detected_not_activated" if verified else "detected_not_verified",
            "version": version,
            "ready": False,
            "action": "Conversion needs a verified sandboxed component. Local grade and text tools remain available. No software was installed.",
        }
    return {
        "state": "not_installed",
        "ready": False,
        "action": "Optional slide conversion is unavailable. Continue with local grade/text tools; obtain optional components only through an approved release.",
    }


def stage_report(**observed):
    return {stage: observed.get(stage, "not_requested") for stage in STAGES}


class OfflineRuntime:
    """No server, token, database or external service is needed for this edition."""

    edition = "offline"
    url = None

    def __init__(self, folder):
        self.folder = Path(folder).absolute()
        self.lock = None

    def start(self):
        from canvas_bridge.desktop import ProfileLock
        from canvas_bridge.desktop_profiles import prepare_profile

        prepare_profile(self.folder, self.edition)
        self.lock = ProfileLock(self.folder)

    def stop(self):
        if self.lock:
            self.lock.close()
            self.lock = None

    def check(self):
        from canvas_bridge.academic.cli import run

        result = asyncio.run(run(SimpleNamespace(command="demo-grade")))
        calculation = result["calculation"]
        try:
            correct = Decimal(str(calculation.get("calculated_percentage"))) == Decimal("85")
        except InvalidOperation:
            correct = False
        if not correct or calculation.get("classification") != "verified_arithmetic":
            raise SetupError(
                "ACADEMIC_CHECK_FAILED",
                "The fictional grade calculation did not match its expected result. Reinstall a verified release.",
            )
        return {
            "environment": "offline_academic",
            "calculated_percentage": "85",
            "expected_calculation": "(80 + 90) / (100 + 100) * 100 = 85%",
            "analysis": "verified",
            "actual_chatgpt": "not_tested",
            "network_requests": 0,
            "stages": stage_report(
                source_retrieved="verified_fictional_fixture",
                analysis_completed="verified_deterministic_calculation",
            ),
        }

    def inspect(self, path, *, own_material=False):
        from canvas_bridge.academic.cli import run

        if Path(path).suffix.lower() not in {".txt", ".md"}:
            raise SetupError(
                "OFFLINE_FORMAT_UNAVAILABLE",
                "This local edition supports TXT and Markdown inspection. Other formats require a release with a verified conversion component. No document was processed.",
            )
        result = asyncio.run(
            run(
                SimpleNamespace(
                    command="inspect-document",
                    path=Path(path),
                    acknowledge_own_material=own_material,
                )
            )
        )
        count = sum(len(p.get("text", "")) for d in result["documents"] for p in d.get("parts", []))
        if not count:
            raise SetupError(
                "NO_USABLE_TEXT",
                "No readable text was established. Try a text document or use a release with a verified optional converter.",
            )
        return {
            "characters_extracted": count,
            "complete": result["complete"],
            "stages": stage_report(
                source_retrieved="verified_local_bytes", content_extracted="verified_text_only"
            ),
            "analysis": "not_performed",
            "external_sharing": "not_permitted",
            "retained_document": False,
        }


def diagnostics(runtime, check=None):
    check = check or {}
    offline = isinstance(runtime, OfflineRuntime)
    result = {
        "server": "not_required"
        if offline
        else "running"
        if runtime.server and runtime.server.started
        else "unavailable",
        "authentication": "not_required"
        if offline
        else "verified_by_authenticated_protocol_check"
        if check.get("planning") == "verified"
        else "not_verified",
        "institution_authorization": "not_enabled",
        "upstream_connectivity": "not_used" if offline else "fictional_provider_only",
        "client": "local_engine_verified"
        if offline and check.get("analysis") == "verified"
        else "MCP_test_client_verified"
        if check.get("planning") == "verified"
        else "not_verified",
        "tool_negotiation": check.get("protocol", "not_required" if offline else "not_verified"),
        "chatgpt": "not_tested_no_connection_claimed",
        "clock": "not_independently_synchronized; enable automatic system date/time if sign-in or update validity fails",
        "token_expiration": "not_applicable"
        if offline
        else "one_hour_local_session; restart explicitly after expiry",
        "converter": converter_status(),
        "file_limits": {"general_bytes": SOURCE_BYTES, "pptx_bytes": LOCAL_IMPORT_BYTES},
    }
    return result
