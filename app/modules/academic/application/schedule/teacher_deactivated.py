"""Clear a deactivated teacher from the schedule (ACA-7)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft


class TeacherDeactivated:
    """Leave the teacher's entries and future lessons as "teacher needed"."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, teacher_id: UUID) -> tuple[int, int]:
        """Set teacher_id to NULL; return (entries cleared, future lessons cleared)."""
        async with self.uow_factory() as uow:
            entries = await uow.entries.clear_teacher(teacher_id)
            lessons = await uow.lessons.clear_teacher_future(
                teacher_id, self.clock.now()
            )
            if entries or lessons:
                uow.audit(
                    AuditDraft(
                        type="teacher.unassigned",
                        user_id=teacher_id,
                        metadata={"entries": entries, "lessons": len(lessons)},
                    )
                )
            await uow.commit()
        return entries, len(lessons)
