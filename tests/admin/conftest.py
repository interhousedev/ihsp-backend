"""Fixtures that wire the notify and admin modules over the test database."""

from dataclasses import dataclass

from app.modules.admin.wiring import AdminServices
from app.modules.admin.wiring import build as build_admin
from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.modules.notify.wiring import NotifyServices
from app.modules.notify.wiring import build as build_notify
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.files import FakeFilesApi
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.links import FakeLinksApi
from tests.fakes.notify.schedule import FakeScheduleQueries
from tests.fakes.notify.telegram_sender import FakeTelegramSender
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class Stack:
    """Notify and admin services on the test database with fake neighbours."""

    admin: AdminServices
    notify: NotifyServices
    identity: FakeIdentityDirectory
    schedule: FakeScheduleQueries
    sender: FakeTelegramSender
    actor: Actor


@pytest.fixture
def stack(
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    kicker: FakeTaskKicker,
    i18n: I18nCore,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> Stack:
    """Real SQL repositories and outbox writer; fake identity, schedule, Telegram."""
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=write_notifications,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    identity = FakeIdentityDirectory()
    schedule = FakeScheduleQueries()
    sender = FakeTelegramSender()
    admin_user = identity.add_user(make_user(Role.ADMIN, first_name="Gulnora"), 900)
    return Stack(
        admin=build_admin(deps, identity=identity, schedule=schedule),
        notify=build_notify(
            deps,
            identity=identity,
            schedule=schedule,
            links=FakeLinksApi(),
            mail=object(),  # type: ignore[arg-type]
            files=FakeFilesApi(),
            telegram=sender,
        ),
        identity=identity,
        schedule=schedule,
        sender=sender,
        actor=Actor(user_id=admin_user.id, roles=frozenset({Role.ADMIN})),
    )
