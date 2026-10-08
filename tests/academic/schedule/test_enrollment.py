"""AcademicEnrollment: registration, EMIS refresh, leaving (ACA-1/3/18/19)."""

import datetime as dt

from app.modules.academic.domain.schedule.errors import GroupNameTakenError
from app.shared.contracts.emis import EmisSubject
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.academic.schedule.env import Env

import pytest


async def test_a_new_student_creates_the_group_from_emis(env: Env) -> None:
    """ACA-1: the group is created when its first student registers."""
    user_id = new_id()

    ref = await env.services.enrollment.ensure_student(
        user_id=user_id,
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=555,
    )

    assert (ref.user_id, ref.group_name, ref.subgroup, ref.status) == (
        user_id,
        "2TN2",
        None,
        "active",
    )
    async with env.uow_factory() as uow:
        group = await uow.groups.get_by_emis_id(3292)
    assert group is not None
    assert (group.slug, group.current_semester, group.emis_curriculum_id) == (
        "2tn2",
        3,
        555,
    )


async def test_a_second_student_joins_the_same_group(env: Env) -> None:
    """ACA-1: one group per EMIS group."""
    first = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=None,
    )

    second = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2TN2",
        current_semester=4,
        curriculum_id=7,
    )

    assert second.group_id == first.group_id
    async with env.uow_factory() as uow:
        group = await uow.groups.get(first.group_id)
    assert group is not None and (group.current_semester, group.emis_curriculum_id) == (
        4,
        7,
    )


async def test_a_group_made_in_advance_is_linked_by_name(env: Env) -> None:
    """ACA-1: Administration may create a group before anyone registers."""
    teacher = env.teacher()
    prepared = await env.group("2TN2", curator=teacher)

    ref = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=None,
    )

    assert ref.group_id == prepared.id
    async with env.uow_factory() as uow:
        group = await uow.groups.get(prepared.id)
    assert group is not None
    assert (group.emis_group_id, group.curator_id) == (3292, teacher.id)


async def test_moving_to_another_group_clears_the_subgroup(env: Env) -> None:
    """ACA-3: the new curator sets the subgroup again."""
    old = await env.group("2TN2", emis_group_id=3292)
    pupil = await env.student(old, subgroup=2)

    ref = await env.services.enrollment.ensure_student(
        user_id=pupil.id,
        group_emis_id=4001,
        group_name="3TN1",
        current_semester=5,
        curriculum_id=None,
    )

    assert ref.group_name == "3TN1" and ref.subgroup is None
    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None and student.subgroup_set_by is None


async def test_staying_in_the_group_keeps_the_subgroup(env: Env) -> None:
    """ACA-3: nothing changes if the group is the same."""
    group = await env.group("2TN2", emis_group_id=3292)
    pupil = await env.student(group, subgroup=2)

    ref = await env.services.enrollment.ensure_student(
        user_id=pupil.id,
        group_emis_id=3292,
        group_name="2TN2",
        current_semester=3,
        curriculum_id=None,
    )

    assert ref.subgroup == 2


async def test_a_renamed_emis_group_is_renamed(env: Env) -> None:
    """ACA-1: 1TN2 becomes 2TN2 in EMIS at the end of the year."""
    group = await env.group("1TN2", emis_group_id=3292)

    await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=None,
    )

    async with env.uow_factory() as uow:
        renamed = await uow.groups.get(group.id)
    assert renamed is not None and (renamed.name, renamed.slug) == ("2TN2", "2tn2")


async def test_an_empty_group_holding_the_new_name_is_archived(env: Env) -> None:
    """ACA-1: last year's empty 2TN2 makes room for this year's."""
    old = await env.group("2TN2", emis_group_id=1111)
    await env.group("1TN2", emis_group_id=3292)

    await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2TN2",
        current_semester=3,
        curriculum_id=None,
    )

    async with env.uow_factory() as uow:
        archived = await uow.groups.get(old.id)
    assert archived is not None and archived.status == "archived"


async def test_a_group_with_students_keeps_its_name(env: Env) -> None:
    """ACA-1: a name in use by active students cannot be taken."""
    busy = await env.group("2TN2", emis_group_id=1111)
    await env.student(busy)

    with pytest.raises(GroupNameTakenError):
        await env.services.enrollment.ensure_student(
            user_id=new_id(),
            group_emis_id=3292,
            group_name="2TN2",
            current_semester=3,
            curriculum_id=None,
        )


async def test_an_imported_student_is_found_by_name_and_group(env: Env) -> None:
    """ACA-18: registration claims the imported student after the name matches."""
    group = await env.group("2TN2")
    imported = await env.student(
        group,
        first_name="Aleksey",
        last_name="Brastilov",
        user_status=UserStatus.UNREGISTERED,
    )

    found = await env.services.enrollment.find_imported_student(
        emis_student_id=1,
        first_name="ALEKSEY",
        last_name="brastilov",
        group_name="2ТН2",
    )

    assert found == imported.id


async def test_only_unregistered_students_can_be_claimed(env: Env) -> None:
    """ACA-18: an active account is never claimed by name."""
    group = await env.group("2TN2")
    await env.student(group, first_name="Aleksey", last_name="Brastilov")

    assert (
        await env.services.enrollment.find_imported_student(
            emis_student_id=None,
            first_name="Aleksey",
            last_name="Brastilov",
            group_name="2TN2",
        )
        is None
    )


async def test_namesakes_and_other_groups_do_not_match(env: Env) -> None:
    """ACA-18: ambiguous or foreign matches return None."""
    group = await env.group("2TN2")
    other = await env.group("2TN1")
    for _ in range(2):
        await env.student(
            group,
            first_name="Ivan",
            last_name="Ivanov",
            user_status=UserStatus.UNREGISTERED,
        )
    await env.student(
        other,
        first_name="Petr",
        last_name="Petrov",
        user_status=UserStatus.UNREGISTERED,
    )
    enrollment = env.services.enrollment

    assert (
        await enrollment.find_imported_student(
            emis_student_id=None,
            first_name="Ivan",
            last_name="Ivanov",
            group_name="2TN2",
        )
        is None
    )
    assert (
        await enrollment.find_imported_student(
            emis_student_id=None,
            first_name="Petr",
            last_name="Petrov",
            group_name="2TN2",
        )
        is None
    )
    assert (
        await enrollment.find_imported_student(
            emis_student_id=None,
            first_name="Petr",
            last_name="Petrov",
            group_name="Nope",
        )
        is None
    )


def subject(emis_id: int, uz: str = "", ru: str = "", en: str = "") -> EmisSubject:
    """An EMIS subject."""
    return EmisSubject(emis_subject_id=emis_id, name_uz=uz, name_ru=ru, name_en=en)


async def test_subjects_are_created_and_listed_in_the_group_curriculum(
    env: Env,
) -> None:
    """SYNC: subjects come from EMIS and fill Group.subject_ids."""
    group = await env.group()

    await env.services.enrollment.sync_subjects(
        group_id=group.id,
        subjects=[
            subject(10, ru="Физика"),
            subject(11, uz="Kimyo", ru="Химия", en="Chemistry"),
        ],
    )

    async with env.uow_factory() as uow:
        saved = await uow.groups.get(group.id)
        assert saved is not None
        subjects = await uow.subjects.get_many(saved.subject_ids)
    assert [subjects[i].emis_subject_id for i in saved.subject_ids] == [10, 11]
    assert subjects[saved.subject_ids[1]].name == {
        "uz": "Kimyo",
        "ru": "Химия",
        "en": "Chemistry",
    }


async def test_syncing_subjects_again_updates_names_without_duplicates(
    env: Env,
) -> None:
    """ADM-7: EMIS leaves languages empty; known names are not erased."""
    first = await env.group("2TN1")
    second = await env.group("2TN2")
    enrollment = env.services.enrollment
    await enrollment.sync_subjects(
        group_id=first.id, subjects=[subject(10, uz="Fizika", ru="Физика")]
    )

    await enrollment.sync_subjects(
        group_id=second.id, subjects=[subject(10, ru="Физика 2", en="Physics")]
    )

    async with env.uow_factory() as uow:
        a = await uow.groups.get(first.id)
        b = await uow.groups.get(second.id)
        assert a is not None and b is not None
        assert a.subject_ids == b.subject_ids and len(a.subject_ids) == 1
        merged = await uow.subjects.get(a.subject_ids[0])
    assert merged is not None
    assert merged.name == {"uz": "Fizika", "ru": "Физика 2", "en": "Physics"}


async def test_a_student_who_leaves_is_marked_and_told(env: Env) -> None:
    """ACA-19: left with date and reason; the account closes in 30 days."""
    group = await env.group()
    pupil = await env.student(group, subgroup=1)

    await env.services.enrollment.mark_left(pupil.id, reason="institution")

    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None
    assert (student.status, student.left_at, student.left_reason) == (
        "left",
        dt.date(2026, 10, 6),
        "transferred",
    )
    [note] = env.notifications
    assert (note.user_id, note.type) == (pupil.id, NotificationType.ACCOUNT_CLOSING)
    assert note.payload == {"closes_on": "2026-11-05"}
    assert note.dedupe_key == f"account-closing:{pupil.id}"


@pytest.mark.parametrize(
    ("reason", "stored"),
    [
        ("graduated", "graduated"),
        ("expelled", "expelled"),
        ("deleted", "other"),
        ("???", "other"),
    ],
)
async def test_leaving_reasons_are_mapped_to_the_stored_values(
    env: Env, reason: str, stored: str
) -> None:
    """README -> Student.left_reason: graduated, expelled, transferred, other."""
    pupil = await env.student(await env.group())

    await env.services.enrollment.mark_left(pupil.id, reason=reason)

    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None and student.left_reason == stored


async def test_leaving_twice_or_for_a_non_student_does_nothing(env: Env) -> None:
    """ACA-19: idempotent; teachers have no student row."""
    pupil = await env.student(await env.group())
    teacher = env.teacher()
    enrollment = env.services.enrollment

    await enrollment.mark_left(pupil.id, reason="expelled")
    await enrollment.mark_left(pupil.id, reason="graduated")
    await enrollment.mark_left(teacher.id, reason="deleted")

    assert len(env.notifications) == 1
    async with env.uow_factory() as uow:
        student = await uow.students.get(pupil.id)
    assert student is not None and student.left_reason == "expelled"


async def test_a_group_without_a_timetable_asks_for_an_import(env: Env) -> None:
    """ACA-1: the caller kicks academic.bootstrap_group once the account is saved."""
    await env.term()

    ref = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=None,
    )

    assert ref.needs_timetable


async def test_a_group_with_a_timetable_does_not_ask_for_an_import(env: Env) -> None:
    """ACA-1: the second student of an imported group finds the timetable there."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN2", emis_group_id=3292)
    await env.entry(
        term, weekday=1, period=1, subject=subject, audience=[str(group.id)]
    )

    ref = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2TN2",
        current_semester=3,
        curriculum_id=None,
    )

    assert not ref.needs_timetable


async def test_without_a_term_there_is_nowhere_to_import_a_timetable(env: Env) -> None:
    """ACA-1: no term yet, no pointless task."""
    ref = await env.services.enrollment.ensure_student(
        user_id=new_id(),
        group_emis_id=3292,
        group_name="2ТН2",
        current_semester=3,
        curriculum_id=None,
    )

    assert not ref.needs_timetable
