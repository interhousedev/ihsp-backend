"""LIB-3 (files part): the bookmarks of a PDF become its outline."""

from app.modules.files.infrastructure.extraction import pdf_outline
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from app.shared.contracts.files import OutlineEntry
from tests.files.helpers import PDF_TYPE, make_pdf, make_pdf_with_outline

import pytest
from pypdf import PdfReader


@pytest.fixture
def extractor() -> FileTextExtractor:
    """The real extractor."""
    return FileTextExtractor()


async def test_bookmarks_give_titles_pages_and_depth(
    extractor: FileTextExtractor,
) -> None:
    """Pages are 1-based; nested bookmarks have a higher level."""
    data = make_pdf_with_outline(
        ["one", "two", "three", "four"],
        [
            ("Chapter 1", 0, 0),
            ("Section 1.1", 1, 1),
            ("Section 1.1.1", 2, 2),
            ("Chapter 2", 3, 0),
        ],
    )

    result = await extractor.extract(PDF_TYPE, data)

    assert result.outline == (
        OutlineEntry("Chapter 1", 1, None, 0),
        OutlineEntry("Section 1.1", 2, None, 1),
        OutlineEntry("Section 1.1.1", 3, None, 2),
        OutlineEntry("Chapter 2", 4, None, 0),
    )
    assert result.pages == 4


async def test_a_pdf_without_bookmarks_has_an_empty_outline(
    extractor: FileTextExtractor,
) -> None:
    """Most scans have none."""
    result = await extractor.extract(PDF_TYPE, make_pdf("only page"))

    assert result.outline == ()


async def test_a_bookmark_that_points_nowhere_keeps_its_title(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page is None when pypdf cannot resolve the destination."""
    data = make_pdf_with_outline(["a", "b"], [("Lost", 0, 0), ("Found", 1, 0)])

    def broken(self: PdfReader, destination: object) -> int:
        if getattr(destination, "title", "") == "Lost":
            raise ValueError("no such page")
        return 1

    monkeypatch.setattr(PdfReader, "get_destination_page_number", broken)

    result = await extractor.extract(PDF_TYPE, data)

    assert [(e.title, e.page) for e in result.outline] == [("Lost", None), ("Found", 2)]


async def test_a_damaged_outline_never_costs_the_text(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Text extraction wins over bookmarks."""
    data = make_pdf_with_outline(["The text survives"], [("Chapter", 0, 0)])

    def explode(self: PdfReader) -> list[object]:
        raise RecursionError("loop in the outline")

    monkeypatch.setattr(PdfReader, "outline", property(explode))

    result = await extractor.extract(PDF_TYPE, data)

    assert "The text survives" in result.text
    assert result.outline == ()


async def test_titles_are_cleaned_and_the_outline_is_capped(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No NUL (JSONB), no runs of white space, at most 200 characters, at most N."""
    monkeypatch.setattr(pdf_outline, "MAX_OUTLINE_ENTRIES", 2)
    data = make_pdf_with_outline(
        ["a", "b", "c"],
        [("A\x00  B", 0, 0), ("x" * 500, 1, 0), ("dropped", 2, 0)],
    )

    result = await extractor.extract(PDF_TYPE, data)

    assert [len(e.title) for e in result.outline] == [3, 200]
    assert result.outline[0].title == "A B"
