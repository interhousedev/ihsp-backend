"""ScheduleQueries: what other modules may ask the schedule (contracts/academic.py)."""

import datetime as dt
import uuid
from dataclasses import dataclass

from app.modules.academic.application.schedule.update_lesson import LessonPatch
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.domain.schedule.term import Term
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
from tests.academic.schedule.env import Env
from tests.factories import make_actor

D7, D8, D9 = dt.date(2026, 10, 7), dt.date(2026, 10, 8), dt.date(2026, 10, 9)


@dataclass(slots=True)
class School:
    """A group with two subgroups, another group and three lessons."""

    term: Term
    group: Group
    other: Group
    sub1: UserRef
    sub2: UserRef
    unset: UserRef
    outsider: UserRef
    teacher: UserRef
    room: Room
    whole: Lesson
    first_half: Lesson
    second_half: Lesson
    elsewhere: Lesson


async def build_school(env: Env) -> School:
    """Seed one term with a group split in two and an unrelated group."""
    term = await env.term()
    math = await env.subject("Математика", short="Мат")
    physics = await env.subject("Физика", short="Физ")
    teacher = env.teacher()
    group = await env.group("2TN2")
    other = await env.group("1TN1", semester=1)
    room = await env.room("102")
    sub1 = await env.student(group, subgroup=1, last_name="One")
    sub2 = await env.student(group, subgroup=2, last_name="Two")
    unset = await env.student(group, last_name="Unset")
    outsider = await env.student(other, last_name="Outsider")
    whole = await env.lesson(
        term,
        day=D7,
        period=1,
        subject=math,
        audience=[audience_keys.key(group.id, None)],
        teacher=teacher,
        room=room,
    )
    first_half = await env.lesson(
        term,
        day=D8,
        period=1,
        subject=physics,
        audience=[audience_keys.key(group.id, 1)],
    )
    second_half = await env.lesson(
        term,
        day=D8,
        period=2,
        subject=physics,
        audience=[audience_keys.key(group.id, 2)],
    )
    elsewhere = await env.lesson(
        term,
        day=D8,
        period=3,
        subject=math,
        audience=[audience_keys.key(other.id, None)],
    )
    return School(
        term,
        group,
        other,
        sub1,
        sub2,
        unset,
        outsider,
        teacher,
        room,
        whole,
        first_half,
        second_half,
        elsewhere,
    )


async def test_a_student_sees_the_whole_group_and_their_subgroup(env: Env) -> None:
    """ACA-2: subgroup 1 does not see subgroup 2's lessons."""
    school = await build_school(env)

    lessons = await env.services.queries.lessons_for_student(school.sub1.id, D7, D9)

    assert [x.id for x in lessons] == [school.whole.id, school.first_half.id]


async def test_a_student_without_a_subgroup_sees_both_subgroups(env: Env) -> None:
    """ACA-2: until the curator assigns one, both subgroups' lessons show."""
    school = await build_school(env)

    lessons = await env.services.queries.lessons_for_student(school.unset.id, D7, D9)

    assert [x.id for x in lessons] == [
        school.whole.id,
        school.first_half.id,
        school.second_half.id,
    ]


async def test_lessons_for_student_includes_cancelled_lessons_and_respects_dates(
    env: Env,
) -> None:
    """ACA-7: cancelled lessons are shown as cancelled; the range is inclusive."""
    school = await build_school(env)
    await env.services.update_lesson.execute(
        make_actor(Role.ADMIN), school.whole.id, LessonPatch(status="cancelled")
    )

    only_first_day = await env.services.queries.lessons_for_student(
        school.sub1.id, D7, D7
    )

    assert [(x.id, x.status) for x in only_first_day] == [
        (school.whole.id, "cancelled")
    ]


async def test_a_student_of_another_group_sees_only_their_lessons(env: Env) -> None:
    """ACA-6: audience keys keep groups apart."""
    school = await build_school(env)

    lessons = await env.services.queries.lessons_for_student(school.outsider.id, D7, D9)

    assert [x.id for x in lessons] == [school.elsewhere.id]


async def test_an_unknown_student_has_no_lessons(env: Env) -> None:
    """Contract: unknown users get an empty list."""
    await build_school(env)

    assert await env.services.queries.lessons_for_student(uuid.uuid4(), D7, D9) == []


async def test_lesson_ref_has_names_room_and_audience(env: Env) -> None:
    """Contract: LessonRef carries what other modules display."""
    school = await build_school(env)

    ref = await env.services.queries.get_lesson(school.first_half.id)
    whole = await env.services.queries.get_lesson(school.whole.id)

    assert ref is not None and whole is not None
    assert ref.subject_name == "Физика" and ref.status == "scheduled"
    assert ref.group_names == ("2TN2/1",) and ref.audience == (f"{school.group.id}:1",)
    assert whole.group_names == ("2TN2",)
    assert (whole.room_slug, whole.room_name, whole.teacher_id) == (
        "102",
        "102",
        school.teacher.id,
    )
    assert (whole.date, whole.period) == (D7, 1)


async def test_an_unknown_lesson_is_none(env: Env) -> None:
    """Contract: get_lesson returns None for unknown ids."""
    await build_school(env)

    assert await env.services.queries.get_lesson(uuid.uuid4()) is None


async def test_lessons_for_teacher(env: Env) -> None:
    """Contract: lessons of a teacher between two dates."""
    school = await build_school(env)

    mine = await env.services.queries.lessons_for_teacher(school.teacher.id, D7, D9)
    none = await env.services.queries.lessons_for_teacher(school.teacher.id, D8, D9)

    assert [x.id for x in mine] == [school.whole.id] and none == []


async def test_audience_membership_follows_subgroups(env: Env) -> None:
    """Contract: is_in_audience is true for the subgroup and for unset students."""
    school = await build_school(env)
    queries = env.services.queries

    assert await queries.is_in_audience(school.sub1.id, school.first_half.id)
    assert not await queries.is_in_audience(school.sub1.id, school.second_half.id)
    assert await queries.is_in_audience(school.unset.id, school.second_half.id)
    assert await queries.is_in_audience(school.sub2.id, school.whole.id)
    assert not await queries.is_in_audience(school.outsider.id, school.whole.id)
    assert not await queries.is_in_audience(uuid.uuid4(), school.whole.id)


async def test_a_student_who_left_is_not_in_the_audience(env: Env) -> None:
    """ACA-19: left students are removed from rosters."""
    school = await build_school(env)
    await env.services.enrollment.mark_left(school.sub1.id, reason="expelled")

    assert not await env.services.queries.is_in_audience(
        school.sub1.id, school.whole.id
    )


async def test_is_lesson_teacher(env: Env) -> None:
    """Contract: only the lesson's teacher qualifies."""
    school = await build_school(env)
    queries = env.services.queries

    assert await queries.is_lesson_teacher(school.teacher.id, school.whole.id)
    assert not await queries.is_lesson_teacher(school.teacher.id, school.first_half.id)
    assert not await queries.is_lesson_teacher(school.sub1.id, school.whole.id)


async def test_head_students_come_from_every_group_of_the_audience(env: Env) -> None:
    """Contract: head_student_ids(lesson) for merged lessons."""
    term = await env.term()
    subject = await env.subject()
    first = await env.group("2TN1")
    second = await env.group("2TN2")
    third = await env.group("2TN3")
    admin = make_actor(Role.ADMIN)
    head_one = await env.student(first, last_name="HeadOne")
    head_two = await env.student(second, last_name="HeadTwo")
    await env.services.update_group.execute(
        admin, first.id, head_student_id=head_one.id
    )
    await env.services.update_group.execute(
        admin, second.id, head_student_id=head_two.id
    )
    merged = await env.lesson(
        term,
        day=D7,
        period=1,
        subject=subject,
        audience=[audience_keys.key(first.id, 2), audience_keys.key(second.id, 2)],
    )
    alone = await env.lesson(
        term, day=D7, period=2, subject=subject, audience=[str(third.id)]
    )

    heads = await env.services.queries.head_student_ids(merged.id)

    assert set(heads) == {head_one.id, head_two.id}
    assert await env.services.queries.head_student_ids(alone.id) == []


async def test_room_lookup_and_day_listing(env: Env) -> None:
    """ROOM-4: the room page lists the day's lessons by period."""
    school = await build_school(env)
    later = await env.lesson(
        school.term,
        day=D7,
        period=3,
        subject=await env.subject("Химия"),
        audience=[str(school.group.id)],
        room=school.room,
    )

    room = await env.services.queries.room_by_slug("102")
    day = await env.services.queries.room_day(school.room.id, D7)

    assert room is not None
    assert (room.id, room.pin, room.status) == (
        school.room.id,
        school.room.pin,
        "active",
    )
    assert [x.id for x in day] == [school.whole.id, later.id]
    assert await env.services.queries.room_by_slug("nope") is None


async def test_group_user_ids_filters_by_semester(env: Env) -> None:
    """Broadcast audiences: groups, optionally narrowed by semester."""
    school = await build_school(env)
    queries = env.services.queries

    both = await queries.group_user_ids([school.group.id, school.other.id])
    third_semester = await queries.group_user_ids(
        [school.group.id, school.other.id], [3]
    )

    assert set(both) == {
        school.sub1.id,
        school.sub2.id,
        school.unset.id,
        school.outsider.id,
    }
    assert set(third_semester) == {school.sub1.id, school.sub2.id, school.unset.id}
    assert await queries.group_user_ids([]) == []


async def test_group_user_ids_without_groups_means_every_group_of_the_semesters(
    env: Env,
) -> None:
    """Broadcast audience (B8): semesters alone select all groups in them."""
    school = await build_school(env)
    queries = env.services.queries

    first_year = await queries.group_user_ids((), [1])
    third = await queries.group_user_ids((), [3])
    both = await queries.group_user_ids((), [1, 3])
    unknown = await queries.group_user_ids((), [4])

    assert first_year == [school.outsider.id]
    assert set(third) == {school.sub1.id, school.sub2.id, school.unset.id}
    assert set(both) == {
        school.sub1.id,
        school.sub2.id,
        school.unset.id,
        school.outsider.id,
    }
    assert unknown == []


async def test_group_user_ids_skip_students_who_left(env: Env) -> None:
    """ACA-19: left students do not receive broadcasts."""
    school = await build_school(env)
    await env.services.enrollment.mark_left(school.sub2.id, reason="graduated")

    users = await env.services.queries.group_user_ids([school.group.id])

    assert school.sub2.id not in users and school.sub1.id in users


async def test_curated_groups_and_student_record(env: Env) -> None:
    """Contract: curated_group_ids and get_student."""
    school = await build_school(env)
    curator = env.teacher("Head", "Teacher")
    admin = make_actor(Role.ADMIN)
    await env.services.update_group.execute(
        admin, school.group.id, curator_id=curator.id
    )

    curated = await env.services.queries.curated_group_ids(curator.id)
    student = await env.services.queries.get_student(school.sub1.id)

    assert curated == [school.group.id]
    assert student is not None
    assert (student.group_name, student.subgroup, student.status) == (
        "2TN2",
        1,
        "active",
    )
    assert await env.services.queries.get_student(uuid.uuid4()) is None


async def test_search_finds_lessons_by_subject_name_for_students_and_teachers(
    env: Env,
) -> None:
    """WEB-4: search lessons of the user by subject or topic."""
    school = await build_school(env)
    queries = env.services.queries

    student_hits = await queries.search_lessons(school.sub1.id, "Физ", 10)
    teacher_hits = await queries.search_lessons(school.teacher.id, "Мат", 10)
    nothing = await queries.search_lessons(school.sub1.id, "Химия", 10)
    limited = await queries.search_lessons(school.unset.id, "Ф", 1)

    assert [x.id for x in student_hits] == [school.first_half.id]
    assert [x.id for x in teacher_hits] == [school.whole.id]
    assert nothing == []
    assert len(limited) == 1


async def test_projected_lessons_continue_after_the_last_generated_one(
    env: Env,
) -> None:
    """WEB-6: the timetable is expanded beyond the 14-day generation horizon."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    entry = await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )
    pupil = await env.student(group, subgroup=1)
    await env.services.generate_lessons.execute(from_date=dt.date(2026, 10, 6), days=14)

    lessons = await env.services.queries.projected_lessons_for_student(
        pupil.id, dt.date(2026, 10, 12), dt.date(2026, 10, 28)
    )

    assert [x.date for x in lessons] == [
        dt.date(2026, 10, 14),
        dt.date(2026, 10, 21),
        dt.date(2026, 10, 28),
    ]
    projected = lessons[1]
    assert projected.id == uuid.uuid5(uuid.NAMESPACE_URL, f"{entry.id}:2026-10-21")
    assert projected.subject_name == "Математика" and projected.status == "scheduled"
    assert projected.starts_at == dt.datetime(2026, 10, 21, 3, 30, tzinfo=dt.UTC)


async def test_projection_respects_subgroups(env: Env) -> None:
    """ACA-2 applies to projected lessons too."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term,
        weekday=3,
        period=1,
        subject=subject,
        audience=[audience_keys.key(group.id, 2)],
    )
    first = await env.student(group, subgroup=1, last_name="First")
    second = await env.student(group, subgroup=2, last_name="Second")
    queries = env.services.queries

    seen_by_first = await queries.projected_lessons_for_student(
        first.id, dt.date(2026, 10, 7), dt.date(2026, 10, 14)
    )
    seen_by_second = await queries.projected_lessons_for_student(
        second.id, dt.date(2026, 10, 7), dt.date(2026, 10, 14)
    )

    assert seen_by_first == []
    assert [x.date for x in seen_by_second] == [
        dt.date(2026, 10, 7),
        dt.date(2026, 10, 14),
    ]
