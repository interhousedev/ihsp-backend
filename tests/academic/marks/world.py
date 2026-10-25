"""A small academic world for the marks tests: group, subjects, student, lessons."""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.orm.term import Term
from app.shared.ids import new_id

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DAY = dt.date(2026, 10, 6)
MATH_EMIS = 101
PHYSICS_EMIS = 102


def _at(day: dt.date, hour: int, minute: int) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=dt.UTC)


@dataclass(slots=True)
class World:
    """Ids of the seeded rows."""

    user_id: UUID
    group_id: UUID
    math_id: UUID
    physics_id: UUID
    term_id: UUID
    teacher_id: UUID
    math_lesson_1: UUID
    math_lesson_2: UUID
    physics_lesson: UUID
    math_next: UUID


def _lesson(
    term_id: UUID,
    group_id: UUID,
    subject_id: UUID,
    teacher_id: UUID,
    day: dt.date,
    period: int,
    start: tuple[int, int],
    end: tuple[int, int],
) -> Lesson:
    return Lesson(
        id=new_id(),
        term_id=term_id,
        date=day,
        period=period,
        starts_at=_at(day, *start),
        ends_at=_at(day, *end),
        subject_id=subject_id,
        teacher_id=teacher_id,
        audience=[str(group_id)],
        status="scheduled",
    )


async def seed_world(
    maker: async_sessionmaker[AsyncSession],
    *,
    backfilled: bool = True,
    current_semester: int | None = 3,
) -> World:
    """Insert a group with two subjects, one student, a term and four lessons."""
    group = Group(
        id=new_id(),
        emis_group_id=3292,
        name="2TN2",
        slug="2tn2",
        current_semester=current_semester,
        status="active",
    )
    math = Subject(
        id=new_id(),
        emis_subject_id=MATH_EMIS,
        name={"uz": "Matematika", "ru": "Математика", "en": "Mathematics"},
        short_name="Math",
    )
    physics = Subject(
        id=new_id(),
        emis_subject_id=PHYSICS_EMIS,
        name={"uz": "Fizika", "ru": "Физика", "en": ""},
        short_name=None,
    )
    group.subject_ids = [math.id, physics.id]
    term = Term(
        id=new_id(),
        academic_year="2026/2027",
        half=1,
        starts_on=dt.date(2026, 9, 1),
        ends_on=dt.date(2026, 12, 31),
        bells=[],
    )
    user_id, teacher_id = new_id(), new_id()
    student = Student(
        user_id=user_id,
        group_id=group.id,
        status="active",
        backfilled_at=_at(dt.date(2026, 9, 2), 0, 0) if backfilled else None,
    )
    m1 = _lesson(term.id, group.id, math.id, teacher_id, DAY, 1, (3, 30), (4, 15))
    m2 = _lesson(term.id, group.id, math.id, teacher_id, DAY, 2, (4, 25), (5, 10))
    ph = _lesson(term.id, group.id, physics.id, teacher_id, DAY, 3, (5, 20), (6, 5))
    nxt = _lesson(
        term.id,
        group.id,
        math.id,
        teacher_id,
        dt.date(2026, 10, 8),
        1,
        (3, 30),
        (4, 15),
    )
    async with maker() as session:
        session.add_all([group, math, physics, term])
        await session.flush()
        session.add(student)
        await session.flush()
        session.add_all([m1, m2, ph, nxt])
        await session.commit()
    return World(
        user_id=user_id,
        group_id=group.id,
        math_id=math.id,
        physics_id=physics.id,
        term_id=term.id,
        teacher_id=teacher_id,
        math_lesson_1=m1.id,
        math_lesson_2=m2.id,
        physics_lesson=ph.id,
        math_next=nxt.id,
    )


async def add_student(
    maker: async_sessionmaker[AsyncSession], world: World, *, backfilled: bool = True
) -> UUID:
    """Add one more student to the world's group."""
    user_id = new_id()
    async with maker() as session:
        session.add(
            Student(
                user_id=user_id,
                group_id=world.group_id,
                status="active",
                backfilled_at=_at(dt.date(2026, 9, 2), 0, 0) if backfilled else None,
            )
        )
        await session.commit()
    return user_id
