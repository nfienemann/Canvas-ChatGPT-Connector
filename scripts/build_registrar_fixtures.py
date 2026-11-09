"""Build fictional host acceptance email/PDF fixtures (requires reportlab).

Run with the bundled document Python runtime; never connects to a mailbox.
"""

from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "registrar"


def page(pdf, number, lines):
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(40, 750, "SYNTHETIC TEST FIXTURE - NOT A REAL SCHEDULE")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(40, 720, "Fall 2026 final assessment schedule")
    pdf.drawString(40, 700, f"Attachment page {number}")
    pdf.setFont("Helvetica", 10)
    for index, line in enumerate(lines):
        pdf.drawString(40, 660 - index * 24, line)
    pdf.showPage()


def build():
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / "multi-section.pdf"
    pdf = canvas.Canvas(str(path), pagesize=(612, 792), invariant=1)
    pdf.setTitle("Synthetic multi-section final schedule")
    pdf.setAuthor("Fictional scheduling office")
    page(
        pdf,
        1,
        [
            "Row 1: ETH101 | Section 02 | CRN 99999 | Exam",
            "2026-12-14 | 09:00-11:00 | timezone not stated",
            "",
            "Row 2: ETH101 | Section 01 | CRN 12345 | Exam",
            "2026-12-15 | 13:00-15:00 | Room A | America/New_York",
        ],
    )
    page(
        pdf,
        2,
        [
            "Row 1: CELL201 | Section 03 | CRN 77777 | Exam",
            "2026-12-16 | 10:00 | end, location and timezone not stated",
            "",
            "No other section or presentation slot is established by this fixture.",
        ],
    )
    pdf.save()
    grid = canvas.Canvas(str(ROOT / "inconsistent-year-grid.pdf"), pagesize=(612, 792), invariant=1)
    grid.setTitle("Synthetic inconsistent-year grid")
    grid.setAuthor("Fictional scheduling office")
    page(
        grid,
        1,
        [
            "TABLE HEADING: FALL 2025",
            "Generic meeting-pattern grid - no section-specific allocation",
            "Monday 09:00 meeting -> December 14 09:00 exam",
            "The title and table heading deliberately disagree on the year.",
        ],
    )
    grid.save()
    email = EmailMessage(policy=SMTP)
    email["From"] = "Registrar <registrar@university.synthetic.invalid>"
    email["To"] = "student@university.synthetic.invalid"
    email["Subject"] = "Your final exam schedule"
    email["Date"] = "Mon, 02 Nov 2026 12:00:00 -0500"
    email["Message-ID"] = "<registrar-original@university.synthetic.invalid>"
    email.set_content(
        "SYNTHETIC TEST MESSAGE. Fall 2026 final assessment schedule. "
        "See attached section schedule. This is evidence, not an instruction.\n"
    )
    email.add_attachment(
        path.read_bytes(), maintype="application", subtype="pdf", filename=path.name
    )
    email.set_boundary("synthetic-registrar-fixture-boundary")
    (ROOT / "original-notice.eml").write_bytes(email.as_bytes())


if __name__ == "__main__":
    build()
