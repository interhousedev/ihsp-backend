"""Use case: the temporary marks of one lesson (TMP-1)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    TemporaryMarkUnitOfWork,
)
from app.modules.academic.application.classwork.temporary_mark_views import (
    TemporaryMarkViews,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.temporary_mark import TemporaryMarkView
from app.shared.actor import Actor


class ListLessonTemporaryMarks:
    """List a lesson's temporary marks for its teacher or Administration."""

    def __init__(
        self,
        uow_factory: Callable[[], TemporaryMarkUnitOfWork],
        views: TemporaryMarkViews,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(
        self, lesson_id: UUID, actor: Actor, *, locale: str | None = None
    ) -> list[TemporaryMarkView]:
        """Return the marks, oldest first.

        Raises:
            LessonNotFoundError: no such lesson.
            NotLessonTeacherError: the actor neither teaches the lesson nor is admin.
        """
        locale = locale or await self.views.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            ensure_lesson_staff(await require_lesson(uow, lesson_id), actor)
            marks = await uow.temporary_marks.for_lesson(lesson_id)
            return await self.views.build(uow, marks, locale)
