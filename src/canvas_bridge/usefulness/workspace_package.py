"""Bounded student workspace archive. A manifest records evidence, never grants."""

import base64
import io
import json
import re
import stat
import zipfile
from hashlib import sha256

from canvas_bridge.domain import DomainError
from canvas_bridge.processes.state import read_portable_export

SCHEMA = "course-workspace-1"
LIMIT = 50_000_000
MANIFEST_LIMIT = 2_000_000


def refuse(code, message):
    raise DomainError("needs_input", message, reason_code=code)


def pack(manifest, payloads):
    body = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()
    if len(body) > MANIFEST_LIMIT or sum(map(len, payloads.values())) + len(body) > LIMIT - 64_000:
        refuse("PORT_PACKAGE_LIMIT", "Reduce the selected course records or payloads.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", body)
        for digest, data in sorted(payloads.items()):
            archive.writestr("payloads/" + digest, data)
    return output.getvalue()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def unpack(raw, owner):
    if len(raw) > LIMIT:
        refuse("PORT_PACKAGE_LIMIT", "Choose a workspace package within 50 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 221 or len({i.filename for i in entries}) != len(entries):
                raise ValueError
            payloads = {}
            body = None
            for entry in entries:
                manifest = entry.filename == "manifest.json"
                if (
                    not manifest
                    and not re.fullmatch(r"payloads/[a-f0-9]{64}", entry.filename)
                    or entry.orig_filename != entry.filename
                    or entry.flag_bits & 1
                    or entry.compress_type != zipfile.ZIP_STORED
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.compress_size != entry.file_size
                    or entry.file_size > (MANIFEST_LIMIT if manifest else 10_000_000)
                ):
                    raise ValueError
                value = archive.read(entry)
                if len(value) != entry.file_size:
                    raise ValueError
                if manifest:
                    body = value
                else:
                    digest = sha256(value).hexdigest()
                    if entry.filename != "payloads/" + digest:
                        raise ValueError
                    payloads[digest] = value
            if body is None:
                raise ValueError
            manifest = json.loads(body.decode("utf8"), object_pairs_hook=unique)
        if manifest["schema_version"] != SCHEMA:
            refuse(
                "PORT_SCHEMA_UNSUPPORTED",
                "This workspace format requires a compatible Bridge version.",
            )
        if manifest["owner"] != owner:
            refuse(
                "PORT_OWNER_MISMATCH", "Open this selection under its verified original identity."
            )
        if (
            not re.fullmatch("[a-f0-9]{32}", manifest["export_id"])
            or type(manifest["generation"]) is not int
            or manifest["generation"] < 0
        ):
            raise ValueError
        from copy import deepcopy

        process = deepcopy(manifest["process"])
        links = manifest.get("link_versions", {})
        if not isinstance(links, dict) or set(links) - {r["id"] for r in process["records"]}:
            raise ValueError
        for rec in process["records"]:
            if rec["id"] not in links:
                continue
            if rec["kind"] != "identity" or "revision" in rec or type(links[rec["id"]]) is not int:
                raise ValueError
            rec["revision"] = links[rec["id"]]
            data = rec["data"]
            groups = [data["canonical_link_proposal"], *data.get("canonical_inventory", [])]
            for group in groups:
                for alias in group["aliases"]:
                    alias.setdefault("instructor", None)
                    for scoped in (alias, *alias["sources"]):
                        if scoped["scope"].setdefault("principal", owner) != owner:
                            raise ValueError
        records = read_portable_export(process, owner=owner)
        if not isinstance(manifest["documents"], list) or len(manifest["documents"]) > 20:
            raise ValueError
        documents = {d["id"]: d for d in manifest["documents"]}
        if len(documents) != len(manifest["documents"]):
            raise ValueError
        required = set()
        for doc in documents.values():
            for version in doc["versions"]:
                digest = version["hash"]
                if not re.fullmatch("[a-f0-9]{64}", digest):
                    raise ValueError
                if version["payload"] == "included":
                    required.add(digest)
                    if len(payloads[digest]) != version["size"]:
                        raise ValueError
                elif version["payload"] != "reference_only":
                    raise ValueError
        if required != set(payloads):
            raise ValueError
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        zipfile.BadZipFile,
        RecursionError,
        OSError,
        NotImplementedError,
    ):
        refuse(
            "PORT_PACKAGE_INVALID", "The workspace inventory, payload, or schema failed validation."
        )
    return manifest, documents, records, payloads


def version(raw, digest, locator, acquired, include, payloads):
    data = base64.b64decode(raw, validate=True)
    if sha256(data).hexdigest() != digest:
        refuse("PORT_SOURCE_CHANGED", "The selected source failed its byte identity check.")
    if include:
        if digest not in payloads and sum(map(len, payloads.values())) + len(data) > LIMIT:
            refuse("PORT_PACKAGE_LIMIT", "Reduce the selected original byte inventory.")
        payloads[digest] = data
    return {
        "hash": digest,
        "size": len(data),
        "locator": locator,
        "acquired_at": acquired,
        "payload": "included" if include else "reference_only",
    }
