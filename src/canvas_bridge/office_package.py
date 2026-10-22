"""Shared, bounded OOXML reader for isolated document workers only.

No extraction to disk, URL retrieval, formula evaluation or service imports.
Registering a container type does not enable a new MCP extraction capability.
"""

import io
import posixpath
import stat
import zipfile
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree as ET

MAX_BYTES = 10_000_000
MAX_ENTRIES = 1000
MAX_EXPANDED_BYTES = 20_000_000
MAX_EXPANSION_RATIO = 200


@dataclass(frozen=True)
class OfficeFormat:
    main_part: str
    main_content_type: str
    locator: str


OFFICE_FORMATS = MappingProxyType(
    {
        "docx": OfficeFormat(
            "word/document.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            "section",
        ),
        "pptx": OfficeFormat(
            "ppt/presentation.xml",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
            "slide",
        ),
        "xlsx": OfficeFormat(
            "xl/workbook.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
            "sheet_cell",
        ),
    }
)

OFFICE_ERRORS = frozenset(
    {
        "office_resource_limit",
        "active_office_content",
        "encrypted_office",
        "encrypted_or_legacy_office",
        "invalid_office_archive",
        "office_type_mismatch",
        "invalid_office_reference",
    }
)


def _safe_name(name: str) -> bool:
    return bool(name) and not (
        any(ord(char) < 32 for char in name)
        or any(char in name for char in "\\:%?#")
        or any(part in {"", ".", ".."} for part in name.split("/"))
    )


class OfficePackage:
    """Validated package members; source references stay within this archive.

    Use only inside the existing OS worker to retain its memory/CPU/wall limits.
    External relationships may exist but are never dereferenced.
    """

    def __init__(self, data: bytes, kind: str):
        if kind not in OFFICE_FORMATS:
            raise ValueError("office_type_mismatch")
        if len(data) > MAX_BYTES:
            raise ValueError("office_resource_limit")
        # Password-protected Office documents normally use an OLE container.
        if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ValueError("encrypted_or_legacy_office")
        if not data.startswith(b"PK\x03\x04"):
            raise ValueError("invalid_office_archive")
        self.format = OFFICE_FORMATS[kind]
        self._archive = zipfile.ZipFile(io.BytesIO(data))
        try:
            self._validate()
        except Exception:
            self._archive.close()
            raise

    def _validate(self):
        entries = self._archive.infolist()
        if (
            len(entries) > MAX_ENTRIES
            or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES
            or any(
                e.file_size > MAX_BYTES
                or e.file_size > max(1, e.compress_size) * MAX_EXPANSION_RATIO
                for e in entries
            )
        ):
            raise ValueError("office_resource_limit")
        if any(e.flag_bits & 1 for e in entries):
            raise ValueError("encrypted_office")
        if len({e.filename.casefold() for e in entries}) != len(entries) or any(
            not _safe_name(e.filename[:-1] if e.is_dir() else e.filename)
            or e.orig_filename != e.filename
            or stat.S_ISLNK(e.external_attr >> 16)
            or e.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            for e in entries
        ):
            raise ValueError("invalid_office_archive")
        self.names = frozenset(e.filename for e in entries if not e.is_dir())
        if any("vbaproject" in n.lower() or "/embeddings/" in n.lower() for n in self.names):
            raise ValueError("active_office_content")
        if self.format.main_part not in self.names or "[Content_Types].xml" not in self.names:
            raise ValueError("office_type_mismatch")
        declarations = self.xml("[Content_Types].xml")
        if (
            declarations.tag
            != "{http://schemas.openxmlformats.org/package/2006/content-types}Types"
        ):
            raise ValueError("office_type_mismatch")
        types = {}
        for entry in declarations:
            content_type = entry.attrib.get("ContentType", "")
            if any(
                marker in content_type.lower()
                for marker in ("macroenabled", "vbaproject", "oleobject")
            ):
                raise ValueError("active_office_content")
            if entry.tag.endswith("}Override"):
                name = entry.attrib.get("PartName", "")
                if name in types:
                    raise ValueError("office_type_mismatch")
                types[name] = content_type
        if types.get("/" + self.format.main_part) != self.format.main_content_type:
            raise ValueError("office_type_mismatch")
        roots = [
            entry
            for entry in self.xml("_rels/.rels")
            if entry.attrib.get("Type", "").endswith("/officeDocument")
        ]
        if len(roots) != 1 or self._resolve("", roots[0]) != self.format.main_part:
            raise ValueError("office_type_mismatch")

    def xml(self, name: str):
        if name not in self.names:
            raise ValueError("invalid_office_reference")
        # ZipFile checks CRC/overlap on reads; defusedxml rejects DTDs/entities.
        return ET.fromstring(self._archive.read(name), forbid_dtd=True, forbid_entities=True)

    def read(self, name: str) -> bytes:
        """Read one validated member in memory; archive bounds and CRC still apply."""
        if name not in self.names:
            raise ValueError("invalid_office_reference")
        return self._archive.read(name)

    def relationships(self, source: str, relationship_type: str):
        """Return matching relationships without following their destinations."""
        directory, filename = posixpath.split(source)
        name = posixpath.join(directory, "_rels", filename + ".rels")
        if name not in self.names:
            return []
        return [
            e for e in self.xml(name) if e.attrib.get("Type", "").endswith("/" + relationship_type)
        ]

    def _resolve(self, source: str, relation) -> str:
        if relation.attrib.get("TargetMode", "Internal") != "Internal":
            raise ValueError("invalid_office_reference")
        target = relation.attrib.get("Target", "")
        parts = urlsplit(target)
        if not target or parts.scheme or parts.netloc or parts.query or parts.fragment:
            raise ValueError("invalid_office_reference")
        target = unquote(target, errors="strict")
        if "\\" in target or target.startswith("//"):
            raise ValueError("invalid_office_reference")
        path = posixpath.normpath(
            target[1:]
            if target.startswith("/")
            else posixpath.join(posixpath.dirname(source), target)
        )
        if not _safe_name(path) or path not in self.names:
            raise ValueError("invalid_office_reference")
        return path

    def related_part(self, source: str, relationship_id: str, relationship_type: str) -> str:
        if source not in self.names:
            raise ValueError("invalid_office_reference")
        directory, filename = posixpath.split(source)
        relations = self.xml(posixpath.join(directory, "_rels", filename + ".rels"))
        matches = [e for e in relations if e.attrib.get("Id") == relationship_id]
        if len(matches) != 1 or not matches[0].attrib.get("Type", "").endswith(
            "/" + relationship_type
        ):
            raise ValueError("invalid_office_reference")
        return self._resolve(source, matches[0])

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._archive.close()
