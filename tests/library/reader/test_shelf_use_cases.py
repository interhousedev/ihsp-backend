"""LIB-7, LIB-16: the shelf holds books, materials and UniLibrary links."""

import datetime as dt

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind, ItemStatus, ShelfState
from app.modules.library.domain.errors import ItemNotFoundError
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring_reader import ReaderServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.fakes.clock import FixedClock
from tests.library.reader.helpers import StoreItem

import pytest


async def test_book_goes_on_the_shelf_and_shows_as_a_card(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-7: the answer is the entry with the item card and the state."""
    entry = await reader.put_shelf_entry.execute(
        student, book.id, ShelfState.WANT, locale="en"
    )

    assert entry.state is ShelfState.WANT
    assert entry.finished_at is None
    assert not entry.removed
    assert entry.item.id == book.id
    assert entry.item.title == "Physics 10"
    assert entry.item.shelf_state is ShelfState.WANT


async def test_finishing_a_book_records_when(
    reader: ReaderServices, student: Actor, book: Item, clock: FixedClock
) -> None:
    """LIB-7: `done` sets `finished_at`, moving back clears it."""
    done = await reader.put_shelf_entry.execute(
        student, book.id, ShelfState.DONE, locale="en"
    )
    clock.advance(hours=1)
    again = await reader.put_shelf_entry.execute(
        student, book.id, ShelfState.READING, locale="en"
    )

    assert done.finished_at == clock.now() - dt.timedelta(hours=1)
    assert again.finished_at is None
    assert again.updated_at == clock.now()


async def test_unilibrary_record_can_be_on_the_shelf_as_a_link(
    reader: ReaderServices, student: Actor, external: Item
) -> None:
    """LIB-7, LIB-12: pinned records are shelved; the card keeps the link-out."""
    entry = await reader.put_shelf_entry.execute(
        student, external.id, ShelfState.WANT, locale="en"
    )

    assert entry.item.kind is ItemKind.EXTERNAL
    assert entry.item.external is not None
    assert entry.item.external.view_url.startswith("https://unilibrary.uz/")


async def test_item_the_user_cannot_see_is_not_found(
    reader: ReaderServices, student: Actor, taken_down: Item, hidden: Item
) -> None:
    """LIB-1: held, taken down or hidden items cannot be shelved (404, not 403)."""
    for item in (taken_down, hidden):
        with pytest.raises(ItemNotFoundError):
            await reader.put_shelf_entry.execute(
                student, item.id, ShelfState.WANT, locale="en"
            )


async def test_unknown_item_is_not_found(
    reader: ReaderServices, student: Actor
) -> None:
    """LIB-7: a made-up id is a 404."""
    with pytest.raises(ItemNotFoundError):
        await reader.put_shelf_entry.execute(
            student, new_id(), ShelfState.WANT, locale="en"
        )


async def test_removing_an_entry_twice_is_harmless(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-7: DELETE answers 204 whether or not the entry existed."""
    await reader.put_shelf_entry.execute(student, book.id, ShelfState.WANT, locale="en")

    await reader.remove_shelf_entry.execute(student, book.id)
    await reader.remove_shelf_entry.execute(student, book.id)
    page = await reader.list_shelf.execute(student, locale="en")

    assert page.items == []


async def test_taken_down_item_stays_as_a_removed_row(
    reader: ReaderServices,
    student: Actor,
    store_item: StoreItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-14: a takedown keeps the title on the shelf and marks the row removed."""
    book = await store_item(make_book(title="Copyrighted"))
    await reader.put_shelf_entry.execute(student, book.id, ShelfState.READING, locale="en")
    async with uow_factory() as uow:
        stored = await uow.items.get(book.id)
        assert stored is not None
        stored.status = ItemStatus.UNPUBLISHED
        stored.description = "secret blurb"
        await uow.items.save(stored)
        await uow.commit()

    page = await reader.list_shelf.execute(student, locale="en")

    [row] = page.items
    assert row.removed
    assert row.item.title == "Copyrighted"
    assert row.item.cover_url is None
    assert row.item.description_excerpt is None
    assert row.state is ShelfState.READING


async def test_shelf_is_newest_first_with_a_cursor_and_a_state_filter(
    reader: ReaderServices,
    student: Actor,
    store_item: StoreItem,
    clock: FixedClock,
) -> None:
    """LIB-7: the list follows the last change and can be narrowed to a state."""
    ids = []
    for index, state in enumerate(
        (ShelfState.WANT, ShelfState.READING, ShelfState.WANT)
    ):
        item = await store_item(make_book(title=f"Book {index}"))
        clock.advance(minutes=1)
        await reader.put_shelf_entry.execute(student, item.id, state, locale="en")
        ids.append(item.id)

    first = await reader.list_shelf.execute(student, limit=2, locale="en")
    second = await reader.list_shelf.execute(
        student, limit=2, cursor=first.next_cursor, locale="en"
    )
    wanted = await reader.list_shelf.execute(student, state=ShelfState.WANT, locale="en")

    assert [e.item.id for e in first.items] == [ids[2], ids[1]]
    assert first.next_cursor is not None
    assert [e.item.id for e in second.items] == [ids[0]]
    assert second.next_cursor is None
    assert [e.item.id for e in wanted.items] == [ids[2], ids[0]]


async def test_shelves_are_private(
    reader: ReaderServices,
    student: Actor,
    other_student: Actor,
    librarian: Actor,
    admin: Actor,
    book: Item,
) -> None:
    """LIB-16: nobody else, librarians and Administration included, sees a shelf."""
    await reader.put_shelf_entry.execute(student, book.id, ShelfState.READING, locale="en")

    for other in (other_student, librarian, admin):
        page = await reader.list_shelf.execute(other, locale="en")
        assert page.items == []
