"""Operator-only signed update packaging. Signing identities are never generated here."""

import argparse
import base64
import hashlib
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from canvas_bridge.desktop_updates import Release, authenticode, canonical, verify_release
from canvas_bridge.onboarding import DESKTOP_VERSION, trust_configuration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--publisher-thumbprint", required=True)
    parser.add_argument("--release-notes", required=True, type=Path)
    parser.add_argument("--compatible-revision", action="append", required=True)
    parser.add_argument("--version", default=DESKTOP_VERSION)
    args = parser.parse_args()
    trust = trust_configuration()
    public = trust.get("release_keys", {}).get(args.key_id)
    if not public or args.publisher_thumbprint.upper() not in trust.get(
        "publisher_thumbprints", []
    ):
        raise SystemExit("Configure reviewed public trust anchors before packaging a release.")
    if args.installer.is_symlink() or not args.installer.is_file():
        raise SystemExit("Use a regular publisher-signed installer.")
    authenticode(args.installer, args.publisher_thumbprint)
    key = serialization.load_pem_private_key(args.key_file.read_bytes(), password=None)
    if (
        not isinstance(key, Ed25519PrivateKey)
        or base64.b64encode(key.public_key().public_bytes_raw()).decode() != public
    ):
        raise SystemExit("The signing identity does not match the configured public release key.")
    with args.installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    now = datetime.now(UTC)
    release = Release(
        version=args.version,
        editions=["offline", "synthetic"],
        key_id=args.key_id,
        issued_at=now,
        expires_at=now + timedelta(days=30),
        installer_sha256=digest,
        installer_bytes=args.installer.stat().st_size,
        publisher_thumbprint=args.publisher_thumbprint.upper(),
        compatible_database_revisions=args.compatible_revision,
        release_notes=args.release_notes.read_text(encoding="utf-8"),
    )
    raw = canonical(release.model_dump(mode="json"))
    signature = base64.b64encode(key.sign(raw))
    verify_release(raw, signature, trust=trust)
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("release.json", raw)
        archive.writestr("release.sig", signature)
        archive.write(args.installer, "installer.exe")
    print("Signed update package created. No signing material was included.")


if __name__ == "__main__":
    main()
