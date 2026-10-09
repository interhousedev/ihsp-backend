"""NB-3 (§ 3.2.7): `notebooks.purge_deleted` removes notebooks deleted 7 days ago."""

from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from tests.factories.notebooks import (
    make_artifact,
    make_message,
    make_notebook,
    make_source,
)
from tests.fakes.clock import FixedClock

WEEK = timedelta(days=7)


async def _exists(uow_factory: UowFactory, notebook_id: UUID) -> bool:
    async with uow_factory() as uow:
        return await uow.notebooks.get(notebook_id) is not None


async def _put_content(uow_factory: UowFactory, notebook: Notebook) -> UUID:
    """A source, a message and an output; return the source id."""
    source = await make_source(uow_factory, notebook)
    await make_message(uow_factory, notebook)
    await make_artifact(uow_factory, notebook)
    return source.id


async def test_purge_removes_notebooks_deleted_more_than_a_week_ago_with_content(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: the notebook, its sources, passages, messages and outputs go."""
    old = await make_notebook(
        uow_factory, student.user_id, deleted_at=clock.now() - WEEK - timedelta(hours=1)
    )
    source_id = await _put_content(uow_factory, old)

    purged = await lifecycle.purge_deleted.execute()

    assert purged == 1
    assert not await _exists(uow_factory, old.id)
    async with uow_factory() as uow:
        assert await uow.sources.get(source_id) is None
        assert await uow.messages.last_seq(old.id, student.user_id) == 0
        assert await uow.artifacts.count_live(old.id) == 0
        assert await uow.passages.list_for_sources([source_id]) == []


async def test_purge_keeps_recent_deletions_live_notebooks_and_the_exact_boundary(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: only notebooks deleted strictly more than 7 days ago are removed."""
    now = clock.now()
    keep = [
        await make_notebook(uow_factory, student.user_id),
        await make_notebook(uow_factory, student.user_id, deleted_at=now),
        await make_notebook(
            uow_factory, student.user_id, deleted_at=now - timedelta(days=6)
        ),
        await make_notebook(uow_factory, other_student.user_id, deleted_at=now - WEEK),
    ]
    gone = await make_notebook(
        uow_factory, other_student.user_id, deleted_at=now - WEEK - timedelta(seconds=1)
    )

    purged = await lifecycle.purge_deleted.execute()

    assert purged == 1
    assert not await _exists(uow_factory, gone.id)
    for notebook in keep:
        assert await _exists(uow_factory, notebook.id)


async def test_purge_is_idempotent(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: a second run has nothing to do."""
    await make_notebook(uow_factory, student.user_id, deleted_at=clock.now() - 2 * WEEK)

    first = await lifecycle.purge_deleted.execute()
    second = await lifecycle.purge_deleted.execute()

    assert (first, second) == (1, 0)


async def test_purge_handles_more_than_one_batch_of_100(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: the job works in batches and still removes everything due."""
    old = clock.now() - 2 * WEEK
    for _ in range(105):
        await make_notebook(uow_factory, student.user_id, deleted_at=old)
    survivor = await make_notebook(uow_factory, student.user_id)

    purged = await lifecycle.purge_deleted.execute()

    assert purged == 105
    async with uow_factory() as uow:
        assert await uow.notebooks.ids_for_owner(student.user_id) == [survivor.id]


async def test_notebook_deleted_by_the_student_is_purged_after_the_week(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: delete, wait 7 days and a bit, run the job."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await lifecycle.delete_notebook.execute(student, notebook.id)

    clock.advance(days=6)
    assert await lifecycle.purge_deleted.execute() == 0
    clock.advance(days=1, minutes=1)
    assert await lifecycle.purge_deleted.execute() == 1
    assert not await _exists(uow_factory, notebook.id)
