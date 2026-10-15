"""PowerPoint export: slides with a title, bullets and speaker notes."""

import io
import re
from typing import Any, Final

from pptx import Presentation
from pptx.util import Inches

_TITLE_LAYOUT: Final = 0
_CONTENT_LAYOUT: Final = 1
_TITLE_ONLY_LAYOUT: Final = 5
# Characters XML 1.0 cannot hold (lxml refuses them, so the export would fail):
# C0 controls but tab/newline/CR, lone surrogates, U+FFFE and U+FFFF.
_NOT_XML: Final = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufffe\uffff]"
)


def _str(value: Any) -> str:
    """A value as text a .pptx can store: XML-incompatible characters removed."""
    return _NOT_XML.sub("", str(value if value is not None else "")).strip()


def _texts(values: Any) -> list[str]:
    """Non-empty strings of a list (anything else gives an empty list)."""
    if not isinstance(values, list):
        return []
    return [text for text in (_str(v) for v in values) if text]


def _lines(slide: dict[str, Any]) -> list[str]:
    """The body lines of a slide, whatever its layout is."""
    lines = _texts(slide.get("bullets"))
    body = _str(slide.get("body"))
    if body:
        lines.append(body)
    for side in ("left", "right"):
        part = slide.get(side)
        if isinstance(part, dict):
            heading = _str(part.get("heading"))
            if heading:
                lines.append(heading)
            lines += _texts(part.get("bullets"))
    quote = slide.get("quote")
    if isinstance(quote, dict) and quote.get("text"):
        who = _str(quote.get("attribution"))
        lines.append(f"«{_str(quote['text'])}»" + (f" — {who}" if who else ""))
    return lines


def _fill(frame: Any, lines: list[str]) -> None:
    """Put one paragraph per line into a text frame."""
    frame.clear()
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line


def _table(slide: Any, table: dict[str, Any]) -> None:
    """Draw a small table under the title."""
    columns = _texts(table.get("columns"))
    rows = [
        [_str(c) for c in r] for r in table.get("rows") or [] if isinstance(r, list)
    ]
    if not columns:
        return
    shape = slide.shapes.add_table(
        len(rows) + 1, len(columns), Inches(0.6), Inches(1.8), Inches(8.8), Inches(0.4)
    )
    for c, name in enumerate(columns):
        shape.table.cell(0, c).text = name
    for r, row in enumerate(rows, start=1):
        for c in range(len(columns)):
            shape.table.cell(r, c).text = row[c] if c < len(row) else ""


def _add_slide(presentation: Any, slide: dict[str, Any]) -> None:
    """Add one slide; the notes go to the speaker notes."""
    title = _str(slide.get("title"))
    layout = slide.get("layout")
    table = slide.get("table") if isinstance(slide.get("table"), dict) else None
    if table is not None:
        made = presentation.slides.add_slide(
            presentation.slide_layouts[_TITLE_ONLY_LAYOUT]
        )
        made.shapes.title.text = title
        _table(made, table)
    elif layout in ("title", "section") and not _lines(slide)[1:]:
        made = presentation.slides.add_slide(presentation.slide_layouts[_TITLE_LAYOUT])
        made.shapes.title.text = title
        _fill(made.placeholders[1].text_frame, _lines(slide))
    else:
        made = presentation.slides.add_slide(
            presentation.slide_layouts[_CONTENT_LAYOUT]
        )
        made.shapes.title.text = title
        _fill(made.placeholders[1].text_frame, _lines(slide))
    notes = _str(slide.get("notes"))
    if notes:
        made.notes_slide.notes_text_frame.text = notes


def slides_to_pptx(
    title: str, subtitle: str | None, slides: list[dict[str, Any]]
) -> bytes:
    """Return a deck; a title slide is added first unless the deck starts with one."""
    presentation = Presentation()
    if not slides or slides[0].get("layout") != "title":
        head = presentation.slides.add_slide(presentation.slide_layouts[_TITLE_LAYOUT])
        head.shapes.title.text = _str(title)
        head.placeholders[1].text_frame.text = _str(subtitle)
    for slide in slides:
        _add_slide(presentation, slide)
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def deck_to_pptx(content: dict[str, Any]) -> bytes:
    """Export a Studio slide deck (``title``, ``subtitle``, ``slides``).

    Each slide is a dict with ``layout`` (title, agenda, section, bullets,
    two_columns, quote, table, summary), ``title`` and the fields of its layout:
    ``bullets``/``body``, ``left``/``right`` (``heading``, ``bullets``), ``quote``
    (``text``, ``attribution``), ``table`` (``columns``, ``rows``); ``notes`` go to
    the speaker notes. Unknown fields are ignored.
    """
    slides = [s for s in content.get("slides") or [] if isinstance(s, dict)]
    return slides_to_pptx(
        str(content.get("title") or ""), content.get("subtitle") or None, slides
    )


build_pptx = deck_to_pptx
"""The reusable name of the deck builder: ``build_pptx(deck) -> bytes``."""
