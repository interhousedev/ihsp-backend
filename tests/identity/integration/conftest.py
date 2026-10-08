"""Fixtures of the identity integration tests: the real unit of work on PostgreSQL."""

from collections.abc import Callable

from app.modules.identity.infrastructure.audit_writer import write_audit_events
from app.modules.identity.infrastructure.uow import IdentityUnitOfWork
from tests.fakes.outbox import InMemoryOutbox

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def outbox() -> InMemoryOutbox:
    """Collects the notification drafts the unit of work writes."""
    return InMemoryOutbox()


@pytest.fixture
def make_uow(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession], outbox: InMemoryOutbox
) -> Callable[[], IdentityUnitOfWork]:
    """Factory of real units of work inside the test transaction."""

    def factory() -> IdentityUnitOfWork:
        return IdentityUnitOfWork(
            sessionmaker_in_tx, outbox.write_notifications, write_audit_events
        )

    return factory
