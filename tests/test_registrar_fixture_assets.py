"""Fixture integrity only; this does not grade host interpretation."""

import io
from email import policy
from email.parser import BytesParser
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).parent / "fixtures" / "registrar"


def test_original_notice_contains_exact_multi_section_attachment():
    message = BytesParser(policy=policy.default).parsebytes(
        (ROOT / "original-notice.eml").read_bytes()
    )
    assert message["From"].addresses[0].addr_spec == "registrar@university.synthetic.invalid"
    assert message["Subject"] == "Your final exam schedule"
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    data = attachments[0].get_payload(decode=True)
    assert data == (ROOT / "multi-section.pdf").read_bytes()
    pdf = PdfReader(io.BytesIO(data))
    assert len(pdf.pages) == 2
    first, second = (p.extract_text() for p in pdf.pages)
    assert "Row 2: ETH101 | Section 01 | CRN 12345 | Exam" in first
    assert first.count("CRN 12345") == 1
    assert "CRN 99999" in first
    assert "CRN 77777" in second and "CRN 67890" not in first + second
    assert "13:00-15:00 | Room A | America/New_York" in first


def test_inconsistent_year_fixture_keeps_both_years_visible():
    pdf = PdfReader(ROOT / "inconsistent-year-grid.pdf")
    text = pdf.pages[0].extract_text()
    assert "Fall 2026 final assessment schedule" in text
    assert "TABLE HEADING: FALL 2025" in text
    assert "no section-specific allocation" in text
