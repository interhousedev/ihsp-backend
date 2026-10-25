"""The unit of work the assessments use cases depend on."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.academic.application.assessments.ports.repositories import (
    AssessmentReader,
    AssessmentRepository,
)
from app.shared.notifications import AuditDraft, NotificationDraft


class AssessmentsUnitOfWork(Protocol):
    """One transaction with the assessment repository, outbox and audit."""

    @property
    def assessments(self) -> AssessmentRepository:
        """Stored assessments."""
        ...

    @property
    def reader(self) -> AssessmentReader:
        """Read queries over other academic tables."""
        ...

    async def __aenter__(self) -> Self:
        """Open a transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the commit."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events for the commit."""
        ...

    async def commit(self) -> None:
        """Write outbox and audit rows and commit."""
        ...


AssessmentsUowFactory = Callable[[], AssessmentsUnitOfWork]
