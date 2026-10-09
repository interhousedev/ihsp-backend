"""LIB-8, LIB-9: My library: continue reading, shelf counts, offline limits."""

import datetime as dt

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, ShelfState
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.modules.library.wiring_reader import ReaderServices
from app.shared.actor import Actor
from tests.factories.library import make_book
from tests.fakes.clock import FixedClock
from tests.library.reader.helpers import StoreItem


async def read(
    reader: ReaderServices,
    actor: Actor,
    item: Item,
    clock: FixedClock,
    *,
    percent: float = 10,
) -> None:
    """Report progress now (the clock moves a minute first so the order is clear)."""
    clock.advance(minutes=1)
    await reader.save_progress.execute(
        actor,
        item.id,
        file_id=item.files[0].file_id,
        locator={"page": 1},
        percent=percent,
        client_ts=clock.now() - dt.timedelta(seconds=1),
        seconds_read=None,
    )


async def test_continue_reading_is_the_last_six_unfinished_items_newest_first(
    reader: ReaderServices, student: Actor, store_item: StoreItem, clock: FixedClock
) -> None:
    """LIB-8: seven books are started, one is finished; six are offered."""
    books = [await store_item(make_book(title=f"Book {i}")) for i in range(8)]
    for index, item in enumerate(books):
        await read(reader, student, item, clock, percent=100 if index == 3 else 10)

    page = await reader.get_me_library.execute(student, locale="en")

    expected = [b.id for i, b in reversed(list(enumerate(books))) if i != 3][:6]
    assert [card.id for card in page.continue_reading] == expected


async def test_continue_reading_skips_items_the_user_can_no_longer_read(
    reader: ReaderServices,
    student: Actor,
    store_item: StoreItem,
    clock: FixedClock,
    uow_factory: UowFactory,
) -> None:
    """LIB-14: a taken-down book leaves the row; the others stay."""
    kept = await store_item(make_book(title="Kept"))
    removed = await store_item(make_book(title="Removed"))
    await read(reader, student, kept, clock)
    await read(reader, student, removed, clock)
    async with uow_factory() as uow:
        item = await uow.items.get(removed.id)
        assert item is not None
        item.status = ItemStatus.UNPUBLISHED
        await uow.items.save(item)
        await uow.commit()

    page = await reader.get_me_library.execute(student, locale="en")

    assert [card.id for card in page.continue_reading] == [kept.id]


async def test_shelf_counts_cover_all_states_and_skip_removed_rows(
    reader: ReaderServices,
    student: Actor,
    store_item: StoreItem,
    taken_down: Item,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-7: zero counts are present; removed rows are not counted."""
    first = await store_item(make_book(title="One"))
    second = await store_item(make_book(title="Two"))
    gone = await store_item(make_book(title="Soon gone"))
    await reader.put_shelf_entry.execute(student, first.id, ShelfState.WANT, locale="en")
    await reader.put_shelf_entry.execute(student, second.id, ShelfState.WANT, locale="en")
    await reader.put_shelf_entry.execute(student, gone.id, ShelfState.READING, locale="en")
    async with uow_factory() as uow:
        item = await uow.items.get(gone.id)
        assert item is not None
        item.status = ItemStatus.UNPUBLISHED
        await uow.items.save(item)
        await uow.commit()

    page = await reader.get_me_library.execute(student, locale="en")

    assert page.shelf_counts == {
        ShelfState.WANT: 2,
        ShelfState.READING: 0,
        ShelfState.DONE: 0,
    }


async def test_offline_limits_come_from_the_settings(
    reader: ReaderServices, library: LibraryServices, student: Actor
) -> None:
    """LIB-9: the app is told how much it may keep on the device."""
    page = await reader.get_me_library.execute(student, locale="en")

    assert page.offline_max_items == library.core.settings.offline_max_items
    assert page.offline_max_bytes == library.core.settings.offline_max_bytes
