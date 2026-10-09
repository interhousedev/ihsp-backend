"""Pages of extracted text, the `no_text` rule and the text hash (doc § 8.1)."""

import hashlib
import re
from collections.abc import Sequence

from app.modules.library.domain.enums import TextStatus
from app.shared.text import search_normalize

CHUNK_CHARS = 4000
"""Size of a virtual page for files without page offsets (Markdown, text)."""

NO_TEXT_CHARS_PER_10_PAGES = 200
"""Fewer characters than this per ten pages means a scan: `no_text`."""

_PARAGRAPHS = re.compile(r"\n\s*\n")


def split_pages(text: str, page_starts: Sequence[int]) -> list[str]:
    """The page texts of a file: cut at the offsets, else in virtual pages."""
    if not page_starts:
        return chunk_text(text)
    bounds = [*page_starts, len(text)]
    return [text[bounds[i] : bounds[i + 1]].strip() for i in range(len(page_starts))]


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Cut a text without pages into pieces of about `size` characters.

    Paragraphs stay whole when they fit; a longer one is cut at a space.
    """
    pieces: list[str] = []
    current = ""
    for paragraph in _PARAGRAPHS.split(text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > size:
            pieces.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
        while len(current) > size:
            cut = current.rfind(" ", 0, size)
            if cut <= 0:
                cut = size
            pieces.append(current[:cut].strip())
            current = current[cut:].strip()
    if current:
        pieces.append(current)
    return pieces


def text_status_for(characters: int, pages: int) -> TextStatus:
    """`ready`, or `no_text` for a scan (under 200 characters per 10 pages)."""
    if characters * 10 < NO_TEXT_CHARS_PER_10_PAGES * max(pages, 1):
        return TextStatus.NO_TEXT
    return TextStatus.READY


def content_hash(text: str, language: str) -> str:
    """SHA-256 of the whitespace- and script-normalised text (duplicate check)."""
    normalised = search_normalize(" ".join(text.split()), language)
    return hashlib.sha256(normalised.encode()).hexdigest()
