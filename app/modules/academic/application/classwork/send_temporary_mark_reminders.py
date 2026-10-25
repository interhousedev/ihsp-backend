"""Use case: remind teachers of temporary marks still missing in EMIS (TMP-3)."""

from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import ViewUnitOfWork
from app.modules.academic.application.classwork.send_absence_digests import (
    AFTER_LESSONS,
    SCHOOL_WEEKDAYS,
)
from app.modules.academic.application.classwork.temporary_mark_views import (
    TemporaryMarkViews,
)
from app.modules.academic.domain.classwork.temporary_mark import (
    TemporaryMark,
    TemporaryMarkView,
)
from app.shared.clock import Clock, local_today
from app.shared.notifications import NotificationDraft, NotificationType


class SendTemporaryMarkReminders:
    """Queue one ``teacher_temporary_marks`` notice per teacher after lessons end."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        views: TemporaryMarkViews,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.views = views

    async def execute(self) -> dict[str, int]:
        """Queue today's reminders; ``{"skipped": 1}``, ``{"waiting": 1}`` or counts.

        Repeated runs are safe: the dedupe key holds teacher and date.
        """
        today = local_today(self.clock)
        if today.weekday() >= SCHOOL_WEEKDAYS:
            return {"skipped": 1}
        async with self.uow_factory() as uow:
            last_end = await uow.digest.last_lesson_end(today)
            if last_end is None:
                return {"skipped": 1}
            if self.clock.now() < last_end + AFTER_LESSONS:
                return {"waiting": 1}
            marks = await uow.temporary_marks.pending(None)
            teachers = await uow.temporary_marks.lessons_of(marks)
            by_teacher: dict[UUID, list[TemporaryMark]] = defaultdict(list)
            for mark in marks:
                teacher_id = teachers.get(mark.lesson_id)
                if teacher_id is not None:
                    by_teacher[teacher_id].append(mark)
            drafts = []
            for teacher_id, own in by_teacher.items():
                locale = await self.people.locale(teacher_id)
                views = await self.views.build(uow, own, locale)
                if views:
                    drafts.append(_draft(teacher_id, today.isoformat(), views))
            uow.notify(*drafts)
            await uow.commit()
        return {"queued": len(drafts)}


def _draft(
    teacher_id: UUID, day: str, views: list[TemporaryMarkView]
) -> NotificationDraft:
    items: list[dict[str, Any]] = [
        {
            "lesson_id": str(v.mark.lesson_id),
            "lesson_date": v.mark.date.isoformat(),
            "period": v.lesson_period,
            "group_name": v.group_name,
            "subject_name": v.subject_name,
            "student_id": str(v.mark.student_id),
            "student_name": v.student_name,
            "value": v.mark.value,
            "comment": v.mark.comment,
        }
        for v in views
    ]
    return NotificationDraft(
        user_id=teacher_id,
        type=NotificationType.TEACHER_TEMPORARY_MARKS,
        payload={"date": day, "count": len(items), "items": items},
        dedupe_key=f"teacher_temporary_marks:{teacher_id}:{day}",
    )
