"""Who a caller is for a lesson: a manager (teacher or admin) or a student."""

from enum import StrEnum
from uuid import UUID

from app.modules.links.domain.errors import LinkNotFoundError, ResourceForbiddenError
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import LessonRef, ScheduleQueries


class LessonViewer(StrEnum):
    """How the caller relates to the lesson."""

    MANAGER = "manager"
    STUDENT = "student"


class LessonAccess:
    """Looks a lesson up and decides what the caller may do with its resources."""

    def __init__(self, schedule: ScheduleQueries) -> None:
        """Store the schedule contract."""
        self.schedule = schedule

    async def lesson(self, lesson_id: UUID) -> LessonRef:
        """Return the lesson or raise LinkNotFoundError."""
        lesson = await self.schedule.get_lesson(lesson_id)
        if lesson is None:
            raise LinkNotFoundError(params={"lesson_id": str(lesson_id)})
        return lesson

    async def viewer(self, actor: Actor, lesson: LessonRef) -> LessonViewer:
        """Return MANAGER for the lesson's teacher or an admin, else STUDENT."""
        if actor.has(Role.ADMIN):
            return LessonViewer.MANAGER
        if await self.schedule.is_lesson_teacher(actor.user_id, lesson.id):
            return LessonViewer.MANAGER
        if await self.schedule.is_in_audience(actor.user_id, lesson.id):
            return LessonViewer.STUDENT
        raise ResourceForbiddenError(params={"lesson_id": str(lesson.id)})
