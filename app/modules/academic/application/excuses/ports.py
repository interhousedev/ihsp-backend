"""Ports of excuses: repository, transaction, people and decision tokens."""

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.modules.academic.application.classwork.ports.work_off_repository import (
    WorkOffRepository,
)
from app.modules.academic.domain.excuses.excuse import (
    Excuse,
    ExcuseMessage,
    ExcuseStatus,
    ExcuseTemplate,
)
from app.shared.notifications import NotificationDraft


class ExcuseRepository(Protocol):
    """Excuses, their thread and the reason templates."""

    async def add(self, excuse: Excuse) -> None:
        """Insert a new excuse."""
        ...

    async def get(self, excuse_id: UUID) -> Excuse | None:
        """Return the excuse (without its thread) or None."""
        ...

    async def save(self, excuse: Excuse) -> None:
        """Write the changed state, version and update time."""
        ...

    async def search(
        self,
        *,
        student_ids: Sequence[UUID] | None,
        status: ExcuseStatus | None,
        offset: int,
        limit: int,
    ) -> list[Excuse]:
        """Newest first; ``student_ids`` None means every student."""
        ...

    async def covering(self, student_ids: Sequence[UUID], day: dt.date) -> list[Excuse]:
        """Approved excuses of the students whose period includes the day."""
        ...

    async def add_message(self, message: ExcuseMessage) -> None:
        """Append a line to the thread."""
        ...

    async def messages(self, excuse_id: UUID) -> list[ExcuseMessage]:
        """The thread, oldest first."""
        ...

    async def templates(self, *, active_only: bool) -> list[ExcuseTemplate]:
        """Templates in their display order."""
        ...


class ExcuseUnitOfWork(Protocol):
    """One transaction over excuses, work-offs and the notification outbox."""

    @property
    def excuses(self) -> ExcuseRepository:
        """Excuses of the open transaction."""
        ...

    @property
    def work_offs(self) -> WorkOffRepository:
        """Work-offs of the open transaction."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications to insert at commit."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    async def commit(self) -> None:
        """Commit the transaction and its outbox."""
        ...


ExcuseUowFactory = Callable[[], ExcuseUnitOfWork]


@dataclass(frozen=True, slots=True)
class StudentContext:
    """The student's current group and its curator."""

    student_id: UUID
    group_id: UUID
    curator_id: UUID | None


@dataclass(frozen=True, slots=True)
class Person:
    """A user as excuses show them."""

    user_id: UUID
    name: str
    locale: str


class ExcuseDirectory(Protocol):
    """Who is whose curator, and who the people are."""

    async def student_context(self, student_id: UUID) -> StudentContext | None:
        """The student's group and curator, or None for a user without a group."""
        ...

    async def curated_student_ids(self, curator_id: UUID) -> list[UUID]:
        """Active students of every group the user curates."""
        ...

    async def people(self, user_ids: Sequence[UUID]) -> dict[UUID, Person]:
        """The users that exist."""
        ...

    async def admin_ids(self) -> list[UUID]:
        """Every administrator."""
        ...


@dataclass(frozen=True, slots=True)
class DecisionGrant:
    """What one Telegram decision token allows."""

    excuse_id: UUID
    user_id: UUID
    approve: bool


class DecisionTokens(Protocol):
    """Single-use tokens behind the approve and reject buttons of Telegram."""

    async def issue(self, excuse_id: UUID, user_id: UUID) -> tuple[str, str]:
        """Return the (approve, reject) tokens, valid for one week."""
        ...

    async def consume(self, token: str, user_id: UUID) -> DecisionGrant | None:
        """Use the token once; None when unknown, used, expired or not the user's."""
        ...

    async def revoke(self, excuse_id: UUID) -> None:
        """Forget every token of the excuse (it was decided another way)."""
        ...
