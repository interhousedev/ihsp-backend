"""Telling students and teachers that a lesson changed (ADM-10, UF-ADM-07)."""

import datetime as dt
from collections.abc import Collection
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.subject import Subject, subject_name
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import NotificationDraft, NotificationType


async def notify_lesson_changed(
    uow: ScheduleUnitOfWork,
    identity: IdentityDirectory,
    lesson: Lesson,
    subject: Subject,
    changes: dict[str, Any],
    *,
    now: dt.datetime,
    teacher_ids: Collection[UUID | None],
) -> None:
    """Queue a lesson_changed notification for the audience and the teachers."""
    recipients = set(await uow.students.user_ids_for_audience(lesson.audience))
    recipients.update(t for t in teacher_ids if t is not None)
    if not recipients:
        return
    users = await identity.get_users(sorted(recipients))
    for user_id in sorted(recipients):
        locale = users[user_id].locale if user_id in users else "ru"
        uow.notify(
            NotificationDraft(
                user_id=user_id,
                type=NotificationType.LESSON_CHANGED,
                payload={
                    "lesson_id": str(lesson.id),
                    "date": lesson.date.isoformat(),
                    "period": lesson.period,
                    "subject_name": subject_name(subject, locale),
                    "changes": changes,
                },
                dedupe_key=f"lesson-changed:{lesson.id}:{now.isoformat()}",
            )
        )
