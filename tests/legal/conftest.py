"""Fixtures of the legal tests: the module on an in-memory store."""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.legal.wiring import LegalOverrides, LegalServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.legal.uow import FakeLegalStore, fake_uow_factory
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FULL = {"uz": "Matn", "ru": "Текст", "en": "Text"}


@dataclass
class LegalHarness:
    """The wired module, its store and two actors."""

    services: LegalServices
    store: FakeLegalStore
    student: Actor
    admin: Actor

    async def publish(self, kind: str = "privacy") -> int:
        """Save a complete draft of ``kind``, publish it, return its version."""
        await self.services.save_draft.execute(
            kind, title=FULL, body_markdown=FULL, announcement=None
        )
        doc = await self.services.publish.execute(kind, actor_id=self.admin.user_id)
        return doc.version


@pytest.fixture
def legal(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> LegalHarness:
    """The module on fakes, with a student and an admin."""
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=async_sessionmaker(class_=AsyncSession),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    store = FakeLegalStore()
    services = build(deps, LegalOverrides(uow_factory=fake_uow_factory(store)))
    return LegalHarness(
        services, store, make_actor(Role.STUDENT), make_actor(Role.ADMIN)
    )
