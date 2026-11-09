"""Credential-free safety/type probe executed only in the existing OS sandbox.

Conservative structural validation, not a claim of antivirus certification.
No extraction output is retained by a storage-only intake.
"""

import base64
import hashlib
import io
import json
import re
import stat
import unicodedata
import warnings
import zipfile
from pathlib import Path, PurePosixPath

from defusedxml import ElementTree as ET
from PIL import Image
from pypdf import PdfReader

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)


def archive_entries(data, *, office=False, budget=None):
    archive = zipfile.ZipFile(io.BytesIO(data))
    entries, names, total = archive.infolist(), set(), 0
    if len(entries) > (5000 if office else 100):
        raise ValueError("UNSAFE_ARCHIVE")
    for info in entries:
        name = info.filename
        folded = unicodedata.normalize("NFKC", name).casefold().rstrip("/")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or any(p in {".", ".."} for p in name.split("/"))
            or any(c in name for c in "\\:\x00")
            or folded in names
            or any(p.endswith((".", " ")) for p in path.parts)
            or stat.S_ISLNK(info.external_attr >> 16)
            or info.flag_bits & 1
        ):
            raise ValueError("UNSAFE_ARCHIVE")
        names.add(folded)
        total += info.file_size
        if total > 200_000_000 or info.file_size > max(1, info.compress_size) * 50:
            raise ValueError("UNSAFE_ARCHIVE")
        if info.is_dir():
            continue
        cap = 50_000_000 if office else 10_000_000
        with archive.open(info) as stream:
            body = stream.read(cap + 1)
        if len(body) != info.file_size or len(body) > cap:
            raise ValueError("UNSAFE_ARCHIVE")
        if budget is not None:
            budget[0] -= len(body)
            if budget[0] < 0:
                raise ValueError("UNSAFE_ARCHIVE")
        if not office and (
            path.suffix.lower() in {".zip", ".tar", ".gz", ".rar", ".7z"}
            or body.startswith((b"Rar!", b"7z\xbc\xaf", b"\x1f\x8b"))
            or body[257:262] == b"ustar"
        ):
            raise ValueError("UNSAFE_ARCHIVE")
        # Office ZIP containers are allowed; another ordinary ZIP hidden as TXT is not.
        if (
            not office
            and body.startswith(b"PK")
            and path.suffix.lower() not in {".docx", ".pptx", ".xlsx"}
        ):
            raise ValueError("UNSAFE_ARCHIVE")
        yield name, body


def inspect(data, kind, preview=False, *, _budget=None, _depth=0):
    budget = _budget if _budget is not None else [200_000_000]
    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data:
        raise ValueError("UNSAFE_CONTENT")
    result = {
        "kind": kind,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "scanner": "bounded-structural-1",
    }
    if kind in {"txt", "md"}:
        text = data.decode("utf-8")
        if (
            b"\x00" in data
            or data.startswith((b"PK", b"%PDF", b"MZ", b"\x89PNG"))
            or re.search(r"(?is)^\s*(?:<!doctype\s+html|<html|<svg|<script)", text)
        ):
            raise ValueError("UNSUPPORTED_MEDIA")
    elif kind in {"png", "jpg", "jpeg"}:
        if len(data) > 25 * 1024 * 1024:
            raise ValueError("UPLOAD_TOO_LARGE")
        if kind == "png":
            # Pillow tolerates trailing bytes; reject appended/concatenated carriers.
            offset = 8
            while offset + 12 <= len(data):
                size = int.from_bytes(data[offset : offset + 4], "big")
                tag = data[offset + 4 : offset + 8]
                offset += size + 12
                if tag == b"IEND":
                    if size or offset != len(data):
                        raise ValueError("UNSAFE_CONTENT")
                    break
            else:
                raise ValueError("UNSAFE_CONTENT")
        elif not data.endswith(b"\xff\xd9"):
            raise ValueError("UNSAFE_CONTENT")
        with Image.open(io.BytesIO(data)) as im:
            if (
                im.format != ("PNG" if kind == "png" else "JPEG")
                or im.width * im.height > 40_000_000
            ):
                raise ValueError("UNSUPPORTED_MEDIA")
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            result["dimensions"] = [im.width, im.height]
            if preview:
                im.thumbnail((2048, 2048))
                clean = Image.new("RGB", im.size, "white")
                clean.paste(im.convert("RGB"))
                out = io.BytesIO()
                clean.save(out, "PNG")
                if out.tell() > 2_000_000:
                    raise ValueError("PROCESSING_UNSUPPORTED")
                result["png"] = base64.b64encode(out.getvalue()).decode()
    elif kind == "pdf":
        if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
            raise ValueError("UNSUPPORTED_MEDIA")
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("UNSAFE_CONTENT")
        seen, pending = set(), [reader.trailer]
        while pending:
            obj = pending.pop()
            if hasattr(obj, "idnum"):
                ref = (obj.idnum, obj.generation)
                if ref in seen:
                    continue
                seen.add(ref)
                if len(seen) > 100_000:
                    raise ValueError("UNSAFE_CONTENT")
                obj = obj.get_object()
            if isinstance(obj, dict):
                if set(obj) & {
                    "/JS",
                    "/JavaScript",
                    "/Launch",
                    "/EmbeddedFiles",
                    "/RichMedia",
                    "/XFA",
                    "/AA",
                    "/OpenAction",
                }:
                    raise ValueError("UNSAFE_CONTENT")
                pending.extend(obj.values())
            elif isinstance(obj, list):
                pending.extend(obj)
    elif kind in {"docx", "pptx", "xlsx"}:
        contents = dict(archive_entries(data, office=True, budget=budget))
        main = {
            "docx": "word/document.xml",
            "pptx": "ppt/presentation.xml",
            "xlsx": "xl/workbook.xml",
        }[kind]
        if main not in contents or "[Content_Types].xml" not in contents:
            raise ValueError("UNSUPPORTED_MEDIA")
        for name, body in contents.items():
            if any(x in name.lower() for x in ("vbaproject", "activex", "externallinks/")):
                raise ValueError("UNSAFE_CONTENT")
            if "embeddings/" in name.lower():
                # Charts commonly carry a non-macro XLSX workbook. Validate that
                # exact package recursively under the shared expansion budget;
                # OLE binaries, arbitrary embedded objects and recursion stay denied.
                if _depth or not name.lower().endswith(".xlsx") or len(body) > 10_000_000:
                    raise ValueError("UNSAFE_CONTENT")
                inspect(body, "xlsx", _budget=budget, _depth=1)
            if name.endswith((".xml", ".rels")):
                root = ET.fromstring(body)
                for element in root.iter():
                    if "macroenabled" in " ".join(element.attrib.values()).lower():
                        raise ValueError("UNSAFE_CONTENT")
                    if element.attrib.get("TargetMode") == "External" and not element.attrib.get(
                        "Type", ""
                    ).endswith("/hyperlink"):
                        raise ValueError("UNSAFE_CONTENT")
    elif kind == "zip":
        accepted, excluded = [], []
        for name, body in archive_entries(data, budget=budget):
            ext = PurePosixPath(name).suffix.lower().lstrip(".")
            if ext not in {"pdf", "docx", "pptx", "xlsx", "txt", "md"}:
                excluded.append(name[:180])
                continue
            inspect(body, ext, _budget=budget)
            accepted.append(
                {
                    "file_name": PurePosixPath(name).name,
                    "member": name,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "kind": ext,
                }
            )
        if not accepted or len(accepted) > 20:
            raise ValueError("UNSAFE_ARCHIVE")
        result.update(members=accepted, excluded=excluded)
    else:
        raise ValueError("UNSUPPORTED_MEDIA")
    return result


def main():
    try:
        request = json.loads(Path("request.json").read_text())
        data = Path("input.bin").read_bytes()
        if len(data) > 100 * 1024 * 1024:
            raise ValueError("UPLOAD_TOO_LARGE")
        result = {
            "ok": True,
            "inspection": inspect(data, request["kind"], request.get("preview", False)),
        }
    except Exception as exc:
        allowed = {
            "UNSAFE_ARCHIVE",
            "UNSAFE_CONTENT",
            "UNSUPPORTED_MEDIA",
            "UPLOAD_TOO_LARGE",
            "PROCESSING_UNSUPPORTED",
        }
        result = {"ok": False, "reason": str(exc) if str(exc) in allowed else "UNSAFE_CONTENT"}
    Path("result.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
