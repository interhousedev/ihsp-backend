"""Word boxes of recognised (OCR) pages as they are kept in a file's metadata (JSON).

An OCR step stores ``metadata["text_source"] = "ocr"`` and
``metadata["page_boxes"] = {"<page>": [[start, end, x, y, w, h], ...]}``: offsets into
the stripped text of the page, the rest fractions of the page from its top left.
"""

from typing import Any

from app.shared.contracts.files import PageLayout, TextBox

TEXT_SOURCE_KEY = "text_source"
BOXES_KEY = "page_boxes"
OCR = "ocr"


def is_ocr(metadata: dict[str, Any]) -> bool:
    """True when the text of the file was recognised from images."""
    return metadata.get(TEXT_SOURCE_KEY) == OCR


def layouts_from_metadata(raw: object) -> dict[int, PageLayout]:
    """The usable pages of stored OCR boxes; malformed rows are skipped."""
    if not isinstance(raw, dict):
        return {}
    layouts: dict[int, PageLayout] = {}
    for key, rows in raw.items():
        if not (isinstance(key, str) and key.isdigit() and isinstance(rows, list)):
            continue
        boxes = tuple(box for row in rows if (box := _box(row)) is not None)
        if boxes:
            layouts[int(key)] = PageLayout(int(key), OCR, boxes)
    return layouts


def _box(row: object) -> TextBox | None:
    if not (isinstance(row, list) and len(row) == 6):
        return None
    start, end, x, y, w, h = row
    if not all(isinstance(v, int | float) for v in row):
        return None
    if int(start) < 0 or int(end) <= int(start):
        return None
    return TextBox(int(start), int(end), float(x), float(y), float(w), float(h))
