"""Fixtures of the privacy tests: the module on an in-memory store."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.privacy.wiring import PrivacyServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.files.storage import InMemoryStorage
from tests.fakes.privacy.uow import (
    FakeAccountControl,
    FakeOwnedFiles,
    FakePersonalData,
    FakePrivacyStore,
    fake_uow_factory,
)
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class PrivacyHarness:
    """The wired module with its fakes and two actors."""

    services: PrivacyServices
    store: FakePrivacyStore
    storage: InMemoryStorage
    accounts: FakeAccountControl
    files: FakeOwnedFiles
    source: FakePersonalData
    student: Actor
    admin: Actor

    @property
    def user_id(self) -> UUID:
        """The student's id."""
        return self.student.user_id


@pytest.fixture
def privacy(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> PrivacyHarness:
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
    store, storage = FakePrivacyStore(), InMemoryStorage()
    accounts, files = FakeAccountControl(clock.now().date()), FakeOwnedFiles()
    student = make_actor(Role.STUDENT)
    source = FakePersonalData({student.user_id: {"id.sessions": [{"id": "1"}]}})
    accounts.add_account(student.user_id)
    services = build(
        deps,
        accounts=accounts,
        storage=storage,
        export_sources=[source],
        erase_sources=[source],
        owned_files=files,
        uow_factory=fake_uow_factory(store),
    )
    return PrivacyHarness(
        services,
        store,
        storage,
        accounts,
        files,
        source,
        student,
        make_actor(Role.ADMIN),
    )
