"""Fixtures of the dashboard tests: the module on an in-memory store."""

import copy
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.dashboard.domain.layout import Layout
from app.modules.dashboard.wiring import DashboardOverrides, DashboardServices, build
from app.settings import Settings
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FakeLayouts:
    """Layouts of a dict shared by every unit of work."""

    def __init__(self, store: dict[UUID, Layout]) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, user_id: UUID, *, for_update: bool = False) -> Layout | None:
        """Return a copy of the layout."""
        found = self.store.get(user_id)
        return copy.deepcopy(found) if found else None

    async def save(self, layout: Layout) -> None:
        """Store a copy."""
        self.store[layout.user_id] = copy.deepcopy(layout)


class FakeDashboardUow:
    """In-memory unit of work."""

    def __init__(self, store: dict[UUID, Layout]) -> None:
        """Bind to the store."""
        self.layouts = FakeLayouts(store)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back."""

    async def commit(self) -> None:
        """Nothing to commit."""


@pytest.fixture
def dashboard(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> DashboardServices:
    """The module wired to the in-memory store."""
    store: dict[UUID, Layout] = {}
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=async_sessionmaker[AsyncSession](),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    return build(deps, DashboardOverrides(uow_factory=lambda: FakeDashboardUow(store)))
