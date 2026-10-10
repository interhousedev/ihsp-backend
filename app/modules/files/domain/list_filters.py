"""Name, type and order filters of the file list (the lesson file picker)."""

from typing import Literal

from app.modules.files.domain.policy import DOCX, PDF, PPTX, XLSX

FileTypeFilter = Literal["pdf", "doc", "sheet", "slides", "text", "image"]
FileSort = Literal["recent", "older"]

_TYPES: dict[str, tuple[str, ...]] = {
    "pdf": (PDF,),
    "doc": (DOCX,),
    "sheet": (XLSX,),
    "slides": (PPTX,),
    "text": ("text/plain", "text/markdown"),
    "image": ("image/png", "image/jpeg"),
}


def content_types_of(kind: str | None) -> tuple[str, ...] | None:
    """Return the content types of a type filter; None means no filter."""
    return None if kind is None else _TYPES.get(kind, ())


def escape_like(text: str) -> str:
    """Escape LIKE wildcards so a search for `50%` matches a literal percent."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
