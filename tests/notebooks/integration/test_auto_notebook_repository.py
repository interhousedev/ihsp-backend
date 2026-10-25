"""NB-AUTO: subject and lesson notebooks in PostgreSQL (uniqueness, lookups, sweeps)."""

from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import AutoSettings, ExcludedRef, Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import NOW, make_notebook, new_notebook_entity

import pytest
from sqlalchemy.exc import IntegrityError


def auto_notebook(
    owner_id: UUID,
    origin: NotebookOrigin = NotebookOrigin.SUBJECT_AUTO,
    *,
    subject_id: UUID | None = None,
    lesson_id: UUID | None = None,
    **fields: object,
) -> Notebook:
    """A subject notebook (or a lesson one) that is not stored."""
    lesson = origin is NotebookOrigin.LESSON_AUTO
    return new_notebook_entity(
        owner_id,
        origin=origin,
        subject_id=subject_id or new_id(),
        lesson_id=(lesson_id or new_id()) if lesson else None,
        auto_settings=AutoSettings(),
        **fields,
    )


async def _add(uow_factory: UowFactory, notebook: Notebook) -> bool:
    async with uow_factory() as uow:
        added = await uow.notebooks.add_auto(notebook)
        await uow.commit()
    return added


async def test_auto_fields_survive_a_round_trip(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: origin, subject, lesson, settings and the sync time are stored."""
    settings = AutoSettings(
        include_classmates=True,
        excluded_refs=[ExcludedRef(ref_key="lesson:1", title="Old slides")],
    )
    notebook = auto_notebook(
        student.user_id,
        NotebookOrigin.LESSON_AUTO,
        auto_synced_at=NOW,
        space_key="lesson:x",
    )
    notebook.auto_settings = settings
    assert await _add(uow_factory, notebook)

    async with uow_factory() as uow:
        loaded = await uow.notebooks.get(notebook.id)

    assert loaded is not None
    assert loaded.origin is NotebookOrigin.LESSON_AUTO and loaded.is_auto
    assert (loaded.subject_id, loaded.lesson_id) == (
        notebook.subject_id,
        notebook.lesson_id,
    )
    assert loaded.auto_settings == settings
    assert loaded.auto_synced_at == NOW and loaded.space_key == "lesson:x"


async def test_a_manual_notebook_has_no_auto_fields(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: a notebook written by the student is `manual` with no settings."""
    notebook = await make_notebook(uow_factory, student.user_id)

    async with uow_factory() as uow:
        loaded = await uow.notebooks.get(notebook.id)

    assert loaded is not None and not loaded.is_auto
    assert loaded.origin is NotebookOrigin.MANUAL and loaded.auto_settings is None


async def test_a_second_live_notebook_of_the_same_subject_is_not_added(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: two parallel opens end with one notebook; the loser learns it."""
    subject = new_id()
    first = auto_notebook(student.user_id, subject_id=subject)
    second = auto_notebook(student.user_id, subject_id=subject)

    assert await _add(uow_factory, first) is True
    assert await _add(uow_factory, second) is False

    async with uow_factory() as uow:
        found = await uow.notebooks.find_auto(
            student.user_id, NotebookOrigin.SUBJECT_AUTO, subject
        )
        assert found is not None and found.id == first.id
        assert await uow.notebooks.get(second.id) is None
        assert await uow.notebooks.count_live_auto(student.user_id) == 1


async def test_a_deleted_subject_notebook_can_be_made_again(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: only live notebooks are unique, so deleting frees the subject."""
    subject = new_id()
    old = auto_notebook(student.user_id, subject_id=subject)
    await _add(uow_factory, old)
    async with uow_factory() as uow:
        stored = await uow.notebooks.get(old.id)
        assert stored is not None
        stored.deleted_at = NOW
        await uow.notebooks.save(stored)
        await uow.commit()

    assert await _add(uow_factory, auto_notebook(student.user_id, subject_id=subject))


async def test_the_same_subject_for_two_students_is_two_notebooks(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-AUTO: uniqueness is per student."""
    subject = new_id()

    assert await _add(uow_factory, auto_notebook(student.user_id, subject_id=subject))
    assert await _add(
        uow_factory, auto_notebook(other_student.user_id, subject_id=subject)
    )


async def test_a_lesson_notebook_is_unique_per_lesson(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: one notebook per student and lesson."""
    lesson = new_id()
    kind = NotebookOrigin.LESSON_AUTO

    assert await _add(
        uow_factory, auto_notebook(student.user_id, kind, lesson_id=lesson)
    )
    assert not await _add(
        uow_factory, auto_notebook(student.user_id, kind, lesson_id=lesson)
    )


async def test_the_constraint_refuses_a_half_made_auto_notebook(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: an auto origin needs its target and settings; manual needs none."""
    broken = [
        new_notebook_entity(student.user_id, origin=NotebookOrigin.SUBJECT_AUTO),
        new_notebook_entity(
            student.user_id, subject_id=new_id(), auto_settings=AutoSettings()
        ),
    ]
    for notebook in broken:
        async with uow_factory() as uow:
            with pytest.raises(IntegrityError):
                await uow.notebooks.add(notebook)


async def test_counts_keep_manual_and_auto_notebooks_apart(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: auto notebooks do not use up the student's 50 notebooks."""
    await make_notebook(uow_factory, student.user_id)
    await _add(uow_factory, auto_notebook(student.user_id))
    await _add(uow_factory, auto_notebook(student.user_id, NotebookOrigin.LESSON_AUTO))

    async with uow_factory() as uow:
        assert await uow.notebooks.count_live(student.user_id) == 1
        assert await uow.notebooks.count_live_auto(student.user_id) == 2


async def test_the_notebooks_that_feed_on_a_lesson_are_its_subjects_and_its_own(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-AUTO: a changed lesson reaches subject notebooks and its lesson notebooks."""
    subject, lesson = new_id(), new_id()
    wanted = [
        auto_notebook(student.user_id, subject_id=subject),
        auto_notebook(other_student.user_id, subject_id=subject),
        auto_notebook(
            student.user_id,
            NotebookOrigin.LESSON_AUTO,
            subject_id=subject,
            lesson_id=lesson,
        ),
    ]
    for notebook in wanted:
        await _add(uow_factory, notebook)
    for unrelated in (
        auto_notebook(student.user_id),
        auto_notebook(student.user_id, NotebookOrigin.LESSON_AUTO, subject_id=subject),
    ):
        await _add(uow_factory, unrelated)
    await make_notebook(uow_factory, student.user_id)

    async with uow_factory() as uow:
        ids = await uow.notebooks.auto_ids_for_lesson(subject, lesson, 10)
        limited = await uow.notebooks.auto_ids_for_lesson(subject, lesson, 1)

    assert set(ids) == {n.id for n in wanted} and len(limited) == 1


async def test_due_notebooks_are_active_ones_not_synced_since_the_cutoff(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-AUTO: never-synced first, then the longest waiting; idle ones are skipped."""
    cutoff = NOW
    opened = NOW - timedelta(days=1)
    never = auto_notebook(student.user_id, last_opened_at=opened, auto_synced_at=None)
    old = auto_notebook(
        student.user_id, last_opened_at=opened, auto_synced_at=NOW - timedelta(hours=3)
    )
    older = auto_notebook(
        student.user_id, last_opened_at=opened, auto_synced_at=NOW - timedelta(hours=9)
    )
    fresh = auto_notebook(
        student.user_id,
        last_opened_at=opened,
        auto_synced_at=NOW + timedelta(minutes=1),
    )
    idle = auto_notebook(
        student.user_id,
        last_opened_at=NOW - timedelta(days=60),
        auto_synced_at=NOW - timedelta(days=30),
    )
    for notebook in (old, fresh, idle, never, older):
        await _add(uow_factory, notebook)
    await make_notebook(uow_factory, student.user_id, last_opened_at=opened)

    async with uow_factory() as uow:
        due = await uow.notebooks.due_auto_sync(cutoff, NOW - timedelta(days=30), 10)

    assert due == [never.id, older.id, old.id]
