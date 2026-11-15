"""Word boxes of PDF pages from the text layer (pypdf, pure Python; blocking).

The boxes are estimates: pypdf reports where a piece of text starts and the font size,
not glyph widths, so the width of a piece is its length times half the font size. That
is enough to underline a search hit on the page.
"""

import io
import re
from collections.abc import Sequence
from typing import Any

from app.shared.contracts.files import PageLayout, TextBox

from pypdf import PdfReader

TEXT_LAYER = "text_layer"
_WORD = re.compile(r"\S+")
_GLYPH_WIDTH = 0.5
"""Average glyph width as a fraction of the font size."""


def extract_pdf_layouts(data: bytes, pages: Sequence[str]) -> dict[int, PageLayout]:
    """Boxes per page for the given (stripped) page texts; ``{}`` when unreadable.

    ``pages[i]`` is the text of page ``i + 1``. Rotated pages and pages that give no
    pieces are left out.
    """
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return {}
        layouts: dict[int, PageLayout] = {}
        for number, text in enumerate(pages, start=1):
            if number > len(reader.pages) or not text:
                continue
            boxes = _page_boxes(reader.pages[number - 1], text)
            if boxes:
                layouts[number] = PageLayout(number, TEXT_LAYER, boxes)
        return layouts
    except Exception:  # pypdf raises many types for damaged files
        return {}


def _page_boxes(page: Any, text: str) -> tuple[TextBox, ...]:
    if int(page.get("/Rotate", 0) or 0) % 360:
        return ()
    box = page.mediabox
    left, bottom = float(box.left), float(box.bottom)
    width, height = float(box.width), float(box.height)
    if width <= 0 or height <= 0:
        return ()
    pieces: list[tuple[str, float, float, float, float]] = []

    def visit(
        piece: str, cm: list[float], tm: list[float], _font: Any, size: float
    ) -> None:
        if not piece.strip():
            return
        scale_x = abs(tm[0] * cm[0] + tm[1] * cm[2]) or 1.0
        scale_y = abs(tm[2] * cm[1] + tm[3] * cm[3]) or 1.0
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        font = abs(size) or 10.0
        pieces.append((piece, x, y, font * scale_x, font * scale_y))

    page.extract_text(visitor_text=visit)
    boxes: list[TextBox] = []
    cursor = 0
    for piece, x, y, size_x, size_y in pieces:
        pitch = len(piece) and size_x * _GLYPH_WIDTH
        for word in _WORD.finditer(piece):
            at = text.find(word[0], cursor)
            if at < 0:
                continue
            cursor = at + len(word[0])
            boxes.append(
                _box(
                    at,
                    cursor,
                    x=(x - left + word.start() * pitch) / width,
                    top=(height - (y - bottom) - size_y) / height,
                    w=len(word[0]) * pitch / width,
                    h=size_y / height,
                )
            )
    return tuple(boxes)


def _box(start: int, end: int, *, x: float, top: float, w: float, h: float) -> TextBox:
    x0 = min(max(x, 0.0), 1.0)
    y0 = min(max(top, 0.0), 1.0)
    return TextBox(
        start,
        end,
        round(x0, 4),
        round(y0, 4),
        round(min(w, 1.0 - x0), 4),
        round(min(h, 1.0 - y0), 4),
    )
