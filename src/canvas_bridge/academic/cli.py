"""Offline academic entry point: no Bridge, account, database, token or network setup."""

import argparse
import asyncio
import hashlib
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from canvas_bridge.academic.gateway import AcademicRequest
from canvas_bridge.academic.services import calculate_grade, document_text
from canvas_bridge.document_policy import SOURCE_BYTES, local_import_limit
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.providers.future_mcp import FutureApprovedMCPProvider
from canvas_bridge.providers.local_document import (
    LocalDocumentProvider,
    LocalExtractionSettings,
    LocalImportPermit,
)
from canvas_bridge.providers.local_grades import LocalGradeProvider
from canvas_bridge.providers.synthetic import SyntheticProvider


async def run(args):
    if args.command == "capabilities":
        providers = (SyntheticProvider(), FutureApprovedMCPProvider())
        return {p.provider_id: p.get_source_capabilities() for p in providers}
    if args.command in {"demo-grade", "demo-forecast"}:
        provider = SyntheticProvider()
        request = AcademicRequest("synthetic-student", "fictional", "demo", "course-fictional")
        authorized = await provider.get_grade_summary(request)
        if args.command == "demo-forecast":
            return forecast(provider, authorized, args)
        return calculate_grade(provider.gateway, authorized)
    if not args.acknowledge_own_material:
        raise DomainError(
            "permission_denied",
            "Local processing requires explicit confirmation that this is your own permitted material.",
        )
    source = args.path
    kind = source.suffix.lstrip(".").lower()
    limit = local_import_limit(kind) if args.command == "inspect-document" else SOURCE_BYTES
    if source.is_symlink() or not source.is_file() or source.stat().st_size > limit:
        raise DomainError(
            "unsupported_feature",
            f"A regular local file within the {limit // 1_000_000} MB limit is required.",
        )
    with source.open("rb") as stream:
        data = stream.read(limit + 1)
    permit = LocalImportPermit(
        "local-console",
        "local-document",
        hashlib.sha256(data).hexdigest(),
        utcnow() + timedelta(minutes=5),
        "Explicit local-console ownership attestation",
        purpose="grade_planning" if args.command == "forecast-grades" else "document_reading",
    )
    if args.command == "forecast-grades":
        provider = LocalGradeProvider(data, permit)
        request = AcademicRequest("local-console", "local", "local-import", "local-document")
        try:
            authorized = await provider.get_grade_summary(request)
            return forecast(provider, authorized, args)
        finally:
            provider.revoke()
    with tempfile.TemporaryDirectory(prefix="bridge-offline-academic-") as folder:
        # No environment settings, database, vault or identity service is loaded.
        settings = LocalExtractionSettings(parser_root=Path(folder))
        provider = LocalDocumentProvider(data, kind, permit, settings=settings)
        request = AcademicRequest(
            "local-console", "local", "local-import", "local-document", purpose="document_reading"
        )
        try:
            authorized = await provider.get_authorized_document(request)
            return document_text(provider.gateway, authorized)
        finally:
            provider.revoke()


def forecast(provider, authorized, args):
    from canvas_bridge.extensions.forecast import grade_forecast_manifest
    from canvas_bridge.extensions.runtime import ExtensionRegistry

    extensions = ExtensionRegistry()
    extensions.register(grade_forecast_manifest())
    return extensions.execute(
        "grade_forecast",
        "1.0.0",
        provider.gateway,
        authorized,
        assumptions={
            "future_possible_points": args.future_points,
            "future_score_percent": args.future_percent,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo-grade", help="Calculate entirely fictional grades without Canvas.")
    commands.add_parser("capabilities", help="Describe implemented and reserved adapters.")
    for name in ("demo-forecast", "forecast-grades"):
        scenario = commands.add_parser(
            name, help="Local aggregate points scenario using the versioned extension SDK."
        )
        scenario.add_argument("--future-points", required=True)
        scenario.add_argument("--future-percent", required=True)
        if name == "forecast-grades":
            scenario.add_argument("path", type=Path)
            scenario.add_argument("--acknowledge-own-material", action="store_true")
    document = commands.add_parser(
        "inspect-document", help="Process a permitted local document; no external sharing."
    )
    document.add_argument("path", type=Path)
    document.add_argument("--acknowledge-own-material", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except DomainError as exc:
        print(json.dumps({"status": exc.status, "summary": exc.message}))
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
