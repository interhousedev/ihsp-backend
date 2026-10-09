"""NB-2: opening a notebook."""

from uuid import UUID

from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import NOW, make_notebook, make_source
from tests.fakes.clock import FixedClock

import pytest


async def test_opening_sets_last_opened_at_and_keeps_updated_at(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-2: opening is not an edit: only `last_opened_at` moves."""
    notebook = await make_notebook(uow_factory, student.user_id)
    clock.advance(hours=3)

    opened = await lifecycle.get_notebook.execute(student, notebook.id)

    async with uow_factory() as uow:
        stored = await uow.notebooks.get(notebook.id)
    assert opened.last_opened_at == clock.now()
    assert opened.updated_at == NOW
    assert stored == opened


async def test_opened_notebook_has_its_source_counters(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: the detail includes the ready and selected source counts."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, notebook)
    await make_source(uow_factory, notebook, selected=False)

    opened = await lifecycle.get_notebook.execute(student, notebook.id)

    assert opened.source_count == 2
    assert (opened.ready_source_count, opened.selected_source_count) == (2, 1)


async def test_opening_moves_the_notebook_to_the_top_of_the_list(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-2: the list is ordered by the last open."""
    older = await make_notebook(uow_factory, student.user_id, last_opened_at=NOW)
    newer = await make_notebook(
        uow_factory, student.user_id, last_opened_at=clock.advance(hours=1)
    )
    clock.advance(hours=1)

    await lifecycle.get_notebook.execute(student, older.id)

    page = await lifecycle.list_notebooks.execute(student)
    assert [n.id for n in page.items] == [older.id, newer.id]


async def test_another_students_notebook_is_not_found(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-3: a foreign notebook answers 404, like a missing one."""
    theirs = await make_notebook(uow_factory, other_student.user_id)

    with pytest.raises(NotebookNotFoundError):
        await lifecycle.get_notebook.execute(student, theirs.id)

    async with uow_factory() as uow:
        stored = await uow.notebooks.get(theirs.id)
    assert stored is not None
    assert stored.last_opened_at is None


@pytest.mark.parametrize("missing", [new_id(), UUID(int=0)])
async def test_unknown_notebook_is_not_found(
    lifecycle: NotebooksLifecycleServices, student: Actor, missing: UUID
) -> None:
    """NB-3: an id that does not exist answers 404."""
    with pytest.raises(NotebookNotFoundError):
        await lifecycle.get_notebook.execute(student, missing)


async def test_deleted_notebook_is_not_found(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: a soft-deleted notebook cannot be opened."""
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=clock.now())

    with pytest.raises(NotebookNotFoundError):
        await lifecycle.get_notebook.execute(student, gone.id)
