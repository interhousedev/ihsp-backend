"""Word boxes of PDF pages from the text layer."""

from app.modules.files.infrastructure.extraction.pdf_layout import extract_pdf_layouts
from tests.files.helpers import make_pdf


def test_boxes_map_words_to_offsets_and_page_fractions() -> None:
    """Each word gets its offsets in the page text and a box inside the page."""
    text = "Hello brave world"
    layouts = extract_pdf_layouts(make_pdf(text, "Second page"), [text, "Second page"])

    first = layouts[1]
    assert first.source == "text_layer"
    assert [text[b.start : b.end] for b in first.boxes] == ["Hello", "brave", "world"]
    for box in first.boxes:
        assert 0 <= box.x < 1 and 0 <= box.y < 1 and box.w > 0 and box.h > 0
        assert box.x + box.w <= 1 and box.y + box.h <= 1
    assert first.boxes[0].x < first.boxes[1].x < first.boxes[2].x
    assert 2 in layouts


def test_unreadable_pdf_gives_no_layouts() -> None:
    """Garbage in, nothing out."""
    assert extract_pdf_layouts(b"not a pdf", ["text"]) == {}
