"""NB-3 (§ 3.2.7): `notebooks.delete_owner` on account deletion."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import (
    make_artifact,
    make_message,
    make_notebook,
    make_source,
)
from tests.fakes.clock import FixedClock


async def _fill(uow_factory: UowFactory, notebook: Notebook) -> None:
    await make_source(uow_factory, notebook)
    await make_message(uow_factory, notebook)
    await make_artifact(uow_factory, notebook)


async def test_every_notebook_of_the_owner_is_deleted_with_its_content(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-3: live and soft-deleted notebooks go at once, with their rows."""
    live = await make_notebook(uow_factory, student.user_id)
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=clock.now())
    await _fill(uow_factory, live)
    await _fill(uow_factory, gone)

    removed = await lifecycle.delete_owner.execute(student.user_id)

    assert removed == 2
    async with uow_factory() as uow:
        assert await uow.notebooks.ids_for_owner(student.user_id) == []
        assert await uow.sources.list_for_notebook(live.id) == []
        assert await uow.messages.last_seq(live.id, student.user_id) == 0
        assert await uow.artifacts.count_live(live.id) == 0


async def test_other_users_notebooks_are_left_alone(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-3: only the given owner is affected."""
    await make_notebook(uow_factory, student.user_id)
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await _fill(uow_factory, theirs)

    await lifecycle.delete_owner.execute(student.user_id)

    async with uow_factory() as uow:
        assert await uow.notebooks.get(theirs.id) is not None
        assert len(await uow.sources.list_for_notebook(theirs.id)) == 1


async def test_running_it_twice_or_for_a_user_without_notebooks_deletes_nothing(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-3: the job is idempotent."""
    await make_notebook(uow_factory, student.user_id)

    first = await lifecycle.delete_owner.execute(student.user_id)
    second = await lifecycle.delete_owner.execute(student.user_id)
    stranger = await lifecycle.delete_owner.execute(new_id())

    assert (first, second, stranger) == (1, 0, 0)


async def test_more_than_one_batch_of_notebooks_is_deleted(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-3: a hundred and five notebooks (the limit does not apply to old data)."""
    for _ in range(105):
        await make_notebook(uow_factory, student.user_id)

    removed = await lifecycle.delete_owner.execute(student.user_id)

    assert removed == 105
    async with uow_factory() as uow:
        assert await uow.notebooks.ids_for_owner(student.user_id) == []


async def test_the_running_outputs_of_the_owner_are_forgotten(
    lifecycle: NotebooksLifecycleServices, core: NotebooksCore, student: Actor
) -> None:
    """NB-3, NB-14: the Redis set of generating outputs is cleared."""
    await core.quota.reserve(student.user_id, ArtifactKind.REPORT, new_id())
    await core.quota.reserve(student.user_id, ArtifactKind.QUIZ, new_id())
    assert await core.quota.running_count(student.user_id) == 2

    await lifecycle.delete_owner.execute(student.user_id)
    await lifecycle.delete_owner.execute(student.user_id)

    assert await core.quota.running_count(student.user_id) == 0
