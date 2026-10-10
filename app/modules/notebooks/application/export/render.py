"""One entry point for the exporters: Studio outputs and assistant text."""

import csv
import io
import re
from typing import Any, Final

from app.modules.notebooks.application.export.docx import markdown_to_docx
from app.modules.notebooks.application.export.pptx import deck_to_pptx, slides_to_pptx
from app.modules.notebooks.application.export.quiz import (
    flashcards_to_csv,
    quiz_to_docx,
)
from app.modules.notebooks.application.export.text import (
    TEXT_KINDS,
    to_json,
    to_markdown,
)
from app.modules.notebooks.application.export.xlsx import (
    data_table_to_xlsx,
    table_to_xlsx,
)
from app.modules.notebooks.domain.enums import ArtifactKind
from app.shared.contracts.documents import DocumentKind, RenderedDocument

CONTENT_TYPES: Final[dict[str, str]] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "csv": "text/csv; charset=utf-8",
}
# The native file of each kind (summary, report and study guide are reports). Mind maps
# and infographics are pictures the web client renders to PNG; they have none here.
KIND_FORMATS: Final[dict[ArtifactKind, str]] = {
    ArtifactKind.REPORT: "docx",
    ArtifactKind.DATA_TABLE: "xlsx",
    ArtifactKind.SLIDES: "pptx",
    ArtifactKind.QUIZ: "docx",
    ArtifactKind.FLASHCARDS: "csv",
}
_UNSAFE_NAME: Final = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')
_SEPARATOR: Final = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_RULE: Final = re.compile(r"^\s*-{3,}\s*$")
_HEADING: Final = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET: Final = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*)$")
_NOTES: Final = re.compile(
    r"^\s*(?:notes?|заметки|примечания|izohlar)\s*:\s*(.*)$", re.I
)
NAME_MAX: Final = 80


def file_name(title: str, kind: str) -> str:
    """A safe file name from the title and the extension of the kind."""
    clean = " ".join(_UNSAFE_NAME.sub(" ", title).split()).strip(".")[:NAME_MAX].strip()
    return f"{clean or 'document'}.{kind}"


def format_for(kind: ArtifactKind) -> str | None:
    """The export format of an output kind, or None if it has none."""
    return KIND_FORMATS.get(kind)


def default_format(kind: ArtifactKind) -> str | None:
    """The download format when none is asked for: Office, else Markdown."""
    office = KIND_FORMATS.get(kind)
    if office is not None:
        return office
    return "md" if kind in TEXT_KINDS else None


def export_as(
    kind: ArtifactKind, title: str, content: dict[str, Any], fmt: str
) -> RenderedDocument:
    """Render a ready output as ``fmt``: its Office format, Markdown or JSON.

    Raises:
        ValueError: The kind has no such format.
    """
    if fmt == KIND_FORMATS.get(kind):
        return export_artifact(kind, title, content)
    if fmt == "json" and (kind in KIND_FORMATS or kind in TEXT_KINDS):
        text, ctype = to_json(title, content), "application/json"
    elif fmt == "md" and kind in TEXT_KINDS:
        text, ctype = to_markdown(kind, title, content), "text/markdown"
    else:
        raise ValueError(f"{kind.value} has no {fmt} export")
    return RenderedDocument(file_name(title, fmt), ctype, text.encode())


def export_artifact(
    kind: ArtifactKind, title: str, content: dict[str, Any]
) -> RenderedDocument:
    """Render a ready Studio output in the format of its kind."""
    fmt = KIND_FORMATS[kind]
    if kind is ArtifactKind.QUIZ:
        data = quiz_to_docx(title, content)
    elif kind is ArtifactKind.FLASHCARDS:
        data = flashcards_to_csv(content)
    elif fmt == "docx":
        data = markdown_to_docx(
            str(content.get("title") or title), str(content.get("markdown") or "")
        )
    elif fmt == "xlsx":
        data = data_table_to_xlsx({**content, "title": content.get("title") or title})
    else:
        data = deck_to_pptx({**content, "title": content.get("title") or title})
    return RenderedDocument(file_name(title, fmt), CONTENT_TYPES[fmt], data)


def parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Read a Markdown table or CSV/TSV text; the first row is the header."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return [], []
    if lines[0].lstrip().startswith("|"):
        cells = [
            [c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in lines
            if not _SEPARATOR.match(ln)
        ]
    else:
        sample = lines[0]
        delimiter = max(("\t", ";", ","), key=sample.count)
        cells = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    return cells[0], cells[1:]


def parse_slides(text: str) -> list[dict[str, Any]]:
    """Split an outline into slides: ``---`` or a ``#`` heading starts a slide.

    Inside a slide, ``#`` is the title, list items are bullets, plain lines are the
    body and ``Notes:`` starts the speaker notes.
    """
    chunks: list[list[str]] = [[]]
    for line in text.replace("\r\n", "\n").split("\n"):
        if _RULE.match(line):
            chunks.append([])
        elif _HEADING.match(line) and any(_HEADING.match(x) for x in chunks[-1]):
            chunks.append([line])
        else:
            chunks[-1].append(line)
    slides: list[dict[str, Any]] = []
    for chunk in chunks:
        slide = _slide(chunk)
        if slide is not None:
            slides.append(slide)
    return slides


def _slide(chunk: list[str]) -> dict[str, Any] | None:
    """One slide of an outline, or None for an empty chunk."""
    title = ""
    bullets: list[str] = []
    body: list[str] = []
    notes: list[str] = []
    in_notes = False
    for line in chunk:
        heading, note, bullet = (
            _HEADING.match(line),
            _NOTES.match(line),
            _BULLET.match(line),
        )
        if not line.strip():
            continue
        if note:
            in_notes = True
            notes.append(note.group(1))
        elif in_notes:
            notes.append(line.strip())
        elif heading and not title:
            title = heading.group(1)
        elif bullet:
            bullets.append(bullet.group(1))
        else:
            body.append(line.strip())
    if not (title or bullets or body):
        return None
    return {
        "layout": "bullets",
        "title": title,
        "bullets": bullets,
        "body": " ".join(body),
        "notes": " ".join(n for n in notes if n),
    }


class DocumentExporter:
    """Implements `DocumentRenderer` over the exporters."""

    def render(self, kind: DocumentKind, title: str, content: str) -> RenderedDocument:
        """Render the assistant's text as a .docx, .xlsx or .pptx."""
        if kind == "docx":
            data = markdown_to_docx(title, content)
        elif kind == "xlsx":
            columns, rows = parse_table(content)
            data = table_to_xlsx(title, columns, rows)
        else:
            data = slides_to_pptx(title, None, parse_slides(content))
        return RenderedDocument(file_name(title, kind), CONTENT_TYPES[kind], data)
