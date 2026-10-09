"""LIB-6, LIB-9, LIB-16: reading progress of books and materials."""

import datetime as dt

from app.modules.library.domain.entities import Item
from app.modules.library.domain.errors import ItemNotFoundError, NotSupportedError
from app.modules.library.domain.reader_errors import (
    FileNotInItemError,
    InvalidLocatorError,
)
from app.modules.library.domain.reader_progress import ReadingProgress
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring_reader import ReaderServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

import pytest


def ago(clock: FixedClock, seconds: float) -> dt.datetime:
    """A client timestamp `seconds` before the server's now."""
    return clock.now() - dt.timedelta(seconds=seconds)


async def report(
    reader: ReaderServices,
    actor: Actor,
    item: Item,
    clock: FixedClock,
    *,
    page: int = 1,
    percent: float = 10,
    seconds_ago: float = 60,
    seconds: int | None = None,
) -> None:
    """Send one progress report for the item's first file."""
    await reader.save_progress.execute(
        actor,
        item.id,
        file_id=item.files[0].file_id,
        locator={"page": page},
        percent=percent,
        client_ts=ago(clock, seconds_ago),
        seconds_read=seconds,
    )


async def stored(
    uow_factory: UowFactory, actor: Actor, item: Item
) -> ReadingProgress:
    """The stored progress of the actor in the item."""
    async with uow_factory() as uow:
        progress = await uow.progress.get(actor.user_id, item.id)
    assert progress is not None
    return progress


async def test_progress_is_saved_and_shows_on_the_card(
    reader: ReaderServices,
    student: Actor,
    book: Item,
    clock: FixedClock,
    uow_factory: UowFactory,
) -> None:
    """LIB-6: the position is stored and the card of the book shows the percent."""
    await report(reader, student, book, clock, page=54, percent=45.5, seconds=30)

    progress = await stored(uow_factory, student, book)
    page = await reader.get_me_library.execute(student, locale="en")

    assert progress.locator == {"page": 54}
    assert progress.seconds_read == 30
    assert page.continue_reading[0].progress_percent == 45.5


async def test_older_report_is_ignored_and_newer_wins(
    reader: ReaderServices,
    student: Actor,
    book: Item,
    clock: FixedClock,
    uow_factory: UowFactory,
) -> None:
    """LIB-9: reports arriving out of order keep the latest position."""
    await report(reader, student, book, clock, page=20, percent=20, seconds_ago=10)
    await report(reader, student, book, clock, page=5, percent=5, seconds_ago=500)
    await report(reader, student, book, clock, page=30, percent=30, seconds_ago=5)

    progress = await stored(uow_factory, student, book)

    assert progress.locator == {"page": 30}
    assert progress.percent == 30


async def test_reading_does_not_change_the_shelf(
    reader: ReaderServices, student: Actor, book: Item, clock: FixedClock
) -> None:
    """LIB-7: progress never moves an item on the shelf by itself."""
    await report(reader, student, book, clock, percent=99)

    shelf = await reader.list_shelf.execute(student, locale="en")

    assert shelf.items == []


async def test_unilibrary_record_cannot_have_progress(
    reader: ReaderServices, student: Actor, external: Item
) -> None:
    """LIB-12: link-only records answer `library/not-supported`."""
    with pytest.raises(NotSupportedError):
        await reader.save_progress.execute(
            student,
            external.id,
            file_id=new_id(),
            locator={"page": 1},
            percent=1,
            client_ts=dt.datetime(2026, 10, 6, 8, tzinfo=dt.UTC),
            seconds_read=None,
        )


async def test_item_the_user_cannot_read_is_not_found(
    reader: ReaderServices,
    student: Actor,
    taken_down: Item,
    clock: FixedClock,
) -> None:
    """LIB-1: no progress on held or taken-down items."""
    with pytest.raises(ItemNotFoundError):
        await report(reader, student, taken_down, clock)


async def test_file_of_another_item_is_refused(
    reader: ReaderServices, student: Actor, book: Item, material: Item, clock: FixedClock
) -> None:
    """LIB-6: the file must belong to the item."""
    with pytest.raises(FileNotInItemError):
        await reader.save_progress.execute(
            student,
            book.id,
            file_id=material.files[0].file_id,
            locator={"page": 1},
            percent=1,
            client_ts=ago(clock, 5),
            seconds_read=None,
        )


async def test_pdf_progress_needs_a_page_locator(
    reader: ReaderServices, student: Actor, book: Item, clock: FixedClock
) -> None:
    """LIB-6: an EPUB-style locator on a PDF is refused."""
    with pytest.raises(InvalidLocatorError):
        await reader.save_progress.execute(
            student,
            book.id,
            file_id=book.files[0].file_id,
            locator={"cfi": "epubcfi(/6)", "progress": 0.3},
            percent=30,
            client_ts=ago(clock, 5),
            seconds_read=None,
        )


async def test_progress_is_private(
    reader: ReaderServices,
    student: Actor,
    other_student: Actor,
    librarian: Actor,
    book: Item,
    clock: FixedClock,
) -> None:
    """LIB-16: others see no progress on their cards and nothing to continue."""
    await report(reader, student, book, clock, percent=60)

    for other in (other_student, librarian):
        page = await reader.get_me_library.execute(other, locale="en")
        assert page.continue_reading == []
