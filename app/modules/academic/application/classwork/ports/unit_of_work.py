"""Ports: units of work, split by what each group of use cases needs."""

from types import TracebackType
from typing import Protocol, Self

from app.modules.academic.application.classwork.ports.absence_digest_reader import (
    AbsenceDigestReader,
)
from app.modules.academic.application.classwork.ports.attendance_reports import (
    AttendanceReports,
)
from app.modules.academic.application.classwork.ports.journal_reader import (
    JournalReader,
)
from app.modules.academic.application.classwork.ports.lesson_reader import LessonReader
from app.modules.academic.application.classwork.ports.lesson_repository import (
    LessonRepository,
)
from app.modules.academic.application.classwork.ports.results_reader import (
    ResultsReader,
)
from app.modules.academic.application.classwork.ports.student_repository import (
    StudentRepository,
)
from app.modules.academic.application.classwork.ports.temporary_mark_repository import (
    TemporaryMarkRepository,
)
from app.modules.academic.application.classwork.ports.todo_repository import (
    TodoRepository,
)
from app.modules.academic.application.classwork.ports.work_off_reader import (
    WorkOffReader,
)
from app.modules.academic.application.classwork.ports.work_off_repository import (
    WorkOffRepository,
    WorkOffTemplateRepository,
)
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft


class UnitOfWork(Protocol):
    """One transaction with an outbox, an audit log and after-commit hooks."""

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
        """Commit, write the outbox and audit rows, run the hooks."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the commit."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events for the commit."""
        ...

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a hook after a successful commit."""
        ...


class LessonUnitOfWork(UnitOfWork, Protocol):
    """Homework, topic and due dates."""

    @property
    def lessons(self) -> LessonRepository:
        """Lesson writes."""
        ...


class AttendanceUnitOfWork(LessonUnitOfWork, Protocol):
    """Attendance needs the lesson and the students of its groups."""

    @property
    def students(self) -> StudentRepository:
        """Students of the groups."""
        ...

    @property
    def work_off_templates(self) -> WorkOffTemplateRepository:
        """The teacher's work-off templates."""
        ...

    @property
    def work_offs(self) -> WorkOffRepository:
        """Work-off tasks of absent students."""
        ...


class TemporaryMarkUnitOfWork(AttendanceUnitOfWork, Protocol):
    """The temporary gradebook needs the lesson, its roster and the marks."""

    @property
    def temporary_marks(self) -> TemporaryMarkRepository:
        """Temporary marks (TMP-1)."""
        ...


class ReaderUnitOfWork(UnitOfWork, Protocol):
    """Lesson read models (reminders)."""

    @property
    def lesson_reader(self) -> LessonReader:
        """Lesson read models."""
        ...


class TodoUnitOfWork(ReaderUnitOfWork, Protocol):
    """Student to-do actions."""

    @property
    def students(self) -> StudentRepository:
        """Students."""
        ...

    @property
    def todos(self) -> TodoRepository:
        """To-do rows."""
        ...


class ViewUnitOfWork(TemporaryMarkUnitOfWork, TodoUnitOfWork, Protocol):
    """Everything the read use cases need (the SQL unit of work has it all)."""

    @property
    def reports(self) -> AttendanceReports:
        """Attendance aggregates."""
        ...

    @property
    def journal(self) -> JournalReader:
        """Journal data."""
        ...

    @property
    def results(self) -> ResultsReader:
        """Marks, results and terms."""
        ...

    @property
    def work_off_reader(self) -> WorkOffReader:
        """Work-off lists and statistics."""
        ...

    @property
    def digest(self) -> AbsenceDigestReader:
        """Reads for the curator absence digest."""
        ...
