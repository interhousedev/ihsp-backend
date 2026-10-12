"""NB-AUTO: subject notebooks are slots, created on the first open."""

import dataclasses
from collections.abc import Callable
from typing import Any

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_lesson
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.auto.conftest import teacher_file

import pytest

GROUP_A = (new_id(), "2TN2")
GROUP_B = (new_id(), "3TN1")


@pytest.fixture
def teacher(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher."""
    return make_actor(Role.TEACHER)


async def test_a_subject_without_a_notebook_is_a_placeholder(
    auto: AutoServices, student: Actor, physics: LessonRef
) -> None:
    """The slot is listed with no notebook and nothing is created by listing."""
    first = await auto.list_subject_slots.execute(student)
    second = await auto.list_subject_slots.execute(student)

    [slot] = first
    assert slot.subject_id == physics.subject_id
    assert slot.subject_name == "Physics"
    assert slot.notebook_id is None and slot.group_id is None
    assert second == first


async def test_first_open_creates_and_second_reuses(
    auto: AutoServices, world: World, student: Actor, physics: LessonRef
) -> None:
    """The first click makes the notebook (filled); the slot then points to it."""
    teacher_file(world, physics)

    made = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id
    )
    again = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id
    )

    assert again.id == made.id and made.source_count == 1
    [slot] = await auto.list_subject_slots.execute(student)
    assert slot.notebook_id == made.id and slot.source_count == 1


async def test_a_lost_race_returns_the_winners_notebook(
    auto: AutoServices,
    student: Actor,
    physics: LessonRef,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two clicks at once: the unique index lets one in, the other reads it."""
    opener = auto.open_auto_notebook
    winner = await opener.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id
    )
    real: Any = opener._existing
    calls = {"n": 0}

    async def blind_first(*args: Any, **kwargs: Any) -> Notebook | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(opener, "_existing", blind_first)

    loser = await opener.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id
    )

    assert loser.id == winner.id
    slots = await auto.list_subject_slots.execute(student)
    assert [s.notebook_id for s in slots] == [winner.id]


async def test_the_unique_index_refuses_a_second_notebook(
    auto: AutoServices, uow_factory: UowFactory, student: Actor, physics: LessonRef
) -> None:
    """The store itself keeps one live notebook per student and subject."""
    made = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.SUBJECT_AUTO, physics.subject_id
    )
    twin = dataclasses.replace(made, id=new_id())

    async with uow_factory() as uow:
        assert await uow.notebooks.add_auto(twin) is False


async def test_a_teacher_has_a_slot_per_subject_and_group(
    auto: AutoServices, world: World, teacher: Actor
) -> None:
    """Algebra . 2TN2, Algebra . 3TN1 and Physics . 2TN2, grouped by subject."""
    algebra = make_lesson(subject="Algebra")
    world.schedule.teach(teacher.user_id, algebra, GROUP_A)
    world.schedule.teach(
        teacher.user_id,
        make_lesson(subject="Algebra", subject_id=algebra.subject_id),
        GROUP_B,
    )
    world.schedule.teach(teacher.user_id, make_lesson(subject="Physics"), GROUP_A)

    slots = await auto.list_subject_slots.execute(teacher)

    assert [(s.subject_name, s.group_name) for s in slots] == [
        ("Algebra", "2TN2"),
        ("Algebra", "3TN1"),
        ("Physics", "2TN2"),
    ]
    assert all(s.notebook_id is None for s in slots)


async def test_a_teacher_notebook_is_scoped_to_the_group(
    auto: AutoServices, world: World, teacher: Actor
) -> None:
    """Opening a group's slot makes its own notebook; the other group stays empty."""
    algebra = make_lesson(subject="Algebra")
    lesson_a = world.schedule.teach(teacher.user_id, algebra, GROUP_A)
    lesson_b = world.schedule.teach(
        teacher.user_id,
        make_lesson(subject="Algebra", subject_id=algebra.subject_id),
        GROUP_B,
    )
    teacher_file(world, lesson_a, "For 2TN2")
    teacher_file(world, lesson_b, "For 3TN1")

    made = await auto.open_auto_notebook.execute(
        teacher, NotebookOrigin.SUBJECT_AUTO, algebra.subject_id, group_id=GROUP_A[0]
    )
    again = await auto.open_auto_notebook.execute(
        teacher, NotebookOrigin.SUBJECT_AUTO, algebra.subject_id, group_id=GROUP_A[0]
    )

    assert again.id == made.id
    assert made.group_id == GROUP_A[0] and made.title == "Algebra · 2TN2"
    assert made.source_count == 1
    by_group = {
        s.group_name: s.notebook_id
        for s in await auto.list_subject_slots.execute(teacher)
    }
    assert by_group == {"2TN2": made.id, "3TN1": None}


async def test_a_teacher_cannot_open_a_group_they_do_not_teach(
    auto: AutoServices, world: World, teacher: Actor
) -> None:
    """No lessons of the subject for the group: not found."""
    algebra = world.schedule.teach(teacher.user_id, make_lesson(), GROUP_A)

    with pytest.raises(NotebookNotFoundError):
        await auto.open_auto_notebook.execute(
            teacher,
            NotebookOrigin.SUBJECT_AUTO,
            algebra.subject_id,
            group_id=GROUP_B[0],
        )
