"""LIB-16: the daily rollup of counters and the numbers librarians see."""

from collections.abc import Awaitable, Callable

from app.modules.library.domain.entities import Item
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from tests.factories.library import make_book

import pytest

StoreItem = Callable[[Item], Awaitable[Item]]


async def test_rollup_writes_counters_once_and_stats_show_them(
    library: LibraryServices,
    librarian: Actor,
    student: Actor,
    other_student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-16: opens and readers reach `item_stats`; a rerun changes nothing."""
    book = await store_item(make_book(title="Fizika 10"))
    stats = library.core.stats
    await stats.opened(book.id, student.user_id)
    await stats.opened(book.id, student.user_id)
    await stats.opened(book.id, other_student.user_id)

    first = await library.taxonomy.rollup_stats.execute()
    second = await library.taxonomy.rollup_stats.execute()
    view = await library.taxonomy.get_stats.execute(librarian)

    assert first == second == 1
    assert (view.opens, view.readers) == (3, 2)
    assert [(t.item.title, t.opens) for t in view.top_items] == [("Fizika 10", 3)]
    assert view.items_by_status["published"] == 1  # type: ignore[index]
    assert view.queue.length == 0


async def test_statistics_are_for_librarians_only(
    library: LibraryServices, student: Actor
) -> None:
    """LIB-16: a student gets no numbers."""
    with pytest.raises(ForbiddenError):
        await library.taxonomy.get_stats.execute(student)
