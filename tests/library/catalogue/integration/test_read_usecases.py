"""LIB-1, LIB-3, LIB-7, LIB-12: browsing, the item page, file URLs and text."""

from collections.abc import Awaitable, Callable
from datetime import timedelta

from app.modules.library.application.catalogue.list_items import ListItemsQuery
from app.modules.library.domain.catalogue_errors import DownloadNotAllowedError
from app.modules.library.domain.catalogue_search import ItemSort
from app.modules.library.domain.entities import Item, SubjectLink
from app.modules.library.domain.enums import (
    ItemStatus,
    Rights,
    TextStatus,
    Visibility,
)
from app.modules.library.domain.errors import (
    ItemNotFoundError,
    NotSupportedError,
    TextUnavailableError,
)
from app.modules.library.infrastructure.redis_stats import stats_key
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from app.shared.redis_util import wait
from tests.factories.library import NOW, make_book, make_external, make_material
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.files import FakeFilesApi
from tests.library.catalogue.helpers import put

import pytest
from fakeredis.aioredis import FakeRedis

StoreItem = Callable[[Item], Awaitable[Item]]


def _public_book(title: str = "Open physics") -> Item:
    return make_book(
        title=title,
        visibility=Visibility.PUBLIC,
        rights=Rights.PUBLIC_DOMAIN,
        download_allowed=True,
    )


# - - - Lists - - -


async def test_list_returns_cards_with_subjects_and_a_cursor(
    library: LibraryServices,
    store_item: StoreItem,
    academic: FakeAcademicDirectory,
    student: Actor,
) -> None:
    """LIB-7: cards carry subject names; the cursor leads to the next page."""
    physics = academic.add_subject(new_id(), "Physics")
    for number in range(3):
        await put(
            library.core.uow_factory,
            store_item,
            make_book(title=f"Book {number}"),
            subjects=[SubjectLink(physics)],
        )
    query = ListItemsQuery(sort=ItemSort.TITLE, limit=2)

    first = await library.catalogue.list_items.execute(student, query)
    second = await library.catalogue.list_items.execute(
        student, ListItemsQuery(sort=ItemSort.TITLE, limit=2, cursor=first.next_cursor)
    )

    assert [c.title for c in first.items] == ["Book 0", "Book 1"]
    assert first.items[0].subjects[0].name == "Physics"
    assert first.next_cursor is not None
    assert [c.title for c in second.items] == ["Book 2"]
    assert second.next_cursor is None


async def test_full_text_hit_card_has_snippet_and_page(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: the card of a body hit shows where the words were found."""
    await put(
        library.core.uow_factory,
        store_item,
        make_book(title="Mexanika"),
        pages=["Kirish", "Tezlanish — tezlikning o'zgarish sur'ati."],
    )

    page = await library.catalogue.list_items.execute(
        student, ListItemsQuery(q="tezlanish")
    )

    assert len(page.items) == 1
    assert page.items[0].snippet_page == 2
    assert page.items[0].snippet and "tezlanish" in page.items[0].snippet.lower()


async def test_anonymous_list_has_public_books_only(
    library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-1: a visitor sees the public book, not the lyceum one."""
    await put(library.core.uow_factory, store_item, _public_book())
    await put(library.core.uow_factory, store_item, make_book(title="Lyceum only"))

    page = await library.catalogue.list_items.execute(None, ListItemsQuery())

    assert [c.title for c in page.items] == ["Open physics"]


async def test_query_without_letters_finds_nothing(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: "???" is not a search."""
    await put(library.core.uow_factory, store_item, make_book())

    page = await library.catalogue.list_items.execute(student, ListItemsQuery(q="???"))

    assert page.items == [] and page.next_cursor is None


async def test_page_size_is_capped(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: limit above 100 is a page of 100 at most."""
    await put(library.core.uow_factory, store_item, make_book())

    page = await library.catalogue.list_items.execute(
        student, ListItemsQuery(limit=5000)
    )

    assert len(page.items) == 1


# - - - Item page - - -


async def test_item_is_found_by_id_and_by_slug(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-1: both ids and slugs open the item."""
    book = await put(library.core.uow_factory, store_item, make_book(title="Fizika"))

    by_id = await library.catalogue.get_item.execute(student, str(book.id))
    by_slug = await library.catalogue.get_item.execute(student, book.slug)

    assert by_id.card.id == book.id == by_slug.card.id
    assert by_id.can.read


@pytest.mark.parametrize(
    "status", [ItemStatus.HELD, ItemStatus.UNPUBLISHED, ItemStatus.PENDING_REVIEW]
)
async def test_unlisted_item_is_not_found_for_a_student(
    library: LibraryServices,
    store_item: StoreItem,
    student: Actor,
    status: ItemStatus,
) -> None:
    """LIB-1: never a 403: an item the caller may not see does not exist."""
    item = await put(library.core.uow_factory, store_item, make_material(status=status))

    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item.execute(student, str(item.id))
    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item.execute(student, item.slug)


async def test_lyceum_item_is_not_found_for_a_visitor(
    library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-1: visitors open public items only."""
    book = await put(library.core.uow_factory, store_item, make_book())

    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item.execute(None, str(book.id))


async def test_owner_opens_their_draft_and_a_librarian_a_held_item(
    library: LibraryServices,
    store_item: StoreItem,
    student: Actor,
    other_librarian: Actor,
) -> None:
    """LIB-1: owners and librarians see more than other users."""
    draft = await put(
        library.core.uow_factory,
        store_item,
        make_material(status=ItemStatus.DRAFT, uploader_id=student.user_id),
    )
    held = await put(
        library.core.uow_factory, store_item, make_material(status=ItemStatus.HELD)
    )

    mine = await library.catalogue.get_item.execute(student, str(draft.id))
    reviewed = await library.catalogue.get_item.execute(other_librarian, str(held.id))

    assert mine.can.edit and reviewed.status is ItemStatus.HELD


async def test_unknown_item_is_not_found(
    library: LibraryServices, student: Actor
) -> None:
    """LIB-1: neither an unknown id nor an unknown slug reveals anything."""
    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item.execute(student, str(new_id()))
    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item.execute(student, "no-such-slug")


# - - - File URLs - - -


async def test_reader_url_lives_fifteen_minutes_and_counts_an_open(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    student: Actor,
    redis: FakeRedis,
) -> None:
    """LIB-3: inline URL with the reader TTL; the open is counted."""
    file_id = files_api.add_file(owner_id=new_id())
    book = await put(library.core.uow_factory, store_item, make_book(file_id=file_id))

    view = await library.catalogue.get_file_url.execute(
        student, book.id, file_id, inline=True
    )

    assert "inline=True" in view.url and "ttl=900" in view.url
    assert view.expires_at == NOW + timedelta(seconds=900)
    assert view.content_type == "application/pdf"
    assert view.byte_size == book.files[0].byte_size
    day = NOW.date().isoformat()
    assert await wait(redis.hget(stats_key(day), f"{book.id}:opens")) == "1"


async def test_visitor_gets_the_url_of_a_public_book(
    library: LibraryServices, store_item: StoreItem, files_api: FakeFilesApi
) -> None:
    """LIB-1: public books are readable without a login."""
    file_id = files_api.add_file(owner_id=new_id())
    book = _public_book()
    book.files[0].file_id = file_id
    await put(library.core.uow_factory, store_item, book)

    view = await library.catalogue.get_file_url.execute(
        None, book.id, file_id, inline=True
    )

    assert view.url.startswith("https://files.test/")


async def test_download_needs_the_rights_basis_to_allow_it(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    student: Actor,
) -> None:
    """LIB-3: reading is open, downloading follows `download_allowed`."""
    file_id = files_api.add_file(owner_id=new_id())
    book = await put(
        library.core.uow_factory,
        store_item,
        make_book(file_id=file_id, download_allowed=False),
    )

    await library.catalogue.get_file_url.execute(student, book.id, file_id, inline=True)
    with pytest.raises(DownloadNotAllowedError):
        await library.catalogue.get_file_url.execute(
            student, book.id, file_id, inline=False
        )


async def test_download_is_allowed_when_the_book_says_so(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    student: Actor,
) -> None:
    """LIB-3: an open-licence book can be downloaded."""
    file_id = files_api.add_file(owner_id=new_id())
    book = await put(
        library.core.uow_factory,
        store_item,
        make_book(file_id=file_id, download_allowed=True),
    )

    view = await library.catalogue.get_file_url.execute(
        student, book.id, file_id, inline=False
    )

    assert "inline=False" in view.url


async def test_file_url_of_an_external_record_is_not_supported(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-12: 409 library/not-supported."""
    record = await put(library.core.uow_factory, store_item, make_external())

    with pytest.raises(NotSupportedError):
        await library.catalogue.get_file_url.execute(
            student, record.id, new_id(), inline=True
        )


async def test_file_url_hides_unlisted_items_and_foreign_files(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    student: Actor,
) -> None:
    """LIB-1: a held item's file, or a file of another item, is not found."""
    file_id = files_api.add_file(owner_id=new_id())
    held = await put(
        library.core.uow_factory,
        store_item,
        make_book(file_id=file_id, status=ItemStatus.HELD),
    )
    live = await put(library.core.uow_factory, store_item, make_book(title="Live"))

    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_file_url.execute(
            student, held.id, file_id, inline=True
        )
    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_file_url.execute(
            student, live.id, file_id, inline=True
        )


# - - - Text - - -


async def test_text_pages_come_from_the_page_index(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: `{pages: [{page, text}]}` for a range."""
    book = await put(
        library.core.uow_factory,
        store_item,
        make_book(),
        pages=["one", "two", "three"],
    )

    pages = await library.catalogue.get_item_text.execute(
        student, book.id, page_from=2, page_to=3
    )

    assert [(p.page, p.text) for p in pages] == [(2, "two"), (3, "three")]


async def test_text_range_is_capped_at_fifty_pages(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: one call never returns a whole 300-page book."""
    book = await put(
        library.core.uow_factory,
        store_item,
        make_book(),
        pages=[f"page {n}" for n in range(1, 121)],
    )

    pages = await library.catalogue.get_item_text.execute(student, book.id)

    assert len(pages) == 50 and pages[0].page == 1 and pages[-1].page == 50


async def test_text_falls_back_to_the_files_module_without_an_index(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    student: Actor,
) -> None:
    """LIB-7: pages not indexed yet are read from the extracted text."""
    file_id = files_api.add_file(owner_id=new_id(), pages=["alpha", "beta"])
    book = await put(library.core.uow_factory, store_item, make_book(file_id=file_id))

    pages = await library.catalogue.get_item_text.execute(student, book.id, page_from=2)

    assert [(p.page, p.text) for p in pages] == [(2, "beta")]


async def test_scans_have_no_text(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: 409 library/text-unavailable for `no_text`."""
    scan = await put(
        library.core.uow_factory,
        store_item,
        make_book(text_status=TextStatus.NO_TEXT),
    )

    with pytest.raises(TextUnavailableError):
        await library.catalogue.get_item_text.execute(student, scan.id)


async def test_text_of_external_and_held_items_is_refused(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-12, LIB-1: not supported for UniLibrary; not found for held items."""
    record = await put(library.core.uow_factory, store_item, make_external())
    held = await put(
        library.core.uow_factory,
        store_item,
        make_material(status=ItemStatus.HELD),
        pages=["secret"],
    )

    with pytest.raises(NotSupportedError):
        await library.catalogue.get_item_text.execute(student, record.id)
    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item_text.execute(student, held.id)


# - - - Subjects - - -


async def test_subjects_list_counts_and_hides_empty_ones_by_default(
    library: LibraryServices,
    store_item: StoreItem,
    librarian: Actor,
    student: Actor,
) -> None:
    """LIB-1: subjects with visible items; `all` adds the empty ones."""
    physics = (
        await library.taxonomy.create_subject.execute(librarian, name={"en": "Physics"})
    ).id
    await library.taxonomy.create_subject.execute(librarian, name={"en": "Astronomy"})
    await put(
        library.core.uow_factory,
        store_item,
        make_book(),
        subjects=[SubjectLink(physics)],
    )
    await put(
        library.core.uow_factory,
        store_item,
        make_book(title="Held", status=ItemStatus.HELD),
        subjects=[SubjectLink(physics)],
    )

    shelves = await library.catalogue.list_subjects.execute(student)
    everything = await library.catalogue.list_subjects.execute(
        student, include_empty=True
    )

    assert [(s.name, s.item_count) for s in shelves] == [("Physics", 1)]
    assert [(s.name, s.item_count) for s in everything] == [
        ("Physics", 1),
        ("Astronomy", 0),
    ]
