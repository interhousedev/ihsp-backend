"""Fixtures of the assessments tests: a seeded academic world and the services."""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.term import Term
from app.modules.academic.wiring_assessments import (
    AssessmentServices,
    build_assessments,
)
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.academic.marks.fakes.identity import FakeIdentity, make_user
from tests.academic.marks.world import World, seed_world
from tests.fakes.clock import FixedClock
from tests.fakes.outbox import InMemoryOutbox

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]

CONTROL_PERIODS = {
    "midterm_1": {"start": "2026-10-19", "end": "2026-10-24"},
    "midterm_2": {"start": "2026-11-23", "end": "2026-11-28"},
    "final": {"start": "2026-12-14", "end": "2026-12-19"},
}


@dataclass(slots=True)
class Env:
    """The seeded world, the services and the people."""

    world: World
    services: AssessmentServices
    outbox: InMemoryOutbox
    identity: FakeIdentity
    maker: Maker
    clock: FixedClock
    head_id: UUID
    subgroup_id: UUID
    other_teacher_id: UUID
    admin_id: UUID

    def student(self) -> Actor:
        """The world's student."""
        return Actor(self.world.user_id, frozenset({Role.STUDENT}))

    def head(self) -> Actor:
        """The head student of the group."""
        return Actor(self.head_id, frozenset({Role.STUDENT}))

    def teacher(self) -> Actor:
        """The teacher of math and physics in the group."""
        return Actor(self.world.teacher_id, frozenset({Role.TEACHER}))

    def stranger(self) -> Actor:
        """A teacher who teaches nothing in the group."""
        return Actor(self.other_teacher_id, frozenset({Role.TEACHER}))

    def admin(self) -> Actor:
        """An administrator."""
        return Actor(self.admin_id, frozenset({Role.ADMIN}))


@pytest.fixture
def outbox() -> InMemoryOutbox:
    """Collects the notifications written at commit."""
    return InMemoryOutbox()


@pytest_asyncio.fixture
async def env(
    sessionmaker_in_tx: Maker,
    outbox: InMemoryOutbox,
    clock: FixedClock,
    settings: Any,
    redis: Any,
    kicker: Any,
    i18n: Any,
) -> Env:
    """A group with a teacher, three students, control weeks and the services."""
    world = await seed_world(sessionmaker_in_tx)
    head_id, subgroup_id = new_id(), new_id()
    async with sessionmaker_in_tx() as session:
        term = await session.get(Term, world.term_id)
        group = await session.get(Group, world.group_id)
        assert term is not None and group is not None
        term.control_periods = CONTROL_PERIODS
        group.head_student_id = head_id
        session.add_all(
            [
                Student(user_id=head_id, group_id=world.group_id, status="active"),
                Student(
                    user_id=subgroup_id,
                    group_id=world.group_id,
                    status="active",
                    subgroup=1,
                ),
            ]
        )
        await session.commit()
    other_teacher_id, admin_id = new_id(), new_id()
    identity = FakeIdentity()
    identity.add(make_user(world.user_id, locale="en"))
    identity.add(make_user(head_id, first_name="Head", locale="ru"))
    identity.add(make_user(subgroup_id, first_name="Sub", locale="uz"))
    identity.add(make_user(world.teacher_id, roles=frozenset({Role.TEACHER})))
    identity.add(make_user(other_teacher_id, roles=frozenset({Role.TEACHER})))
    identity.add(make_user(admin_id, roles=frozenset({Role.ADMIN})))
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=outbox.write_notifications,
        audit_writer=outbox.write_audit,
        outbox_committed_hook=None,
    )
    services = build_assessments(deps, identity=identity)  # type: ignore[arg-type]
    return Env(
        world,
        services,
        outbox,
        identity,
        sessionmaker_in_tx,
        clock,
        head_id,
        subgroup_id,
        other_teacher_id,
        admin_id,
    )


async def add_exam_lesson(
    env: Env,
    day: dt.date,
    *,
    kind: str = "midterm",
    subject_id: UUID | None = None,
    topic: str | None = None,
    emis_topic: str | None = None,
    hour: int = 4,
    audience: list[str] | None = None,
    status: str = "scheduled",
) -> UUID:
    """Insert a lesson of the given EMIS kind (scheduled; for the whole group)."""
    lesson_id = new_id()
    start = dt.datetime.combine(day, dt.time(hour, 0), tzinfo=dt.UTC)
    async with env.maker() as session:
        session.add(
            Lesson(
                id=lesson_id,
                term_id=env.world.term_id,
                date=day,
                period=hour,
                starts_at=start,
                ends_at=start + dt.timedelta(minutes=45),
                subject_id=subject_id or env.world.math_id,
                teacher_id=env.world.teacher_id,
                audience=audience or [str(env.world.group_id)],
                status=status,
                kind=kind,
                topic=topic,
                emis_topic=emis_topic,
            )
        )
        await session.commit()
    return lesson_id
