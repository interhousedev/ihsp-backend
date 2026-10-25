"""Use case: the lesson's teacher sets a student's temporary mark (TMP-1)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    TemporaryMarkUnitOfWork,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.application.classwork.temporary_mark_views import (
    TemporaryMarkViews,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import StudentNotInLessonError
from app.modules.academic.domain.classwork.temporary_mark import (
    TemporaryMarkView,
    clean_comment,
    ensure_value,
)
from app.shared.actor import Actor
from app.shared.clock import Clock


class SetTemporaryMark:
    """Create or replace one student's temporary mark for a lesson."""

    def __init__(
        self,
        uow_factory: Callable[[], TemporaryMarkUnitOfWork],
        clock: Clock,
        roster_loader: RosterLoader,
        views: TemporaryMarkViews,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.roster_loader = roster_loader
        self.views = views

    async def execute(
        self,
        lesson_id: UUID,
        student_id: UUID,
        actor: Actor,
        *,
        value: int,
        comment: str | None = None,
        locale: str | None = None,
    ) -> TemporaryMarkView:
        """Save the mark and return it with names.

        Raises:
            LessonNotFoundError: no such lesson.
            NotLessonTeacherError: the actor neither teaches the lesson nor is admin.
            TemporaryMarkValueInvalidError: the value is not 2, 3, 4 or 5.
            TemporaryMarkCommentInvalidError: the comment is too long.
            StudentNotInLessonError: the student is not on the lesson's roster.
        """
        value = ensure_value(value)
        text = clean_comment(comment)
        locale = locale or await self.views.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_lesson_staff(lesson, actor)
            roster = await self.roster_loader.load(uow, lesson)
            if student_id not in {s.user_id for s in roster.entries}:
                raise StudentNotInLessonError(
                    params={"lesson_id": str(lesson_id), "student_id": str(student_id)}
                )
            saved = await uow.temporary_marks.upsert(
                lesson_id=lesson_id,
                student_id=student_id,
                subject_id=lesson.subject_id,
                date=lesson.date,
                value=value,
                comment=text,
                author_id=actor.user_id,
                at=self.clock.now(),
            )
            views = await self.views.build(uow, [saved], locale)
            await uow.commit()
        return views[0]
