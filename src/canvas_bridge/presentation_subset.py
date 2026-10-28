"""Build a private single-slide package inside the existing parser sandbox.

Copy dependency bytes verbatim except for freezing dynamic slide-number fields.
Prune presentation lists, relationships and content types; DOM serialization
preserves namespace prefixes used by markup compatibility attributes.
The caller must preflight the entire original package before invoking this.
"""

import posixpath
import zipfile
from urllib.parse import quote, unquote

from defusedxml.minidom import parseString

if __package__:
    from canvas_bridge.document_policy import PPTX_MEMBER_BYTES, PPTX_SOURCE_BYTES, PPTX_XML_BYTES
    from canvas_bridge.presentation_worker import Package, bounded, local
else:
    from document_policy import PPTX_MEMBER_BYTES, PPTX_SOURCE_BYTES, PPTX_XML_BYTES
    from presentation_worker import Package, bounded, local


def relpath(part):
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def rewrite(raw, prune, *, first_slide=None):
    with parseString(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True) as dom:
        for node in list(dom.getElementsByTagName("*")):
            if node.parentNode and prune(node):
                node.parentNode.removeChild(node)
        if first_slide is not None:
            start = int(dom.documentElement.getAttribute("firstSlideNum") or "1")
            if not 1 <= start <= 2_147_483_647 - first_slide:
                raise ValueError("conversion_page_mismatch")
            dom.documentElement.setAttribute("firstSlideNum", str(start + first_slide - 1))
        result = dom.toxml(encoding="utf-8")
    bounded("xml_member_bytes", len(result), PPTX_XML_BYTES)
    return result


def freeze_slide_number(raw, displayed_number):
    """LibreOffice renumbers dynamic fields even with firstSlideNum set.

    Freeze only slide-number fields to text; retain run styling and prefixes.
    Other text, equations, images and shape geometry remain untouched.
    """
    with parseString(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True) as dom:
        fields = [
            e
            for e in dom.getElementsByTagName("*")
            if e.localName == "fld" and e.getAttribute("type").lower() == "slidenum"
        ]
        if not fields:
            return raw
        for field in fields:
            prefix = field.prefix + ":" if field.prefix else ""
            run = dom.createElementNS(field.namespaceURI, prefix + "r")
            for child in list(field.childNodes):
                if child.nodeType == child.ELEMENT_NODE and child.localName == "rPr":
                    run.appendChild(child.cloneNode(deep=True))
            text = dom.createElementNS(field.namespaceURI, prefix + "t")
            text.appendChild(dom.createTextNode(str(displayed_number)))
            run.appendChild(text)
            field.parentNode.replaceChild(run, field)
        result = dom.toxml(encoding="utf-8")
    bounded("xml_member_bytes", len(result), PPTX_XML_BYTES)
    return result


def replace_media_xml(raw, name, replacements):
    """Rewrite only validated internal media targets and their content types."""
    with parseString(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True) as dom:
        if name == "[Content_Types].xml":
            for node in dom.getElementsByTagName("*"):
                old = node.getAttribute("PartName").lstrip("/")
                if node.localName == "Override" and old in replacements:
                    node.setAttribute("PartName", "/" + replacements[old][0])
                    node.setAttribute("ContentType", "image/png")
            # Explicit overrides avoid conflicting or absent extension defaults.
            existing = {n.getAttribute("PartName") for n in dom.getElementsByTagName("*")}
            for new, _ in replacements.values():
                if "/" + new not in existing:
                    node = dom.createElementNS(dom.documentElement.namespaceURI, "Override")
                    node.setAttribute("PartName", "/" + new)
                    node.setAttribute("ContentType", "image/png")
                    dom.documentElement.appendChild(node)
        elif name.endswith(".rels"):
            parent = posixpath.dirname(posixpath.dirname(name))
            for node in dom.getElementsByTagName("*"):
                if (
                    node.localName != "Relationship"
                    or node.getAttribute("TargetMode") == "External"
                ):
                    continue
                target = unquote(node.getAttribute("Target"))
                old = posixpath.normpath(posixpath.join(parent, target)).lstrip("/")
                if old in replacements:
                    node.setAttribute(
                        "Target", quote(posixpath.relpath(replacements[old][0], parent), safe="/")
                    )
        result = dom.toxml(encoding="utf-8")
    bounded("xml_member_bytes", len(result), PPTX_XML_BYTES)
    return result


def single_slide(data, number, output, *, media_replacements=None):
    with Package(data) as package:
        paths = package.slide_paths()
        if not 1 <= number <= len(paths):
            raise ValueError("page_limit_or_range")
        selected = paths[number - 1]
        slide = package.xml(selected)
        hidden = slide.get("show", "1") in {"0", "false"}
        image_references = sum(local(e) == "blip" for e in slide.iter())
        kept, pending = set(), [selected]

        def visit():
            while pending:
                part = pending.pop()
                if part in kept:
                    continue
                # Cross-slide navigation/dependencies cannot quietly import
                # another slide or make the one-page mapping ambiguous.
                if part in paths and part != selected:
                    raise ValueError("conversion_page_mismatch")
                kept.add(part)
                relations, _ = package.relations(part)
                if relpath(part) in package.names:
                    kept.add(relpath(part))
                pending.extend(target for _, target in relations.values())

        visit()  # selected slide -> layout -> master -> theme/media/notes
        presentation = "ppt/presentation.xml"
        relations, _ = package.relations(presentation)
        allowed_ids = {
            rid
            for rid, (kind, target) in relations.items()
            if (
                target == selected
                if kind == "slide"
                else target in kept
                if kind in {"slideMaster", "notesMaster", "handoutMaster"}
                else True
            )
        }
        kept.update({presentation, relpath(presentation), "[Content_Types].xml"})
        pending.extend(target for rid, (_, target) in relations.items() if rid in allowed_ids)
        roots, _ = package.relations("")
        if [target for kind, target in roots.values() if kind == "officeDocument"] != [
            presentation
        ]:
            raise ValueError("conversion_page_mismatch")
        kept.add("_rels/.rels")
        pending.extend(target for _, target in roots.values())
        visit()

        def prune_presentation(node):
            if node.localName in {"custShowLst", "sectionLst"}:
                return True
            if node.localName in {"sldId", "sldMasterId", "notesMasterId", "handoutMasterId"}:
                ids = [
                    a.value
                    for a in node.attributes.values()
                    if a.localName == "id" and a.namespaceURI
                ]
                return len(ids) != 1 or ids[0] not in allowed_ids
            return False

        changes = {
            presentation: rewrite(
                package.read(presentation), prune_presentation, first_slide=number
            ),
            relpath(presentation): rewrite(
                package.read(relpath(presentation)),
                lambda n: n.localName == "Relationship" and n.getAttribute("Id") not in allowed_ids,
            ),
            "[Content_Types].xml": rewrite(
                package.read("[Content_Types].xml"),
                lambda n: (
                    n.localName == "Override" and n.getAttribute("PartName").lstrip("/") not in kept
                ),
            ),
        }
        displayed_number = int(package.xml(presentation).get("firstSlideNum", "1")) + number - 1
        replacements = {
            name: value for name, value in (media_replacements or {}).items() if name in kept
        }
        for old, (new, raw) in replacements.items():
            # The only supported rewrite is same-directory EMF -> canonical PNG.
            if (
                new != old + ".png"
                or new.casefold() in {n.casefold() for n in package.names}
                or not raw.startswith(b"\x89PNG\r\n\x1a\n")
            ):
                raise ValueError("unsupported_slide_media")
            bounded("media_member_bytes", len(raw), PPTX_MEMBER_BYTES)
        # Stored members avoid creating a compression bomb from reserialized XML.
        # Original source/member/expansion limits still apply, including output.
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as target:
            for name in sorted(kept):
                raw = changes[name] if name in changes else package.read(name, PPTX_MEMBER_BYTES)
                if name in replacements:
                    name, raw = replacements[name]
                elif replacements and (name.endswith(".rels") or name == "[Content_Types].xml"):
                    raw = replace_media_xml(raw, name, replacements)
                if name.endswith(".xml") and name.startswith(
                    ("ppt/slides/", "ppt/slideLayouts/", "ppt/slideMasters/")
                ):
                    raw = freeze_slide_number(raw, displayed_number)
                target.writestr(name, raw)
                bounded("subset_source_bytes", target.fp.tell(), PPTX_SOURCE_BYTES)
        bounded("subset_source_bytes", output.stat().st_size, PPTX_SOURCE_BYTES)
        return {
            "source_slide_count": len(paths),
            "selected_slide": number,
            "hidden": hidden,
            "subset_bytes": output.stat().st_size,
            "subset_members": len(kept),
            "source_slide_image_references": image_references,
            "normalized_emf_bitmaps": len(replacements),
        }
