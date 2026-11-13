"""A group linked to EMIS for the first time is re-pulled once."""

from app.modules.academic.domain.schedule.group import group_match_key
from app.modules.academic.domain.schedule.student import Student
from app.shared.contracts.academic import StudentRef
from app.shared.ids import new_id
from tests.academic.schedule.curriculum_builders import make_curriculum
from tests.academic.schedule.env import Env
from tests.fakes.academic.schedule.identity import make_user

import pytest


async def _ensure(env: Env, emis_id: int, name: str) -> StudentRef:
    return await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=emis_id,
        group_name=name,
        current_semester=3,
        curriculum_id=None,
    )


@pytest.mark.parametrize("spelling", ["2 tn 2", "2-TN-2", "2ТН2", " 2tn-2 "])
def test_spellings_of_one_group_share_a_match_key(spelling: str) -> None:
    """Case, spaces, hyphens and Cyrillic look-alikes do not matter."""
    assert group_match_key(spelling) == "2tn2"


async def test_a_waiting_group_is_adopted_by_normalized_name(env: Env) -> None:
    """A group added as "2 tn 2" is the EMIS group "2-TN-2"."""
    waiting = await env.group("2 tn 2")

    ref = await _ensure(env, 3292, "2-TN-2")

    assert ref.group_id == waiting.id
    assert ref.group_first_linked is True
    async with env.uow_factory() as uow:
        group = await uow.groups.get(waiting.id)
    assert group is not None
    assert (group.emis_group_id, group.name, group.slug) == (3292, "2-TN-2", "2-tn-2")


async def test_a_group_with_another_emis_id_is_never_taken(env: Env) -> None:
    """The same name with a different EMIS id makes a new group."""
    other = await env.group("2TN2", emis_group_id=111)

    ref = await _ensure(env, 3292, "2ТН2")

    assert ref.group_id != other.id
    async with env.uow_factory() as uow:
        kept = await uow.groups.get(other.id)
    assert kept is not None and kept.emis_group_id == 111


async def test_only_the_first_registration_links_the_group(env: Env) -> None:
    """The second student finds the group linked and asks for no re-pull."""
    await env.group("2TN2")

    first = await _ensure(env, 3292, "2TN2")
    second = await _ensure(env, 3292, "2TN2")

    assert first.group_first_linked is True
    assert second.group_first_linked is False


async def test_the_repull_forces_the_curriculum_and_syncs_linked_members(
    env: Env,
) -> None:
    """Curriculum read again, other members with a working link queued."""
    group = await env.group("2TN2", emis_group_id=3292)
    registrant = await env.student(group, first_name="Aliya", last_name="One")
    member = await env.student(group, first_name="Bola", last_name="Two")
    broken = env.identity.add(make_user(login="three.cora", emis_status="needs_reauth"))
    async with env.uow_factory() as uow:
        await uow.students.add(Student(user_id=broken.id, group_id=group.id))
        await uow.commit()
    env.emis.curriculum_result = make_curriculum()
    await env.emis_import.sync_group_curriculum.ensure(group.id)
    before = len(env.emis.calls)
    env.kicker.calls.clear()

    await env.emis_import.repull_group.execute(group_id=group.id, user_id=registrant.id)

    assert any(call[0] == "curriculum" for call in env.emis.calls[before:])
    assert env.kicker.calls == [
        ("academic.run_student_sync", {"user_id": str(member.id)})
    ]
