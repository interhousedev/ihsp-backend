"""LIB-10, NB-8: the student's own highlights and notes as a source."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import SourceUnsupportedError
from app.modules.notebooks.domain.source_input import LibraryNotesInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources.support import (
    add_one,
    add_ready,
    passages_of,
    stored,
)


async def test_the_notes_of_a_book_are_added_under_its_title(
    sources: SourcesServices,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: a notes source names the book and keeps the item id."""
    book = world.library.add_book("Physics 10")
    world.library.add_note(student.user_id, book)

    added = await add_one(
        sources, student, notebook, LibraryNotesInput(item_id=book.id)
    )

    assert added.kind is SourceKind.LIBRARY_NOTES
    assert added.title == "Notes on Physics 10"
    assert added.ref == {"item_id": str(book.id)}
    assert added.ref_key == f"library-notes:{book.id}"
    assert added.origin == {
        "item_id": str(book.id),
        "item_title": "Physics 10",
        "item_kind": "book",
        "author": "A. Author",
    }


async def test_notes_become_quote_and_note_lines_with_their_pages(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: "quote (p. N)" plus the note, in reading order."""
    book = world.library.add_book("Physics 10")
    world.library.add_note(student.user_id, book, quote="Second law", page=3)
    world.library.add_note(
        student.user_id,
        book,
        quote="First law",
        note="Inertia, remember",
        page=2,
        minutes=5,
    )

    ready = await add_ready(
        sources, uow_factory, student, notebook, LibraryNotesInput(item_id=book.id)
    )

    [passage] = await passages_of(uow_factory, ready.id)
    assert ready.status is SourceStatus.READY
    assert passage.text == (
        "# Highlights and notes: Physics 10\n\n"
        "> First law (p. 2)\nInertia, remember\n\n"
        "> Second law (p. 3)"
    )
    assert ready.upstream_version is not None


async def test_only_the_students_own_notes_are_read(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10, LIB-8: another student's highlights never reach this notebook."""
    book = world.library.add_book()
    world.library.add_note(student.user_id, book, quote="mine")
    world.library.add_note(other_student.user_id, book, quote="theirs")

    ready = await add_ready(
        sources, uow_factory, student, notebook, LibraryNotesInput(item_id=book.id)
    )

    [passage] = await passages_of(uow_factory, ready.id)
    assert "mine" in passage.text
    assert "theirs" not in passage.text


async def test_a_book_without_notes_is_refused(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: there is nothing to learn from yet."""
    book = world.library.add_book()

    result = await sources.add_sources.execute(
        student, notebook.id, [LibraryNotesInput(item_id=book.id)]
    )

    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    assert error.params == {"hint": "no_notes"}


async def test_new_notes_make_the_source_outdated_and_a_sync_reads_them(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10, NB-8: highlights added later are offered as an update."""
    book = world.library.add_book()
    world.library.add_note(student.user_id, book, quote="first")
    ready = await add_ready(
        sources, uow_factory, student, notebook, LibraryNotesInput(item_id=book.id)
    )
    world.library.add_note(student.user_id, book, quote="added later", page=4)

    assert await sources.sweep_sources.execute() == 1
    assert (await stored(uow_factory, ready.id)).status is SourceStatus.STALE
    await sources.sync_source.execute(student, notebook.id, ready.id)
    await sources.process_source.execute(ready.id)

    [passage] = await passages_of(uow_factory, ready.id)
    assert "added later" in passage.text
    assert (await stored(uow_factory, ready.id)).status is SourceStatus.READY


async def test_unchanged_notes_are_left_alone_by_the_sweep(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: no change, no stale mark."""
    book = world.library.add_book()
    world.library.add_note(student.user_id, book)
    await add_ready(
        sources, uow_factory, student, notebook, LibraryNotesInput(item_id=book.id)
    )

    assert await sources.sweep_sources.execute() == 0
