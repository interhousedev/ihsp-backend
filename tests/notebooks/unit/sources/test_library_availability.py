"""LIB-10, LIB-7: a held or taken-down item turns its sources `unavailable`."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceFailure,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.source_input import (
    LibraryItemInput,
    LibraryNotesInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.notebooks.library import FakeBook
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.support import (
    PROCESS_TASK,
    add_one,
    add_ready,
    passages_of,
    stored,
    stored_notebook,
)

import pytest


async def ready_chapter(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> tuple[FakeBook, Source]:
    """A book with a ready source for pages 2 and 3."""
    book = world.library.add_book("Physics 10")
    source = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LibraryItemInput(item_id=book.id, page_from=2, page_to=3),
    )
    assert source.status is SourceStatus.READY
    return book, source


# - - - Processing - - -


async def test_a_book_held_before_processing_makes_the_source_unavailable(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: the reader re-checks access when the text is read."""
    book = world.library.add_book()
    added = await add_one(sources, student, notebook, LibraryItemInput(item_id=book.id))
    world.library.hold(book)

    await sources.process_source.execute(added.id)

    result = await stored(uow_factory, added.id)
    assert result.status is SourceStatus.UNAVAILABLE
    assert result.failure is SourceFailure.FORBIDDEN
    assert (result.document_id, result.passage_count) == (None, 0)
    assert await passages_of(uow_factory, added.id) == []
    assert (await stored_notebook(uow_factory, notebook.id)).source_count == 1


async def test_a_book_removed_before_processing_is_reported_as_deleted(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: a vanished item reads as `deleted`."""
    book = world.library.add_book()
    added = await add_one(sources, student, notebook, LibraryItemInput(item_id=book.id))
    del world.library.books[book.id]

    await sources.process_source.execute(added.id)

    result = await stored(uow_factory, added.id)
    assert (result.status, result.failure) == (
        SourceStatus.UNAVAILABLE,
        SourceFailure.DELETED,
    )


# - - - The daily sweep - - -


async def test_the_sweep_turns_the_sources_of_a_taken_down_book_unavailable(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10, LIB-7: within a day the text of a taken-down book is gone."""
    book, chapter = await ready_chapter(sources, uow_factory, world, student, notebook)
    world.library.add_note(student.user_id, book)
    notes = await add_ready(
        sources, uow_factory, student, notebook, LibraryNotesInput(item_id=book.id)
    )
    world.library.hold(book)

    assert await sources.sweep_sources.execute() == 2

    for source_id in (chapter.id, notes.id):
        gone = await stored(uow_factory, source_id)
        assert gone.status is SourceStatus.UNAVAILABLE
        assert gone.failure is SourceFailure.FORBIDDEN
        assert (gone.document_id, gone.passage_count, gone.char_count) == (None, 0, 0)
        assert (gone.guide, gone.guide_status) == (None, GuideStatus.NONE)
        assert await passages_of(uow_factory, source_id) == []
    assert (await stored(uow_factory, chapter.id)).title == "Physics 10, pp. 2-3"
    assert (await stored_notebook(uow_factory, notebook.id)).char_count == 0


async def test_a_second_sweep_has_nothing_left_to_do(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: unavailable sources are not touched again while the item is held."""
    book, _ = await ready_chapter(sources, uow_factory, world, student, notebook)
    world.library.hold(book)

    assert await sources.sweep_sources.execute() == 1
    assert await sources.sweep_sources.execute() == 0


async def test_healthy_library_sources_are_left_alone(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: the sweep must not mistake a chapter for a deleted file."""
    _, chapter = await ready_chapter(sources, uow_factory, world, student, notebook)

    assert await sources.sweep_sources.execute() == 0
    assert (await stored(uow_factory, chapter.id)).status is SourceStatus.READY


async def test_a_student_who_lost_access_loses_the_source(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: access is the student's, not the book's alone."""
    book, chapter = await ready_chapter(sources, uow_factory, world, student, notebook)
    book.readers = set()

    assert await sources.sweep_sources.execute() == 1

    assert (await stored(uow_factory, chapter.id)).status is SourceStatus.UNAVAILABLE


async def test_the_sweep_checks_each_owner_of_a_shared_chapter(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """LIB-10: one student keeps the source while the other loses access."""
    book = world.library.add_book()
    item = LibraryItemInput(item_id=book.id)
    mine = await add_ready(sources, uow_factory, student, notebook, item)
    theirs = await add_ready(sources, uow_factory, other_student, their_notebook, item)
    book.readers = {student.user_id}

    assert await sources.sweep_sources.execute() == 1

    assert (await stored(uow_factory, mine.id)).status is SourceStatus.READY
    assert (await stored(uow_factory, theirs.id)).status is SourceStatus.UNAVAILABLE


# - - - Recovery - - -


async def test_a_restored_book_brings_the_source_back_with_the_next_sweep(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """LIB-10, LIB-7: restore reopens the source; it is read again at once."""
    book, chapter = await ready_chapter(sources, uow_factory, world, student, notebook)
    world.library.hold(book)
    await sources.sweep_sources.execute()
    world.library.restore(book)
    kicker.calls.clear()

    assert await sources.sweep_sources.execute() == 1
    waiting = await stored(uow_factory, chapter.id)
    await sources.process_source.execute(chapter.id)

    assert waiting.status is SourceStatus.PENDING
    assert kicker.calls[0] == (PROCESS_TASK, {"source_id": str(chapter.id)})
    back = await stored(uow_factory, chapter.id)
    assert back.status is SourceStatus.READY
    assert back.failure is None
    assert [p.page for p in await passages_of(uow_factory, chapter.id)] == [2, 3]


async def test_the_sweep_keeps_a_source_unavailable_while_the_book_is_held(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: no flapping between the states."""
    book, chapter = await ready_chapter(sources, uow_factory, world, student, notebook)
    world.library.hold(book)
    await sources.sweep_sources.execute()

    await sources.sweep_sources.execute()

    assert (await stored(uow_factory, chapter.id)).status is SourceStatus.UNAVAILABLE


async def test_syncing_after_a_restore_makes_the_source_ready_again(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: the Sync button recovers an unavailable library source."""
    book, chapter = await ready_chapter(sources, uow_factory, world, student, notebook)
    world.library.hold(book)
    await sources.sweep_sources.execute()
    world.library.restore(book)

    synced = await sources.sync_source.execute(student, notebook.id, chapter.id)
    await sources.process_source.execute(chapter.id)

    assert synced.status is SourceStatus.PENDING
    assert (await stored(uow_factory, chapter.id)).status is SourceStatus.READY


async def test_syncing_while_the_book_is_still_held_leaves_it_unavailable(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: a failed sync does not pretend to succeed."""
    book, chapter = await ready_chapter(sources, uow_factory, world, student, notebook)
    world.library.hold(book)
    await sources.sweep_sources.execute()

    await sources.sync_source.execute(student, notebook.id, chapter.id)
    await sources.process_source.execute(chapter.id)

    result = await stored(uow_factory, chapter.id)
    assert (result.status, result.failure) == (
        SourceStatus.UNAVAILABLE,
        SourceFailure.FORBIDDEN,
    )


@pytest.mark.parametrize("kind", [SourceKind.LIBRARY_ITEM, SourceKind.LIBRARY_NOTES])
async def test_both_library_kinds_can_be_synced(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kind: SourceKind,
) -> None:
    """LIB-10, NB-8: the Sync button works for books and for notes."""
    book = world.library.add_book()
    world.library.add_note(student.user_id, book)
    item = (
        LibraryItemInput(item_id=book.id)
        if kind is SourceKind.LIBRARY_ITEM
        else LibraryNotesInput(item_id=book.id)
    )
    ready = await add_ready(sources, uow_factory, student, notebook, item)

    synced = await sources.sync_source.execute(student, notebook.id, ready.id)

    assert synced.status is SourceStatus.PENDING
