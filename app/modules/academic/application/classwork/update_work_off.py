"""Use case: the lesson's teacher edits a work-off (WO-3, WO-4)."""

import datetime as dt
from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.absence_notices import AbsenceNotices
from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import WorkOffNotFoundError
from app.modules.academic.domain.classwork.work_off import (
    UNSET,
    Unset,
    WorkOff,
    clean_text,
    ensure_status,
)
from app.shared.actor import Actor
from app.shared.clock import Clock


class UpdateWorkOff:
    """Change text, due date or status of one work-off."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        clock: Clock,
        notices: AbsenceNotices,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.notices = notices

    async def execute(
        self,
        work_off_id: UUID,
        actor: Actor,
        *,
        text: str | None = None,
        due_date: dt.date | None | Unset = UNSET,
        status: str | None = None,
    ) -> WorkOff:
        """Apply the given fields and return the work-off.

        A new text queues the student's ``lesson_absence`` update notice. Status
        ``done`` sets ``done_at``; ``assigned`` clears it.

        Raises:
            WorkOffNotFoundError: no such work-off.
            NotLessonTeacherError: the actor neither teaches the lesson nor is admin.
            WorkOffTextInvalidError: empty or too long text.
            WorkOffStatusInvalidError: a status other than assigned or done.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            current = await uow.work_offs.get(work_off_id)
            if current is None:
                raise WorkOffNotFoundError(params={"work_off_id": str(work_off_id)})
            lesson = await require_lesson(uow, current.lesson_id)
            ensure_lesson_staff(lesson, actor)
            new_text = current.text if text is None else clean_text(text)
            new_status = current.status if status is None else ensure_status(status)
            done_at = current.done_at
            if new_status != current.status:
                done_at = now if new_status == "done" else None
            saved = await uow.work_offs.update(
                work_off_id,
                text=new_text,
                due_date=current.due_date if isinstance(due_date, Unset) else due_date,
                status=new_status,
                done_at=done_at,
                at=now,
            )
            if new_text != current.text:
                uow.notify(
                    *await self.notices.drafts(
                        lesson,
                        {current.student_id: True},
                        {current.student_id: saved},
                        version=lesson.attendance_version,
                    )
                )
            await uow.commit()
        return saved
