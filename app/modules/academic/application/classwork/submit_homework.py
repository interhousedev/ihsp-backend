"""Use case: the student hands in files for a lesson's homework."""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.homework_notices import (
    HomeworkNotices,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    HomeworkUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import (
    keys_of,
    require_student,
)
from app.modules.academic.application.classwork.submission_views import (
    SubmissionViewBuilder,
)
from app.modules.academic.domain.classwork.errors import (
    HomeworkNotFoundError,
    HomeworkSubmissionsClosedError,
    LessonNotFoundError,
)
from app.modules.academic.domain.classwork.review_rules import (
    ensure_student_may_change,
)
from app.modules.academic.domain.classwork.submission_rules import (
    check_submission_files,
    clean_comment,
    clean_text,
    ensure_content,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi


class SubmitHomework:
    """Hand in or replace the submission; after the due date it counts as late."""

    def __init__(
        self,
        uow_factory: Callable[[], HomeworkUnitOfWork],
        clock: Clock,
        files: FilesApi,
        views: SubmissionViewBuilder,
        notices: HomeworkNotices,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files
        self.views = views
        self.notices = notices

    async def execute(
        self,
        lesson_id: UUID,
        actor: Actor,
        file_ids: Sequence[UUID],
        comment: str | None,
        text: str | None = None,
    ) -> dict[str, Any]:
        """Save the submission and return the ``HomeworkSubmission`` JSON."""
        clean = clean_comment(comment)
        answer = clean_text(text)
        ensure_content(file_ids, answer)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            lesson = await uow.lesson_reader.visible_lesson(keys_of(student), lesson_id)
            if lesson is None:
                raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
            if not lesson.has_homework:
                raise HomeworkNotFoundError(params={"lesson_id": str(lesson_id)})
            if not lesson.homework_accept_submissions:
                raise HomeworkSubmissionsClosedError(
                    params={"lesson_id": str(lesson_id)}
                )
            existing = await uow.submissions.get(student.user_id, lesson_id)
            if existing is not None:
                ensure_student_may_change(existing.review_status)
            found = await self.files.get_many(list(file_ids))
            check_submission_files(file_ids, found, actor.user_id)
            record = await uow.submissions.upsert(
                student.user_id, lesson_id, file_ids, answer, clean, now
            )
            await self.notices.submitted(
                uow, lesson=lesson, student=student, record=record, now=now
            )
            await uow.commit()
        return await self.views.student_view(record, lesson.homework_due_date)
