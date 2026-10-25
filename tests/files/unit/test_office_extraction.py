"""PPTX and XLSX text: one page per slide or sheet."""

import io
import zipfile

from app.modules.files.infrastructure.extraction.office_text import (
    extract_pptx,
    extract_xlsx,
)


def _zip(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def test_slides_are_pages_with_their_paragraphs() -> None:
    """Slides in number order; runs of a paragraph joined, entities decoded."""
    data = _zip(
        {
            "ppt/slides/slide2.xml": (
                "<p:sld><a:p><a:r><a:t>Second</a:t></a:r></a:p></p:sld>"
            ),
            "ppt/slides/slide1.xml": (
                "<p:sld><a:p><a:r><a:t>Light &amp; </a:t></a:r><a:r><a:t>sugar</a:t>"
                "</a:r></a:p><a:p><a:r><a:t>Chlorophyll</a:t></a:r></a:p></p:sld>"
            ),
        }
    )
    text = extract_pptx(data)
    assert text.text == "Light & sugar\nChlorophyll\nSecond"
    assert (text.pages, text.page_starts) == (2, (0, 26))


def test_sheets_read_shared_inline_and_plain_values() -> None:
    """A row per line with ` | ` between cells."""
    data = _zip(
        {
            "xl/sharedStrings.xml": (
                "<sst><si><t>Leaf</t></si><si><t>Area</t></si></sst>"
            ),
            "xl/worksheets/sheet1.xml": (
                '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
                '<c r="B1" t="s"><v>1</v></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>Oak</t></is></c>'
                '<c r="B2"><v>12.5</v></c></row></sheetData>'
            ),
        }
    )
    assert extract_xlsx(data).text == "Leaf | Area\nOak | 12.5"
