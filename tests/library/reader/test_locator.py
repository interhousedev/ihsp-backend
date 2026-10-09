"""LIB-6, LIB-9: a reading position is `{page}` for PDF and `{cfi, progress}` for EPUB."""

from typing import Any

from app.modules.library.domain.enums import FileFormat
from app.modules.library.domain.reader_errors import InvalidLocatorError
from app.modules.library.domain.reader_locator import locator_page, validate_locator

import pytest


def test_pdf_locator_keeps_only_the_page() -> None:
    """LIB-6: a PDF position is a page number; stray keys are dropped."""
    result = validate_locator({"page": 54, "junk": 1}, FileFormat.PDF)

    assert result == {"page": 54}


@pytest.mark.parametrize(
    "raw",
    [{}, {"page": 0}, {"page": -3}, {"page": "7"}, {"page": True}, {"cfi": "x"}],
)
def test_pdf_locator_without_a_positive_page_is_refused(raw: dict[str, Any]) -> None:
    """LIB-6: a PDF locator needs a page of at least 1."""
    with pytest.raises(InvalidLocatorError):
        validate_locator(raw, FileFormat.PDF)


def test_epub_locator_needs_cfi_and_progress() -> None:
    """LIB-6: an EPUB position is a CFI plus the progress 0 to 1."""
    result = validate_locator(
        {"cfi": "epubcfi(/6/4!/4/2)", "progress": 0.25}, FileFormat.EPUB
    )

    assert result == {"cfi": "epubcfi(/6/4!/4/2)", "progress": 0.25}


@pytest.mark.parametrize(
    "raw",
    [
        {"page": 3},
        {"cfi": "", "progress": 0.1},
        {"cfi": "epubcfi(/6)", "progress": 1.5},
        {"cfi": "epubcfi(/6)", "progress": -0.1},
        {"cfi": "epubcfi(/6)"},
        {"cfi": "x" * 501, "progress": 0.5},
    ],
)
def test_epub_locator_with_a_bad_shape_is_refused(raw: dict[str, Any]) -> None:
    """LIB-6: a broken EPUB locator is a validation error."""
    with pytest.raises(InvalidLocatorError):
        validate_locator(raw, FileFormat.EPUB)


def test_text_formats_accept_either_shape() -> None:
    """LIB-6: Markdown and plain text readers may use a page or a progress."""
    page = validate_locator({"page": 2}, FileFormat.MD)
    scroll = validate_locator({"cfi": "line:40", "progress": 0.4}, FileFormat.TXT)

    assert page == {"page": 2}
    assert scroll == {"cfi": "line:40", "progress": 0.4}


def test_locator_page_reads_the_page_when_there_is_one() -> None:
    """LIB-8: exports show a page reference only for page locators."""
    assert locator_page({"page": 12}) == 12
    assert locator_page({"cfi": "epubcfi(/6)", "progress": 0.5}) is None
