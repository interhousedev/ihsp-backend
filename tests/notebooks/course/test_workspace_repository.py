"""LMS-AI 3.1/3.2: a workspace is never a student's notebook nor an auto notebook."""

from datetime import timedelta
from typing import Any

from app.modules.notebooks.domain.entities import AutoSettings, Notebook
from app.modules.notebooks.domain.enums import MessageRole, NotebookOrigin
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_message, make_notebook, new_notebook_entity
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.lms_workspace import WorkspaceCourse

import pytest
from sqlalchemy.exc import IntegrityError


async def _subject_notebook(uow_factory: UowFactory, owner: Actor) -> Notebook:
    """A live subject notebook of the owner (opened now, never synced)."""
    return await make_notebook(
        uow_factory,
        owner.user_id,
        origin=NotebookOrigin.SUBJECT_AUTO,
        subject_id=new_id(),
        auto_settings=AutoSettings(),
    )


async def test_counts_leave_the_workspace_out(
    uow_factory: UowFactory, workspace: Notebook, teacher: Actor
) -> None:
    """LMS-AI 3.1: not in the 30-notebook quota nor in the auto notebook count."""
    await make_notebook(uow_factory, teacher.user_id)
    await _subject_notebook(uow_factory, teacher)

    async with uow_factory() as uow:
        manual = await uow.notebooks.count_live(teacher.user_id)
        auto = await uow.notebooks.count_live_auto(teacher.user_id)

    assert (manual, auto) == (1, 1)


async def test_the_auto_sync_sweep_never_picks_a_workspace(
    uow_factory: UowFactory, workspace: Notebook, teacher: Actor, clock: FixedClock
) -> None:
    """LMS-AI 3.1: the sweep looks at subject and lesson notebooks only."""
    subject = await _subject_notebook(uow_factory, teacher)
    now = clock.now()
    async with uow_factory() as uow:
        for notebook in (subject, workspace):
            stored = await uow.notebooks.get(notebook.id)
            assert stored is not None
            stored.last_opened_at = now
            await uow.notebooks.save(stored)
        await uow.commit()

    async with uow_factory() as uow:
        due = await uow.notebooks.due_auto_sync(
            now + timedelta(hours=1), now - timedelta(days=1), 50
        )

    assert due == [subject.id]


async def test_the_workspace_of_a_course_is_found_while_it_lives(
    uow_factory: UowFactory, workspace: Notebook, course: WorkspaceCourse
) -> None:
    """LMS-AI 3.2: `get_by_course` returns the live workspace only."""
    async with uow_factory() as uow:
        found = await uow.notebooks.get_by_course(course.id)
        assert found is not None and found.id == workspace.id
        found.deleted_at = found.updated_at
        await uow.notebooks.save(found)
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.notebooks.get_by_course(course.id) is None


async def test_a_new_workspace_may_follow_a_deleted_one(
    uow_factory: UowFactory, workspace: Notebook, course: WorkspaceCourse
) -> None:
    """LMS-AI 3.2: the unique index counts live workspaces only."""
    async with uow_factory() as uow:
        old = await uow.notebooks.get(workspace.id)
        assert old is not None
        old.deleted_at = old.updated_at
        await uow.notebooks.save(old)
        added = await uow.notebooks.add_workspace(
            new_notebook_entity(origin=NotebookOrigin.COURSE, course_id=course.id)
        )
        await uow.commit()

    assert added


@pytest.mark.parametrize(
    "fields",
    [
        {"origin": NotebookOrigin.MANUAL, "course_id": new_id()},
        {"origin": NotebookOrigin.COURSE},
        {
            "origin": NotebookOrigin.COURSE,
            "course_id": new_id(),
            "subject_id": new_id(),
        },
    ],
)
async def test_the_database_keeps_origin_and_course_together(
    uow_factory: UowFactory, fields: dict[str, Any]
) -> None:
    """LMS-AI 3.2: `course_id` exactly for workspaces (CHECK auto_target)."""
    with pytest.raises(IntegrityError):
        async with uow_factory() as uow:
            await uow.notebooks.add(new_notebook_entity(**fields))


async def test_deleting_the_owner_keeps_the_workspace(
    services: NotebooksServices,
    uow_factory: UowFactory,
    workspace: Notebook,
    teacher: Actor,
    editor: Actor,
) -> None:
    """LMS-AI 3.1: the workspace belongs to the course; the owner's own rows go."""
    own = await make_notebook(uow_factory, teacher.user_id)
    mine = await make_message(uow_factory, workspace, user_id=teacher.user_id)
    theirs = await make_message(
        uow_factory, workspace, user_id=editor.user_id, role=MessageRole.USER
    )

    removed = await services.delete_owner.execute(teacher.user_id)

    async with uow_factory() as uow:
        assert removed == 1
        assert await uow.notebooks.get(own.id) is None
        assert await uow.notebooks.get(workspace.id) is not None
        assert await uow.messages.get(mine.id) is None
        assert await uow.messages.get(theirs.id) is not None
