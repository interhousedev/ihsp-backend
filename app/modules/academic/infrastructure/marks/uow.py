"""The marks unit of work over one SQLAlchemy session."""

from app.modules.academic.infrastructure.marks.repositories import (
    emis_attendance_repository,
    lesson_matcher,
    marks_reader,
    marks_repository,
    results_repository,
    student_sync_repository,
    sync_runs_repository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlMarksUnitOfWork(SqlUnitOfWork):
    """One transaction with every marks repository bound to its session."""

    students: student_sync_repository.SqlStudentSyncRepository
    marks: marks_repository.SqlMarksRepository
    results: results_repository.SqlResultsRepository
    lessons: lesson_matcher.SqlLessonMatcher
    sync_runs: sync_runs_repository.SqlSyncRunsRepository
    reader: marks_reader.SqlMarksReader
    emis_attendance: emis_attendance_repository.SqlEmisAttendanceRepository

    def _init_repos(self) -> None:
        """Create the repositories bound to the open session."""
        self.students = student_sync_repository.SqlStudentSyncRepository(self.session)
        self.marks = marks_repository.SqlMarksRepository(self.session)
        self.results = results_repository.SqlResultsRepository(self.session)
        self.lessons = lesson_matcher.SqlLessonMatcher(self.session)
        self.sync_runs = sync_runs_repository.SqlSyncRunsRepository(self.session)
        self.reader = marks_reader.SqlMarksReader(self.session)
        self.emis_attendance = emis_attendance_repository.SqlEmisAttendanceRepository(
            self.session
        )
