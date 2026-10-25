"""LIB-10: the library reader that notebooks use; access is re-checked on every call."""

import datetime as dt

from app.modules.library.application.bridge.source_reader import (
    LibrarySourceReaderImpl,
)
from app.modules.library.domain.enums import (
    AnnotationKind,
    ItemStatus,
    TextStatus,
    Visibility,
)
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.contracts.library import LibrarySourceUnavailableError
from app.shared.ids import new_id
from tests.factories.library import make_external, make_material
from tests.fakes.library.files import FakeFilesApi
from tests.library.bridge.conftest import AddBook, AddNote, SetStatus, StoreItem

import pytest

PAGES = ("Forces.\n", "Newton's first law.", "Newton's second law.", "Energy.")
NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


# - - - describe - - -


async def test_describe_gives_the_title_author_and_files_of_a_book(
    reader: LibrarySourceReaderImpl, student: Actor, add_book: AddBook
) -> None:
    """LIB-10: the notebook shows what the item is and which file to read."""
    book = await add_book(*PAGES, title="Physics 10")

    ref = await reader.describe(book.id, student)

    assert (ref.id, ref.kind, ref.title) == (book.id, "book", "Physics 10")
    assert (ref.author_label, ref.page_count) == ("A. Author", 120)
    [file] = ref.files
    assert file.file_id == book.files[0].file_id
    assert (file.format, file.pages, file.text_status) == ("pdf", 120, "ready")
    assert file.is_primary


async def test_describe_labels_a_material_with_its_uploader(
    reader: LibrarySourceReaderImpl, student: Actor, store_item: StoreItem
) -> None:
    """LIB-10: materials have no author line, the uploader stands in."""
    material = await store_item(make_material(title="Kinematics notes"))

    ref = await reader.describe(material.id, student)

    assert (ref.kind, ref.author_label) == ("material", "Aziza K.")


async def test_describe_of_an_unknown_item_is_not_found(
    reader: LibrarySourceReaderImpl, student: Actor
) -> None:
    """LIB-10: the error names the reason and the item."""
    missing = new_id()

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.describe(missing, student)

    assert (caught.value.reason, caught.value.item_id) == ("not_found", missing)


async def test_describe_of_a_unilibrary_record_is_not_supported(
    reader: LibrarySourceReaderImpl, student: Actor, store_item: StoreItem
) -> None:
    """LIB-10, LIB-2: external records are link-only."""
    record = await store_item(make_external())

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.describe(record.id, student)

    assert caught.value.reason == "not_supported"


async def test_describe_of_a_lyceum_book_is_not_found_without_a_role(
    reader: LibrarySourceReaderImpl, visitor: Actor, add_book: AddBook
) -> None:
    """LIB-10, LIB-1: a lyceum-only book is not readable by an anonymous actor."""
    book = await add_book(*PAGES, visibility=Visibility.LYCEUM)

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.describe(book.id, visitor)

    assert caught.value.reason == "not_found"


# - - - read_text - - -


async def test_the_whole_file_is_read_with_its_page_starts(
    reader: LibrarySourceReaderImpl, student: Actor, add_book: AddBook
) -> None:
    """LIB-10: without a range every page is returned."""
    book = await add_book(*PAGES, title="Physics 10")
    file_id = book.files[0].file_id

    result = await reader.read_text(book.id, file_id, actor=student)

    assert result.text == "".join(page + "\n" for page in PAGES)
    assert result.page_starts == (0, 9, 29, 50)
    assert (result.item_id, result.file_id, result.title) == (
        book.id,
        file_id,
        "Physics 10",
    )
    assert (result.page_from, result.page_to) == (1, 4)


async def test_a_page_range_is_cut_out_of_the_text(
    reader: LibrarySourceReaderImpl, student: Actor, add_book: AddBook
) -> None:
    """LIB-10: pages 2 to 3 only, offsets restart at the first page of the range."""
    book = await add_book(*PAGES)

    result = await reader.read_text(
        book.id, book.files[0].file_id, actor=student, page_from=2, page_to=3
    )

    assert result.text == "Newton's first law.\nNewton's second law.\n"
    assert result.page_starts == (0, 20)
    assert (result.page_from, result.page_to) == (2, 3)


async def test_a_range_past_the_last_page_is_cut_to_it(
    reader: LibrarySourceReaderImpl, student: Actor, add_book: AddBook
) -> None:
    """LIB-10: the reader reports the pages it really gave."""
    book = await add_book(*PAGES)

    result = await reader.read_text(
        book.id, book.files[0].file_id, actor=student, page_from=4, page_to=40
    )

    assert (result.text, result.page_from, result.page_to) == ("Energy.\n", 4, 4)


async def test_a_range_beyond_the_file_has_no_text(
    reader: LibrarySourceReaderImpl, student: Actor, add_book: AddBook
) -> None:
    """LIB-10: nothing to read on those pages."""
    book = await add_book(*PAGES)

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_text(
            book.id, book.files[0].file_id, actor=student, page_from=9, page_to=12
        )

    assert caught.value.reason == "no_text"


async def test_a_file_that_is_not_the_items_is_not_found(
    reader: LibrarySourceReaderImpl, student: Actor, add_book: AddBook
) -> None:
    """LIB-10: a file id of another item must not be read through this one."""
    book = await add_book(*PAGES)
    other = await add_book(*PAGES)

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_text(book.id, other.files[0].file_id, actor=student)

    assert caught.value.reason == "not_found"


@pytest.mark.parametrize(
    "status",
    [TextStatus.NONE, TextStatus.PENDING, TextStatus.NO_TEXT, TextStatus.FAILED],
)
async def test_a_file_without_ready_text_has_no_text(
    reader: LibrarySourceReaderImpl,
    student: Actor,
    add_book: AddBook,
    status: TextStatus,
) -> None:
    """LIB-10: scans and unprocessed files cannot be sources."""
    book = await add_book(*PAGES, text_status=status)

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_text(book.id, book.files[0].file_id, actor=student)

    assert caught.value.reason == "no_text"


async def test_a_file_that_vanished_from_storage_is_not_found(
    reader: LibrarySourceReaderImpl,
    student: Actor,
    add_book: AddBook,
    files_api: FakeFilesApi,
) -> None:
    """LIB-10: the item row can outlive its file."""
    book = await add_book(*PAGES)
    del files_api.files[book.files[0].file_id]

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_text(book.id, book.files[0].file_id, actor=student)

    assert caught.value.reason == "not_found"


async def test_a_held_book_stops_being_readable_and_a_restore_reopens_it(
    reader: LibrarySourceReaderImpl,
    student: Actor,
    add_book: AddBook,
    set_status: SetStatus,
) -> None:
    """LIB-10, LIB-7: access is checked on every call, not when the source is added."""
    book = await add_book(*PAGES)
    file_id = book.files[0].file_id
    await reader.read_text(book.id, file_id, actor=student)

    await set_status(book, ItemStatus.HELD)
    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_text(book.id, file_id, actor=student)
    await set_status(book, ItemStatus.PUBLISHED)
    restored = await reader.read_text(book.id, file_id, actor=student)

    assert caught.value.reason == "unavailable"
    assert restored.text.startswith("Forces.")


async def test_an_unpublished_book_is_unavailable(
    reader: LibrarySourceReaderImpl,
    student: Actor,
    add_book: AddBook,
    set_status: SetStatus,
) -> None:
    """LIB-10: takedowns and unpublishing end the use of the text."""
    book = await add_book(*PAGES)
    await set_status(book, ItemStatus.UNPUBLISHED)

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_text(book.id, book.files[0].file_id, actor=student)

    assert caught.value.reason == "unavailable"


# - - - read_annotations - - -


async def test_annotations_are_the_actors_own_and_not_deleted(
    reader: LibrarySourceReaderImpl,
    add_note: AddNote,
    student: Actor,
    other_student: Actor,
    add_book: AddBook,
) -> None:
    """LIB-10, LIB-8: notes are private; nobody reads another user's highlights."""
    book = await add_book(*PAGES)
    other_book = await add_book(*PAGES)
    await add_note(student.user_id, book.id, quote="mine")
    await add_note(student.user_id, book.id, quote="gone", deleted=True)
    await add_note(other_student.user_id, book.id, quote="theirs")
    await add_note(student.user_id, other_book.id, quote="elsewhere")

    result = await reader.read_annotations(book.id, actor=student)

    assert [a.quote for a in result] == ["mine"]


async def test_annotations_come_oldest_first_with_their_page_and_note(
    reader: LibrarySourceReaderImpl,
    add_note: AddNote,
    student: Actor,
    add_book: AddBook,
) -> None:
    """LIB-10: kind, quote, note, page, colour and time are passed on."""
    book = await add_book(*PAGES)
    await add_note(student.user_id, book.id, quote="later", minutes=9)
    await add_note(
        student.user_id,
        book.id,
        kind=AnnotationKind.NOTE,
        quote="earlier",
        note="Check this",
        locator={"page": 7},
        minutes=1,
    )
    await add_note(
        student.user_id,
        book.id,
        kind=AnnotationKind.BOOKMARK,
        quote=None,
        locator={"cfi": "epubcfi(/6/4)", "progress": 0.3},
        minutes=5,
    )

    result = await reader.read_annotations(book.id, actor=student)

    assert [a.quote for a in result] == ["earlier", None, "later"]
    first = result[0]
    assert (first.kind, first.note, first.page, first.color) == (
        "note",
        "Check this",
        7,
        "yellow",
    )
    assert first.updated_at == NOW + dt.timedelta(minutes=1)
    assert result[1].page is None


async def test_annotations_of_a_held_book_are_unavailable(
    reader: LibrarySourceReaderImpl,
    student: Actor,
    add_book: AddBook,
    set_status: SetStatus,
) -> None:
    """LIB-10: the notes source follows the book's availability."""
    book = await add_book(*PAGES)
    await set_status(book, ItemStatus.HELD)

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_annotations(book.id, actor=student)

    assert caught.value.reason == "unavailable"


async def test_annotations_of_a_unilibrary_record_are_not_supported(
    reader: LibrarySourceReaderImpl, student: Actor, store_item: StoreItem
) -> None:
    """LIB-10, LIB-2: no notes on link-only records."""
    record = await store_item(make_external())

    with pytest.raises(LibrarySourceUnavailableError) as caught:
        await reader.read_annotations(record.id, actor=student)

    assert caught.value.reason == "not_supported"


# - - - wiring - - -


async def test_the_library_module_exposes_the_reader_on_the_bridge(
    library: LibraryServices, student: Actor, add_book: AddBook
) -> None:
    """LIB-10: `library.bridge.source_reader` is what notebooks get."""
    book = await add_book(*PAGES, title="Chemistry 11")

    ref = await library.bridge.source_reader.describe(book.id, student)

    assert ref.title == "Chemistry 11"
