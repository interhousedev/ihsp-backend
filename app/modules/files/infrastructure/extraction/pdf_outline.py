"""The bookmarks of a PDF as an outline (pypdf; blocking)."""

import re
from typing import Any

from app.modules.files.infrastructure.extraction.limits import (
    MAX_OUTLINE_ENTRIES,
    MAX_OUTLINE_TITLE,
)
from app.shared.contracts.files import OutlineEntry

import structlog
from pypdf import PdfReader
from pypdf.generic import Destination

log = structlog.get_logger(__name__)

_MAX_DEPTH = 20
_SPACES = re.compile(r"\s+")


def read_pdf_outline(reader: PdfReader) -> tuple[OutlineEntry, ...]:
    """Return the bookmarks in document order, 1-based pages, depth from 0.

    A damaged outline never costs the text: the entries read so far are returned.
    """
    entries: list[OutlineEntry] = []
    try:
        _walk(reader, reader.outline, 0, entries)
    except Exception as exc:  # pypdf raises many types, and loops end in RecursionError
        log.warning("pdf_outline_failed", error=str(exc))
    return tuple(entries)


def _walk(
    reader: PdfReader,
    items: list[Any],  # pypdf's OutlineType is a recursive union of lists
    level: int,
    out: list[OutlineEntry],
) -> None:
    """Add the bookmarks; a nested list holds the children of the bookmark before it."""
    for item in items:
        if len(out) >= MAX_OUTLINE_ENTRIES:
            return
        if isinstance(item, list):
            if level < _MAX_DEPTH:
                _walk(reader, item, level + 1, out)
        elif isinstance(item, Destination):
            title = _SPACES.sub(" ", (item.title or "").replace("\x00", "")).strip()
            if title:
                page = _page_of(reader, item)
                out.append(OutlineEntry(title[:MAX_OUTLINE_TITLE], page, None, level))


def _page_of(reader: PdfReader, destination: Destination) -> int | None:
    """The 1-based page a bookmark points at, or None when it cannot be resolved."""
    try:
        number = reader.get_destination_page_number(destination)
    except Exception:  # an unresolved destination raises several types
        return None
    return None if number is None or number < 0 else number + 1
