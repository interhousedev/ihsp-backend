"""LIB-3 (files part): page count, outline and content hash of processed books."""

import hashlib
from uuid import UUID, uuid4

from app.modules.files.domain.errors import FileDeletedError, StoredFileNotFoundError
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope, OutlineEntry
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import (
    EPUB_TYPE,
    PDF_TYPE,
    TocItem,
    make_epub,
    make_pdf,
    make_pdf_with_outline,
    upload_and_complete,
    upload_ready,
)

import pytest

BOOK = FilePurpose.LIBRARY_BOOK


async def _book(fakes: FilesFakes, librarian: Actor, name: str, data: bytes) -> UUID:
    content_type = EPUB_TYPE if name.endswith(".epub") else PDF_TYPE
    return await upload_ready(
        fakes, librarian, name=name, data=data, content_type=content_type, purpose=BOOK
    )


async def test_an_epub_is_processed_into_pages_outline_and_text(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """Chapters are pages: text, offsets, page count and contents all agree."""
    toc: list[TocItem] = [("One", "ch1.xhtml", []), ("Two", "ch2.xhtml#x", [])]
    data = make_epub(["<p>Alpha</p>", "<p>Beta</p>"], toc=toc)

    file_id = await _book(fakes, librarian, "book.epub", data)

    public = fakes.services.public
    full = await public.read_text_with_pages(file_id)
    assert full.text == "Alpha\nBeta"
    assert full.page_starts == (0, 6)
    assert await public.page_count(file_id) == 2
    assert await public.read_outline(file_id) == [
        OutlineEntry("One", 1, "ch1.xhtml", 0),
        OutlineEntry("Two", 2, "ch2.xhtml#x", 0),
    ]


async def test_a_pdf_gives_its_page_count_and_bookmarks(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """The library fills `pages` and `toc` from these."""
    data = make_pdf_with_outline(
        ["one", "two", "three"], [("Start", 0, 0), ("Middle", 2, 1)]
    )

    file_id = await _book(fakes, librarian, "book.pdf", data)

    public = fakes.services.public
    assert await public.page_count(file_id) == 3
    assert await public.read_outline(file_id) == [
        OutlineEntry("Start", 1, None, 0),
        OutlineEntry("Middle", 3, None, 1),
    ]


async def test_a_scan_without_text_still_has_a_page_count_and_outline(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """`no_text` books are common: the metadata does not depend on the text."""
    data = make_pdf_with_outline(["", ""], [("Cover", 0, 0)])

    file_id = await _book(fakes, librarian, "scan.pdf", data)

    public = fakes.services.public
    assert fakes.db.row(file_id).text_bytes is None
    assert await public.page_count(file_id) == 2
    assert [e.title for e in await public.read_outline(file_id)] == ["Cover"]


async def test_files_without_pages_have_no_page_count_and_no_outline(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """Plain text has neither; nothing is invented."""
    file_id = await upload_ready(
        fakes,
        librarian,
        name="poem.txt",
        data=b"roses are red",
        content_type="text/plain",
        purpose=FilePurpose.LIBRARY_MATERIAL,
    )

    public = fakes.services.public
    assert await public.page_count(file_id) is None
    assert await public.read_outline(file_id) == []


async def test_a_file_that_is_not_processed_yet_answers_none_and_empty(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """Between complete and process there is no metadata."""
    view = await upload_and_complete(
        fakes,
        librarian,
        name="book.pdf",
        data=make_pdf("x"),
        content_type=PDF_TYPE,
        purpose=BOOK,
    )

    public = fakes.services.public
    assert await public.page_count(view.file.id) is None
    assert await public.read_outline(view.file.id) == []


async def test_files_processed_before_outlines_existed_give_an_empty_list(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """Old rows carry `pages` and offsets but no `outline` key."""
    file_id = await _book(fakes, librarian, "old.pdf", make_pdf("a", "b"))
    row = fakes.db.row(file_id)
    row.metadata.pop("outline", None)

    assert await fakes.services.public.read_outline(file_id) == []
    assert await fakes.services.public.page_count(file_id) == 2


async def test_unusable_outline_metadata_is_skipped_entry_by_entry(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """A bad row of metadata never breaks the reader's contents."""
    file_id = await _book(fakes, librarian, "book.pdf", make_pdf("a"))
    fakes.db.row(file_id).metadata["outline"] = [
        {"title": "Good", "page": 1, "href": None, "level": 0},
        {"title": 5},
        "junk",
        {"title": "Bad page", "page": "x", "href": None, "level": 0},
    ]

    outline = await fakes.services.public.read_outline(file_id)

    assert outline == [OutlineEntry("Good", 1, None, 0)]


async def test_reading_the_outline_of_a_missing_or_deleted_file_fails_like_the_text(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """Same errors as `read_text_page`."""
    file_id = await _book(fakes, librarian, "book.pdf", make_pdf("a"))
    async with fakes.db.uow() as uow:
        await uow.files.mark_deleted([file_id], fakes.clock.now())
        await uow.commit()

    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.public.read_outline(uuid4())
    with pytest.raises(FileDeletedError):
        await fakes.services.public.read_outline(file_id)


async def test_an_unknown_file_has_no_page_count_and_no_hash(
    fakes: FilesFakes,
) -> None:
    """None, never an error."""
    public = fakes.services.public

    assert await public.page_count(uuid4()) is None
    assert await public.sha256(uuid4()) is None


async def test_the_hash_is_the_lower_case_hex_sha256_of_the_content(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """Uploads store the checksum the browser signed (verified by storage)."""
    data = make_pdf("Duplicate me")
    file_id = await _book(fakes, librarian, "book.pdf", data)

    assert (
        await fakes.services.public.sha256(file_id) == hashlib.sha256(data).hexdigest()
    )


async def test_the_hash_of_server_side_files_is_computed_from_the_bytes(
    fakes: FilesFakes,
) -> None:
    """`store_bytes` hashes what it writes."""
    data = make_pdf("From the server")
    ref = await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.LIBRARY,
        purpose=FilePurpose.LIBRARY_MATERIAL,
        name="a.pdf",
        data=data,
    )

    assert (
        await fakes.services.public.sha256(ref.id) == hashlib.sha256(data).hexdigest()
    )
