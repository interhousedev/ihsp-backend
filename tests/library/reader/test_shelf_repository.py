"""LIB-7: the SQL shelf keeps one entry per user and item and pages newest first."""

import datetime as dt
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, ShelfState, Visibility
from app.modules.library.domain.reader_shelf import ShelfEntry
from app.modules.library.ports.shelf_repository import ShelfCursor
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import make_book

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
StoreItem = Callable[[Item], Awaitable[Item]]


def entry(
    user_id: UUID,
    item_id: UUID | None = None,
    state: ShelfState = ShelfState.WANT,
    minutes: int = 0,
) -> ShelfEntry:
    """An entry changed `minutes` after NOW."""
    at = NOW + dt.timedelta(minutes=minutes)
    return ShelfEntry(
        user_id=user_id,
        item_id=item_id or new_id(),
        state=state,
        finished_at=at if state is ShelfState.DONE else None,
        created_at=at,
        updated_at=at,
    )


async def test_save_inserts_and_then_replaces_the_state(
    uow_factory: UowFactory,
) -> None:
    """LIB-7: a second save of the same item changes the state, not the count."""
    user = new_id()
    first = entry(user, state=ShelfState.WANT)
    async with uow_factory() as uow:
        await uow.shelf.save(first)
        await uow.shelf.save(entry(user, first.item_id, ShelfState.DONE, minutes=5))
        loaded = await uow.shelf.get(user, first.item_id)
        counts = await uow.shelf.counts(user)

    assert loaded is not None
    assert loaded.state is ShelfState.DONE
    assert loaded.finished_at == NOW + dt.timedelta(minutes=5)
    assert counts == {ShelfState.DONE: 1}


async def test_states_and_get_see_only_the_owner_entry(
    uow_factory: UowFactory,
) -> None:
    """LIB-16: another user's entry for the same item is invisible."""
    owner, stranger, item = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.shelf.save(entry(owner, item, ShelfState.READING))

        mine = await uow.shelf.states(owner, [item])
        theirs = await uow.shelf.states(stranger, [item])
        missing = await uow.shelf.get(stranger, item)

    assert mine == {item: ShelfState.READING}
    assert theirs == {}
    assert missing is None


async def test_remove_reports_whether_something_was_removed(
    uow_factory: UowFactory,
) -> None:
    """LIB-7: removing twice is harmless."""
    user = new_id()
    saved = entry(user)
    async with uow_factory() as uow:
        await uow.shelf.save(saved)

        first = await uow.shelf.remove(user, saved.item_id)
        second = await uow.shelf.remove(user, saved.item_id)

    assert (first, second) == (True, False)


async def test_list_page_is_newest_first_with_cursor_and_state_filter(
    uow_factory: UowFactory,
) -> None:
    """LIB-7: pages follow `updated_at` descending and can filter by state."""
    user = new_id()
    older = entry(user, state=ShelfState.WANT, minutes=1)
    middle = entry(user, state=ShelfState.READING, minutes=2)
    newest = entry(user, state=ShelfState.WANT, minutes=3)
    async with uow_factory() as uow:
        for saved in (older, middle, newest):
            await uow.shelf.save(saved)

        first = await uow.shelf.list_page(user, state=None, after=None, limit=2)
        rest = await uow.shelf.list_page(
            user,
            state=None,
            after=ShelfCursor(first[-1].updated_at, first[-1].item_id),
            limit=2,
        )
        wanted = await uow.shelf.list_page(
            user, state=ShelfState.WANT, after=None, limit=10
        )

    assert [e.item_id for e in first] == [newest.item_id, middle.item_id]
    assert [e.item_id for e in rest] == [older.item_id]
    assert [e.item_id for e in wanted] == [newest.item_id, older.item_id]


async def test_delete_all_clears_only_that_users_shelf(
    uow_factory: UowFactory,
) -> None:
    """LIB-16: closing an account removes the shelf and nobody else's."""
    leaving, staying = new_id(), new_id()
    async with uow_factory() as uow:
        await uow.shelf.save(entry(leaving))
        await uow.shelf.save(entry(leaving))
        await uow.shelf.save(entry(staying))

        removed = await uow.shelf.delete_all(leaving)

        assert removed == 2
        assert await uow.shelf.counts(leaving) == {}
        assert await uow.shelf.counts(staying) == {ShelfState.WANT: 1}


async def test_counts_can_leave_out_items_that_are_no_longer_listed(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-7: removed rows stay on the shelf but are not counted."""
    user = new_id()
    shown = await store_item(make_book(title="Shown"))
    taken_down = await store_item(make_book(title="Gone", status=ItemStatus.UNPUBLISHED))
    hidden = await store_item(make_book(title="Hidden", visibility=Visibility.HIDDEN))
    async with uow_factory() as uow:
        for item in (shown, taken_down, hidden):
            await uow.shelf.save(entry(user, item.id, ShelfState.READING))

        everything = await uow.shelf.counts(user)
        listed = await uow.shelf.counts(user, listed_only=True)

    assert everything == {ShelfState.READING: 3}
    assert listed == {ShelfState.READING: 1}
