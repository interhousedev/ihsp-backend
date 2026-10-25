"""LIB-3 (files part): EPUB text and contents. Every spine chapter is one page."""

import io
import zipfile

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction import epub_text
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from app.shared.contracts.files import OutlineEntry
from tests.files.helpers import EPUB_TYPE, TocItem, make_epub

import pytest


@pytest.fixture
def extractor() -> FileTextExtractor:
    """The real extractor."""
    return FileTextExtractor()


async def test_the_extractor_supports_epub(extractor: FileTextExtractor) -> None:
    """`.epub` joins PDF, DOCX, TXT and MD."""
    assert extractor.supports(EPUB_TYPE)


async def test_every_spine_chapter_is_one_page(extractor: FileTextExtractor) -> None:
    """Pages = chapters; `page_starts` are the offsets of the chapter texts."""
    data = make_epub(["<p>Alpha beta</p>", "<p>Gamma delta</p>", "<p>Epsilon</p>"])

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.pages == 3
    assert result.text == "Alpha beta\nGamma delta\nEpsilon"
    assert result.page_starts == (0, 11, 23)
    for start, expected in zip(
        result.page_starts, ("Alpha", "Gamma", "Epsilon"), strict=True
    ):
        assert result.text[start:].startswith(expected)


async def test_the_spine_decides_the_order_not_the_file_names(
    extractor: FileTextExtractor,
) -> None:
    """The reading order of the package is the order of the pages."""
    data = make_epub(["<p>first file</p>", "<p>second file</p>"], spine_order=[1, 0])

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.text == "second file\nfirst file"


async def test_html_becomes_plain_blocks_without_markup_or_scripts(
    extractor: FileTextExtractor,
) -> None:
    """Blocks are separated by blank lines, inline tags do not split words."""
    body = (
        "<h1>Chapter <i>One</i></h1>"
        "<p>Hel<b>lo</b>   there,\n  reader &amp; friend&nbsp;&#1046;.</p>"
        "<script>var hidden = 1;</script><style>p {color: red}</style>"
        "<ul><li>first</li><li>second</li></ul>"
        "<p>line<br/>break</p>"
    )

    result = await extractor.extract(EPUB_TYPE, make_epub([body]))

    assert result.text == (
        "# Chapter One\n\n"
        "Hello there, reader & friend Ж.\n\n"
        "- first\n\n"
        "- second\n\n"
        "line\nbreak"
    )
    assert "hidden" not in result.text
    assert "red" not in result.text


async def test_table_rows_are_lines_and_cells_are_tab_separated(
    extractor: FileTextExtractor,
) -> None:
    """Same reading of tables as the DOCX extractor."""
    body = (
        "<table><tr><th>Name</th><th>Mark</th></tr>"
        "<tr><td>Alice</td><td>5</td></tr></table>"
    )

    result = await extractor.extract(EPUB_TYPE, make_epub([body]))

    assert result.text == "Name\tMark\nAlice\t5"


async def test_a_chapter_without_text_still_counts_as_a_page(
    extractor: FileTextExtractor,
) -> None:
    """A cover page is chapter 1; later page numbers must not shift."""
    data = make_epub(['<img src="cover.png" alt="cover"/>', "<p>Body</p>"])

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.pages == 2
    assert result.page_starts == (0, 1)
    assert result.text == "\nBody"


async def test_utf16_chapters_are_decoded(extractor: FileTextExtractor) -> None:
    """The EPUB standard allows UTF-16 content documents."""
    chapter = ("<html><body><p>Привет, мир</p></body></html>").encode("utf-16")
    data = make_epub(["<p>x</p>"], extra_files={"OEBPS/ch1.xhtml": chapter})

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.text == "Привет, мир"


async def test_a_chapter_missing_from_the_archive_is_an_empty_page(
    extractor: FileTextExtractor,
) -> None:
    """A damaged book is still readable and searchable where it is intact."""
    data = make_epub(["<p>one</p>", "<p>two</p>"])
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(buffer, "w") as target,
    ):
        for info in source.infolist():
            if info.filename != "OEBPS/ch1.xhtml":
                target.writestr(info, source.read(info))

    result = await extractor.extract(EPUB_TYPE, buffer.getvalue())

    assert result.pages == 2
    assert result.text == "\ntwo"


async def test_chapters_in_a_subfolder_and_percent_encoded_names(
    extractor: FileTextExtractor,
) -> None:
    """hrefs are relative to the package file and may be URL-encoded."""
    data = make_epub(
        ["<p>text</p>"],
        folder="book/OEBPS",
        toc=[("Start", "ch1.xhtml#a%20b", [])],
    )

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.text == "text"
    assert result.outline == (OutlineEntry("Start", 1, "ch1.xhtml#a%20b", 0),)


# - - - Table of contents - - -


def _toc() -> list[TocItem]:
    return [
        ("Part I", "ch1.xhtml", [("Section 1.1", "ch1.xhtml#s1", [])]),
        ("Part II", "ch3.xhtml", []),
        ("Elsewhere", "notes/extra.xhtml", []),
    ]


async def test_the_navigation_document_gives_the_outline(
    extractor: FileTextExtractor,
) -> None:
    """EPUB 3: titles, depth, the chapter number and the href inside the book."""
    data = make_epub(["<p>a</p>", "<p>b</p>", "<p>c</p>"], toc=_toc())

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.outline == (
        OutlineEntry("Part I", 1, "ch1.xhtml", 0),
        OutlineEntry("Section 1.1", 1, "ch1.xhtml#s1", 1),
        OutlineEntry("Part II", 3, "ch3.xhtml", 0),
        OutlineEntry("Elsewhere", None, "notes/extra.xhtml", 0),
    )


async def test_the_ncx_is_used_when_there_is_no_navigation_document(
    extractor: FileTextExtractor,
) -> None:
    """EPUB 2 books keep their contents in toc.ncx."""
    data = make_epub(["<p>a</p>", "<p>b</p>", "<p>c</p>"], toc=_toc(), toc_kind="ncx")

    result = await extractor.extract(EPUB_TYPE, data)

    assert [(e.title, e.page, e.level) for e in result.outline] == [
        ("Part I", 1, 0),
        ("Section 1.1", 1, 1),
        ("Part II", 3, 0),
        ("Elsewhere", None, 0),
    ]


async def test_the_navigation_document_wins_over_the_ncx(
    extractor: FileTextExtractor,
) -> None:
    """Books that carry both are read like EPUB 3."""
    nav_only: list[TocItem] = [("From nav", "ch1.xhtml", [])]
    data = make_epub(["<p>a</p>"], toc=nav_only, toc_kind="both")

    result = await extractor.extract(EPUB_TYPE, data)

    assert [e.title for e in result.outline] == ["From nav"]


async def test_a_book_without_contents_has_an_empty_outline(
    extractor: FileTextExtractor,
) -> None:
    """The library then shows chapters by number."""
    result = await extractor.extract(EPUB_TYPE, make_epub(["<p>a</p>"]))

    assert result.outline == ()


async def test_outline_titles_are_cleaned_and_capped(
    extractor: FileTextExtractor,
) -> None:
    """Whitespace collapses; empty titles are dropped; long ones are cut."""
    toc: list[TocItem] = [
        ("  Spaced\n   title ", "ch1.xhtml", []),
        ("", "ch1.xhtml", []),
        ("x" * 500, "ch1.xhtml", []),
    ]

    result = await extractor.extract(EPUB_TYPE, make_epub(["<p>a</p>"], toc=toc))

    assert [len(e.title) for e in result.outline] == [12, 200]
    assert result.outline[0].title == "Spaced title"


async def test_the_outline_has_a_maximum_size(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A book with a huge contents list does not bloat the metadata."""
    monkeypatch.setattr(epub_text, "MAX_OUTLINE_ENTRIES", 2)
    toc: list[TocItem] = [(f"T{i}", "ch1.xhtml", []) for i in range(5)]

    result = await extractor.extract(EPUB_TYPE, make_epub(["<p>a</p>"], toc=toc))

    assert [e.title for e in result.outline] == ["T0", "T1"]


# - - - Damaged and hostile books - - -


@pytest.mark.parametrize(
    "files",
    [
        {},  # no container.xml
        {"META-INF/container.xml": b"<container/>"},  # no rootfile
        {"META-INF/container.xml": b"not xml"},
    ],
)
async def test_an_archive_that_is_not_an_epub_raises_extraction_error(
    extractor: FileTextExtractor, files: dict[str, bytes]
) -> None:
    """A zip without a package is not a book."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    with pytest.raises(TextExtractionError):
        await extractor.extract(EPUB_TYPE, buffer.getvalue())


async def test_garbage_raises_extraction_error(extractor: FileTextExtractor) -> None:
    """Never a zipfile error."""
    with pytest.raises(TextExtractionError):
        await extractor.extract(EPUB_TYPE, b"PK\x03\x04 truncated")


async def test_a_package_without_a_spine_raises_extraction_error(
    extractor: FileTextExtractor,
) -> None:
    """Nothing to read."""
    data = make_epub(
        ["<p>a</p>"],
        extra_files={
            "OEBPS/content.opf": b'<package xmlns="http://www.idpf.org/2007/opf">'
            b"<manifest/></package>"
        },
    )

    with pytest.raises(TextExtractionError, match="spine"):
        await extractor.extract(EPUB_TYPE, data)


async def test_a_zip_with_too_many_entries_is_refused(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zip-bomb guard: entry count."""
    monkeypatch.setattr(epub_text, "MAX_EPUB_ENTRIES", 3)

    with pytest.raises(TextExtractionError, match="too many parts"):
        await extractor.extract(EPUB_TYPE, make_epub(["<p>a</p>"]))


async def test_text_that_unpacks_too_large_is_refused(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the parts we read count: images do not, big chapters do."""
    monkeypatch.setattr(epub_text, "MAX_ZIP_UNCOMPRESSED", 400)

    with pytest.raises(TextExtractionError, match="too large"):
        await extractor.extract(EPUB_TYPE, make_epub(["<p>a</p>"]))


async def test_images_do_not_count_against_the_unpacked_text_limit(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 300 MB illustrated book must not be refused for its pictures."""
    monkeypatch.setattr(epub_text, "MAX_ZIP_UNCOMPRESSED", 5_000)
    data = make_epub(["<p>a</p>"], extra_files={"OEBPS/big.png": b"\x00" * 50_000})

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.text == "a"


async def test_text_beyond_the_cap_is_cut_and_later_offsets_are_dropped(
    extractor: FileTextExtractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Like PDFs: the page count stays true, the offsets stay inside the text."""
    monkeypatch.setattr(epub_text, "MAX_TEXT_CHARS", 25)
    data = make_epub([f"<p>{'x' * 20}</p>"] * 3)

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.pages == 3
    assert len(result.text) <= 25
    assert result.page_starts == (0, 21)


async def test_nul_characters_are_removed_by_the_extractor(
    extractor: FileTextExtractor,
) -> None:
    """PostgreSQL cannot store NUL."""
    chapter = b"<html><body><p>a\x00b</p></body></html>"
    data = make_epub(["<p>x</p>"], extra_files={"OEBPS/ch1.xhtml": chapter})

    result = await extractor.extract(EPUB_TYPE, data)

    assert result.text == "ab"
