"""The unit of work the marks use cases depend on."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.academic.application.marks.ports.repositories import (
    EmisAttendanceRepository,
    LessonMatcher,
    MarksReader,
    MarksRepository,
    ResultsRepository,
    StudentSyncRepository,
    SyncRunsRepository,
)
from app.shared.notifications import AuditDraft, NotificationDraft


class MarksUnitOfWork(Protocol):
    """One transaction with the marks repositories, outbox and audit."""

    @property
    def students(self) -> StudentSyncRepository:
        """Sync fields and curriculum of students."""
        ...

    @property
    def marks(self) -> MarksRepository:
        """Marks written by the sync."""
        ...

    @property
    def results(self) -> ResultsRepository:
        """Current results."""
        ...

    @property
    def lessons(self) -> LessonMatcher:
        """Lesson lookup for new marks."""
        ...

    @property
    def sync_runs(self) -> SyncRunsRepository:
        """Sync run summaries."""
        ...

    @property
    def emis_attendance(self) -> EmisAttendanceRepository:
        """Attendance the sync read from EMIS."""
        ...

    @property
    def reader(self) -> MarksReader:
        """Read queries of the student-facing views."""
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


MarksUowFactory = Callable[[], MarksUnitOfWork]
