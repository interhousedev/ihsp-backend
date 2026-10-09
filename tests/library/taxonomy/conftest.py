"""Fixtures of the taxonomy tests: recorded notifications and audit events."""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.library.infrastructure.uow import LibrarySqlUnitOfWork
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft
from tests.fakes.library.academic import FakeAcademicDirectory

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class Recorded:
    """What the units of work wrote to the outbox and the audit log."""

    notifications: list[NotificationDraft] = field(default_factory=list)
    audits: list[AuditDraft] = field(default_factory=list)

    async def write_outbox(
        self, session: AsyncSession, drafts: list[NotificationDraft]
    ) -> None:
        """Remember the notifications."""
        self.notifications.extend(drafts)

    async def write_audit(
        self, session: AsyncSession, drafts: list[AuditDraft]
    ) -> None:
        """Remember the audit events."""
        self.audits.extend(drafts)


@pytest.fixture
def recorded() -> Recorded:
    """Notifications and audit events written by the use cases of the test."""
    return Recorded()


@pytest.fixture
def uow_factory(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession], recorded: Recorded
) -> UowFactory:
    """Units of work on the test transaction that record outbox and audit rows."""

    def factory() -> LibraryUnitOfWork:
        return LibrarySqlUnitOfWork(
            sessionmaker_in_tx, recorded.write_outbox, recorded.write_audit
        )

    return factory


@pytest.fixture
def subject_id(academic: FakeAcademicDirectory) -> UUID:
    """A subject that exists in the academic directory."""
    return academic.add_subject(new_id(), "Physics")
