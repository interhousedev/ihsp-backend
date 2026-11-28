"""Use case: enrolled students with progress and attempts (UF-LMS-15 step 1)."""

from collections import defaultdict
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.attempt_presenter import number
from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.progress_service import (
    current_progress_pct,
)
from app.modules.lms.application.learning.step_context import (
    load_course,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningCourseStudentView,
    LearningPersonRefView,
    LearningStudentAttemptView,
    LearningStudentWidgetResultView,
)
from app.modules.lms.domain.learning.access import REVIEW
from app.modules.lms.domain.learning.block_results import RESULT_PREFIX
from app.modules.lms.domain.learning.entities import Attempt
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


class ListCourseStudents:
    """Show reviewers who is enrolled and how they are doing."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        gate: AudienceGate,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.gate = gate

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
            widgets: dict[UUID, list[LearningStudentWidgetResultView]] = {}
            progress: dict[UUID, int] = {}
            if version is not None:
                cards = await uow.states.cards_for_users(
                    [e.user_id for e in enrollments], version.manifest.step_ids()
                )
                for enrollment in enrollments:
                    progress[enrollment.user_id] = await current_progress_pct(
                        uow, self.gate, enrollment, version
                    )
                    widgets[enrollment.user_id] = _widget_items(
                        cards.get(enrollment.user_id, {})
                    )
            attempts: dict[UUID, list[Attempt]] = defaultdict(list)
            for attempt in await uow.attempts.list_submitted_for_course(course_id):
                attempts[attempt.user_id].append(attempt)
        users = await self.identity.get_users([e.user_id for e in enrollments])
        students = [
            LearningCourseStudentView(
                user=LearningPersonRefView(
                    id=user.id, first_name=user.first_name, last_name=user.last_name
                ),
                progress_pct=progress.get(enrollment.user_id, enrollment.progress_pct),
                completed_at=enrollment.completed_at,
                attempts=[_attempt_item(a) for a in attempts[enrollment.user_id]],
                widget_results=widgets.get(enrollment.user_id, []),
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


def _widget_items(
    cards: dict[UUID, dict[str, Any]],
) -> list[LearningStudentWidgetResultView]:
    """Return the browser-graded code and HTML results, shown as not verified."""
    return [
        LearningStudentWidgetResultView(
            step_id=step_id,
            block_id=key[len(RESULT_PREFIX) :],
            score_pct=float(record.get("pct", 0)),
            passed=bool(record.get("passed")),
            verified=bool(record.get("verified", False)),
        )
        for step_id, step_cards in cards.items()
        for key, record in step_cards.items()
        if key.startswith(RESULT_PREFIX) and record.get("kind") == "widget"
    ]
