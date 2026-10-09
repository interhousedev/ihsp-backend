"""Text of DOCX files: paragraphs, headings, lists and tables, in document order.

The text keeps the structure the notebooks chunker understands (§ 3.2.3): blocks are
separated by blank lines, headings become Markdown headings (``# Title``, ``## …``)
and list items start with ``- ``. Text that python-docx's `Paragraph.text` misses is
read too: content controls (``w:sdt``) at block and run level, tracked insertions
(``w:ins``), simple fields and smart tags. Merged table cells are written once.
"""

import io
import re
import zipfile
from collections.abc import Iterator
from typing import Any

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction.limits import (
    MAX_TEXT_CHARS,
    MAX_ZIP_ENTRIES,
    MAX_ZIP_UNCOMPRESSED,
)
from app.modules.files.ports.text_extractor import ExtractedText

from docx import Document
from docx.oxml.ns import qn

MAX_HEADING_LEVEL = 6
_P, _TBL, _SDT, _SDT_CONTENT = qn("w:p"), qn("w:tbl"), qn("w:sdt"), qn("w:sdtContent")
_TR, _TC, _T, _TAB = qn("w:tr"), qn("w:tc"), qn("w:t"), qn("w:tab")
_BREAKS = frozenset({qn("w:br"), qn("w:cr")})
_BLOCK, _ROW, _CELL = frozenset({_P, _TBL}), frozenset({_TR}), frozenset({_TC})
_P_PR, _P_STYLE, _NUM_PR = qn("w:pPr"), qn("w:pStyle"), qn("w:numPr")
_OUTLINE, _VAL = qn("w:outlineLvl"), qn("w:val")
_HEADING_STYLE = re.compile(r"^(?:heading|заголовок|sarlavha)\s*(\d)$", re.IGNORECASE)
_TITLE_STYLES = frozenset({"title", "название", "заголовок"})
_LIST_STYLE = re.compile(r"^(?:list|список)", re.IGNORECASE)
_SPACES = re.compile(r"[ \t]*\n[ \t]*")


def _check_zip(data: bytes) -> None:
    """Refuse zip bombs before python-docx unpacks the parts."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise TextExtractionError("docx has too many parts")
    if sum(info.file_size for info in infos) > MAX_ZIP_UNCOMPRESSED:
        raise TextExtractionError("docx is too large when unpacked")


def _children(parent: Any, tags: frozenset[str]) -> Iterator[Any]:
    """Children with one of `tags`, also those wrapped in content controls."""
    for child in parent.iterchildren():
        if child.tag in tags:
            yield child
        elif child.tag == _SDT:
            for content in child.iterchildren(_SDT_CONTENT):
                yield from _children(content, tags)


def _int(value: object) -> int | None:
    """An integer attribute, or None when it is missing or not a number."""
    try:
        return int(str(value))
    except ValueError:
        return None


def _paragraph_text(paragraph: Any) -> str:
    """Every visible character of a paragraph (runs at any depth), tabs and breaks.

    Nested paragraphs (text boxes) are separated by line breaks.
    """
    parts: list[str] = []
    for element in paragraph.iter():
        tag = element.tag
        if tag == _T:
            parts.append(element.text or "")
        elif tag == _TAB:
            parts.append("\t")
        elif tag in _BREAKS or (tag == _P and element is not paragraph):
            parts.append("\n")
    return "".join(parts).strip()


def _style_names(document: Any) -> dict[str, tuple[str, int | None]]:
    """Style id -> (lower-case name, outline level) of the paragraph styles."""
    names: dict[str, tuple[str, int | None]] = {}
    for style in document.styles:
        element = style.element
        outline = element.find(f"{_P_PR}/{_OUTLINE}")
        level = _int(outline.get(_VAL)) if outline is not None else None
        names[style.style_id] = ((style.name or "").casefold(), level)
    return names


def _heading_level(name: str, outline: int | None) -> int | None:
    """1-based heading depth of a paragraph style, None for body text."""
    if name in _TITLE_STYLES:
        return 1
    match = _HEADING_STYLE.match(name)
    if match:
        return min(int(match.group(1)) + 1, MAX_HEADING_LEVEL)
    if outline is not None and outline < MAX_HEADING_LEVEL - 1:
        return outline + 2
    return None


class _Writer:
    """Turns the body of a document into Markdown-like blocks."""

    def __init__(self, styles: dict[str, tuple[str, int | None]]) -> None:
        self.styles = styles
        self.blocks: list[str] = []
        self.size = 0

    def full(self) -> bool:
        """True once enough text was collected."""
        return self.size >= MAX_TEXT_CHARS

    def add(self, block: str) -> None:
        if block:
            self.blocks.append(block)
            self.size += len(block) + 2

    def paragraph(self, element: Any) -> None:
        text = _paragraph_text(element)
        if not text:
            return
        p_pr = element.find(_P_PR)
        style = p_pr.find(_P_STYLE) if p_pr is not None else None
        style_id = style.get(_VAL) if style is not None else ""
        name, outline = self.styles.get(style_id or "", ("", None))
        own_outline = p_pr.find(_OUTLINE) if p_pr is not None else None
        if own_outline is not None:
            outline = _int(own_outline.get(_VAL))
        level = _heading_level(name, outline)
        if level is not None:
            self.add("#" * level + " " + " ".join(text.split()))
        elif (p_pr is not None and p_pr.find(_NUM_PR) is not None) or (
            _LIST_STYLE.match(name)
        ):
            self.add("- " + _SPACES.sub(" ", text))
        else:
            self.add(text)

    def table(self, element: Any) -> None:
        rows = []
        for row in _children(element, _ROW):
            cells = [_cell_text(cell) for cell in _children(row, _CELL)]
            if any(cells):
                rows.append("\t".join(cells))
        self.add("\n".join(rows))


def _cell_text(cell: Any) -> str:
    """The paragraphs of a table cell (nested tables included), on one line."""
    outer = (p for p in cell.iter(_P) if next(p.iterancestors(_P), None) is None)
    return " ".join(" ".join(_paragraph_text(p).split()) for p in outer).strip()


def extract_docx(data: bytes) -> ExtractedText:
    """Return the text of a document: headings, paragraphs, list items and tables.

    Blocks are separated by blank lines; table rows are one line each with the cells
    joined by tabs (a merged cell appears once).
    """
    try:
        _check_zip(data)
        document = Document(io.BytesIO(data))
        writer = _Writer(_style_names(document))
        for block in _children(document.element.body, _BLOCK):
            if block.tag == _P:
                writer.paragraph(block)
            else:
                writer.table(block)
            if writer.full():
                break
    except TextExtractionError:
        raise
    except Exception as exc:  # BadZipFile, KeyError, lxml errors, ...
        raise TextExtractionError(f"docx: {exc}") from exc
    return ExtractedText(text="\n\n".join(writer.blocks)[:MAX_TEXT_CHARS])
