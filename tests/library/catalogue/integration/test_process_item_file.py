"""LIB-13: the scan job `library.process_item_file`."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.catalogue.list_items import ListItemsQuery
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    EventKind,
    ItemLanguage,
    ItemStatus,
    TextStatus,
    UploaderRole,
)
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.contracts.files import OutlineEntry
from app.shared.ids import new_id
from tests.factories.library import make_book, make_material
from tests.fakes.library.catalogue_files import FakeScanFilesApi
from tests.library.catalogue.helpers import put

StoreItem = Callable[[Item], Awaitable[Item]]
LOREM = "Newton's second law links force, mass and acceleration. " * 30


def _pending(item: Item, file_id: UUID) -> Item:
    item.files[0].file_id = file_id
    item.files[0].text_status = TextStatus.PENDING
    item.files[0].pages = None
    item.has_text = False
    item.page_count = None
    return item


def _with(item: Item, fields: dict[str, object]) -> Item:
    for key, value in fields.items():
        setattr(item, key, value)
    return item


def _book(file_id: UUID, **fields: object) -> Item:
    return _pending(_with(make_book(), fields), file_id)


def _material(file_id: UUID, **fields: object) -> Item:
    item = make_material()
    role = fields.pop("uploader_role", None)
    if role is not None and item.material is not None:
        item.material.uploader_role = UploaderRole(str(role))
    return _pending(_with(item, fields), file_id)


async def _run(library: LibraryServices, item: Item) -> Item:
    await library.catalogue.process_item_file.execute(item.id, item.files[0].file_id)
    async with library.core.uow_factory() as uow:
        loaded = await uow.items.get(item.id)
    assert loaded is not None
    return loaded


async def _history(library: LibraryServices, item: Item) -> list[EventKind]:
    async with library.core.uow_factory() as uow:
        return [event.kind for event in await uow.events.history(item.id)]


# - - - Text, pages, contents - - -


async def test_text_file_becomes_ready_with_pages_toc_hashes_and_index(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeScanFilesApi,
    student: Actor,
) -> None:
    """LIB-13: status, page count, contents, hashes and the page index."""
    file_id = files_api.add_file(
        owner_id=new_id(),
        pages=[LOREM, "Second page about tezlanish and velocity. " * 20],
        sha256="a" * 64,
    )
    files_api.outlines[file_id] = [
        OutlineEntry("Kirish", 1, None, 0),
        OutlineEntry("Tezlanish", 2, None, 1),
    ]
    book = await put(library.core.uow_factory, store_item, _book(file_id))

    scanned = await _run(library, book)

    stored = scanned.files[0]
    assert stored.text_status is TextStatus.READY and stored.pages == 2
    assert stored.sha256 == "a" * 64
    assert stored.toc == [
        {"title": "Kirish", "level": 1, "page": 1},
        {"title": "Tezlanish", "level": 2, "page": 2},
    ]
    assert scanned.has_text and scanned.page_count == 2
    assert scanned.content_hash is not None and len(scanned.content_hash) == 64
    found = await library.catalogue.list_items.execute(
        student, ListItemsQuery(q="tezlanish")
    )
    assert found.items[0].snippet_page == 2


async def test_a_scan_without_text_is_no_text_and_not_indexed(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: under 200 characters per 10 pages."""
    file_id = files_api.add_file(owner_id=new_id(), pages=["", "", "", "", "ii"] * 2)
    book = await put(library.core.uow_factory, store_item, _book(file_id))

    scanned = await _run(library, book)

    assert scanned.files[0].text_status is TextStatus.NO_TEXT
    assert scanned.has_text is False and scanned.page_count == 10
    async with library.core.uow_factory() as uow:
        assert await uow.pages.count(book.id, file_id) == 0


async def test_file_without_extracted_text_is_no_text_not_failed(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: the files module's "no text" answer means a scan, not an error."""
    file_id = files_api.add_file(owner_id=new_id())
    files_api.no_text.add(file_id)
    book = await put(library.core.uow_factory, store_item, _book(file_id))

    scanned = await _run(library, book)

    assert scanned.files[0].text_status is TextStatus.NO_TEXT


async def test_extraction_error_marks_the_file_failed(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: `text_status=failed`, nothing else breaks."""
    file_id = files_api.add_file(owner_id=new_id(), pages=[LOREM])
    files_api.broken.add(file_id)
    book = await put(library.core.uow_factory, store_item, _book(file_id))

    scanned = await _run(library, book)

    assert scanned.files[0].text_status is TextStatus.FAILED
    assert scanned.has_text is False


async def test_text_without_page_offsets_is_cut_into_virtual_pages(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: Markdown and text files get virtual pages for snippets."""
    paragraphs = [f"Paragraph {n}. " + "word " * 300 for n in range(8)]
    file_id = files_api.add_file(owner_id=new_id(), pages=["\n\n".join(paragraphs)])
    files_api.flat.add(file_id)
    material = await put(library.core.uow_factory, store_item, _material(file_id))

    scanned = await _run(library, material)

    pages = scanned.files[0].pages
    assert pages is not None and pages >= 3
    async with library.core.uow_factory() as uow:
        assert await uow.pages.count(material.id, file_id) == pages


async def test_uzbek_cyrillic_text_is_found_with_a_latin_query(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeScanFilesApi,
    student: Actor,
) -> None:
    """LIB-7: pages of Uzbek items are indexed Latin-normalised."""
    text = "Ғазал ўзбек адабиётининг қадимий жанри. " * 20
    file_id = files_api.add_file(owner_id=new_id(), pages=[text])
    book = await put(
        library.core.uow_factory,
        store_item,
        _book(file_id, language=ItemLanguage.UZ_CYRL, title="Kitob"),
    )
    await _run(library, book)

    found = await library.catalogue.list_items.execute(
        student, ListItemsQuery(q="gʻazal")
    )

    assert [c.title for c in found.items] == ["Kitob"]
    assert found.items[0].snippet_page == 1


async def test_running_twice_gives_the_same_result(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: idempotent: pages are replaced, and an item is no duplicate of itself."""
    file_id = files_api.add_file(
        owner_id=new_id(), pages=[LOREM, LOREM + " more"], sha256="b" * 64
    )
    material = await put(library.core.uow_factory, store_item, _material(file_id))

    first = await _run(library, material)
    second = await _run(library, material)

    assert second.files[0].pages == first.files[0].pages == 2
    assert second.content_hash == first.content_hash
    assert second.material is not None
    assert second.material.scan["findings"] == []
    async with library.core.uow_factory() as uow:
        assert await uow.pages.count(material.id, file_id) == 2


async def test_unknown_item_or_removed_file_is_skipped(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: a file detached before the job ran is not an error."""
    file_id = files_api.add_file(owner_id=new_id(), pages=[LOREM])
    book = await put(library.core.uow_factory, store_item, _book(file_id))

    await library.catalogue.process_item_file.execute(new_id(), file_id)
    await library.catalogue.process_item_file.execute(book.id, new_id())


# - - - Findings - - -


async def test_personal_data_and_exam_markers_are_flagged_and_change_no_status(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: a teacher's published material stays published; findings are codes."""
    text = (
        "Midterm, variant 3. Call +998 90 123 45 67 or write to a.k@example.uz. "
        + LOREM
    )
    file_id = files_api.add_file(owner_id=new_id(), pages=[text])
    material = await put(
        library.core.uow_factory,
        store_item,
        _material(
            file_id, status=ItemStatus.PUBLISHED, uploader_role=UploaderRole.TEACHER
        ),
    )

    scanned = await _run(library, material)

    assert scanned.status is ItemStatus.PUBLISHED
    assert scanned.material is not None
    assert scanned.material.scan["findings"] == ["phone_number", "email", "exam_marker"]
    assert "998" not in str(scanned.material.scan)
    assert scanned.material.scan["file_id"] == str(file_id)


async def test_same_file_hash_is_reported_as_a_duplicate_without_rejecting(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: `duplicate` finding with `duplicate_of`; no automatic rejection."""
    first_file = files_api.add_file(owner_id=new_id(), pages=[LOREM], sha256="c" * 64)
    second_file = files_api.add_file(
        owner_id=new_id(), pages=["Totally different text. " * 40], sha256="c" * 64
    )
    original = await put(library.core.uow_factory, store_item, _material(first_file))
    await _run(library, original)
    copy = await put(
        library.core.uow_factory,
        store_item,
        _material(second_file, status=ItemStatus.PENDING_REVIEW),
    )

    scanned = await _run(library, copy)

    assert scanned.status is ItemStatus.PENDING_REVIEW
    assert scanned.material is not None
    assert scanned.material.scan["findings"] == ["duplicate"]
    assert scanned.material.scan["duplicate_of"] == [str(original.id)]


async def test_same_text_in_another_file_is_a_duplicate_too(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: text hash catches a re-saved PDF with another file hash."""
    first_file = files_api.add_file(owner_id=new_id(), pages=[LOREM], sha256="d" * 64)
    second_file = files_api.add_file(
        owner_id=new_id(), pages=[LOREM.upper().lower() + "  "], sha256="e" * 64
    )
    original = await put(library.core.uow_factory, store_item, _material(first_file))
    await _run(library, original)
    copy = await put(library.core.uow_factory, store_item, _material(second_file))

    scanned = await _run(library, copy)

    assert scanned.material is not None
    assert scanned.material.scan["duplicate_of"] == [str(original.id)]


async def test_a_new_version_is_not_a_duplicate_of_the_one_it_replaces(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: re-uploading the same file as a new version is expected."""
    first_file = files_api.add_file(owner_id=new_id(), pages=[LOREM], sha256="f" * 64)
    second_file = files_api.add_file(owner_id=new_id(), pages=[LOREM], sha256="f" * 64)
    old = await put(library.core.uow_factory, store_item, _material(first_file))
    await _run(library, old)
    new = await put(
        library.core.uow_factory,
        store_item,
        _material(second_file, supersedes_id=old.id),
    )

    scanned = await _run(library, new)

    assert scanned.material is not None
    assert scanned.material.scan["findings"] == []


async def test_book_duplicates_are_logged_as_an_event(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """LIB-13: books have no scan column; the finding goes into the history."""
    first_file = files_api.add_file(owner_id=new_id(), pages=[LOREM], sha256="9" * 64)
    second_file = files_api.add_file(owner_id=new_id(), pages=[LOREM], sha256="9" * 64)
    original = await put(library.core.uow_factory, store_item, _book(first_file))
    await _run(library, original)
    copy = await put(library.core.uow_factory, store_item, _book(second_file))

    await _run(library, copy)

    assert EventKind.EDITED in await _history(library, copy)
    async with library.core.uow_factory() as uow:
        events = await uow.events.history(copy.id)
    assert events[-1].data["scan"]["findings"] == ["duplicate"]
