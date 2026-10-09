"""NB-3: deleting a notebook (soft delete, kept for 7 days)."""

from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_artifact, make_notebook, make_source
from tests.fakes.clock import FixedClock

import pytest


async def test_delete_marks_the_notebook_and_hides_it(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: `deleted_at` is set; the notebook leaves the list and cannot be opened."""
    notebook = await make_notebook(uow_factory, student.user_id)
    clock.advance(hours=2)

    await lifecycle.delete_notebook.execute(student, notebook.id)

    async with uow_factory() as uow:
        stored = await uow.notebooks.get(notebook.id)
        live = await uow.notebooks.count_live(student.user_id)
    assert stored is not None
    assert stored.deleted_at == clock.now()
    assert stored.updated_at == clock.now()
    assert live == 0
    assert (await lifecycle.list_notebooks.execute(student)).items == []
    with pytest.raises(NotebookNotFoundError):
        await lifecycle.get_notebook.execute(student, notebook.id)


async def test_delete_keeps_sources_and_outputs_until_the_purge(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-3: nothing else is touched by a soft delete."""
    notebook = await make_notebook(uow_factory, student.user_id)
    source = await make_source(uow_factory, notebook)
    artifact = await make_artifact(uow_factory, notebook)

    await lifecycle.delete_notebook.execute(student, notebook.id)

    async with uow_factory() as uow:
        assert await uow.sources.get(source.id) == source
        stored = await uow.artifacts.get(artifact.id)
    assert stored is not None
    assert stored.deleted_at is None


async def test_deleting_twice_is_not_found_the_second_time(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: a deleted notebook is a 404 like any missing one; the date stays."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await lifecycle.delete_notebook.execute(student, notebook.id)
    deleted_at = clock.now()
    clock.advance(days=1)

    with pytest.raises(NotebookNotFoundError):
        await lifecycle.delete_notebook.execute(student, notebook.id)

    async with uow_factory() as uow:
        stored = await uow.notebooks.get(notebook.id)
    assert stored is not None and stored.deleted_at == deleted_at


async def test_another_students_notebook_cannot_be_deleted(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-3: a foreign notebook answers 404 and stays alive."""
    theirs = await make_notebook(uow_factory, other_student.user_id)

    with pytest.raises(NotebookNotFoundError):
        await lifecycle.delete_notebook.execute(student, theirs.id)

    async with uow_factory() as uow:
        stored = await uow.notebooks.get(theirs.id)
    assert stored is not None and stored.deleted_at is None


async def test_deleting_frees_a_place_under_the_notebook_limit(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-1, NB-3: a deleted notebook no longer counts against the 50."""
    first = await make_notebook(uow_factory, student.user_id)
    for _ in range(49):
        await make_notebook(uow_factory, student.user_id)

    await lifecycle.delete_notebook.execute(student, first.id)
    created = await lifecycle.create_notebook.execute(student)

    assert created.owner_id == student.user_id
