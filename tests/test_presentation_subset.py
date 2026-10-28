"""Only fictional slide data; no native converter required for package checks."""

import io
import zipfile
from pathlib import Path

import pytest

from canvas_bridge.presentation_subset import freeze_slide_number, single_slide
from canvas_bridge.presentation_worker import Package


def fixture_bytes():
    return Path("tests/fixtures/synthetic_visual_slides.pptx").read_bytes()


def changed(data, part, change):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(out, "w") as target:
        for name in original.namelist():
            raw = original.read(name)
            target.writestr(name, change(raw) if name == part else raw)
    return out.getvalue()


@pytest.mark.parametrize("number", [1, 2, 3])
def test_subset_preserves_only_selected_slide_and_dependency_bytes(tmp_path, number):
    source = fixture_bytes()
    before = bytes(source)
    output = tmp_path / "one.pptx"
    metadata = single_slide(source, number, output)
    assert source == before
    assert metadata["source_slide_count"] == 3
    assert metadata["selected_slide"] == number
    assert metadata["hidden"] == (number == 3)
    with Package(source) as original, Package(output.read_bytes()) as subset:
        expected = original.slide_paths()[number - 1]
        assert subset.slide_paths() == [expected]
        for path in original.slide_paths():
            assert (path in subset.names) == (path == expected)
        assert subset.read(expected) == original.read(expected)
        assert subset.xml("ppt/presentation.xml").get("firstSlideNum") == str(number)
        for name in subset.names:
            if name.endswith(".rels"):
                # All copied relationships resolve; no dangling media/layouts.
                from canvas_bridge.presentation_subset import relpath

                parts = [p for p in subset.names | {""} if relpath(p) == name]
                assert len(parts) == 1
                subset.relations(parts[0])
            if name.startswith(
                ("ppt/media/", "ppt/slideMasters/", "ppt/slideLayouts/", "ppt/theme/")
            ):
                expected_bytes = original.read(name, 32 * 1024 * 1024)
                if name.endswith(".xml") and name.startswith(
                    ("ppt/slideMasters/", "ppt/slideLayouts/")
                ):
                    expected_bytes = freeze_slide_number(expected_bytes, number)
                assert subset.read(name, 32 * 1024 * 1024) == expected_bytes
        if number == 2:
            assert metadata["source_slide_image_references"] > 0
            assert any(p.startswith("ppt/media/") for p in subset.names)


def test_reordered_slide_uses_presentation_order_and_preserves_hidden_boolean(tmp_path):
    # Use the actual fixture relationship IDs without relying on filename order.
    from defusedxml.minidom import parseString

    def reorder(raw):
        with parseString(raw) as dom:
            slides = [e for e in dom.getElementsByTagName("*") if e.localName == "sldId"]
            parent = slides[0].parentNode
            parent.insertBefore(slides[-1], slides[0])
            return dom.toxml(encoding="utf-8")

    source = changed(fixture_bytes(), "ppt/presentation.xml", reorder)
    source = changed(
        source, "ppt/slides/slide3.xml", lambda raw: raw.replace(b'show="0"', b'show="false"')
    )
    output = tmp_path / "hidden.pptx"
    result = single_slide(source, 1, output)
    assert result["hidden"]
    with Package(output.read_bytes()) as subset:
        assert subset.slide_paths() == ["ppt/slides/slide3.xml"]


def test_absent_slide_never_creates_native_input(tmp_path):
    output = tmp_path / "absent.pptx"
    with pytest.raises(ValueError, match="page_limit_or_range"):
        single_slide(fixture_bytes(), 4, output)
    assert not output.exists()


def test_cross_slide_relationship_rejects_ambiguous_mapping(tmp_path):
    def cross_link(raw):
        return raw.replace(
            b"</Relationships>",
            b'<Relationship Id="cross" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slide1.xml"/></Relationships>',
        )

    source = changed(fixture_bytes(), "ppt/slides/_rels/slide2.xml.rels", cross_link)
    with Package(source) as package:
        assert any(
            kind == "slide" for kind, _ in package.relations("ppt/slides/slide2.xml")[0].values()
        )
    with pytest.raises(ValueError, match="conversion_page_mismatch"):
        single_slide(source, 2, tmp_path / "cross.pptx")


def numbered_hidden_slide(data):
    shape = b"""<p:sp><p:nvSpPr><p:cNvPr id="987" name="Original number"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="90000" y="90000"/><a:ext cx="900000" cy="900000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:fld id="{00000000-0000-0000-0000-000000000001}" type="slidenum"><a:rPr lang="en-US" sz="2400"/><a:t>3</a:t></a:fld></a:p></p:txBody></p:sp>"""
    return changed(
        data,
        "ppt/slides/slide3.xml",
        lambda raw: raw.replace(b"</p:spTree>", shape + b"</p:spTree>"),
    )


def test_number_fields_freeze_with_style_and_namespace_prefixes(tmp_path):
    source = numbered_hidden_slide(fixture_bytes())
    output = tmp_path / "numbered.pptx"
    single_slide(source, 3, output)
    with Package(output.read_bytes()) as subset:
        xml = subset.read("ppt/slides/slide3.xml")
        assert b'type="slidenum"' not in xml
        assert b"<a:t>3</a:t>" in xml and b'sz="2400"' in xml
    raw = b'<a:p xmlns:a="urn:drawing" xmlns:mc="urn:compatibility" xmlns:x="urn:extra" mc:Ignorable="x"><a:fld type="slidenum"><a:t>1</a:t></a:fld></a:p>'
    frozen = freeze_slide_number(raw, 14)
    assert b'xmlns:x="urn:extra"' in frozen and b'mc:Ignorable="x"' in frozen
    assert b"<a:t>14</a:t>" in frozen
