"""Fixtures of the onboarding tests: the module over the faces fakes."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.onboarding.wiring import OnboardingServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.faces.conftest import FacesHarness, fh  # noqa: F401
from tests.fakes.clock import FixedClock
from tests.fakes.onboarding.uow import (
    FakeImporter,
    FakeOnboardingStore,
    FakeOnboardingUow,
)
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FacesGateOverFaces:
    """FaceGate backed by the real faces use case on the faces fakes."""

    def __init__(self, harness: FacesHarness) -> None:
        """Bind to the faces harness."""
        self._fh = harness

    async def has_face(self, user_id: UUID) -> bool:
        """Whether the faces module has a profile."""
        return await self._fh.services.has_face.execute(user_id)


@dataclass
class OnboardingHarness:
    """The wired module and the fakes behind it."""

    services: OnboardingServices
    store: FakeOnboardingStore
    importer: FakeImporter
    faces: FacesHarness
    make_actor: Callable[..., Actor]

    def student(self, name: str = "Ali Karimov") -> Actor:
        """A student known to the faces directory."""
        info = self.faces.directory.add_student(name)
        return Actor(user_id=info.user_id, roles=frozenset({Role.STUDENT}))


@pytest.fixture
def oh(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
    fh: FacesHarness,  # noqa: F811
) -> OnboardingHarness:
    """The module on fakes."""
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
    store, importer = FakeOnboardingStore(), FakeImporter()
    services = build(
        deps,
        faces=FacesGateOverFaces(fh),
        importer=importer,
        uow_factory=lambda: FakeOnboardingUow(store),
    )
    return OnboardingHarness(services, store, importer, fh, make_actor)
