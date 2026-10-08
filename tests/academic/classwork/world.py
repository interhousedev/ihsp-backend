"""A small academic world for the classwork tests."""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.result import Result
from app.modules.academic.infrastructure.orm.room import Room
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.orm.term import Term
from app.shared.actor import Role
from app.shared.clock import TASHKENT
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from tests.fakes.academic.classwork.identity import FakeIdentity

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]

# The fixed clock is 2026-10-06 09:00 UTC = 14:00 in Tashkent, a Tuesday.
DAY = dt.date(2026, 10, 6)

# "Not given": add_lesson(teacher_id=None) means a lesson that needs a teacher.
UNSET: Any = object()


@dataclass(slots=True)
class World:
    """Ids and names of the seeded rows."""

    term_id: UUID
    group_id: UUID
    other_group_id: UUID
    physics_id: UUID
    math_id: UUID
    room_id: UUID
    teacher: UserRef
    other_teacher: UserRef
    curator: UserRef
    admin: UserRef
    aziz: UserRef  # subgroup 1
    bobur: UserRef  # subgroup 2
    camila: UserRef  # no subgroup
    outsider: UserRef  # another group


def local(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    """A Tashkent wall-clock time as UTC."""
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=TASHKENT).astimezone(
        dt.UTC
    )


def period_times(day: dt.date, period: int) -> tuple[dt.datetime, dt.datetime]:
    """Period 1 is 08:30; periods are 55 minutes apart and last 45."""
    start = dt.datetime.combine(day, dt.time(8, 30), tzinfo=TASHKENT) + dt.timedelta(
        minutes=55 * (period - 1)
    )
    return start.astimezone(dt.UTC), (start + dt.timedelta(minutes=45)).astimezone(
        dt.UTC
    )


async def seed_world(maker: Maker, identity: FakeIdentity) -> World:
    """Insert two groups, subjects, a room, a term and four students."""
    teacher = identity.add("Gulnara", "Kalandarova", Role.TEACHER)
    other_teacher = identity.add("Rustam", "Yusupov", Role.TEACHER)
    curator = identity.add("Nilufar", "Ergasheva", Role.TEACHER)
    admin = identity.add("Anvar", "Boboev", Role.ADMIN)
    aziz = identity.add("Aziz", "Abdullaev")
    bobur = identity.add("Bobur", "Karimov")
    camila = identity.add("Camila", "Rakhimova")
    outsider = identity.add("Dilnoza", "Saidova")
    group = Group(
        id=new_id(),
        emis_group_id=3292,
        name="2TN2",
        slug="2tn2",
        current_semester=2,
        status="active",
        curator_id=curator.id,
    )
    other = Group(
        id=new_id(),
        emis_group_id=3293,
        name="2TN1",
        slug="2tn1",
        current_semester=2,
        status="active",
    )
    physics = Subject(
        id=new_id(),
        name={"uz": "Fizika", "ru": "Физика", "en": "Physics"},
        short_name="Phys",
    )
    math = Subject(
        id=new_id(),
        name={"uz": "Matematika", "ru": "Математика", "en": ""},
        short_name=None,
    )
    room = Room(id=new_id(), slug="204", name="204", pin="483920")
    term = Term(
        id=new_id(),
        academic_year="2026/2027",
        half=1,
        starts_on=dt.date(2026, 9, 1),
        ends_on=dt.date(2026, 12, 31),
        bells=[],
    )
    async with maker() as session:
        session.add_all([group, other, physics, math, room, term])
        await session.flush()
        for user, grp, sub in (
            (aziz, group, 1),
            (bobur, group, 2),
            (camila, group, None),
            (outsider, other, None),
        ):
            session.add(
                Student(user_id=user.id, group_id=grp.id, subgroup=sub, status="active")
            )
        await session.commit()
    return World(
        term_id=term.id,
        group_id=group.id,
        other_group_id=other.id,
        physics_id=physics.id,
        math_id=math.id,
        room_id=room.id,
        teacher=teacher,
        other_teacher=other_teacher,
        curator=curator,
        admin=admin,
        aziz=aziz,
        bobur=bobur,
        camila=camila,
        outsider=outsider,
    )


async def add_lesson(
    maker: Maker,
    world: World,
    *,
    day: dt.date = DAY,
    period: int = 1,
    subject_id: UUID | None = None,
    teacher_id: UUID | None = UNSET,
    audience: list[str] | None = None,
    **columns: Any,
) -> UUID:
    """Insert a lesson of the world's group; extra columns override defaults."""
    start, end = period_times(day, period)
    values: dict[str, Any] = {
        "id": new_id(),
        "term_id": world.term_id,
        "date": day,
        "period": period,
        "starts_at": start,
        "ends_at": end,
        "subject_id": subject_id or world.physics_id,
        "teacher_id": world.teacher.id if teacher_id is UNSET else teacher_id,
        "room_id": world.room_id,
        "audience": audience or [str(world.group_id)],
        "status": "scheduled",
    }
    values.update(columns)
    async with maker() as session:
        session.add(Lesson(**values))
        await session.commit()
    return values["id"]  # type: ignore[no-any-return]


async def lesson_row(maker: Maker, lesson_id: UUID) -> Lesson:
    """Reload the lesson row for assertions."""
    async with maker() as session:
        row = (
            await session.execute(sa.select(Lesson).where(Lesson.id == lesson_id))
        ).scalar_one()
        return row


async def add_mark(
    maker: Maker,
    student_id: UUID,
    subject_id: UUID,
    *,
    value: int = 5,
    day: dt.date = DAY,
    lesson_id: UUID | None = None,
    semester: int = 2,
    created_at: dt.datetime | None = None,
) -> None:
    """Insert a lesson mark."""
    async with maker() as session:
        mark = Mark(
            id=new_id(),
            student_id=student_id,
            subject_id=subject_id,
            semester=semester,
            type="lesson",
            value=value,
            date=day,
            ordinal=1,
            lesson_id=lesson_id,
        )
        if created_at is not None:
            mark.created_at = created_at
        session.add(mark)
        await session.commit()


async def add_result(
    maker: Maker,
    student_id: UUID,
    semester: int,
    value: float,
    subject_id: UUID | None = None,
) -> None:
    """Insert a result row (the GPA row when ``subject_id`` is None)."""
    async with maker() as session:
        session.add(
            Result(
                id=new_id(),
                student_id=student_id,
                semester=semester,
                subject_id=subject_id,
                value=value,
            )
        )
        await session.commit()


async def seed_attendance(maker: Maker, world: World) -> dict[str, UUID]:
    """Three physics lessons with attendance, one math and one physics without.

    l1: Aziz absent and excused; l2: Aziz and Bobur absent; l3: everyone present;
    math: not taken (yesterday, Yusupov); today: not taken (08:30, started).
    """
    everyone = [world.aziz.id, world.bobur.id, world.camila.id]
    day = dt.timedelta
    l1 = await add_lesson(
        maker,
        world,
        day=DAY - day(days=3),
        topic="Waves",
        attendance_roster=everyone,
        attendance_absent=[world.aziz.id],
        attendance_excused={str(world.aziz.id): {"by": "c", "at": "t", "comment": "x"}},
        attendance_version=1,
    )
    l2 = await add_lesson(
        maker,
        world,
        day=DAY - day(days=2),
        attendance_roster=everyone,
        attendance_absent=[world.aziz.id, world.bobur.id],
        attendance_version=1,
    )
    l3 = await add_lesson(
        maker,
        world,
        day=DAY - day(days=1),
        attendance_roster=everyone,
        attendance_absent=[],
        attendance_version=1,
    )
    math = await add_lesson(
        maker,
        world,
        day=DAY - day(days=1),
        period=2,
        subject_id=world.math_id,
        teacher_id=world.other_teacher.id,
    )
    today = await add_lesson(maker, world, day=DAY, period=1)
    return {"l1": l1, "l2": l2, "l3": l3, "math": math, "today": today}
