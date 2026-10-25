"""Unit of work port of the academic schedule."""

from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.modules.academic.application.schedule.ports.repositories import (
    CurriculumRepository,
    GroupRepository,
    LessonRepository,
    RoomRepository,
    StudentRepository,
    SubjectRepository,
    TermRepository,
    TimetableEntryRepository,
)
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft


class ScheduleUnitOfWork(Protocol):
    """One transaction over the schedule repositories."""

    @property
    def terms(self) -> TermRepository:
        """Terms."""
        ...

    @property
    def groups(self) -> GroupRepository:
        """Groups."""
        ...

    @property
    def students(self) -> StudentRepository:
        """Students."""
        ...

    @property
    def subjects(self) -> SubjectRepository:
        """Subjects."""
        ...

    @property
    def curricula(self) -> CurriculumRepository:
        """Group curricula from EMIS."""
        ...

    @property
    def rooms(self) -> RoomRepository:
        """Rooms."""
        ...

    @property
    def entries(self) -> TimetableEntryRepository:
        """Timetable entries."""
        ...

    @property
    def lessons(self) -> LessonRepository:
        """Lessons."""
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

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the commit."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events for the commit."""
        ...

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a coroutine after a successful commit."""
        ...

    async def commit(self) -> None:
        """Write outbox and audit rows, commit, run after-commit hooks."""
        ...

    async def lock_term(self, term_id: UUID) -> None:
        """Take the per-term advisory lock for the rest of the transaction."""
        ...
