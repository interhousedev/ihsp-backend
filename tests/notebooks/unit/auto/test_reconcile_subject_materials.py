"""Check that all lesson materials of a subject are in its subject notebooks."""

from app.modules.notebooks.wiring_auto import AutoServices
from app.shared.actor import Actor
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.auto.conftest import open_subject, teacher_file


async def test_reconcile_adds_the_missing_materials_and_counts_the_present(
    auto: AutoServices, world: World, student: Actor, physics: LessonRef
) -> None:
    """Admin check: missing materials come in; a second run adds nothing twice."""
    teacher_file(world, physics, "First")
    await open_subject(auto, student, physics)
    teacher_file(world, physics, "Second")

    first = await auto.reconcile_subject_materials.execute(physics.subject_id)
    second = await auto.reconcile_subject_materials.execute(physics.subject_id)

    assert (first.notebooks, first.added, first.already_present) == (1, 1, 1)
    assert (second.added, second.already_present) == (0, 2)


async def test_a_teacher_checks_only_their_own_notebooks(
    auto: AutoServices, world: World, student: Actor, physics: LessonRef
) -> None:
    """A teacher's run skips the notebooks of other owners; an admin's sees all."""
    teacher_file(world, physics, "First")
    await open_subject(auto, student, physics)

    other = await auto.reconcile_subject_materials.execute(
        physics.subject_id, owner_id=new_id()
    )
    own = await auto.reconcile_subject_materials.execute(
        physics.subject_id, owner_id=student.user_id
    )
    admin = await auto.reconcile_subject_materials.execute(physics.subject_id)

    assert (other.notebooks, own.notebooks, admin.notebooks) == (0, 1, 1)
