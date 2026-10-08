"""SQL unit of work of the academic schedule."""

from uuid import UUID

from app.modules.academic.infrastructure.schedule.repositories import (
    SqlGroupRepository,
    SqlLessonRepository,
    SqlRoomRepository,
    SqlStudentRepository,
    SqlSubjectRepository,
    SqlTermRepository,
    SqlTimetableEntryRepository,
)
from app.shared.db.uow import SqlUnitOfWork

from sqlalchemy import text


class SqlScheduleUnitOfWork(SqlUnitOfWork):
    """One transaction over terms, groups, students, rooms, entries and lessons."""

    terms: SqlTermRepository
    groups: SqlGroupRepository
    students: SqlStudentRepository
    subjects: SqlSubjectRepository
    rooms: SqlRoomRepository
    entries: SqlTimetableEntryRepository
    lessons: SqlLessonRepository

    def _init_repos(self) -> None:
        """Create repositories bound to the open session."""
        self.terms = SqlTermRepository(self.session)
        self.groups = SqlGroupRepository(self.session)
        self.students = SqlStudentRepository(self.session)
        self.subjects = SqlSubjectRepository(self.session)
        self.rooms = SqlRoomRepository(self.session)
        self.entries = SqlTimetableEntryRepository(self.session)
        self.lessons = SqlLessonRepository(self.session)

    async def lock_term(self, term_id: UUID) -> None:
        """Serialize writers of one term until the transaction ends."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:term_id))"),
            {"term_id": str(term_id)},
        )
