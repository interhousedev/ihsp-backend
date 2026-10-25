"""Demo files built in code: small, and they read back as what they claim to be."""

import io
import struct

from app.bootstrap.seed.demo_files import DEMO_FILES

from docx import Document
from pypdf import PdfReader


def test_every_demo_file_is_under_100_kb_and_built_the_same_twice() -> None:
    """The seed stores the same bytes on every run."""
    for name, build in DEMO_FILES.items():
        data = build()
        assert 0 < len(data) < 100 * 1024, name
        assert build() == data, name


def test_worksheet_pdf_is_one_readable_page() -> None:
    """A valid PDF with the title and the tasks on its only page."""
    data = DEMO_FILES["derivatives-worksheet.pdf"]()

    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1
    assert "derivatives" in reader.pages[0].extract_text().lower()


def test_circuit_png_is_an_rgb_picture_of_the_stated_size() -> None:
    """An 8-bit RGB PNG, 320 x 200."""
    data = DEMO_FILES["ohm-circuit.png"]()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (320, 200)
    assert (data[24], data[25]) == (8, 2)  # bit depth, colour type RGB
    assert data.endswith(b"IEND\xaeB`\x82")


def test_history_docx_opens_with_its_heading_and_tasks() -> None:
    """A Word file: the heading first, then the numbered tasks."""
    document = Document(io.BytesIO(DEMO_FILES["history-plan.docx"]()))

    texts = [paragraph.text for paragraph in document.paragraphs]
    assert texts[0] == "Tarix: Amir Temur davlati (reja)"
    assert any("Samarqand" in text for text in texts)


def test_unit6_notes_are_utf8_text() -> None:
    """Plain text notes, readable as UTF-8."""
    text = DEMO_FILES["unit6-notes.txt"]().decode("utf-8")

    assert text.startswith("Unit 6 notes")
    assert "curriculum" in text
