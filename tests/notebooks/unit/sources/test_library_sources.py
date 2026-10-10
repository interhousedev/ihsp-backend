"""LIB-10, NB-2: library books and materials as notebook sources."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    LibraryNotSupportedError,
    SourceDuplicateError,
    SourceForbiddenError,
    SourceTooLargeError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import (
    LibraryItemInput,
    LibraryNotesInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import (
    PROCESS_TASK,
    add_one,
    add_ready,
    passages_of,
    stored,
)

import pytest

# - - - Adding a book or a chapter - - -


async def test_a_whole_book_is_added_pending_under_its_title(
    sources: SourcesServices,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """LIB-10: no range, no pages in the title; the primary file is read."""
    book = world.library.add_book("Physics 10")

    added = await add_one(sources, student, notebook, LibraryItemInput(item_id=book.id))

    assert added.kind is SourceKind.LIBRARY_ITEM
    assert added.status is SourceStatus.PENDING
    assert added.title == "Physics 10"
    assert added.ref == {
        "item_id": str(book.id),
        "file_id": str(book.file_id),
        "format": "pdf",
        "format": "pdf",
    }
    assert added.ref_key == f"library:{book.file_id}:1:0"
    assert added.origin == {
        "item_id": str(book.id),
        "item_title": "Physics 10",
        "item_kind": "book",
        "author": "A. Author",
    }
    assert kicker.calls == [(PROCESS_TASK, {"source_id": str(added.id)})]


async def test_a_chapter_shows_its_pages_in_the_title(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: "Physics 10, pp. 2-3" tells the source from the whole book."""
    book = world.library.add_book("Physics 10")

    added = await add_one(
        sources,
        student,
        notebook,
        LibraryItemInput(item_id=book.id, file_id=book.file_id, page_from=2, page_to=3),
    )

    assert added.title == "Physics 10, pp. 2-3"
    assert added.ref == {
        "item_id": str(book.id),
        "file_id": str(book.file_id),
        "format": "pdf",
        "page_from": 2,
        "page_to": 3,
    }
    assert added.ref_key == f"library:{book.file_id}:2:3"
    assert added.origin is not None
    assert (added.origin["page_from"], added.origin["page_to"]) == (2, 3)


async def test_the_same_chapter_twice_is_a_duplicate_but_another_chapter_is_not(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: ranges of one book are separate sources."""
    book = world.library.add_book()
    chapter = LibraryItemInput(item_id=book.id, page_from=1, page_to=2)
    await add_one(sources, student, notebook, chapter)

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [chapter, LibraryItemInput(item_id=book.id, page_from=3, page_to=4)],
    )

    assert [r.index for r in result.rejected] == [0]
    assert isinstance(result.rejected[0].error, SourceDuplicateError)
    assert [s.title for s in result.items] == ["Physics 10, pp. 3-4"]


async def test_a_chapter_is_read_with_its_real_page_numbers(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10, NB-3: citations say p. 3 for page 3 of the book, not p. 1."""
    book = world.library.add_book("Physics 10")

    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LibraryItemInput(item_id=book.id, page_from=3, page_to=4),
    )

    passages = await passages_of(uow_factory, ready.id)
    assert ready.status is SourceStatus.READY
    assert ready.title == "Physics 10, pp. 3-4"
    assert [p.page for p in passages] == [3, 4]
    assert "second law" in passages[0].text
    assert "Energy is conserved" in passages[1].text


async def test_a_whole_book_keeps_the_page_numbers_of_the_file(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: without a range the pages start at 1."""
    book = world.library.add_book()

    ready = await add_ready(
        sources, uow_factory, student, notebook, LibraryItemInput(item_id=book.id)
    )

    assert [p.page for p in await passages_of(uow_factory, ready.id)] == [1, 2, 3, 4]


async def test_a_material_is_a_source_too(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: materials of teachers and students work like books."""
    material = world.library.add_book("Kinematics notes", kind="material")

    added = await add_one(
        sources, student, notebook, LibraryItemInput(item_id=material.id)
    )

    assert added.origin is not None
    assert added.origin["item_kind"] == "material"


# - - - Refusals when adding - - -


async def test_a_unilibrary_record_is_refused_with_the_librarys_problem_type(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10, LIB-2: `library/not-supported`, status 409."""
    record = world.library.add_external()

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [LibraryItemInput(item_id=record.id), LibraryNotesInput(item_id=record.id)],
    )

    assert result.items == []
    for rejected in result.rejected:
        assert isinstance(rejected.error, LibraryNotSupportedError)
        assert (rejected.error.code, rejected.error.status) == (
            "library/not-supported",
            409,
        )


async def test_a_book_the_student_may_not_read_looks_like_a_missing_one(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: a student without access gets the same answer as for an unknown id."""
    closed = world.library.add_book(readers=(new_id(),))

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [LibraryItemInput(item_id=closed.id), LibraryItemInput(item_id=new_id())],
    )

    assert [type(r.error) for r in result.rejected] == [SourceForbiddenError] * 2


async def test_a_held_book_cannot_be_added(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: held and taken-down items are not sources."""
    book = world.library.add_book()
    world.library.hold(book)

    result = await sources.add_sources.execute(
        student, notebook.id, [LibraryItemInput(item_id=book.id)]
    )

    assert isinstance(result.rejected[0].error, SourceForbiddenError)


async def test_a_file_of_another_item_is_refused(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: the file must belong to the item."""
    book = world.library.add_book()
    other = world.library.add_book("Chemistry 10")

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [LibraryItemInput(item_id=book.id, file_id=other.file_id)],
    )

    assert isinstance(result.rejected[0].error, SourceForbiddenError)


@pytest.mark.parametrize("text_status", ["none", "no_text", "failed", "pending"])
async def test_a_scan_without_text_is_refused_with_a_hint(
    sources: SourcesServices,
    world: World,
    student: Actor,
    notebook: Notebook,
    text_status: str,
) -> None:
    """LIB-10: "scanned pages have no text": the message comes at add time."""
    scan = world.library.add_book("Old atlas", text_status=text_status)

    result = await sources.add_sources.execute(
        student, notebook.id, [LibraryItemInput(item_id=scan.id)]
    )

    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    expected = "not_ready" if text_status == "pending" else "no_text"
    assert error.params == {"hint": expected}


async def test_pages_beyond_the_book_are_refused(
    sources: SourcesServices, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: a range with no pages in it has no text."""
    book = world.library.add_book()

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [LibraryItemInput(item_id=book.id, page_from=40, page_to=50)],
    )

    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    assert error.params == {"hint": "no_text"}


async def test_a_whole_textbook_over_the_limit_asks_for_a_chapter(
    build: Build, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: the 600 000-character rule (here 2 000) names the way out."""
    sources = build(notebooks={"source_max_chars": 2000})
    textbook = world.library.add_book(
        "Big textbook", tuple(f"Page {n}. " + "word " * 150 for n in range(1, 6))
    )

    result = await sources.add_sources.execute(
        student, notebook.id, [LibraryItemInput(item_id=textbook.id)]
    )
    chapter = await sources.add_sources.execute(
        student,
        notebook.id,
        [LibraryItemInput(item_id=textbook.id, page_from=1, page_to=2)],
    )

    error = result.rejected[0].error
    assert isinstance(error, SourceTooLargeError)
    assert error.params["hint"] == "range"
    assert error.params["limit"] == 2000
    assert chapter.rejected == []
    assert [s.title for s in chapter.items] == ["Big textbook, pp. 1-2"]


async def test_without_a_library_the_kinds_are_unsupported(
    build: Build, world: World, student: Actor, notebook: Notebook
) -> None:
    """LIB-10: a process that has no library module cannot add these kinds."""
    sources = build(library=False)
    book = world.library.add_book()

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [LibraryItemInput(item_id=book.id), LibraryNotesInput(item_id=book.id)],
    )

    assert [type(r.error) for r in result.rejected] == [SourceUnsupportedError] * 2


# - - - Shared documents - - -


async def test_one_chapter_read_by_two_students_is_processed_once(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """LIB-10, NB-14: the second student's source reuses the shared document."""
    book = world.library.add_book()
    chapter = LibraryItemInput(item_id=book.id, page_from=2, page_to=3)
    first = await add_ready(sources, uow_factory, student, notebook, chapter)
    second = await add_one(sources, other_student, their_notebook, chapter)
    reads_before = world.library.calls.count("read_text")

    await sources.process_source.execute(second.id)

    shared = await stored(uow_factory, second.id)
    assert world.library.calls.count("read_text") == reads_before
    assert shared.status is SourceStatus.READY
    assert shared.document_id == first.document_id
    assert shared.document_id is not None


async def test_another_chapter_is_another_document(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """LIB-10: the shared document is keyed by file and pages."""
    book = world.library.add_book()
    first = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LibraryItemInput(item_id=book.id, page_from=1, page_to=2),
    )
    second = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        LibraryItemInput(item_id=book.id, page_from=3, page_to=4),
    )

    assert first.document_id != second.document_id


async def test_a_shared_document_is_not_handed_to_someone_who_lost_access(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """LIB-10, LIB-7: a held book's text is not reused for a source added before."""
    book = world.library.add_book()
    item = LibraryItemInput(item_id=book.id)
    await add_ready(sources, uow_factory, student, notebook, item)
    waiting = await add_one(sources, other_student, their_notebook, item)
    world.library.hold(book)

    await sources.process_source.execute(waiting.id)

    result = await stored(uow_factory, waiting.id)
    assert result.status is SourceStatus.UNAVAILABLE
    assert result.document_id is None
