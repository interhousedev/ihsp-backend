"""Which lessons a person may read links of, and who may set them."""

from uuid import UUID

from app.modules.library.domain.reader_errors import LessonNotFoundError
from app.modules.library.ports.lesson_directory import LessonDirectory, LessonSubject
from app.shared.actor import Actor, Role


async def lesson_for_reader(
    lessons: LessonDirectory, actor: Actor, lesson_id: UUID
) -> LessonSubject:
    """The lesson for its teacher, its students and Administration; else not found."""
    lesson = await lessons.get_lesson_subject(lesson_id)
    if lesson is None:
        raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
    if Role.ADMIN in actor.roles:
        return lesson
    if await lessons.is_lesson_teacher(actor.user_id, lesson_id):
        return lesson
    if await lessons.is_in_audience(actor.user_id, lesson_id):
        return lesson
    raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})


async def lesson_for_teacher(
    lessons: LessonDirectory, actor: Actor, lesson_id: UUID
) -> LessonSubject:
    """The lesson for its teacher and Administration; others get a 404."""
    lesson = await lessons.get_lesson_subject(lesson_id)
    if lesson is None:
        raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
    if Role.ADMIN in actor.roles or await lessons.is_lesson_teacher(
        actor.user_id, lesson_id
    ):
        return lesson
    raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})


class NoLessons:
    """Used when the academic lessons are not wired (tests of other areas)."""

    async def get_lesson_subject(self, lesson_id: UUID) -> LessonSubject | None:
        """No lesson is known."""
        return None

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Nobody teaches an unknown lesson."""
        return False

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Nobody attends an unknown lesson."""
        return False

    async def earlier_lessons(self, lesson_id: UUID, *, limit: int) -> list[UUID]:
        """There is no history."""
        return []
