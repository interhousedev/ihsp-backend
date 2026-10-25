"""Use case: recompute automatic homework due dates after lessons changed."""

from collections.abc import Callable, Sequence
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    LessonUnitOfWork,
)
from app.modules.academic.domain.classwork.lesson import Lesson

LOOKBACK_DAYS = 28


class RecomputeDueDates:
    """Move the due dates of automatic homework to the next lesson (ACA-10)."""

    def __init__(self, uow_factory: Callable[[], LessonUnitOfWork]) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, lesson_ids: Sequence[UUID]) -> int:
        """Recompute for the changed lessons and for those that precede them.

        Returns the number of due dates that changed. Lessons that no longer
        exist are skipped.
        """
        async with self.uow_factory() as uow:
            changed = await uow.lessons.get_many(lesson_ids)
            targets: dict[UUID, Lesson] = {}
            for lesson in changed:
                if lesson.has_homework and lesson.homework_due_auto:
                    targets[lesson.id] = lesson
                earlier = await uow.lessons.auto_homework_before(
                    subject_id=lesson.subject_id,
                    audience=lesson.audience,
                    before=lesson.date,
                    lookback_days=LOOKBACK_DAYS,
                )
                targets.update({item.id: item for item in earlier})
            updated = 0
            for lesson in targets.values():
                if not lesson.scheduled:
                    continue
                due = await uow.lessons.next_lesson_date(
                    subject_id=lesson.subject_id,
                    audience=lesson.audience,
                    after=lesson.date,
                )
                if due != lesson.homework_due_date:
                    await uow.lessons.set_due_date(lesson.id, due)
                    updated += 1
            await uow.commit()
        return updated
