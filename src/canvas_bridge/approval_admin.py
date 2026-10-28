"""Offline administrator tooling; never imported by an MCP/browser handler.

Keys must be provisioned by authorized administrators outside the running service.
This tool packages approvals already obtained; it does not decide eligibility.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from canvas_bridge.approval_policy import (
    ApprovalRecord,
    SealedEvidence,
    canonical_bytes,
    read_bounded,
)


def seal_evidence(content: bytes, key: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("An administrator-held 32-byte evidence key is required")
    nonce = os.urandom(12)
    return (
        SealedEvidence(
            nonce=base64.b64encode(nonce).decode(),
            ciphertext=base64.b64encode(
                AESGCM(key).encrypt(nonce, content, b"canvas-approval-v1")
            ).decode(),
        )
        .model_dump_json()
        .encode()
    )


def sign_record(record: dict, key_id: str, key: bytes) -> dict:
    ApprovalRecord.model_validate(record)
    signature = Ed25519PrivateKey.from_private_bytes(key).sign(canonical_bytes(record))
    return {"key_id": key_id, "record": record, "signature": base64.b64encode(signature).decode()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    seal = actions.add_parser("seal-evidence", help="Encrypt previously obtained correspondence")
    seal.add_argument("--input", type=Path, required=True)
    seal.add_argument("--key-file", type=Path, required=True)
    seal.add_argument("--evidence-root", type=Path, required=True)
    sign = actions.add_parser("sign-record", help="Attest one administrator-reviewed record")
    sign.add_argument("--input", type=Path, required=True)
    sign.add_argument("--key-file", type=Path, required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "seal-evidence":
        encrypted = seal_evidence(
            read_bounded(args.input, 10_000_000), read_bounded(args.key_file, 32)
        )
        digest = hashlib.sha256(encrypted).hexdigest()
        # Administrator creates an ACL-protected destination in advance. Never
        # guess OS permissions or put plaintext/signing keys in the service tree.
        with (args.evidence_root / (digest + ".sealed")).open("xb") as stream:
            stream.write(encrypted)
        print(digest)
    else:
        signed = sign_record(
            json.loads(read_bounded(args.input)), args.key_id, read_bounded(args.key_file, 32)
        )
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(signed, stream, sort_keys=True)


if __name__ == "__main__":
    main()
