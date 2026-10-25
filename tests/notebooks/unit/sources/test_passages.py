"""NB-3, NB-6, NB-15: the passages of a source, page by page, and one passage."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from app.shared.pagination import encode_cursor
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.clock import FixedClock
from tests.notebooks.unit.sources.support import passages_of

import pytest


def _texts(count: int) -> tuple[str, ...]:
    return tuple(f"Passage {n} of the source." for n in range(1, count + 1))


async def _source(uow_factory: UowFactory, notebook: Notebook, count: int) -> Source:
    return await make_source(uow_factory, notebook, texts=_texts(count))


# - - - Paging - - -


async def test_passages_come_in_reading_order_page_by_page(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: the cursor continues after the last `seq` of the page."""
    source = await _source(uow_factory, notebook, 7)

    first = await sources.list_passages.execute(
        student, notebook.id, source.id, limit=3
    )
    second = await sources.list_passages.execute(
        student, notebook.id, source.id, first.next_cursor, 3
    )
    third = await sources.list_passages.execute(
        student, notebook.id, source.id, second.next_cursor, 3
    )

    assert [p.seq for p in first.items] == [1, 2, 3]
    assert [p.seq for p in second.items] == [4, 5, 6]
    assert [p.seq for p in third.items] == [7]
    assert first.next_cursor is not None
    assert second.next_cursor is not None
    assert third.next_cursor is None
    assert first.items[0].text == "Passage 1 of the source."


async def test_a_page_has_60_passages_by_default_and_200_at_most(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: no or a non-positive limit gives 60; a larger one is cut to 200."""
    source = await _source(uow_factory, notebook, 205)

    default = await sources.list_passages.execute(student, notebook.id, source.id)
    zero = await sources.list_passages.execute(student, notebook.id, source.id, limit=0)
    biggest = await sources.list_passages.execute(
        student, notebook.id, source.id, limit=500
    )
    rest = await sources.list_passages.execute(
        student, notebook.id, source.id, biggest.next_cursor, 500
    )

    assert len(default.items) == len(zero.items) == 60
    assert default.next_cursor is not None
    assert len(biggest.items) == 200
    assert [p.seq for p in rest.items] == [201, 202, 203, 204, 205]
    assert rest.next_cursor is None


async def test_a_source_without_passages_has_an_empty_page(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: a source that is not read yet lists nothing."""
    source = await make_source(uow_factory, notebook, texts=())

    page = await sources.list_passages.execute(student, notebook.id, source.id)

    assert (page.items, page.next_cursor) == ([], None)


@pytest.mark.parametrize("cursor", ["not a cursor!", "WzFd"])
async def test_a_malformed_cursor_is_a_validation_error(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    cursor: str,
) -> None:
    """NB-3: a cursor that is not ours is a 422 naming the field."""
    source = await _source(uow_factory, notebook, 3)

    with pytest.raises(ValidationFailedError) as raised:
        await sources.list_passages.execute(student, notebook.id, source.id, cursor)

    assert raised.value.params == {"field": "cursor"}


async def test_a_cursor_with_an_unusable_position_starts_from_the_top(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: a negative position counts as the first page."""
    source = await _source(uow_factory, notebook, 3)

    page = await sources.list_passages.execute(
        student, notebook.id, source.id, encode_cursor({"seq": -5})
    )

    assert [p.seq for p in page.items] == [1, 2, 3]


async def test_passages_of_another_students_or_another_notebooks_source_are_a_404(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
    clock: FixedClock,
) -> None:
    """NB-15: foreign, misplaced, unknown and deleted-notebook cases look alike."""
    source = await _source(uow_factory, notebook, 2)
    elsewhere = await make_notebook(uow_factory, student.user_id)
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=clock.now())
    in_gone = await _source(uow_factory, gone, 1)

    for actor, notebook_id, source_id in (
        (other_student, notebook.id, source.id),
        (other_student, their_notebook.id, source.id),
        (student, elsewhere.id, source.id),
        (student, notebook.id, new_id()),
        (student, gone.id, in_gone.id),
    ):
        with pytest.raises(NotebookNotFoundError):
            await sources.list_passages.execute(actor, notebook_id, source_id)


# - - - One passage - - -


async def test_a_passage_comes_with_its_source_and_its_neighbours(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-6: the citation popover shows the passage between the ones around it."""
    source = await _source(uow_factory, notebook, 7)
    middle = (await passages_of(uow_factory, source.id))[3]

    detail = await sources.get_passage.execute(student, notebook.id, middle.id, 2)

    assert detail.passage == middle
    assert detail.source.id == source.id
    assert [p.seq for p in detail.before] == [2, 3]
    assert [p.seq for p in detail.after] == [5, 6]


async def test_the_first_passage_has_nothing_before_it(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-6: neighbours stop at the ends of the source."""
    source = await _source(uow_factory, notebook, 3)
    first = (await passages_of(uow_factory, source.id))[0]

    detail = await sources.get_passage.execute(student, notebook.id, first.id, 2)

    assert detail.before == []
    assert [p.seq for p in detail.after] == [2, 3]


@pytest.mark.parametrize(("asked", "around"), [(0, 0), (-3, 0), (99, 5)])
async def test_the_context_is_between_zero_and_five_passages(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    asked: int,
    around: int,
) -> None:
    """NB-6: no context by default; never more than five on each side."""
    source = await _source(uow_factory, notebook, 13)
    middle = (await passages_of(uow_factory, source.id))[6]

    detail = await sources.get_passage.execute(student, notebook.id, middle.id, asked)

    assert (len(detail.before), len(detail.after)) == (around, around)


async def test_another_students_passage_is_a_404(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-15: knowing a passage id gives no access to someone else's text."""
    source = await _source(uow_factory, notebook, 2)
    passage = (await passages_of(uow_factory, source.id))[0]

    for actor, notebook_id in (
        (other_student, notebook.id),
        (other_student, their_notebook.id),
    ):
        with pytest.raises(NotebookNotFoundError):
            await sources.get_passage.execute(actor, notebook_id, passage.id)


async def test_a_passage_of_another_notebook_or_a_removed_source_is_a_404(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-6: the passage must belong to the notebook in the path and still exist."""
    source = await _source(uow_factory, notebook, 2)
    elsewhere = await make_notebook(uow_factory, student.user_id)
    passage = (await passages_of(uow_factory, source.id))[0]

    for notebook_id, passage_id in (
        (elsewhere.id, passage.id),
        (notebook.id, new_id()),
    ):
        with pytest.raises(NotebookNotFoundError):
            await sources.get_passage.execute(student, notebook_id, passage_id)

    await sources.remove_source.execute(student, notebook.id, source.id)
    with pytest.raises(NotebookNotFoundError):
        await sources.get_passage.execute(student, notebook.id, passage.id)
