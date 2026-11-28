"""Use cases: the teacher opens, grades, returns or un-reviews one submission.

A grade also writes the student's temporary mark of the lesson (DECISIONS #5), which
the teacher later enters into EMIS; the submission remembers that mark by id. A
mark the teacher set by hand before the grade is left alone and not linked. A
return or a cleared review deletes the linked mark.
"""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.homework_notices import (
    HomeworkNotices,
)
from app.modules.academic.application.classwork.people import Person
from app.modules.academic.application.classwork.ports.unit_of_work import (
    HomeworkUnitOfWork,
)
from app.modules.academic.application.classwork.submission_views import (
    SubmissionViewBuilder,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import (
    LessonNotFoundError,
    SubmissionNotFoundError,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import SubmissionRecord
from app.modules.academic.domain.classwork.review_rules import ReviewAction, decide
from app.modules.academic.domain.classwork.temporary_mark import COMMENT_MAX
from app.shared.actor import Actor
from app.shared.clock import Clock

UowFactory = Callable[[], HomeworkUnitOfWork]


async def _load(
    uow: HomeworkUnitOfWork, submission_id: UUID, actor: Actor
) -> tuple[SubmissionRecord, Lesson]:
    """The submission and its lesson, for the lesson's teacher or an admin only.

    Raises:
        SubmissionNotFoundError: No such submission.
        NotLessonTeacherError: The actor neither teaches the lesson nor is admin.
    """
    record = await uow.submissions.get_by_id(submission_id)
    if record is None:
        raise SubmissionNotFoundError(params={"submission_id": str(submission_id)})
    lesson = await uow.lessons.get(record.lesson_id)
    if lesson is None:
        raise LessonNotFoundError(params={"lesson_id": str(record.lesson_id)})
    ensure_lesson_staff(lesson, actor)
    return record, lesson


async def _row(
    uow: HomeworkUnitOfWork,
    views: SubmissionViewBuilder,
    lesson: Lesson,
    record: SubmissionRecord,
) -> dict[str, Any]:
    """The ``HomeworkSubmissionRow`` of one submission, files with download links."""
    student = await uow.students.get(record.student_id)
    person = await views.people.person(record.student_id) or Person(
        record.student_id, "", ""
    )
    reviewers = await views.people.people(
        [record.reviewed_by] if record.reviewed_by else []
    )
    files = await views.teacher_files([record])
    return views.teacher_row(
        student=person,
        group_name=student.group_name if student else "",
        subgroup=student.subgroup if student else None,
        record=record,
        due=lesson.homework_due_date,
        files=files,
        reviewers=reviewers,
    )


async def _drop_mark(uow: HomeworkUnitOfWork, record: SubmissionRecord) -> None:
    """Delete the temporary mark an earlier grade of this submission made."""
    if record.temporary_mark_id is not None:
        await uow.temporary_marks.delete_by_id(record.temporary_mark_id)


async def _grade_mark(
    uow: HomeworkUnitOfWork,
    lesson: Lesson,
    record: SubmissionRecord,
    *,
    grade: int,
    comment: str | None,
    author_id: UUID,
    now: dt.datetime,
) -> UUID | None:
    """Write the temporary mark of a grade; None when a hand-set mark is kept."""
    existing = await uow.temporary_marks.get(lesson.id, record.student_id)
    if existing is not None and existing.id != record.temporary_mark_id:
        return None
    mark = await uow.temporary_marks.upsert(
        lesson_id=lesson.id,
        student_id=record.student_id,
        subject_id=lesson.subject_id,
        date=lesson.date,
        value=grade,
        comment=comment[:COMMENT_MAX] if comment else None,
        author_id=author_id,
        at=now,
    )
    return mark.id


class GetStaffHomeworkSubmission:
    """One submission as its teacher sees it."""

    def __init__(self, uow_factory: UowFactory, views: SubmissionViewBuilder) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(self, submission_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the ``HomeworkSubmissionRow``.

        Raises:
            SubmissionNotFoundError: No such submission.
            NotLessonTeacherError: The actor neither teaches the lesson nor is admin.
        """
        async with self.uow_factory() as uow:
            record, lesson = await _load(uow, submission_id, actor)
            return await _row(uow, self.views, lesson, record)


class ReviewHomeworkSubmission:
    """Grade (2..5, comment optional) or return (comment required) a submission."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        views: SubmissionViewBuilder,
        notices: HomeworkNotices,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.views = views
        self.notices = notices

    async def execute(
        self,
        submission_id: UUID,
        actor: Actor,
        *,
        action: ReviewAction,
        grade: int | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Save the review, tell the student and return the updated row.

        Raises:
            ReviewGradeInvalidError: ``grade`` without a grade of 2..5.
            ReviewCommentRequiredError: ``return`` without a comment.
            ReviewCommentTooLongError: The comment is over 2000 characters.
            SubmissionNotFoundError: No such submission.
            NotLessonTeacherError: The actor neither teaches the lesson nor is admin.
        """
        decision = decide(action, grade, comment)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            record, lesson = await _load(uow, submission_id, actor)
            mark_id: UUID | None = None
            if decision.grade is not None:
                mark_id = await _grade_mark(
                    uow,
                    lesson,
                    record,
                    grade=decision.grade,
                    comment=decision.comment,
                    author_id=actor.user_id,
                    now=now,
                )
            else:
                await _drop_mark(uow, record)
            saved = await uow.submissions.set_review(
                submission_id,
                status=decision.status,
                grade=decision.grade,
                teacher_comment=decision.comment,
                reviewer_id=actor.user_id,
                now=now,
                temporary_mark_id=mark_id,
            )
            self.notices.reviewed(uow, lesson, saved)
            row = await _row(uow, self.views, lesson, saved)
            await uow.commit()
        return row


class ClearHomeworkReview:
    """Undo a review: back to ``pending``, the grade's temporary mark deleted."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, submission_id: UUID, actor: Actor) -> None:
        """Clear the review; nobody is notified.

        Raises:
            SubmissionNotFoundError: No such submission.
            NotLessonTeacherError: The actor neither teaches the lesson nor is admin.
        """
        async with self.uow_factory() as uow:
            record, _ = await _load(uow, submission_id, actor)
            await _drop_mark(uow, record)
            await uow.submissions.clear_review(submission_id)
            await uow.commit()
