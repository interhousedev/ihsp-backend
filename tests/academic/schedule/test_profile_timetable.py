"""Student profile and the student and staff timetables (WEB-5, WEB-16, STF-3)."""

import datetime as dt

from app.modules.academic.application.schedule.date_range import InvalidDateRangeError
from app.modules.academic.domain.schedule.errors import StudentNotFoundError
from app.shared.actor import Role
from tests.academic.schedule.env import MAIL_DOMAIN, Env
from tests.factories import make_actor

import pytest


async def test_the_profile_has_group_curator_head_and_mailbox(env: Env) -> None:
    """WEB-16: the student sees group, subgroup, curator, head student and mailbox."""
    curator = env.teacher()
    group = await env.group("2TN2", curator=curator, semester=3)
    head = await env.student(group, last_name="Head", first_name="Hanna")
    me = await env.student(group, subgroup=2, last_name="Karimova", first_name="Aliya")
    await env.services.update_group.execute(
        make_actor(Role.ADMIN), group.id, head_student_id=head.id
    )

    profile = await env.services.get_student_profile.execute(
        make_actor(Role.STUDENT, user_id=me.id)
    )

    assert (profile.user_id, profile.first_name, profile.last_name) == (
        me.id,
        "Aliya",
        "Karimova",
    )
    assert profile.mailbox == f"karimova.aliya@{MAIL_DOMAIN}"
    assert (profile.group_id, profile.group_name, profile.subgroup) == (
        group.id,
        "2TN2",
        2,
    )
    assert profile.curator is not None and profile.curator.id == curator.id
    assert profile.head_student is not None and profile.head_student.id == head.id
    assert profile.current_semester == 3 and profile.emis_status == "active"


async def test_a_user_who_is_not_a_student_has_no_profile(env: Env) -> None:
    """WEB-16: teachers have no student profile."""
    teacher = env.teacher()

    with pytest.raises(StudentNotFoundError):
        await env.services.get_student_profile.execute(
            make_actor(Role.STUDENT, user_id=teacher.id)
        )


async def test_the_student_timetable_follows_the_subgroup(env: Env) -> None:
    """WEB-5: the student's day or week for their group and subgroup."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    teacher = env.teacher()
    pupil = await env.student(group, subgroup=1)
    await env.entry(
        term,
        weekday=3,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
    )
    await env.entry(
        term, weekday=3, period=2, subject=subject, audience=[f"{group.id}:2"]
    )
    await env.services.generate_lessons.execute(from_date=dt.date(2026, 10, 6), days=14)

    items = await env.services.get_student_timetable.execute(
        make_actor(Role.STUDENT, user_id=pupil.id),
        dt.date(2026, 10, 7),
        dt.date(2026, 10, 13),
    )

    assert [(i["date"], i["period"]) for i in items] == [
        ("2026-10-07", 1),
        ("2026-10-07", 2),
    ]
    item = items[0]
    assert item["subgroup"] is None
    assert items[1]["subgroup"] == {
        "subgroup_id": 2,
        "subgroup_name": "2TN2/2",
        "is_own_subgroup": False,
    }
    assert item["teacher"]["id"] == str(teacher.id)
    assert item["audience"] == [
        {"group_id": str(group.id), "group_name": "2TN2", "subgroup": None}
    ]
    assert item["subject"] == {
        "id": str(subject.id),
        "name": "Математика",
        "short_name": "Мат",
    }
    assert item["status"] == "scheduled" and item["has_homework"] is False


async def test_the_student_timetable_reaches_beyond_generated_lessons(env: Env) -> None:
    """WEB-6: the timetable is expanded from entries past the 14-day horizon."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    pupil = await env.student(group)
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )
    await env.services.generate_lessons.execute(from_date=dt.date(2026, 10, 6), days=14)

    items = await env.services.get_student_timetable.execute(
        make_actor(Role.STUDENT, user_id=pupil.id),
        dt.date(2026, 10, 19),
        dt.date(2026, 10, 25),
    )

    assert [i["date"] for i in items] == ["2026-10-21"]


async def test_the_timetable_defaults_to_the_coming_week(env: Env) -> None:
    """API: from defaults to today; to defaults to a week later."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    pupil = await env.student(group)
    await env.lesson(
        term,
        day=dt.date(2026, 10, 12),
        period=1,
        subject=subject,
        audience=[str(group.id)],
    )
    await env.lesson(
        term,
        day=dt.date(2026, 10, 13),
        period=1,
        subject=subject,
        audience=[str(group.id)],
    )

    items = await env.services.get_student_timetable.execute(
        make_actor(Role.STUDENT, user_id=pupil.id), None, None
    )

    assert [i["date"] for i in items] == ["2026-10-12"]  # Oct 6..12


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (dt.date(2026, 10, 10), dt.date(2026, 10, 9)),
        (dt.date(2026, 1, 1), dt.date(2026, 12, 31)),
    ],
)
async def test_a_reversed_or_huge_range_is_rejected(
    env: Env, start: dt.date, end: dt.date
) -> None:
    """API: the range is validated."""
    pupil = await env.student(await env.group())

    with pytest.raises(InvalidDateRangeError):
        await env.services.get_student_timetable.execute(
            make_actor(Role.STUDENT, user_id=pupil.id), start, end
        )


async def test_the_staff_timetable_lists_the_teachers_lessons(env: Env) -> None:
    """STF-3: a teacher's lessons, including cancelled ones."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    other = env.teacher("Other", "Teacher")
    mine = await env.lesson(
        term,
        day=dt.date(2026, 10, 7),
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
    )
    await env.lesson(
        term,
        day=dt.date(2026, 10, 7),
        period=2,
        subject=subject,
        audience=[str(group.id)],
        teacher=other,
    )

    items = await env.services.get_staff_timetable.execute(
        make_actor(Role.TEACHER, user_id=teacher.id),
        dt.date(2026, 10, 7),
        dt.date(2026, 10, 7),
    )

    assert [i["id"] for i in items] == [str(mine.id)]


async def test_the_other_subgroup_is_shown_only_where_it_adds_a_lesson(
    env: Env,
) -> None:
    """Own subgroup wins a slot of the same subject; other slots show the other."""
    term = await env.term()
    english = await env.subject("Английский", short="Англ")
    it = await env.subject("Информатика", short="Инф")
    group = await env.group("2TN2")
    pupil = await env.student(group, subgroup=1)
    for sub in (1, 2):
        await env.entry(
            term, weekday=3, period=1, subject=english, audience=[f"{group.id}:{sub}"]
        )
    await env.entry(term, weekday=3, period=2, subject=it, audience=[f"{group.id}:2"])
    await env.services.generate_lessons.execute(from_date=dt.date(2026, 10, 6), days=14)

    items = await env.services.get_student_timetable.execute(
        make_actor(Role.STUDENT, user_id=pupil.id),
        dt.date(2026, 10, 7),
        dt.date(2026, 10, 7),
    )

    assert [
        (i["period"], i["subgroup"]["subgroup_id"], i["subgroup"]["is_own_subgroup"])
        for i in items
    ] == [(1, 1, True), (2, 2, False)]


async def test_a_student_without_a_subgroup_owns_every_lesson(env: Env) -> None:
    """Until a subgroup is set, the student attends both halves."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    pupil = await env.student(group)
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[f"{group.id}:2"]
    )
    await env.services.generate_lessons.execute(from_date=dt.date(2026, 10, 6), days=14)

    items = await env.services.get_student_timetable.execute(
        make_actor(Role.STUDENT, user_id=pupil.id),
        dt.date(2026, 10, 7),
        dt.date(2026, 10, 7),
    )

    assert [i["subgroup"] for i in items] == [
        {"subgroup_id": 2, "subgroup_name": "2TN2/2", "is_own_subgroup": True}
    ]
