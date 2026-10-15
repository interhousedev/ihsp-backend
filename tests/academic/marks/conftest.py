"""Fixtures of the marks tests: SQL unit of work, fakes and the sync use cases."""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.modules.academic.application.marks.apply_ratings import ApplyRatings
from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.sync_all import SyncAll
from app.modules.academic.application.marks.sync_student import SyncStudent
from app.modules.academic.infrastructure.marks.uow import SqlMarksUnitOfWork
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.wiring_marks import MarksServices, build_marks
from app.shared.actor import Role
from app.shared.contracts.academic import StudentRef
from app.shared.contracts.identity import UserPreferences
from app.shared.contracts.links import ResourceRef
from app.shared.key_lock import KeyLock
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.academic.marks.fakes.bell_sync import FakeBellSync
from tests.academic.marks.fakes.emis import FakeEmis, make_ratings
from tests.academic.marks.fakes.enrollment import (
    FakeEnrollment,
    FakeLinks,
    FakeSchedule,
)
from tests.academic.marks.fakes.identity import (
    FakeIdentity,
    FakeIdentityCommands,
    make_user,
)
from tests.academic.marks.fakes.timetable_sync import FakeTimetableSync
from tests.academic.marks.world import (
    DAY,
    MATH_EMIS,
    PHYSICS_EMIS,
    World,
    seed_world,
)
from tests.fakes.clock import FixedClock
from tests.fakes.outbox import InMemoryOutbox
from tests.fakes.tasks import FakeTaskKicker

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(slots=True)
class Env:
    """Everything a sync test touches."""

    world: World
    emis: FakeEmis
    identity: FakeIdentity
    commands: FakeIdentityCommands
    enrollment: FakeEnrollment
    outbox: InMemoryOutbox
    sync: SyncStudent
    uow_factory: MarksUowFactory
    clock: FixedClock
    bells: FakeBellSync
    timetables: FakeTimetableSync
    kicker: FakeTaskKicker

    def sync_all(self, lock: KeyLock | None = None) -> SyncAll:
        """Build SyncAll that runs one student at a time without delays."""
        return SyncAll(
            uow_factory=self.uow_factory,
            sync_student=self.sync,
            bell_sync=self.bells,
            timetable_sync=self.timetables,
            identity=self.identity,  # type: ignore[arg-type]
            clock=self.clock,
            concurrency=1,
            spread_seconds=0,
            lock=lock,
        )


@pytest.fixture
def outbox() -> InMemoryOutbox:
    """Collects notification drafts written at commit."""
    return InMemoryOutbox()


@pytest.fixture
def uow_factory(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession], outbox: InMemoryOutbox
) -> MarksUowFactory:
    """Marks units of work on the test transaction."""

    def make() -> SqlMarksUnitOfWork:
        return SqlMarksUnitOfWork(
            sessionmaker_in_tx, outbox.write_notifications, outbox.write_audit
        )

    return make


@pytest_asyncio.fixture
async def env(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    uow_factory: MarksUowFactory,
    outbox: InMemoryOutbox,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> Env:
    """A seeded world with an active student and a sync use case wired to fakes."""
    world = await seed_world(sessionmaker_in_tx)
    identity = FakeIdentity()
    identity.add(make_user(world.user_id), UserPreferences(locale="en"))
    emis = FakeEmis()
    commands = FakeIdentityCommands()
    enrollment = FakeEnrollment(
        StudentRef(
            user_id=world.user_id,
            group_id=world.group_id,
            group_name="2TN2",
            subgroup=None,
            status="active",
            synced_at=None,
        )
    )
    sync = SyncStudent(
        uow_factory=uow_factory,
        emis=emis,
        identity=identity,  # type: ignore[arg-type]
        identity_commands=commands,  # type: ignore[arg-type]
        enrollment=enrollment,
        apply=ApplyRatings(clock=clock),
        clock=clock,
        kicker=kicker,
        institution_id=10815,
    )
    return Env(
        world,
        emis,
        identity,
        commands,
        enrollment,
        outbox,
        sync,
        uow_factory,
        clock,
        FakeBellSync(),
        FakeTimetableSync(),
        kicker,
    )


OTHER_DAY = dt.date(2026, 10, 7)


def _resource(lesson_id: UUID, title: str, hidden: bool) -> ResourceRef:
    return ResourceRef(
        link_id=uuid4(),
        lesson_id=lesson_id,
        role="material",
        kind="url",
        short_url=f"https://s.ihsu.uz/{title}",
        title=title,
        author_id=UUID(int=77),
        author_first_name="Bobur",
        hidden=hidden,
        file_id=None,
    )


@pytest_asyncio.fixture
async def services(
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    settings: Any,
    redis: Any,
    kicker: Any,
    i18n: Any,
) -> MarksServices:
    """Marks services on the test transaction, with data and one math resource."""
    w = env.world
    env.identity.add(
        make_user(
            w.teacher_id,
            first_name="Bobur",
            last_name="Aliev",
            roles=frozenset({Role.TEACHER}),
        )
    )
    env.identity.add(make_user(UUID(int=77), first_name="Bobur", last_name="Aliev"))
    env.emis.set(
        make_ratings(
            MATH_EMIS,
            3,
            [
                ("lesson", DAY, 5),
                ("lesson", DAY, 4),
                ("lesson", OTHER_DAY, 3),
                ("midterm", DAY, 5),
            ],
            rating=90,
        )
    )
    env.emis.set(make_ratings(PHYSICS_EMIS, 3, [("lesson", DAY, 3)]))
    await env.sync.execute(w.user_id)
    async with sessionmaker_in_tx() as session:
        lesson = await session.get(Lesson, w.math_lesson_1)
        assert lesson is not None
        lesson.attendance_roster = [w.user_id]
        lesson.attendance_absent = [w.user_id]
        lesson.attendance_version = 1
        await session.commit()
    deps = ModuleDeps(
        settings=settings,
        clock=env.clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=env.outbox.write_notifications,
        audit_writer=env.outbox.write_audit,
        outbox_committed_hook=None,
    )
    links = FakeLinks(
        {
            w.math_lesson_1: [
                _resource(w.math_lesson_1, "notes", False),
                _resource(w.math_lesson_1, "secret", True),
            ]
        }
    )
    return build_marks(
        deps,
        emis=env.emis,
        identity=env.identity,  # type: ignore[arg-type]
        schedule=FakeSchedule({w.user_id}),  # type: ignore[arg-type]
        identity_commands=env.commands,  # type: ignore[arg-type]
        enrollment=env.enrollment,
        links=links,  # type: ignore[arg-type]
        bell_sync=env.bells,
        timetable_sync=env.timetables,
        material_resync=env.timetables,
    )
