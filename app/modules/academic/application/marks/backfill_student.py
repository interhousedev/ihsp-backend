"""Import all semesters of a freshly registered student, silently (SYNC-4)."""

from uuid import UUID

from app.modules.academic.application.marks.sync_student import SyncStudent
from app.modules.academic.domain.marks.sync import SyncOutcome


class BackfillStudent:
    """Profile refresh plus an alert-free import of semesters 1 to 4."""

    def __init__(self, *, sync_student: SyncStudent) -> None:
        """Store the student sync use case."""
        self._sync_student = sync_student

    async def execute(self, user_id: UUID) -> SyncOutcome:
        """Run a backfill sync for the student."""
        return await self._sync_student.execute(user_id, None, mode="backfill")
