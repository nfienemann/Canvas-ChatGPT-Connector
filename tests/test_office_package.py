"""Shared DOCX/XLSX container proofs; all contents are synthetic."""

import io
import stat
import struct
import zipfile

import pytest
from defusedxml.common import DTDForbidden

from canvas_bridge.office_package import OFFICE_FORMATS, OfficePackage
from canvas_bridge.parser_sandbox import validate_result
from canvas_bridge.parser_worker import extract
from tests.test_academic_intelligence import office_manifest, ooxml


def workbook():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        office_manifest(archive, "xlsx")
        archive.writestr(
            "xl/workbook.xml", '<workbook><sheets><sheet name="Analysis"/></sheets></workbook>'
        )
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet><sheetData/></worksheet>")
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rSheet" Type="urn:relationship/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
    return stream.getvalue()


def revised(data, updates=None, additions=None, remove=()):
    stream = io.BytesIO()
    updates = updates or {}
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(stream, "w") as target:
        for entry in source.infolist():
            if entry.filename not in remove:
                target.writestr(entry, updates.get(entry.filename, source.read(entry)))
        for name, content in additions or []:
            target.writestr(name, content)
    return stream.getvalue()


@pytest.mark.parametrize("kind", ["docx", "pptx", "xlsx"])
def test_registry_validates_actual_package_not_extension(kind):
    data = workbook() if kind == "xlsx" else ooxml(kind)
    with OfficePackage(data, kind) as package:
        assert package.format == OFFICE_FORMATS[kind]
        assert package.xml(package.format.main_part) is not None
    for other in OFFICE_FORMATS:
        if other != kind:
            with pytest.raises(ValueError, match="office_type_mismatch"):
                OfficePackage(data, other)


@pytest.mark.parametrize(
    "name",
    [
        "../outside.xml",
        "/absolute.xml",
        "word/../../outside.xml",
        "word//a.xml",
        "word/./a.xml",
        "word\\evil.xml",
        "C:/evil.xml",
        "word/%2e%2e/a.xml",
        "word/a.xml:stream",
    ],
)
def test_noncanonical_member_names_fail_closed(name):
    # ZipInfo normalizes backslashes when *writing* on Windows. Mutate both ZIP
    # filename records afterwards so the reader sees the hostile source bytes.
    data = revised(ooxml("docx"), additions=[(name.replace("\\", "/"), "x")])
    if "\\" in name:
        data = data.replace(name.replace("\\", "/").encode(), name.encode())
    with pytest.raises(ValueError, match="invalid_office_archive"):
        OfficePackage(data, "docx")


@pytest.mark.parametrize("kind", ["docx", "xlsx"])
def test_duplicate_names_symlinks_and_active_content(kind):
    data = workbook() if kind == "xlsx" else ooxml(kind)
    main = OFFICE_FORMATS[kind].main_part
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = revised(data, additions=[(main, "<x/>")])
    link = zipfile.ZipInfo("symlink.xml")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    for bad in [
        duplicate,
        revised(data, additions=[(main.upper(), "<x/>")]),
        revised(data, additions=[(link, "outside")]),
    ]:
        with pytest.raises(ValueError, match="invalid_office_archive"):
            OfficePackage(bad, kind)
    for name in ["word/vbaProject.bin", "xl/embeddings/object.bin"]:
        with pytest.raises(ValueError, match="active_office_content"):
            OfficePackage(revised(data, additions=[(name, "x")]), kind)


@pytest.mark.parametrize("kind", ["docx", "xlsx"])
def test_required_manifest_signature_and_macro_content_types(kind):
    data = workbook() if kind == "xlsx" else ooxml(kind)
    with pytest.raises(ValueError, match="office_type_mismatch"):
        OfficePackage(revised(data, remove=["[Content_Types].xml"]), kind)
    with pytest.raises(ValueError, match="invalid_office_archive"):
        OfficePackage(b"not a ZIP archive", kind)
    with pytest.raises(ValueError, match="encrypted_or_legacy_office"):
        OfficePackage(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"unknown legacy content", kind)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        types = archive.read("[Content_Types].xml")
    bad = types.replace(
        OFFICE_FORMATS[kind].main_content_type.encode(),
        b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    )
    with pytest.raises(ValueError, match="active_office_content"):
        OfficePackage(revised(data, {"[Content_Types].xml": bad}), kind)


def test_zip_limits_encryption_and_crc():
    data = ooxml("docx")
    bomb = io.BytesIO(data)
    with zipfile.ZipFile(bomb, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/bomb.xml", "x" * 1_000_000)
    too_many = revised(data, additions=[(f"parts/{i}.xml", "x") for i in range(1001)])
    for bad in [bomb.getvalue(), too_many, b"X" * 10_000_001]:
        with pytest.raises(ValueError, match="office_resource_limit"):
            OfficePackage(bad, "docx")
    encrypted = bytearray(data)
    central = encrypted.index(b"PK\x01\x02")
    struct.pack_into("<H", encrypted, central + 8, 1)
    with pytest.raises(ValueError, match="encrypted_office"):
        OfficePackage(bytes(encrypted), "docx")
    damaged = bytearray(workbook())
    at = damaged.index(b"<workbook>")
    damaged[at] = ord("!")
    with OfficePackage(bytes(damaged), "xlsx") as package, pytest.raises(zipfile.BadZipFile):
        package.xml("xl/workbook.xml")


@pytest.mark.parametrize(
    "target",
    [
        "../../outside.xml",
        "../../../xl/worksheets/sheet1.xml",
        "https://private.invalid/x",
        "//private.invalid/x",
        "file:///private",
        "worksheets\\sheet1.xml",
        "%2f%2fprivate.invalid/x",
        "worksheets/sheet1.xml?token=secret",
        "worksheets/sheet1.xml#fragment",
        "worksheets/missing.xml",
    ],
)
def test_unsafe_or_missing_relationships_are_not_followed(target):
    xml = f'<Relationships><Relationship Id="rSheet" Type="urn:x/worksheet" Target="{target}"/></Relationships>'
    data = revised(workbook(), {"xl/_rels/workbook.xml.rels": xml})
    with (
        OfficePackage(data, "xlsx") as package,
        pytest.raises(ValueError, match="invalid_office_reference"),
    ):
        package.related_part("xl/workbook.xml", "rSheet", "worksheet")


def test_relationships_resolve_locally_and_reject_external_or_duplicate_ids():
    # Absolute package references and ordinary parent-relative references are valid.
    for target in [
        "worksheets/sheet1.xml",
        "/xl/worksheets/sheet1.xml",
        "../xl/worksheets/sheet1.xml",
    ]:
        relation = f'<Relationship Id="rSheet" Type="urn:x/worksheet" Target="{target}"/>'
        data = revised(
            workbook(), {"xl/_rels/workbook.xml.rels": f"<Relationships>{relation}</Relationships>"}
        )
        with OfficePackage(data, "xlsx") as package:
            assert (
                package.related_part("xl/workbook.xml", "rSheet", "worksheet")
                == "xl/worksheets/sheet1.xml"
            )
        for bad in [
            relation + relation,
            relation.replace("Target=", 'TargetMode="External" Target='),
        ]:
            data = revised(
                workbook(), {"xl/_rels/workbook.xml.rels": f"<Relationships>{bad}</Relationships>"}
            )
            with (
                OfficePackage(data, "xlsx") as package,
                pytest.raises(ValueError, match="invalid_office_reference"),
            ):
                package.related_part("xl/workbook.xml", "rSheet", "worksheet")


@pytest.mark.parametrize("member", ["[Content_Types].xml", "_rels/.rels", "word/document.xml"])
def test_xml_entities_never_resolve(member):
    malicious = '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///secret">]><x>&secret;</x>'
    data = revised(ooxml("docx"), {member: malicious})
    with pytest.raises(DTDForbidden), OfficePackage(data, "docx") as package:
        package.xml(member)


def test_errors_are_sanitized_and_existing_source_locators_are_preserved():
    from canvas_bridge.domain import DomainError

    with pytest.raises(DomainError, match="office_type_mismatch"):
        validate_result({"ok": False, "reason": "office_type_mismatch"}, b"")
    with pytest.raises(DomainError) as error:
        validate_result(
            {"ok": False, "reason": "private content https://signed.invalid/secret"}, b""
        )
    assert "secret" not in str(error.value)
    for kind, locator in [("docx", "section"), ("pptx", "slide")]:
        result = extract(ooxml(kind), kind)
        assert result["pages"][0]["locator_kind"] == locator
        assert result["coverage"] == "text_only"
        assert extract(ooxml(kind), kind) == result
