"""Use case: enrolled students with progress and attempts (UF-LMS-15 step 1)."""

from collections import defaultdict
from uuid import UUID

from app.modules.lms.application.learning.attempt_presenter import number
from app.modules.lms.application.learning.progress_service import ensure_progress
from app.modules.lms.application.learning.step_context import (
    load_course,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningCourseStudentView,
    LearningPersonRefView,
    LearningStudentAttemptView,
)
from app.modules.lms.domain.learning.access import REVIEW
from app.modules.lms.domain.learning.entities import Attempt
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


class ListCourseStudents:
    """Show reviewers who is enrolled and how they are doing."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, identity: IdentityDirectory
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity

    async def execute(
        self, actor: Actor, course_id: UUID
    ) -> list[LearningCourseStudentView]:
        """Return the students of a course; needs the `review` permission."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(REVIEW)
            enrollments = await uow.enrollments.list_for_course(course_id)
            version = (
                await uow.versions.get(course.live_version_id)
                if course.live_version_id
                else None
            )
            for enrollment in enrollments:
                if version is not None:
                    await ensure_progress(uow, enrollment, version, self.clock.now())
            attempts: dict[UUID, list[Attempt]] = defaultdict(list)
            for attempt in await uow.attempts.list_submitted_for_course(course_id):
                attempts[attempt.user_id].append(attempt)
            await uow.commit()
        users = await self.identity.get_users([e.user_id for e in enrollments])
        students = [
            LearningCourseStudentView(
                user=LearningPersonRefView(
                    id=user.id, first_name=user.first_name, last_name=user.last_name
                ),
                progress_pct=enrollment.progress_pct,
                completed_at=enrollment.completed_at,
                attempts=[_attempt_item(a) for a in attempts[enrollment.user_id]],
            )
            for enrollment in enrollments
            if (user := users.get(enrollment.user_id)) is not None
        ]
        return sorted(
            students,
            key=lambda s: (s.user.last_name.casefold(), s.user.first_name.casefold()),
        )


def _attempt_item(attempt: Attempt) -> LearningStudentAttemptView:
    """Return one submitted attempt in the list of a student."""
    return LearningStudentAttemptView(
        id=attempt.id,
        step_id=attempt.step_id,
        block_id=attempt.block_id,
        score=number(attempt.effective_score),
        max_score=number(attempt.max_score),
        passed=bool(attempt.passed),
        submitted_at=attempt.submitted_at or attempt.started_at,
    )
