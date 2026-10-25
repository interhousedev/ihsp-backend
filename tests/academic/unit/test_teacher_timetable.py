"""A student reads a teacher's timetable (all groups) and the teacher cards.

Frozen clock: Tuesday 2026-10-06, 14:00 in Tashkent. Runs on the in-memory fakes.
"""

import dataclasses
import datetime as dt
from dataclasses import dataclass

from app.modules.academic.application.schedule.date_range import (
    InvalidDateRangeError,
)
from app.modules.academic.application.schedule.get_teacher_timetable import (
    TeacherSlot,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.errors import TeacherNotFoundError
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import Term
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserRef
from tests.academic.schedule.env import Env, build_env
from tests.factories import make_actor
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis

TUE = dt.date(2026, 10, 6)  # the frozen day
WED = TUE + dt.timedelta(days=1)
THU = TUE + dt.timedelta(days=2)
FRI = TUE + dt.timedelta(days=3)
SAT = TUE + dt.timedelta(days=4)
SUN = TUE + dt.timedelta(days=5)
NEXT_MON = TUE + dt.timedelta(days=6)


@pytest.fixture
def env(clock: FixedClock, kicker: FakeTaskKicker, redis: FakeRedis) -> Env:
    """The schedule services on in-memory fakes."""
    return build_env("fake", clock=clock, kicker=kicker, redis=redis)


@dataclass(slots=True)
class World:
    """A student of 2TN2 and a teacher who teaches 2TN2 and 1TN1."""

    env: Env
    term: Term
    math: Subject
    physics: Subject
    mine: Group
    other: Group
    student: UserRef
    teacher: UserRef
    actor: Actor

    async def lesson(
        self,
        day: dt.date,
        group: Group,
        *,
        period: int = 1,
        teacher: UserRef | None = None,
        subject: Subject | None = None,
        subgroup: int | None = None,
    ) -> Lesson:
        """Add a lesson of the world's teacher (default) for a group."""
        return await self.env.lesson(
            self.term,
            day=day,
            period=period,
            subject=subject or self.math,
            audience=[audience_keys.key(group.id, subgroup)],
            teacher=teacher or self.teacher,
        )

    async def timetable(
        self,
        start: dt.date | None = TUE,
        end: dt.date | None = NEXT_MON,
        *,
        teacher: UserRef | None = None,
    ) -> list[TeacherSlot]:
        """Run GetTeacherTimetable as the student."""
        return await self.env.services.get_teacher_timetable.execute(
            self.actor, (teacher or self.teacher).id, start, end
        )


@pytest.fixture
async def world(env: Env) -> World:
    """The world, with one lesson for the student's group (so the teacher counts)."""
    term = await env.term()
    mine = await env.group("2TN2")
    other = await env.group("1TN1", semester=1)
    student = await env.student(mine)
    built = World(
        env=env,
        term=term,
        math=await env.subject("Математика"),
        physics=await env.subject("Физика"),
        mine=mine,
        other=other,
        student=student,
        teacher=env.teacher("Gulnora", "Alieva"),
        actor=make_actor(Role.STUDENT, user_id=student.id),
    )
    await built.lesson(TUE, mine, period=1)
    return built


# - - - the timetable of a teacher - - -


async def test_only_the_lessons_of_the_teacher_are_returned(world: World) -> None:
    colleague = world.env.teacher("Bobur", "Zokirov")
    ours = await world.lesson(WED, world.mine, period=2)
    await world.lesson(WED, world.mine, period=3, teacher=colleague)
    await world.lesson(WED, world.other, period=4, teacher=colleague)

    slots = await world.timetable()

    assert [s.id for s in slots][-1] == ours.id
    assert len(slots) == 2  # the Tuesday lesson of the fixture and the Wednesday one
    assert all(s.subject_name == "Математика" for s in slots)


async def test_lessons_of_every_group_are_returned_not_only_the_students(
    world: World,
) -> None:
    await world.lesson(WED, world.other, period=2, subject=world.physics)

    slots = await world.timetable()

    assert [(s.date, s.group) for s in slots] == [(TUE, "2TN2"), (WED, "1TN1")]
    assert slots[1].subject_id == world.physics.id


async def test_the_range_is_inclusive_and_defaults_to_a_week_from_today(
    world: World,
) -> None:
    for day in (WED, THU, FRI):
        await world.lesson(day, world.mine)

    middle = await world.timetable(WED, THU)
    single = await world.timetable(FRI, FRI)
    default = await world.timetable(None, None)

    assert [s.date for s in middle] == [WED, THU]
    assert [s.date for s in single] == [FRI]
    assert [s.date for s in default] == [TUE, WED, THU, FRI]  # Tuesday to Monday


async def test_a_reversed_range_is_rejected(world: World) -> None:
    with pytest.raises(InvalidDateRangeError):
        await world.timetable(THU, WED)


async def test_saturday_and_sunday_lessons_are_left_out(world: World) -> None:
    await world.lesson(FRI, world.mine)
    await world.lesson(SAT, world.mine)
    await world.lesson(SUN, world.other)
    await world.lesson(NEXT_MON, world.other)

    slots = await world.timetable()

    assert [s.date for s in slots] == [TUE, FRI, NEXT_MON]
    assert all(s.date.isoweekday() <= 5 for s in slots)


async def test_mine_is_true_only_for_the_students_own_group_and_subgroup(
    world: World,
) -> None:
    sub = await world.env.student(world.mine, subgroup=2, first_name="Bek")
    await world.lesson(WED, world.other, period=1)
    await world.lesson(WED, world.mine, period=2, subgroup=1)
    await world.lesson(WED, world.mine, period=3, subgroup=2)

    as_whole_group = await world.timetable(WED, WED)
    world.actor = make_actor(Role.STUDENT, user_id=sub.id)
    as_subgroup_two = await world.timetable(WED, WED)

    # The student without a subgroup belongs to both halves of the group.
    assert [(s.group, s.mine) for s in as_whole_group] == [
        ("1TN1", False),
        ("2TN2/1", True),
        ("2TN2/2", True),
    ]
    assert [(s.group, s.mine) for s in as_subgroup_two] == [
        ("1TN1", False),
        ("2TN2/1", False),
        ("2TN2/2", True),
    ]


async def test_cancelled_lessons_stay_with_their_status(world: World) -> None:
    gone = await world.lesson(WED, world.mine)
    assert world.env.store is not None
    world.env.store.lessons[gone.id].status = "cancelled"

    slots = await world.timetable(WED, WED)

    assert [(s.id, s.status) for s in slots] == [(gone.id, "cancelled")]


async def test_a_slot_carries_no_student_data(world: World) -> None:
    room = await world.env.room("305")
    await world.env.lesson(
        world.term,
        day=WED,
        period=2,
        subject=world.math,
        audience=[audience_keys.key(world.mine.id, None)],
        teacher=world.teacher,
        room=room,
    )

    slots = await world.timetable(WED, WED)

    assert slots[0].room == "305"
    assert {f.name for f in dataclasses.fields(TeacherSlot)} == {
        "id",
        "date",
        "starts_at",
        "ends_at",
        "subject_id",
        "subject_name",
        "room",
        "group",
        "mine",
        "status",
        "lesson_id",
    }


async def test_slots_are_sorted_by_start(world: World) -> None:
    await world.lesson(WED, world.other, period=3)
    await world.lesson(WED, world.mine, period=2)
    await world.lesson(THU, world.mine, period=1)

    slots = await world.timetable()

    assert [s.starts_at for s in slots] == sorted(s.starts_at for s in slots)
    assert [s.date for s in slots] == [TUE, WED, WED, THU]


async def test_lessons_beyond_the_generated_ones_are_projected_from_entries(
    env: Env,
) -> None:
    term = await env.term()
    mine = await env.group("2TN2")
    other = await env.group("1TN1", semester=1)
    student = await env.student(mine)
    teacher = env.teacher()
    math = await env.subject("Математика")
    await env.entry(
        term,
        weekday=2,
        period=1,
        subject=math,
        audience=[audience_keys.key(mine.id, None)],
        teacher=teacher,
    )
    await env.entry(
        term,
        weekday=3,
        period=2,
        subject=math,
        audience=[audience_keys.key(other.id, None)],
        teacher=teacher,
    )
    actor = make_actor(Role.STUDENT, user_id=student.id)

    slots = await env.services.get_teacher_timetable.execute(
        actor, teacher.id, TUE, SUN
    )
    again = await env.services.get_teacher_timetable.execute(
        actor, teacher.id, TUE, SUN
    )

    assert [(s.date, s.group, s.mine) for s in slots] == [
        (TUE, "2TN2", True),
        (WED, "1TN1", False),
    ]
    assert [s.id for s in slots] == [s.id for s in again]  # stable projected ids


# - - - who may see a teacher - - -


async def test_a_teacher_who_does_not_teach_the_student_is_not_found(
    world: World,
) -> None:
    stranger = world.env.teacher("Nobody", "Else")
    await world.lesson(WED, world.other, teacher=stranger)

    with pytest.raises(TeacherNotFoundError):
        await world.timetable(teacher=stranger)


async def test_a_user_who_teaches_nothing_is_not_found(world: World) -> None:
    not_a_teacher = world.env.identity.users[world.student.id]

    with pytest.raises(TeacherNotFoundError):
        await world.timetable(teacher=not_a_teacher)


async def test_a_teacher_of_another_subgroup_is_not_found(world: World) -> None:
    half = world.env.teacher("Half", "Group")
    await world.lesson(WED, world.mine, teacher=half, subgroup=1)
    pupil = await world.env.student(world.mine, subgroup=2, first_name="Dil")
    world.actor = make_actor(Role.STUDENT, user_id=pupil.id)

    with pytest.raises(TeacherNotFoundError):
        await world.timetable(teacher=half)


async def test_a_student_who_left_does_not_see_the_teacher(world: World) -> None:
    gone = await world.env.student(world.mine, status="left", first_name="Gone")
    world.actor = make_actor(Role.STUDENT, user_id=gone.id)

    with pytest.raises(TeacherNotFoundError):
        await world.timetable()


async def test_a_teacher_teaching_only_by_an_entry_is_found(env: Env) -> None:
    term = await env.term()
    mine = await env.group("2TN2")
    student = await env.student(mine)
    teacher = env.teacher()
    await env.entry(
        term,
        weekday=2,
        period=1,
        subject=await env.subject("Физика"),
        audience=[audience_keys.key(mine.id, None)],
        teacher=teacher,
    )

    slots = await env.services.get_teacher_timetable.execute(
        make_actor(Role.STUDENT, user_id=student.id), teacher.id, TUE, TUE
    )

    assert [(s.date, s.mine) for s in slots] == [(TUE, True)]


# - - - the teacher cards (GetMyTeachers, GetMyTeacher) - - -


async def test_the_card_has_school_days_upcoming_lessons_subject_refs_and_photo(
    world: World,
) -> None:
    monday = TUE - dt.timedelta(days=1)
    plus_14 = TUE + dt.timedelta(days=14)
    for day in (monday, FRI, SAT, NEXT_MON, plus_14, plus_14 + dt.timedelta(days=1)):
        await world.lesson(day, world.mine, period=2, subject=world.physics)
    cancelled = await world.lesson(WED, world.mine, period=3)
    assert world.env.store is not None
    world.env.store.lessons[cancelled.id].status = "cancelled"
    world.env.identity.photos[world.teacher.id] = "https://photos.test/gulnora.jpg"

    [card] = await world.env.services.get_my_teachers.execute(world.actor)

    assert [d.date for d in card.week] == [monday, TUE, FRI]  # Monday to Friday
    assert [d.date for d in card.upcoming] == [TUE, FRI, NEXT_MON, plus_14]
    assert card.photo_url == "https://photos.test/gulnora.jpg"
    assert [(s.name, s.id) for s in card.subject_refs] == [
        ("Математика", world.math.id),
        ("Физика", world.physics.id),
    ]
    assert card.subjects == ["Математика", "Физика"]
    assert card.upcoming[0].subject_id == world.math.id
    assert card.upcoming[1].subject_id == world.physics.id


async def test_photos_of_all_teachers_are_asked_in_one_call(world: World) -> None:
    second = world.env.teacher("Bobur", "Zokirov")
    await world.lesson(WED, world.mine, teacher=second)

    cards = await world.env.services.get_my_teachers.execute(world.actor)

    assert len(cards) == 2
    assert len(world.env.identity.photo_calls) == 1
    assert {c.photo_url for c in cards} == {None}


async def test_a_teacher_with_only_saturday_lessons_is_not_listed(
    world: World,
) -> None:
    saturday_teacher = world.env.teacher("Sat", "Urday")
    await world.lesson(SAT, world.mine, teacher=saturday_teacher)

    cards = await world.env.services.get_my_teachers.execute(world.actor)

    assert [c.last_name for c in cards] == ["Alieva"]


async def test_one_teacher_is_returned_with_the_same_card(world: World) -> None:
    await world.lesson(WED, world.mine, period=2)
    [listed] = await world.env.services.get_my_teachers.execute(world.actor)

    single = await world.env.services.get_my_teacher.execute(
        world.actor, world.teacher.id
    )

    assert single == listed


async def test_a_teacher_without_lessons_in_the_window_still_has_a_card(
    world: World,
) -> None:
    far = world.env.teacher("Far", "Away")
    await world.lesson(TUE + dt.timedelta(days=60), world.mine, teacher=far)

    single = await world.env.services.get_my_teacher.execute(world.actor, far.id)

    assert single.id == far.id
    assert single.current is None and single.next is None
    assert single.week == [] and single.upcoming == [] and single.subjects == []


async def test_a_teacher_who_does_not_teach_the_student_has_no_card(
    world: World,
) -> None:
    stranger = world.env.teacher("Nobody", "Else")
    await world.lesson(WED, world.other, teacher=stranger)

    with pytest.raises(TeacherNotFoundError):
        await world.env.services.get_my_teacher.execute(world.actor, stranger.id)
