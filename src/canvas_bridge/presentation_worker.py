"""Bounded OOXML presentation facts. No rendering, fetching or interpretation.

This module runs inside the existing credential-free OS worker for live bytes.
Relations are package paths only; XML entities, active content and unsafe paths
are rejected. Embedded workbooks are not opened; charts use stored XML caches.
"""

import io
import posixpath
import zipfile
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree as ET

if __package__:
    from canvas_bridge.document_policy import (
        PPTX_EXPANDED_BYTES,
        PPTX_MEMBER_BYTES,
        PPTX_MEMBERS,
        PPTX_RATIO,
        PPTX_SLIDES,
        PPTX_XML_BYTES,
        PresentationLimit,
    )
else:
    from document_policy import (
        PPTX_EXPANDED_BYTES,
        PPTX_MEMBER_BYTES,
        PPTX_MEMBERS,
        PPTX_RATIO,
        PPTX_SLIDES,
        PPTX_XML_BYTES,
        PresentationLimit,
    )


def local(element):
    return element.tag.rsplit("}", 1)[-1]


def bounded(budget, observed, limit):
    if observed > limit:
        raise PresentationLimit(budget, observed, limit)


def safe_name(name):
    return bool(
        name
        and not name.startswith(("/", "\\"))
        and "\\" not in name
        and ":" not in name
        and not any(ord(c) < 32 for c in name)
        and all(p not in {".", "..", ""} for p in name.rstrip("/").split("/"))
    )


class Package:
    def __init__(self, data):
        self.archive = zipfile.ZipFile(io.BytesIO(data))
        self.read_bytes = 0

    def __enter__(self):
        try:
            entries = self.archive.infolist()
            bounded("zip_members", len(entries), PPTX_MEMBERS)
            bounded("zip_expanded_bytes", sum(e.file_size for e in entries), PPTX_EXPANDED_BYTES)
            self.names = {e.filename for e in entries}
            if len({e.filename.casefold() for e in entries}) != len(entries):
                raise ValueError("invalid_pptx_archive")
            for entry in entries:
                name = entry.filename
                if (
                    not safe_name(name)
                    or not safe_name(entry.orig_filename)
                    or not safe_name(unquote(entry.orig_filename))
                    or entry.flag_bits & 1
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("invalid_pptx_archive")
                bounded("zip_member_bytes", entry.file_size, PPTX_MEMBER_BYTES)
                bounded(
                    "zip_compression_ratio",
                    entry.file_size,
                    max(1, entry.compress_size) * PPTX_RATIO,
                )
                if name.lower().endswith((".xml", ".rels")):
                    bounded("xml_member_bytes", entry.file_size, PPTX_XML_BYTES)
                lowered = name.lower()
                if (
                    "vbaproject" in lowered
                    or "/activex/" in lowered
                    or ("/embeddings/" in lowered and not lowered.endswith(".xlsx"))
                ):
                    raise ValueError("active_office_content")
            if "[Content_Types].xml" in self.names:
                if any(
                    "macroenabled" in e.get("ContentType", "").lower()
                    or "oleobject" in e.get("ContentType", "").lower()
                    for e in self.xml("[Content_Types].xml")
                ):
                    raise ValueError("active_office_content")
            return self
        except BaseException:
            self.archive.close()
            raise

    def __exit__(self, *args):
        self.archive.close()

    def read(self, name, limit=PPTX_XML_BYTES):
        # ZipFile enforces CRC; the read cap also guards actual inflation, rather
        # than trusting central-directory size declarations alone.
        with self.archive.open(name) as stream:
            data = stream.read(limit + 1)
        bounded("xml_member_bytes", len(data), limit)
        self.read_bytes += len(data)
        bounded("zip_read_bytes", self.read_bytes, PPTX_EXPANDED_BYTES)
        return data

    def xml(self, name):
        return ET.fromstring(
            self.read(name), forbid_dtd=True, forbid_entities=True, forbid_external=True
        )

    def relations(self, part):
        path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        if path not in self.names:
            return {}, 0
        relations, external = {}, 0
        for entry in self.xml(path):
            rid, target = entry.get("Id"), entry.get("Target", "")
            if not rid or rid in relations:
                raise ValueError("invalid_slide_reference")
            if entry.get("TargetMode", "Internal") == "External":
                external += 1
                continue
            decoded = unquote(target)
            parsed = urlsplit(decoded)
            if (
                not decoded
                or parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
                or "\\" in decoded
                or any(ord(c) < 32 for c in decoded)
            ):
                raise ValueError("invalid_slide_reference")
            path = posixpath.normpath(
                decoded.lstrip("/")
                if decoded.startswith("/")
                else posixpath.join(posixpath.dirname(part), decoded)
            )
            if not safe_name(path) or path not in self.names:
                raise ValueError("invalid_slide_reference")
            relations[rid] = (entry.get("Type", "").rsplit("/", 1)[-1], path)
        return relations, external

    def slide_paths(self):
        rels, _ = self.relations("ppt/presentation.xml")
        root = self.xml("ppt/presentation.xml")
        namespaces = {
            "http://schemas.openxmlformats.org/presentationml/2006/main": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            "http://purl.oclc.org/ooxml/presentationml/main": "http://purl.oclc.org/ooxml/officeDocument/relationships",
        }
        namespace = root.tag.removeprefix("{").partition("}")[0]
        if namespace not in namespaces or root.tag != f"{{{namespace}}}presentation":
            raise ValueError("invalid_slide_reference")
        # Section extensions also contain sldId elements, but those hold numeric
        # references to slides, not package relationships or presentation order.
        lists = root.findall(f"{{{namespace}}}sldIdLst")
        if len(lists) != 1:
            raise ValueError("invalid_slide_reference")
        paths = []
        for entry in lists[0]:
            if entry.tag != f"{{{namespace}}}sldId":
                raise ValueError("invalid_slide_reference")
            rid = entry.get(f"{{{namespaces[namespace]}}}id")
            relation = rels.get(rid)
            if not relation or relation[0] != "slide" or not relation[1].startswith("ppt/slides/"):
                raise ValueError("invalid_slide_reference")
            paths.append(relation[1])
            bounded("slide_count", len(paths), PPTX_SLIDES)
        if not paths or len(set(paths)) != len(paths):
            raise ValueError("invalid_slide_reference")
        return paths


def paragraphs(root, *, notes=False):
    # Placeholder slide numbers/date/footer/header are not speaker notes.
    if notes:
        roots = [
            e
            for e in root.iter()
            if local(e) == "sp"
            and not any(
                local(p) == "ph" and p.get("type") in {"sldNum", "dt", "ftr", "hdr", "sldImg"}
                for p in e.iter()
            )
        ]
    else:
        roots = [root]
    return "\n".join(
        "".join(e.text or "" for e in p.iter() if local(e) == "t")
        for r in roots
        for p in r.iter()
        if local(p) == "p"
    ).strip()


def extract_presentation(data, max_text):
    pages, total, warnings = [], 0, []
    with Package(data) as package:
        paths = package.slide_paths()
        metadata = {}
        if "docProps/core.xml" in package.names:
            for entry in package.xml("docProps/core.xml"):
                if local(entry) in {"title", "creator", "subject"}:
                    metadata[{"creator": "author"}.get(local(entry), local(entry))] = (
                        entry.text or ""
                    )[:1000]
        coverage = "text_only"
        for number, path in enumerate(paths, 1):
            page = {
                "page": number,
                "slide_number": number,
                "locator_kind": "slide",
                "text": "",
                "state": "no_text",
                "text_spans": [],
                "extraction_method": "ooxml_text",
                "visual_render_status": "not_rendered",
                "visual_observation": None,
                "warnings": [],
                "media_presence": {
                    "images": 0,
                    "charts": 0,
                    "diagrams": 0,
                    "audio_video": 0,
                    "external_relationships": 0,
                    "graphics_inspected": False,
                },
            }
            separator = 2 if pages else 0
            remaining = max(0, max_text - total - separator)

            def append(text, source_kind, page=page):
                nonlocal remaining
                if not text:
                    return
                if len(page["text_spans"]) >= 128:
                    page["state"] = "truncated"
                    return
                gap = "\n" if page["text"] else ""
                value = (gap + text)[:remaining]
                start = len(page["text"]) + len(gap)
                page["text"] += value
                remaining -= len(value)
                if len(value) < len(gap + text):
                    page["state"] = "truncated"
                if len(page["text"]) > start:
                    page["text_spans"].append(
                        {"start": start, "end": len(page["text"]), "source_kind": source_kind}
                    )

            try:
                root = package.xml(path)
                if __package__:
                    from canvas_bridge.scientific_structure import ooxml_structure
                else:
                    from scientific_structure import ooxml_structure

                page["structure"] = ooxml_structure(root, "pptx")
                rels, external = package.relations(path)
                media = page["media_presence"]
                media["external_relationships"] = external
                page["hidden"] = root.get("show", "1") in {"0", "false"}
                append(paragraphs(root), "slide_shapes_and_tables")
                for kind, target in rels.values():
                    if kind == "image":
                        media["images"] += 1
                    elif kind in {"audio", "video", "media"}:
                        media["audio_video"] += 1
                    elif kind.startswith("diagram"):
                        media["diagrams"] += 1
                    elif kind == "chart":
                        media["charts"] += 1
                        chart = package.xml(target)
                        _, chart_external = package.relations(target)
                        media["external_relationships"] += chart_external
                        # Titles/axis labels and stored series/category/numeric caches;
                        # formulas and embedded workbooks are never evaluated/opened.
                        append(
                            "\n".join(e.text or "" for e in chart.iter() if local(e) in {"t", "v"}),
                            "chart_cached_text_and_values",
                        )
                        page["warnings"].append(
                            "Chart caches may be stale; series geometry and formula results are not verified."
                        )
                    elif kind == "notesSlide":
                        append(paragraphs(package.xml(target), notes=True), "speaker_notes")
                # Inherited backgrounds/layouts and shape-only diagrams also need
                # pixels. Counts are references, not an interpretation of content.
                media["drawing_shapes"] = sum(
                    local(e) in {"sp", "cxnSp", "grpSp", "graphicFrame"} for e in root.iter()
                )
                media["inherited_graphics_possible"] = any(
                    k in {"slideLayout", "slideMaster"} for k, _ in rels.values()
                )
                if external:
                    page["warnings"].append("External relationships were not fetched.")
                if any(
                    local(e) in {"oMath", "oMathPara", "AlternateContent", "timing"}
                    for e in root.iter()
                ):
                    page["warnings"].append(
                        "Equations, extension content and animation may be omitted; inspect rendered pixels."
                    )
                if page["state"] != "truncated":
                    page["state"] = "extracted" if page["text"].strip() else "no_text"
            except PresentationLimit:
                raise
            except Exception:
                # Preserve earlier facts, but never invent content for a damaged
                # slide. All exception text and package paths stay in the worker.
                page["state"] = "unreadable"
                page["warnings"].append("Slide or related XML could not be read completely.")
            if page["state"] != "extracted":
                coverage = "partial"
            if page["state"] == "truncated":
                page["warnings"].append(
                    "Slide text or provenance budget exhausted; some content is omitted."
                )
            total += len(page["text"]) + separator
            if total > max_text:
                # Empty later slides still get a record, without exceeding the
                # canonical separator budget used by the shared reader.
                break
            pages.append(page)
            if total >= max_text and number < len(paths):
                coverage = "partial"
                break
        if len(pages) != len(paths):
            coverage = "partial"
            warnings.append("Text budget exhausted; remaining slides were not extracted.")
        warnings.extend(
            [
                "Slide numbers follow presentation order, including hidden slides. Text is XML order, not visual reading order.",
                "Speaker notes and stored chart text/values have separate provenance spans; chart caches may be stale.",
                "Images, diagrams, equations, layouts, animations and inherited master text are not interpreted. External links and embedded workbooks are not opened.",
            ]
        )
        return {
            "metadata": metadata,
            "pages": pages,
            "page_count": len(paths),
            "coverage": coverage,
            "warnings": warnings,
            "resource_usage": {"source_bytes": len(data), "zip_read_bytes": package.read_bytes},
        }
