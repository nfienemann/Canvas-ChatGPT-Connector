"""Synthetic visual ground truth. No real papers or academic records."""

import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from tests.test_file_reading import scientific_pdf


def visual_pdf():
    writer = PdfWriter()
    writer.append(io.BytesIO(scientific_pdf(["placeholder"] * 4)))
    streams = [
        b"""
BT /F1 18 Tf 40 735 Td (Synthetic scientific reading) Tj ET
BT /F1 12 Tf 40 690 Td (The results in Figure 2 are discussed on this page.) Tj ET
BT /F1 12 Tf 40 665 Td (This reference does not locate the graph. See page 4.) Tj ET
""",
        b"""
q .9 .9 .9 rg 40 400 532 310 re f Q
0 0 0 RG 40 640 m 572 640 l S 40 470 m 572 470 l S
BT /F1 16 Tf 50 680 Td (Table 1. Synthetic review counts) Tj ET
BT /F1 12 Tf 50 655 Td (Database) Tj ET
BT /F1 12 Tf 230 655 Td (Search results) Tj ET
BT /F1 12 Tf 390 655 Td (Relevant articles) Tj ET
BT /F1 12 Tf 50 610 Td (PubMed) Tj ET
BT /F1 12 Tf 240 610 Td (224) Tj ET
BT /F1 12 Tf 460 610 Td (122) Tj ET
BT /F1 12 Tf 50 565 Td (Database B) Tj ET
BT /F1 12 Tf 240 565 Td (619) Tj ET
BT /F1 12 Tf 50 520 Td (Database C) Tj ET
BT /F1 12 Tf 240 520 Td (37) Tj ET
BT /F1 12 Tf 50 445 Td (After combining databases and removing exclusions,) Tj ET
BT /F1 12 Tf 50 425 Td (122 articles remained in the final review.) Tj ET
BT /F1 12 Tf 40 340 Td (Left column begins here.) Tj ET
BT /F1 12 Tf 320 340 Td (Right column starts separately.) Tj ET
BT /F1 12 Tf 40 310 Td (Left column continues here.) Tj ET
BT /F1 12 Tf 320 310 Td (Right column continues here.) Tj ET
""",
        b"""
BT /F1 18 Tf 40 735 Td (Synthetic discussion: prose only) Tj ET
BT /F1 12 Tf 40 680 Td (This page explains ethical questions.) Tj ET
BT /F1 12 Tf 320 680 Td (The second column continues.) Tj ET
BT /F1 12 Tf 40 650 Td (It contains ordinary paragraphs.) Tj ET
BT /F1 12 Tf 320 650 Td (No data visualization is drawn.) Tj ET
""",
        b"""
BT /F1 18 Tf 40 745 Td (Figure 2. Synthetic dose response) Tj ET
BT /F1 12 Tf 40 720 Td (Panel A: Treated response increases with dose.) Tj ET
BT /F1 12 Tf 40 700 Td (Error bars are shown; their definition is unspecified.) Tj ET
BT /F1 16 Tf 70 665 Td (A) Tj ET
BT /F1 16 Tf 360 665 Td (B) Tj ET
0 0 0 RG 80 400 m 80 620 l S 80 400 m 290 400 l S
350 400 m 350 620 l S 350 400 m 550 400 l S
BT /F1 12 Tf 110 350 Td (Dose [mg/L]) Tj ET
BT /F1 12 Tf 380 350 Td (Time [h]) Tj ET
BT /F1 12 Tf 1 0 0 1 42 630 Tm (Response [%]) Tj ET
BT /F1 12 Tf 330 630 Td (Count) Tj ET
BT /F1 11 Tf 70 383 Td (0) Tj ET
BT /F1 11 Tf 167 383 Td (5) Tj ET
BT /F1 11 Tf 272 383 Td (10) Tj ET
BT /F1 11 Tf 55 395 Td (0) Tj ET
BT /F1 11 Tf 50 495 Td (50) Tj ET
BT /F1 11 Tf 45 595 Td (100) Tj ET
0 .25 .9 RG 3 w 90 430 m 180 490 l 280 570 l S
.9 .15 .1 RG 90 440 m 180 445 l 280 448 l S
0 0 0 RG 1 w 180 478 m 180 502 l S 174 478 m 186 478 l S 174 502 m 186 502 l S
BT /F1 12 Tf 115 330 Td (Blue: Treated) Tj ET
BT /F1 12 Tf 115 310 Td (Red: Control) Tj ET
BT /F1 12 Tf 235 600 Td (p = 0.03) Tj ET
q .4 .4 .4 rg 380 400 35 80 re f 440 400 35 120 re f 500 400 35 160 re f Q
q 1 .5 0 rg 500 300 m 520 280 l 500 260 l 480 280 l h f Q
""",
    ]
    for page, commands in zip(writer.pages, streams, strict=True):
        stream = DecodedStreamObject()
        stream.set_data(commands)
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
