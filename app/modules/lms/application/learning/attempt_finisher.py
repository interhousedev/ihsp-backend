"""Grading an attempt and storing its result (LMS-15 to LMS-17)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_revision,
)
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.domain.learning.entities import Attempt, RevisionData
from app.modules.lms.domain.learning.grading import grade_attempt, is_passed
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


class AttemptFinisher:
    """Grades attempts on the revision they were taken on, then updates progress."""

    def __init__(self, completion: StepCompletion) -> None:
        """Store the completion service."""
        self.completion = completion

    async def finish(
        self,
        uow: LearningUnitOfWork,
        attempt: Attempt,
        *,
        at: datetime,
        now: datetime,
    ) -> RevisionData:
        """Grade the saved answers, store the result and update step completion."""
        revision = await load_revision(uow, attempt.revision_id)
        test = find_test_block(revision.content, attempt.block_id)
        grade = grade_attempt(test, attempt.variant, attempt.answers)
        attempt.score = grade.score
        attempt.max_score = grade.max_score
        attempt.passed = is_passed(
            grade.score, grade.max_score, test.config.passing_score_pct
        )
        attempt.submitted_at = at
        await uow.attempts.save(attempt)
        if not attempt.is_preview:
            await self.completion.after_graded(uow, attempt, now)
        return revision

    async def finish_expired(
        self,
        uow: LearningUnitOfWork,
        user_id: UUID,
        step_id: UUID,
        *,
        preview: bool,
        now: datetime,
    ) -> int:
        """Auto-submit attempts whose time ran out; return how many were closed.

        The result is stamped with the deadline, not with the moment of the read.
        """
        closed = 0
        for attempt in await uow.attempts.list_open(user_id, step_id, preview=preview):
            if attempt.is_expired(now) and attempt.deadline_at is not None:
                await self.finish(uow, attempt, at=attempt.deadline_at, now=now)
                closed += 1
        return closed
