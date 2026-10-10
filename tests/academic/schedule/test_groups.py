"""Groups, curators, head students and subgroups (ADM-6, STF-12, ACA-1, ACA-2)."""

from app.modules.academic.domain.schedule.errors import (
    CuratorNotTeacherError,
    GroupEmisIdTakenError,
    GroupNameInvalidError,
    GroupNameTakenError,
    GroupNotFoundError,
    HeadStudentInvalidError,
    NotGroupCuratorError,
    SubgroupAssignmentInvalidError,
)
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest


async def test_a_group_name_is_stored_in_latin_with_a_slug(env: Env) -> None:
    """ACA-1: EMIS sends 2ТН2 in Cyrillic; we store 2TN2 with the slug 2tn2."""
    created = await env.services.create_group.execute(
        name="2ТН2", emis_group_id=3292, current_semester=3
    )

    assert (created.name, created.slug) == ("2TN2", "2tn2")
    assert created.current_semester == 3
    assert created.students_count == 0 and created.curator is None


async def test_an_active_group_name_cannot_be_reused(env: Env) -> None:
    """README -> Group: the slug is unique among active groups."""
    await env.services.create_group.execute(name="2TN2")

    with pytest.raises(GroupNameTakenError):
        await env.services.create_group.execute(name="2ТН2")


async def test_an_emis_group_can_be_linked_once(env: Env) -> None:
    """README -> Group: emis_group_id is unique."""
    await env.services.create_group.execute(name="2TN1", emis_group_id=3292)

    with pytest.raises(GroupEmisIdTakenError):
        await env.services.create_group.execute(name="2TN2", emis_group_id=3292)


async def test_a_blank_group_name_is_invalid(env: Env) -> None:
    """ADM-6: a group needs a name."""
    with pytest.raises(GroupNameInvalidError):
        await env.services.create_group.execute(name="  ")


async def test_the_curator_must_be_a_teacher(env: Env) -> None:
    """ADM-6: only a teacher can be the head teacher of a group."""
    group = await env.group()
    student_group = await env.group("2TN1")
    pupil = await env.student(student_group)
    admin = make_actor(Role.ADMIN)

    with pytest.raises(CuratorNotTeacherError):
        await env.services.update_group.execute(admin, group.id, curator_id=pupil.id)


async def test_setting_a_curator_is_audited(env: Env) -> None:
    """ADM-6: the curator is set and the change is recorded."""
    group = await env.group()
    teacher = env.teacher()
    admin = make_actor(Role.ADMIN)

    detail = await env.services.update_group.execute(
        admin, group.id, curator_id=teacher.id
    )

    assert detail.curator is not None and detail.curator.id == teacher.id
    assert [(a.type, a.user_id, a.actor_id) for a in env.audits] == [
        ("group.curator_set", teacher.id, admin.user_id)
    ]


async def test_the_head_student_must_be_an_active_student_of_the_group(
    env: Env,
) -> None:
    """ADM-6: the head student comes from the group's students."""
    group = await env.group()
    other = await env.group("2TN1")
    outsider = await env.student(other)
    left = await env.student(group, status="left", last_name="Left")
    admin = make_actor(Role.ADMIN)

    for candidate in (outsider, left):
        with pytest.raises(HeadStudentInvalidError):
            await env.services.update_group.execute(
                admin, group.id, head_student_id=candidate.id
            )


async def test_a_head_student_is_set_and_audited(env: Env) -> None:
    """ADM-6: set the head student of the group."""
    group = await env.group()
    head = await env.student(group)
    admin = make_actor(Role.ADMIN)

    detail = await env.services.update_group.execute(
        admin, group.id, head_student_id=head.id
    )

    assert detail.head_student is not None and detail.head_student.id == head.id
    assert env.audits[0].type == "group.head_student_set"


async def test_none_clears_the_curator_and_unset_leaves_it(env: Env) -> None:
    """API: PATCH null clears; an omitted field keeps the value."""
    teacher = env.teacher()
    group = await env.group(curator=teacher)
    admin = make_actor(Role.ADMIN)

    kept = await env.services.update_group.execute(admin, group.id, status="archived")
    cleared = await env.services.update_group.execute(admin, group.id, curator_id=None)

    assert kept.curator is not None and kept.status == "archived"
    assert cleared.curator is None


async def test_an_unknown_group_is_not_found(env: Env) -> None:
    """API: unknown ids answer 404."""
    with pytest.raises(GroupNotFoundError):
        await env.services.get_group_detail.execute(make_actor(Role.ADMIN), new_id())


async def test_the_curator_assigns_subgroups_and_it_is_audited(env: Env) -> None:
    """STF-12, UF-STF-10: the curator sets each student's subgroup."""
    teacher = env.teacher()
    group = await env.group(curator=teacher)
    first = await env.student(group, first_name="Aliya", last_name="Aliyeva")
    second = await env.student(group, first_name="Bobur", last_name="Boburov")
    actor = make_actor(Role.TEACHER, user_id=teacher.id)

    detail = await env.services.assign_subgroups.execute(
        actor, group.id, [(first.id, 1), (second.id, 2)]
    )

    by_id = {s.user_id: s.subgroup for s in detail.students}
    assert by_id == {first.id: 1, second.id: 2}
    assert detail.subgroups_assigned == 2
    assert sorted(a.type for a in env.audits) == ["subgroup.assigned"] * 2
    assert {a.user_id for a in env.audits} == {first.id, second.id}


async def test_assignment_remembers_who_set_the_subgroup(env: Env) -> None:
    """README -> Student: subgroup_set_by and subgroup_set_at."""
    teacher = env.teacher()
    group = await env.group(curator=teacher)
    pupil = await env.student(group)

    await env.services.assign_subgroups.execute(
        make_actor(Role.TEACHER, user_id=teacher.id), group.id, [(pupil.id, 2)]
    )

    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None
    assert student.subgroup_set_by == teacher.id
    assert student.subgroup_set_at == env.clock.now()


async def test_a_teacher_who_is_not_the_curator_cannot_assign(env: Env) -> None:
    """UF-STF-10: only the curator or Administration (403)."""
    curator = env.teacher()
    stranger = env.teacher("Other", "Teacher")
    group = await env.group(curator=curator)
    pupil = await env.student(group)

    with pytest.raises(NotGroupCuratorError) as caught:
        await env.services.assign_subgroups.execute(
            make_actor(Role.TEACHER, user_id=stranger.id), group.id, [(pupil.id, 1)]
        )

    assert caught.value.status == 403


async def test_an_admin_can_assign_subgroups(env: Env) -> None:
    """ADM-6: Administration may override a subgroup."""
    group = await env.group()
    pupil = await env.student(group)

    detail = await env.services.assign_subgroups.execute(
        make_actor(Role.ADMIN), group.id, [(pupil.id, 1)]
    )

    assert detail.students[0].subgroup == 1


async def test_a_subgroup_can_be_cleared(env: Env) -> None:
    """STF-12: null means not set."""
    group = await env.group()
    pupil = await env.student(group, subgroup=2)

    detail = await env.services.assign_subgroups.execute(
        make_actor(Role.ADMIN), group.id, [(pupil.id, None)]
    )

    assert detail.students[0].subgroup is None


async def test_assignments_for_strangers_are_rejected_and_nothing_is_saved(
    env: Env,
) -> None:
    """ACA-2: every user must belong to the group; the whole request is atomic."""
    group = await env.group()
    other = await env.group("2TN1")
    member = await env.student(group)
    stranger = await env.student(other)

    with pytest.raises(SubgroupAssignmentInvalidError):
        await env.services.assign_subgroups.execute(
            make_actor(Role.ADMIN), group.id, [(member.id, 1), (stranger.id, 1)]
        )

    async with env.uow_factory() as uow:
        saved = await uow.students.get(member.id)
    assert saved is not None and saved.subgroup is None
    assert env.audits == []


async def test_only_subgroups_one_and_two_exist(env: Env) -> None:
    """ACA-2: each group has exactly two subgroups."""
    group = await env.group()
    pupil = await env.student(group)

    with pytest.raises(SubgroupAssignmentInvalidError):
        await env.services.assign_subgroups.execute(
            make_actor(Role.ADMIN), group.id, [(pupil.id, 3)]
        )


async def test_group_detail_shows_names_and_registration(env: Env) -> None:
    """ADM-6, ACA-18: imported students appear as not registered."""
    teacher = env.teacher()
    group = await env.group(curator=teacher)
    await env.student(group, first_name="Aliya", last_name="Aliyeva")
    await env.student(
        group,
        first_name="Bobur",
        last_name="Boburov",
        user_status=UserStatus.UNREGISTERED,
    )

    detail = await env.services.get_group_detail.execute(
        make_actor(Role.TEACHER, user_id=teacher.id), group.id
    )

    rows = [(s.last_name, s.registered) for s in detail.students]
    assert rows == [("Aliyeva", True), ("Boburov", False)]
    assert (detail.students_count, detail.unregistered_count) == (2, 1)
    assert detail.curator is not None and detail.curator.last_name == "Kalandarova"


async def test_group_detail_is_hidden_from_other_teachers(env: Env) -> None:
    """UF-STF-09: only the curator sees the roster."""
    group = await env.group(curator=env.teacher())
    stranger = env.teacher("Other", "Teacher")

    with pytest.raises(NotGroupCuratorError):
        await env.services.get_group_detail.execute(
            make_actor(Role.TEACHER, user_id=stranger.id), group.id
        )


async def test_left_students_are_listed_but_not_counted(env: Env) -> None:
    """ACA-19: left students stay in the data but not in the counts."""
    group = await env.group()
    await env.student(group, last_name="Active")
    await env.student(group, last_name="Gone", status="left")

    detail = await env.services.get_group_detail.execute(
        make_actor(Role.ADMIN), group.id
    )

    assert detail.students_count == 1
    assert {s.last_name: s.status for s in detail.students} == {
        "Active": "active",
        "Gone": "left",
    }


async def test_list_groups_has_counts_and_people(env: Env) -> None:
    """ADM-6: students count, subgroups assigned, unregistered, curator, head."""
    teacher = env.teacher()
    group = await env.group("2TN2", curator=teacher)
    await env.group("1TN1")
    head = await env.student(group, subgroup=1, last_name="Head")
    await env.student(group, last_name="Second")
    await env.student(group, last_name="Ghost", user_status=UserStatus.UNREGISTERED)
    admin = make_actor(Role.ADMIN)
    await env.services.update_group.execute(admin, group.id, head_student_id=head.id)

    groups = await env.services.list_groups.execute()

    assert [g.name for g in groups] == ["1TN1", "2TN2"]
    item = groups[1]
    assert (item.students_count, item.subgroups_assigned, item.unregistered_count) == (
        3,
        1,
        1,
    )
    assert item.curator is not None and item.head_student is not None
    assert item.head_student.last_name == "Head"


async def test_list_groups_can_filter_by_status(env: Env) -> None:
    """ADM-6: archived groups are filtered by ?status."""
    group = await env.group("2TN2")
    await env.group("1TN1")
    await env.services.update_group.execute(
        make_actor(Role.ADMIN), group.id, status="archived"
    )

    archived = await env.services.list_groups.execute("archived")

    assert [g.name for g in archived] == ["2TN2"]


async def test_a_teacher_sees_only_the_groups_they_curate(env: Env) -> None:
    """STF-12: GET /v1/staff/groups lists the curated groups."""
    teacher = env.teacher()
    mine = await env.group("2TN2", curator=teacher)
    await env.group("1TN1", curator=env.teacher("Other", "Teacher"))

    groups = await env.services.list_curated_groups.execute(
        make_actor(Role.TEACHER, user_id=teacher.id)
    )

    assert [g.id for g in groups] == [mine.id]


async def test_a_group_can_be_renamed_and_moved_to_another_semester(env: Env) -> None:
    """The name and the semester of a group are editable; the slug follows the name."""
    group = await env.group()
    admin = make_actor(Role.ADMIN)

    detail = await env.services.update_group.execute(
        admin, group.id, name="1tn9", current_semester=3
    )

    assert (detail.name, detail.slug, detail.current_semester) == ("1TN9", "1tn9", 3)


async def test_renaming_into_the_name_of_another_active_group_is_refused(
    env: Env,
) -> None:
    """Two active groups never share a name."""
    group = await env.group()
    other = await env.group("2TN1")
    admin = make_actor(Role.ADMIN)

    with pytest.raises(GroupNameTakenError):
        await env.services.update_group.execute(admin, group.id, name=other.name)
