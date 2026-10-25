"""A reading position inside a file (LIB-6).

PDFs use `{page}`; EPUBs use `{cfi, progress}`. Markdown and plain text may use
either, depending on how the reader splits them. Pure rules, no I/O.
"""

from collections.abc import Mapping
from typing import Any

from app.modules.library.domain.enums import FileFormat
from app.modules.library.domain.reader_errors import InvalidLocatorError

MAX_CFI_LENGTH = 500


def _page_locator(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    page = raw.get("page")
    if isinstance(page, int) and not isinstance(page, bool) and page >= 1:
        return {"page": page}
    return None


def _cfi_locator(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    cfi = raw.get("cfi")
    progress = raw.get("progress")
    if not isinstance(cfi, str) or not 0 < len(cfi) <= MAX_CFI_LENGTH:
        return None
    if isinstance(progress, bool) or not isinstance(progress, int | float):
        return None
    if not 0 <= progress <= 1:
        return None
    return {"cfi": cfi, "progress": float(progress)}


def validate_locator(raw: Mapping[str, Any], file_format: FileFormat) -> dict[str, Any]:
    """The clean locator for the file format, or `InvalidLocatorError`."""
    if file_format is FileFormat.PDF:
        result = _page_locator(raw)
    elif file_format is FileFormat.EPUB:
        result = _cfi_locator(raw)
    else:
        result = _page_locator(raw) or _cfi_locator(raw)
    if result is None:
        raise InvalidLocatorError(
            params={"format": file_format.value}, support_details=f"locator {dict(raw)}"
        )
    return result


def locator_page(locator: Mapping[str, Any]) -> int | None:
    """The page of a page locator, or None for an EPUB position."""
    page = locator.get("page")
    return page if isinstance(page, int) and not isinstance(page, bool) else None
