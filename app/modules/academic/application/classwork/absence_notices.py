"""Builds the ``lesson_absence`` notifications for students (WO-4)."""

import datetime as dt
from collections.abc import Mapping
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.work_off import WorkOff
from app.shared.notifications import NotificationDraft, NotificationType


class AbsenceNotices:
    """Turns "student became absent / work-off changed" into drafts."""

    def __init__(self, people: PeopleDirectory) -> None:
        """Store the people directory."""
        self.people = people

    async def drafts(
        self,
        lesson: Lesson,
        targets: Mapping[UUID, bool],
        work_offs: Mapping[UUID, WorkOff],
        *,
        version: int,
    ) -> list[NotificationDraft]:
        """One draft per target student; ``targets`` maps student to ``update``."""
        if not targets:
            return []
        teacher = await self.people.person(lesson.teacher_id)
        teacher_name = (
            "" if teacher is None else f"{teacher.first_name} {teacher.last_name}"
        )
        drafts = []
        for student_id, update in targets.items():
            locale = await self.people.locale(student_id)
            work_off = work_offs.get(student_id)
            drafts.append(
                NotificationDraft(
                    user_id=student_id,
                    type=NotificationType.LESSON_ABSENCE,
                    payload=_payload(lesson, locale, teacher_name, work_off, update),
                    dedupe_key=_dedupe_key(
                        lesson, student_id, work_off, update, version
                    ),
                )
            )
        return drafts


def _payload(
    lesson: Lesson,
    locale: str,
    teacher_name: str,
    work_off: WorkOff | None,
    update: bool,
) -> dict[str, object]:
    return {
        "lesson_id": str(lesson.id),
        "date": lesson.date.isoformat(),
        "period": lesson.period,
        "subject_name": lesson.subject_name(locale),
        "teacher_name": teacher_name,
        "work_off_text": None if work_off is None else work_off.text,
        "due_date": (
            None
            if work_off is None or work_off.due_date is None
            else work_off.due_date.isoformat()
        ),
        "update": update,
    }


def _dedupe_key(
    lesson: Lesson,
    student_id: UUID,
    work_off: WorkOff | None,
    update: bool,
    version: int,
) -> str:
    base = f"lesson_absence:{lesson.id}:{student_id}"
    if update and work_off is not None:
        stamp: dt.datetime = work_off.updated_at
        return f"{base}:{version}:{stamp.isoformat()}"
    return f"{base}:{version}"
