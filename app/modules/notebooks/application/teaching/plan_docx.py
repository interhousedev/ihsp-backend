"""Write a lesson plan (Markdown) into a copy of the teacher's .docx template.

The template's styles, headers, footers and page setup stay; its body is replaced.
"""

import io
import re
from typing import Any, Final

from docx import Document

_HEADING: Final = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET: Final = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED: Final = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_RULE: Final = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_SEPARATOR: Final = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_BOLD: Final = re.compile(r"(\*\*[^*\n]+\*\*)")
_SECT_PR: Final = "sectPr"


def _style(document: Any, name: str) -> str | None:
    """The style name when the template has it, else None."""
    try:
        document.styles[name]
    except KeyError:
        return None
    return name


def _paragraph(document: Any, text: str, style: str | None = None) -> None:
    """A paragraph in the style (or none); ``**bold**`` gets its own runs."""
    paragraph = document.add_paragraph(style=style)
    for part in _BOLD.split(text):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            paragraph.add_run(part[2:-2]).bold = True
        elif part:
            paragraph.add_run(part)


def _table(document: Any, lines: list[str]) -> None:
    """A Markdown table as a Word table (plain when the style is absent)."""
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in lines
        if not _SEPARATOR.match(line)
    ]
    if not rows:
        return
    width = max(len(r) for r in rows)
    table = document.add_table(rows=len(rows), cols=width)
    grid = _style(document, "Table Grid")
    if grid:
        table.style = grid
    for y, row in enumerate(rows):
        for x, text in enumerate(row):
            table.cell(y, x).text = text


def _clear_body(document: Any) -> None:
    """Remove paragraphs and tables; the section properties (headers) stay."""
    body = document.element.body
    for child in list(body):
        if not child.tag.endswith(_SECT_PR):
            body.remove(child)


def _heading(document: Any, match: Any) -> None:
    """Write a heading paragraph (bold when the style is absent)."""
    level = min(len(match.group(1)), 9)
    style = _style(document, f"Heading {level}")
    _paragraph(document, match.group(2), style)
    runs = document.paragraphs[-1].runs
    if style is None and runs:
        runs[0].bold = True


def _line(document: Any, line: str, bullet: Any, numbered: Any) -> None:
    """Write one non-table line."""
    heading, item = _HEADING.match(line), _BULLET.match(line)
    count = _NUMBERED.match(line)
    if heading:
        _heading(document, heading)
    elif item:
        _paragraph(document, item.group(1), bullet)
    elif count:
        _paragraph(document, count.group(1), numbered)
    elif line.strip() and not _RULE.match(line):
        _paragraph(document, line.strip())


def _write(document: Any, markdown: str) -> None:
    bullet = _style(document, "List Bullet")
    numbered = _style(document, "List Number")
    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|") and line.count("|") >= 2:
            end = i
            while end < len(lines) and lines[end].lstrip().startswith("|"):
                end += 1
            _table(document, lines[i:end])
            i = end
            continue
        _line(document, line, bullet, numbered)
        i += 1


def plan_into_template(template: bytes, markdown: str) -> bytes:
    """Return the template document with its body replaced by the plan."""
    document = Document(io.BytesIO(template))
    _clear_body(document)
    _write(document, markdown)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
