"""NB-3, NB-5, NB-15: listing, ticking and removing sources."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SummaryStatus
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.source_input import FileInput, TextInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import make_file
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources.support import (
    add_ready,
    passages_of,
    stored_notebook,
)

import pytest

TEXT = "Photosynthesis turns light into chemical energy in plants."


async def _two(
    sources: SourcesServices, uow_factory: UowFactory, student: Actor, nb: Notebook
) -> tuple[Source, Source]:
    first = await add_ready(
        sources, uow_factory, student, nb, TextInput(title="First", text=TEXT)
    )
    second = await add_ready(
        sources, uow_factory, student, nb, TextInput(title="Second", text=TEXT + " x")
    )
    return first, second


# - - - List - - -


async def test_sources_are_listed_in_the_order_of_the_panel(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: ordered by position, whatever their status."""
    third = await make_source(uow_factory, notebook, title="Third", position=3)
    first = await make_source(uow_factory, notebook, title="First", position=1)
    second = await make_source(uow_factory, notebook, title="Second", position=2)

    listed = await sources.list_sources.execute(student, notebook.id)

    assert [s.id for s in listed] == [first.id, second.id, third.id]


async def test_an_empty_notebook_has_no_sources(
    sources: SourcesServices, student: Actor, notebook: Notebook
) -> None:
    """NB-3: an empty list, not an error."""
    assert await sources.list_sources.execute(student, notebook.id) == []


async def test_deleted_and_foreign_notebooks_cannot_be_listed(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    their_notebook: Notebook,
    clock: FixedClock,
) -> None:
    """NB-15: a deleted notebook and someone else's look alike: 404."""
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=clock.now())

    for notebook_id in (gone.id, their_notebook.id, new_id()):
        with pytest.raises(NotebookNotFoundError):
            await sources.list_sources.execute(student, notebook_id)


# - - - Select - - -


async def test_all_sources_can_be_unticked_and_ticked(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-5: no ids means every source; the whole list comes back."""
    await _two(sources, uow_factory, student, notebook)

    none = await sources.select_sources.execute(student, notebook.id, False)
    assert [s.selected for s in none] == [False, False]
    cleared = await stored_notebook(uow_factory, notebook.id)
    assert (cleared.summary_status, cleared.summary_due_at) == (
        SummaryStatus.NONE,
        None,
    )

    everything = await sources.select_sources.execute(student, notebook.id, True)
    assert [s.selected for s in everything] == [True, True]
    assert (
        await stored_notebook(uow_factory, notebook.id)
    ).summary_status is SummaryStatus.STALE


async def test_only_the_given_sources_are_changed(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-5: ticking is per source; an empty id list changes nothing."""
    _, second = await _two(sources, uow_factory, student, notebook)

    await sources.select_sources.execute(student, notebook.id, False)
    some = await sources.select_sources.execute(student, notebook.id, True, [second.id])
    nothing = await sources.select_sources.execute(student, notebook.id, True, [])

    assert [(s.title, s.selected) for s in some] == [("First", False), ("Second", True)]
    assert [s.selected for s in nothing] == [False, True]


async def test_ids_of_another_notebook_are_ignored(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-5, NB-15: a source of someone else's notebook is not touched."""
    theirs = await make_source(uow_factory, their_notebook)

    await sources.select_sources.execute(student, notebook.id, False, [theirs.id])

    async with uow_factory() as uow:
        stored = await uow.sources.get(theirs.id)
    assert stored is not None and stored.selected


async def test_only_the_owner_can_tick_sources(
    sources: SourcesServices, other_student: Actor, notebook: Notebook
) -> None:
    """NB-15: ticking in someone else's notebook is a 404."""
    with pytest.raises(NotebookNotFoundError):
        await sources.select_sources.execute(other_student, notebook.id, False)


# - - - Remove - - -


async def test_removing_a_source_deletes_its_passages_and_recounts(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-3: the row and its passages go at once; the counters follow."""
    first, second = await _two(sources, uow_factory, student, notebook)
    old = await passages_of(uow_factory, first.id)

    await sources.remove_source.execute(student, notebook.id, first.id)

    listed = await sources.list_sources.execute(student, notebook.id)
    assert [s.id for s in listed] == [second.id]
    async with uow_factory() as uow:
        assert await uow.passages.get(old[0].id, notebook.id) is None
    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.source_count == 1
    assert saved.char_count == listed[0].char_count
    assert saved.summary_status is SummaryStatus.STALE


async def test_removing_the_last_source_clears_the_summary_state(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-4: nothing left to summarise."""
    source = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Only", text=TEXT)
    )

    await sources.remove_source.execute(student, notebook.id, source.id)

    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.source_count, saved.char_count) == (0, 0)
    assert (saved.summary_status, saved.summary_due_at) == (SummaryStatus.NONE, None)


async def test_a_removed_file_can_be_added_again(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-2: removing frees the duplicate key."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    source = await add_ready(
        sources, uow_factory, student, notebook, FileInput(file_id=ref.id)
    )
    await sources.remove_source.execute(student, notebook.id, source.id)

    again = await sources.add_sources.execute(
        student, notebook.id, [FileInput(file_id=ref.id)]
    )

    assert again.rejected == []
    assert len(again.items) == 1


async def test_a_source_can_only_be_removed_by_its_owner_from_its_notebook(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """NB-15: foreign, misplaced and unknown sources are all a 404."""
    source = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Mine", text=TEXT)
    )
    elsewhere = await make_notebook(uow_factory, student.user_id)

    for actor, notebook_id, source_id in (
        (other_student, notebook.id, source.id),
        (other_student, their_notebook.id, source.id),
        (student, elsewhere.id, source.id),
        (student, notebook.id, new_id()),
    ):
        with pytest.raises(NotebookNotFoundError):
            await sources.remove_source.execute(actor, notebook_id, source_id)

    assert len(await sources.list_sources.execute(student, notebook.id)) == 1
