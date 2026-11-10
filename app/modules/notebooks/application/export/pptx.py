"""PowerPoint export: slides with a title, bullets and speaker notes."""

import io
import re
from collections.abc import Mapping
from typing import Any, Final

from pptx import Presentation
from pptx.util import Inches, Pt

_TITLE_LAYOUT: Final = 0
_CONTENT_LAYOUT: Final = 1
_TITLE_ONLY_LAYOUT: Final = 5
_IMAGE_LAYOUTS: Final = frozenset({"image_left", "image_right", "full_image"})
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


def _image_bytes(slide: dict[str, Any], images: Mapping[str, bytes]) -> bytes | None:
    """The stored picture of an image slide, when it is among the loaded ones."""
    image = slide.get("image")
    if not isinstance(image, dict):
        return None
    return images.get(str(image.get("file_id")))


def _credit(slide: dict[str, Any]) -> str:
    """``alt — Author, License (source)``: the caption and the speaker-note line."""
    image = slide.get("image")
    if not isinstance(image, dict):
        return ""
    credit = _str(image.get("attribution"))
    source = _str(image.get("source_url"))
    parts = [_str(image.get("alt")), credit]
    text = " — ".join(part for part in parts if part)
    return f"{text} ({source})" if source and text else text or source


def _textbox(
    slide: Any,
    lines: list[str],
    box: tuple[float, float, float, float],
    *,
    size: int,
    bold: bool = False,
) -> None:
    """A text box at (left, top, width, height) inches, one paragraph per line."""
    frame = slide.shapes.add_textbox(*(Inches(v) for v in box)).text_frame
    frame.word_wrap = True
    _fill(frame, lines)
    for paragraph in frame.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(size)
            run.font.bold = bold


def _picture(slide: Any, data: bytes, box: tuple[float, float, float, float]) -> bool:
    """Fit the picture into the box (keeps the ratio, centred); False if unreadable."""
    left, top, width, height = (Inches(v) for v in box)
    try:
        shape = slide.shapes.add_picture(io.BytesIO(data), left, top)
    except Exception:  # noqa: BLE001 - an unreadable picture must not fail the export
        return False
    ratio = min(width / shape.width, height / shape.height)
    shape.width, shape.height = int(shape.width * ratio), int(shape.height * ratio)
    shape.left = left + int((width - shape.width) / 2)
    shape.top = top + int((height - shape.height) / 2)
    return True


def _image_slide(
    presentation: Any, slide: dict[str, Any], data: bytes, layout: str
) -> Any:
    """image_left / image_right / full_image; an unreadable picture is left out."""
    made = presentation.slides.add_slide(presentation.slide_layouts[_TITLE_ONLY_LAYOUT])
    title = _str(slide.get("title"))
    credit = _credit(slide)
    if layout == "full_image":
        _picture(made, data, (0, 0, 10, 7.5))
        made.shapes.title.text = title
        made.shapes.title.top, made.shapes.title.height = Inches(0.2), Inches(1.0)
        if credit:
            _textbox(made, [credit], (0.3, 7.0, 9.4, 0.4), size=10)
        return made
    made.shapes.title.text = title
    left = layout == "image_left"
    picture_box = (0.5 if left else 5.3, 1.8, 4.2, 4.4)
    text_box = (5.0 if left else 0.5, 1.8, 4.5 if left else 4.6, 4.4)
    _picture(made, data, picture_box)
    _textbox(made, _lines(slide), text_box, size=18)
    if credit:
        _textbox(made, [credit], (picture_box[0], 6.3, picture_box[2], 0.8), size=10)
    return made


def _stats_slide(presentation: Any, slide: dict[str, Any]) -> Any:
    """Big numbers side by side, each with its label."""
    made = presentation.slides.add_slide(presentation.slide_layouts[_TITLE_ONLY_LAYOUT])
    made.shapes.title.text = _str(slide.get("title"))
    stats = [s for s in slide.get("stats") or [] if isinstance(s, dict)]
    width = 9.0 / max(len(stats), 1)
    for index, stat in enumerate(stats):
        left = 0.5 + index * width
        _textbox(
            made, [_str(stat.get("value"))], (left, 2.4, width, 1.2), size=44, bold=True
        )
        _textbox(made, [_str(stat.get("label"))], (left, 3.7, width, 1.5), size=18)
    return made


def _timeline_slide(presentation: Any, slide: dict[str, Any]) -> Any:
    """The steps top to bottom: the label in bold, then the text."""
    made = presentation.slides.add_slide(presentation.slide_layouts[_TITLE_ONLY_LAYOUT])
    made.shapes.title.text = _str(slide.get("title"))
    steps = [s for s in slide.get("timeline") or [] if isinstance(s, dict)]
    height = 5.2 / max(len(steps), 1)
    for index, step in enumerate(steps):
        top = 1.8 + index * height
        _textbox(
            made, [_str(step.get("label"))], (0.5, top, 2.2, height), size=18, bold=True
        )
        _textbox(made, [_str(step.get("text"))], (2.9, top, 6.6, height), size=16)
    return made


def _comparison_slide(presentation: Any, slide: dict[str, Any]) -> Any:
    """Two columns, each with a bold heading and its points."""
    made = presentation.slides.add_slide(presentation.slide_layouts[_TITLE_ONLY_LAYOUT])
    made.shapes.title.text = _str(slide.get("title"))
    for index, side in enumerate(("left", "right")):
        part = slide.get(side)
        if not isinstance(part, dict):
            continue
        left = 0.5 + index * 4.7
        _textbox(
            made, [_str(part.get("heading"))], (left, 1.8, 4.3, 0.6), size=22, bold=True
        )
        _textbox(made, _texts(part.get("bullets")), (left, 2.5, 4.3, 4.0), size=16)
    return made


def _special_slide(
    presentation: Any, slide: dict[str, Any], data: bytes | None
) -> Any | None:
    """Build a table, image, stats, timeline or comparison slide, else None."""
    layout = slide.get("layout")
    table = slide.get("table")
    if isinstance(table, dict):
        made = presentation.slides.add_slide(
            presentation.slide_layouts[_TITLE_ONLY_LAYOUT]
        )
        made.shapes.title.text = _str(slide.get("title"))
        _table(made, table)
        return made
    if data is not None:
        return _image_slide(presentation, slide, data, str(layout))
    if layout == "stats" and slide.get("stats"):
        return _stats_slide(presentation, slide)
    if layout == "timeline" and slide.get("timeline"):
        return _timeline_slide(presentation, slide)
    if layout == "comparison" and isinstance(slide.get("left"), dict):
        return _comparison_slide(presentation, slide)
    return None


def _text_slide(presentation: Any, slide: dict[str, Any]) -> Any:
    """A title (or content) slide with the slide's lines."""
    if slide.get("layout") in ("title", "section") and not _lines(slide)[1:]:
        index = _TITLE_LAYOUT
    else:
        index = _CONTENT_LAYOUT
    made = presentation.slides.add_slide(presentation.slide_layouts[index])
    made.shapes.title.text = _str(slide.get("title"))
    _fill(made.placeholders[1].text_frame, _lines(slide))
    return made


def _add_slide(
    presentation: Any, slide: dict[str, Any], images: Mapping[str, bytes]
) -> None:
    """Add one slide; the notes (and a picture's credit) go to the speaker notes."""
    layout = slide.get("layout")
    data = _image_bytes(slide, images) if layout in _IMAGE_LAYOUTS else None
    made = _special_slide(presentation, slide, data)
    if made is None:
        made = _text_slide(presentation, slide)
    notes = [_str(slide.get("notes"))]
    if data is not None:
        credit = _credit(slide)
        notes.append(f"Image: {credit}" if credit else "")
    text = "\n\n".join(note for note in notes if note)
    if text:
        made.notes_slide.notes_text_frame.text = text


def slides_to_pptx(
    title: str,
    subtitle: str | None,
    slides: list[dict[str, Any]],
    images: Mapping[str, bytes] | None = None,
) -> bytes:
    """Return a deck; a title slide is added first unless the deck starts with one.

    `images` maps a stored picture's file id to its bytes.
    """
    presentation = Presentation()
    if not slides or slides[0].get("layout") != "title":
        head = presentation.slides.add_slide(presentation.slide_layouts[_TITLE_LAYOUT])
        head.shapes.title.text = _str(title)
        head.placeholders[1].text_frame.text = _str(subtitle)
    for slide in slides:
        _add_slide(presentation, slide, images or {})
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def deck_to_pptx(
    content: dict[str, Any], images: Mapping[str, bytes] | None = None
) -> bytes:
    """Export a Studio slide deck (``title``, ``subtitle``, ``slides``).

    Each slide is a dict with ``layout`` (title, agenda, section, bullets,
    two_columns, quote, table, summary, image_left, image_right, full_image, stats,
    timeline, comparison), ``title`` and the fields of its layout:
    ``bullets``/``body``, ``left``/``right`` (``heading``, ``bullets``), ``quote``
    (``text``, ``attribution``), ``table`` (``columns``, ``rows``), ``image``
    (``file_id``, ``alt``, ``attribution``, ``source_url``: placed from `images`, the
    credit goes to the caption and the notes), ``stats`` (``value``, ``label``),
    ``timeline`` (``label``, ``text``); ``notes`` go to the speaker notes. Unknown
    fields are ignored.
    """
    slides = [s for s in content.get("slides") or [] if isinstance(s, dict)]
    return slides_to_pptx(
        str(content.get("title") or ""),
        content.get("subtitle") or None,
        slides,
        images,
    )


build_pptx = deck_to_pptx
"""The reusable name of the deck builder: ``build_pptx(deck) -> bytes``."""
