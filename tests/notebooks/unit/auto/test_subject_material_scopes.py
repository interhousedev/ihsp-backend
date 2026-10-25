"""Subject materials of teachers: for all their groups, or for one group (subgroup)."""

import dataclasses
from collections.abc import Callable
from typing import cast
from uuid import UUID

from app.modules.notebooks.application.material_target import DefaultMaterialDraft
from app.modules.notebooks.application.staff_subject_materials import (
    StaffSubjectMaterials,
)
from app.modules.notebooks.application.teaching_directory import TeachingDirectory
from app.modules.notebooks.domain.default_materials import (
    DefaultMaterialKind,
    MaterialScope,
    default_material_of,
)
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import (
    DefaultMaterialNotFoundError,
    SubjectNotTaughtError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import LessonRef, ScheduleQueries
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_file, make_lesson
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.auto.conftest import PAGE, open_subject

import pytest

EMIS = 301
G1, G2, G3 = new_id(), new_id(), new_id()


@pytest.fixture
def admin(make_actor: Callable[..., Actor]) -> Actor:
    """An administrator."""
    return make_actor(Role.ADMIN)


@pytest.fixture
def teacher(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def other_teacher(make_actor: Callable[..., Actor]) -> Actor:
    """Another teacher."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def staff(core: NotebooksCore, world: World) -> StaffSubjectMaterials:
    """The teacher's use cases over the fakes."""
    return StaffSubjectMaterials(
        uow_factory=core.uow_factory,
        clock=core.deps.clock,
        teaching=TeachingDirectory(
            schedule=cast(ScheduleQueries, world.schedule),
            terms=world.terms,
            clock=core.deps.clock,
        ),
        files=cast(FilesApi, world.files),
    )


@pytest.fixture
def physics(world: World) -> UUID:
    """The subject, with its EMIS id."""
    subject_id = new_id()
    world.schedule.set_emis_id(subject_id, EMIS)
    return subject_id


def _lesson(
    world: World,
    teacher: Actor,
    student: Actor | None,
    key: str,
    label: str,
    subject_id: UUID,
    placed: tuple[UUID, int | None] | None = None,
) -> LessonRef:
    """A lesson given to one audience key; the student attends and sits there."""
    lesson = dataclasses.replace(
        make_lesson(subject="Physics", subject_id=subject_id),
        teacher_id=teacher.user_id,
        audience=(key,),
        group_names=(label,),
    )
    world.schedule.lessons.append(lesson)
    world.schedule.taught.append((teacher.user_id, lesson))
    if student is not None:
        world.schedule.attend(student.user_id, lesson)
        if placed is not None:
            world.schedule.place(student.user_id, *placed)
    return lesson


def _file(world: World, owner: Actor, name: str) -> DefaultMaterialDraft:
    ref = world.files.add_text(make_file(owner.user_id, name=name), PAGE + name)
    return DefaultMaterialDraft(
        kind=DefaultMaterialKind.FILE, title=name, file_id=ref.id
    )


async def _titles(
    auto: AutoServices,
    uow_factory: UowFactory,
    actor: Actor,
    subject_id: UUID,
    group_id: UUID | None = None,
) -> set[str]:
    notebook = await auto.open_auto_notebook.execute(
        actor, NotebookOrigin.SUBJECT_AUTO, subject_id, group_id=group_id
    )
    await auto.sync_auto_notebook.execute(notebook.id)
    async with uow_factory() as uow:
        sources = await uow.sources.list_for_notebook(notebook.id)
    return {s.title for s in sources if default_material_of(s) is not None}


async def test_tiers_reach_the_right_notebooks(
    auto: AutoServices,
    staff: StaffSubjectMaterials,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    teacher: Actor,
    other_teacher: Actor,
    student: Actor,
    other_student: Actor,
    make_actor: Callable[..., Actor],
    physics: UUID,
) -> None:
    """Admin: all. Teacher+subject: that teacher's groups. Group: that group only."""
    third = make_actor(Role.STUDENT)
    _lesson(world, teacher, student, str(G1), "1A", physics, (G1, None))
    _lesson(world, teacher, other_student, str(G2), "1B", physics, (G2, None))
    _lesson(world, other_teacher, third, str(G3), "1C", physics, (G3, None))
    await auto.add_default_material.execute(admin, EMIS, _file(world, admin, "Admin"))
    await staff.add(teacher, physics, _file(world, teacher, "Mine"))
    await staff.add(teacher, physics, _file(world, teacher, "G1 only"), group_id=G1)

    both = {"Admin", "Mine", "G1 only"}
    assert await _titles(auto, uow_factory, student, physics) == both
    assert await _titles(auto, uow_factory, other_student, physics) == {
        "Admin",
        "Mine",
    }
    assert await _titles(auto, uow_factory, third, physics) == {"Admin"}
    # The teacher's own notebooks of the groups follow the same rules.
    assert await _titles(auto, uow_factory, teacher, physics, G1) == both
    assert await _titles(auto, uow_factory, teacher, physics, G2) == {"Admin", "Mine"}


async def test_subgroup_materials_stay_in_their_subgroup(
    auto: AutoServices,
    staff: StaffSubjectMaterials,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    teacher: Actor,
    student: Actor,
    other_student: Actor,
    physics: UUID,
) -> None:
    """A divided subject: subgroup 1's material is not seen in subgroup 2."""
    _lesson(world, teacher, student, f"{G1}:1", "EN/1", physics, (G1, 1))
    _lesson(world, teacher, other_student, f"{G1}:2", "EN/2", physics, (G1, 2))
    await auto.add_default_material.execute(admin, EMIS, _file(world, admin, "Admin"))
    await staff.add(
        teacher, physics, _file(world, teacher, "Sub 1"), group_id=G1, subgroup=1
    )
    await staff.add(teacher, physics, _file(world, teacher, "Whole"), group_id=G1)

    assert await _titles(auto, uow_factory, student, physics) == {
        "Admin",
        "Sub 1",
        "Whole",
    }
    assert await _titles(auto, uow_factory, other_student, physics) == {
        "Admin",
        "Whole",
    }


async def test_a_student_without_a_subgroup_gets_whole_group_materials_only(
    auto: AutoServices,
    staff: StaffSubjectMaterials,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    teacher: Actor,
    make_actor: Callable[..., Actor],
    physics: UUID,
) -> None:
    """Not yet placed in a half: admin and whole-group materials, no subgroup ones."""
    third = make_actor(Role.STUDENT)
    _lesson(world, teacher, third, f"{G1}:1", "EN/1", physics, (G1, None))
    await auto.add_default_material.execute(admin, EMIS, _file(world, admin, "Admin"))
    await staff.add(
        teacher, physics, _file(world, teacher, "Sub 1"), group_id=G1, subgroup=1
    )
    await staff.add(teacher, physics, _file(world, teacher, "Whole"), group_id=G1)

    assert await _titles(auto, uow_factory, third, physics) == {"Admin", "Whole"}


async def test_a_student_moved_to_another_subgroup_follows_the_new_one(
    auto: AutoServices,
    staff: StaffSubjectMaterials,
    uow_factory: UowFactory,
    world: World,
    teacher: Actor,
    student: Actor,
    physics: UUID,
) -> None:
    """The next sync swaps subgroup 1's materials for subgroup 2's."""
    _lesson(world, teacher, student, f"{G1}:1", "EN/1", physics, (G1, 1))
    _lesson(world, teacher, None, f"{G1}:2", "EN/2", physics)
    await staff.add(
        teacher, physics, _file(world, teacher, "Sub 1"), group_id=G1, subgroup=1
    )
    await staff.add(
        teacher, physics, _file(world, teacher, "Sub 2"), group_id=G1, subgroup=2
    )
    assert await _titles(auto, uow_factory, student, physics) == {"Sub 1"}

    _lesson(world, teacher, student, f"{G1}:2", "EN/2", physics, (G1, 2))

    assert await _titles(auto, uow_factory, student, physics) == {"Sub 2"}


async def test_a_teacher_cannot_add_for_a_group_or_subject_they_do_not_teach(
    staff: StaffSubjectMaterials,
    world: World,
    teacher: Actor,
    other_teacher: Actor,
    physics: UUID,
) -> None:
    """Not their group, not their subgroup, not their subject: forbidden."""
    _lesson(world, teacher, None, f"{G1}:1", "EN/1", physics)

    with pytest.raises(SubjectNotTaughtError):
        await staff.add(teacher, physics, _file(world, teacher, "x"), group_id=G2)
    with pytest.raises(SubjectNotTaughtError):
        await staff.add(
            teacher, physics, _file(world, teacher, "y"), group_id=G1, subgroup=2
        )
    with pytest.raises(SubjectNotTaughtError):
        await staff.add(other_teacher, physics, _file(world, other_teacher, "z"))


async def test_sync_is_idempotent_and_removal_takes_the_copy_out(
    auto: AutoServices,
    staff: StaffSubjectMaterials,
    uow_factory: UowFactory,
    world: World,
    teacher: Actor,
    student: Actor,
    physics: UUID,
) -> None:
    """A second sync adds nothing; removing the material removes the copy."""
    _lesson(world, teacher, student, str(G1), "1A", physics, (G1, None))
    material = await staff.add(teacher, physics, _file(world, teacher, "Mine"))
    notebook = await open_subject(
        auto, student, make_lesson(subject="Physics", subject_id=physics)
    )
    async with uow_factory() as uow:  # opening the notebook synced it already
        assert len(await uow.sources.list_for_notebook(notebook.id)) == 1
    again = await auto.sync_auto_notebook.execute(notebook.id)
    assert (again.added, again.removed) == (0, 0)

    await staff.remove(teacher, physics, material.id)
    after = await auto.sync_auto_notebook.execute(notebook.id)

    assert after.removed == 1


async def test_overview_has_three_tiers_and_only_own_materials_can_be_removed(
    auto: AutoServices,
    staff: StaffSubjectMaterials,
    world: World,
    admin: Actor,
    teacher: Actor,
    other_teacher: Actor,
    physics: UUID,
) -> None:
    """Admin read-only, mine, per group; others' and admin ones are not removable."""
    _lesson(world, teacher, None, str(G1), "1A", physics)
    _lesson(world, other_teacher, None, str(G1), "1A", physics)
    admin_material = await auto.add_default_material.execute(
        admin, EMIS, _file(world, admin, "Admin")
    )
    mine = await staff.add(teacher, physics, _file(world, teacher, "Mine"))
    group = await staff.add(teacher, physics, _file(world, teacher, "Grp"), group_id=G1)
    theirs = await staff.add(other_teacher, physics, _file(world, other_teacher, "T"))

    view = await staff.overview(teacher, physics)

    assert [x.id for x in view.admin] == [admin_material.id]
    assert [x.id for x in view.mine] == [mine.id]
    assert [x.id for x in view.groups] == [group.id]
    assert group.scope is MaterialScope.GROUP
    for other in (admin_material.id, theirs.id):
        with pytest.raises(DefaultMaterialNotFoundError):
            await staff.remove(teacher, physics, other)
