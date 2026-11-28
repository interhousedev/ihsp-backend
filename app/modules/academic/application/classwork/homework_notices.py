"""Notifications of homework hand-ins and reviews, written in the same transaction."""

import datetime as dt

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    HomeworkUnitOfWork,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import (
    StudentRecord,
    SubmissionRecord,
)
from app.modules.academic.domain.classwork.review_rules import (
    notify_effective,
    should_notify_teacher,
)
from app.modules.academic.domain.classwork.submission_rules import submission_status
from app.shared.notifications import NotificationDraft, NotificationType

PREVIEW_CHARS = 200


def comment_preview(comment: str | None) -> str | None:
    """The first 200 characters of a teacher comment."""
    if not comment:
        return None
    return comment if len(comment) <= PREVIEW_CHARS else comment[:PREVIEW_CHARS]


class HomeworkNotices:
    """The teacher is told of hand-ins, the student of grades and returns."""

    def __init__(self, people: PeopleDirectory) -> None:
        """Store the people directory."""
        self.people = people

    async def submitted(
        self,
        uow: HomeworkUnitOfWork,
        *,
        lesson: Lesson,
        student: StudentRecord,
        record: SubmissionRecord,
        now: dt.datetime,
    ) -> bool:
        """Tell the lesson's teacher about a hand-in; True when a notice was queued.

        Muted teachers and lessons get none, and a student who submits again within
        ten minutes of the last notice does not tell the teacher twice.
        """
        teacher_id = lesson.teacher_id
        if teacher_id is None or teacher_id == student.user_id or record.id is None:
            return False
        settings = await uow.homework_settings.get(teacher_id)
        if not notify_effective(lesson.homework_notify, settings.notify_on_submission):
            return False
        if not should_notify_teacher(record.notified_at, now):
            return False
        person = await self.people.person(student.user_id)
        name = f"{person.first_name} {person.last_name}" if person else ""
        late = (
            submission_status(record.submitted_at, lesson.homework_due_date) == "late"
        )
        uow.notify(
            NotificationDraft(
                user_id=teacher_id,
                type=NotificationType.HOMEWORK_SUBMITTED,
                payload={
                    "lesson_id": str(lesson.id),
                    "submission_id": str(record.id),
                    "student_name": name,
                    "subject_names": dict(lesson.subject_names),
                    "group_name": student.group_name,
                    "lesson_date": lesson.date.isoformat(),
                    "late": late,
                    "file_count": len(record.file_ids),
                },
                dedupe_key=f"homework_submitted:{record.id}:{now.isoformat()}",
            )
        )
        await uow.submissions.mark_notified(record.id, now)
        return True

    def reviewed(
        self, uow: HomeworkUnitOfWork, lesson: Lesson, record: SubmissionRecord
    ) -> None:
        """Tell the student their submission was graded or returned."""
        if record.reviewed_at is None or record.id is None:
            return
        uow.notify(
            NotificationDraft(
                user_id=record.student_id,
                type=NotificationType.HOMEWORK_REVIEWED,
                payload={
                    "lesson_id": str(lesson.id),
                    "subject_names": dict(lesson.subject_names),
                    "lesson_date": lesson.date.isoformat(),
                    "review_status": record.review_status,
                    "grade": record.grade,
                    "comment_preview": comment_preview(record.teacher_comment),
                },
                dedupe_key=(
                    f"homework_reviewed:{record.id}:{record.reviewed_at.isoformat()}"
                ),
            )
        )
