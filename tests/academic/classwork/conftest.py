"""Fixtures of the classwork tests: SQL unit of work, fakes and the services."""

from dataclasses import dataclass
from typing import Any

from app.modules.academic.wiring_classwork import ClassworkServices, build_classwork
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import StudentRef
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.academic.classwork.world import Maker, World, seed_world
from tests.fakes.academic.classwork.identity import FakeIdentity
from tests.fakes.academic.classwork.links import FakeLinks
from tests.fakes.academic.classwork.schedule import FakeSchedule
from tests.fakes.clock import FixedClock
from tests.fakes.outbox import InMemoryOutbox
from tests.fakes.tasks import FakeTaskKicker

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(slots=True)
class Env:
    """Everything a classwork test touches."""

    services: ClassworkServices
    world: World
    identity: FakeIdentity
    schedule: FakeSchedule
    links: FakeLinks
    maker: Maker
    clock: FixedClock
    redis: FakeRedis
    outbox: InMemoryOutbox

    def actor(self, role: Role, user_id: Any) -> Actor:
        """Build an actor for a seeded user."""
        return Actor(user_id=user_id, roles=frozenset({role}))

    @property
    def teacher(self) -> Actor:
        """The teacher of the seeded lessons."""
        return self.actor(Role.TEACHER, self.world.teacher.id)

    @property
    def other_teacher(self) -> Actor:
        """A teacher of nobody's lessons."""
        return self.actor(Role.TEACHER, self.world.other_teacher.id)

    @property
    def curator(self) -> Actor:
        """The curator of the group."""
        return self.actor(Role.TEACHER, self.world.curator.id)

    @property
    def admin(self) -> Actor:
        """Administration."""
        return self.actor(Role.ADMIN, self.world.admin.id)

    def student(self, which: str) -> Actor:
        """The student actor ``aziz``, ``bobur``, ``camila`` or ``outsider``."""
        return self.actor(Role.STUDENT, getattr(self.world, which).id)


@pytest.fixture
def outbox() -> InMemoryOutbox:
    """Collects notification and audit drafts written at commit."""
    return InMemoryOutbox()


@pytest_asyncio.fixture
async def env(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    outbox: InMemoryOutbox,
) -> Env:
    """Seeded world plus the classwork services over the test transaction."""
    identity, schedule, links = FakeIdentity(), FakeSchedule(), FakeLinks()
    world = await seed_world(sessionmaker_in_tx, identity)
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
    schedule.curated[world.curator.id] = [world.group_id]
    for user, group_id, group_name, subgroup in (
        (world.aziz, world.group_id, "2TN2", 1),
        (world.bobur, world.group_id, "2TN2", 2),
        (world.camila, world.group_id, "2TN2", None),
        (world.outsider, world.other_group_id, "2TN1", None),
    ):
        schedule.students[user.id] = StudentRef(
            user_id=user.id,
            group_id=group_id,
            group_name=group_name,
            subgroup=subgroup,
            status="active",
            synced_at=None,
        )
    services = build_classwork(
        deps,
        identity=identity,
        schedule=schedule,
        links=links,
    )
    return Env(
        services=services,
        world=world,
        identity=identity,
        schedule=schedule,
        links=links,
        maker=sessionmaker_in_tx,
        clock=clock,
        redis=redis,
        outbox=outbox,
    )
