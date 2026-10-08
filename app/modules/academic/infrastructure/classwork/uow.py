"""The classwork unit of work over one SQLAlchemy session."""

from app.modules.academic.infrastructure.classwork.attendance_reports import (
    SqlAttendanceReports,
)
from app.modules.academic.infrastructure.classwork.journal_reader import (
    SqlJournalReader,
)
from app.modules.academic.infrastructure.classwork.lesson_reader import SqlLessonReader
from app.modules.academic.infrastructure.classwork.lesson_repository import (
    SqlLessonRepository,
)
from app.modules.academic.infrastructure.classwork.results_reader import (
    SqlResultsReader,
)
from app.modules.academic.infrastructure.classwork.student_repository import (
    SqlStudentRepository,
)
from app.modules.academic.infrastructure.classwork.todo_repository import (
    SqlTodoRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlClassworkUnitOfWork(SqlUnitOfWork):
    """One transaction with every classwork repository bound to its session."""

    lessons: SqlLessonRepository
    lesson_reader: SqlLessonReader
    students: SqlStudentRepository
    todos: SqlTodoRepository
    reports: SqlAttendanceReports
    journal: SqlJournalReader
    results: SqlResultsReader

    def _init_repos(self) -> None:
        """Create the repositories bound to the open session."""
        self.lessons = SqlLessonRepository(self.session)
        self.lesson_reader = SqlLessonReader(self.session)
        self.students = SqlStudentRepository(self.session)
        self.todos = SqlTodoRepository(self.session)
        self.reports = SqlAttendanceReports(self.session)
        self.journal = SqlJournalReader(self.session)
        self.results = SqlResultsReader(self.session)
