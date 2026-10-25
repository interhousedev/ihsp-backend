"""Use case: override the score of an attempt with a comment (UF-LMS-15 step 3)."""

from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.modules.lms.application.learning.get_attempt import can_review, review_view
from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_revision,
)
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningAttemptReviewView
from app.modules.lms.domain.learning.errors import (
    AttemptNotFoundError,
    AttemptNotSubmittedError,
    CoursePermissionError,
    PreviewAttemptError,
    ScoreInvalidError,
)
from app.modules.lms.domain.learning.grading import is_passed
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


class OverrideScore:
    """Let a reviewer set the score; `passed`, completion and progress follow."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        completion: StepCompletion,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.completion = completion

    async def execute(
        self, actor: Actor, attempt_id: UUID, score: float, comment: str
    ) -> LearningAttemptReviewView:
        """Store the override, recompute `passed` and update completion."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            attempt = await uow.attempts.get(attempt_id, for_update=True)
            if attempt is None:
                raise AttemptNotFoundError(params={"attempt_id": str(attempt_id)})
            if not await can_review(uow, actor, attempt):
                raise CoursePermissionError(params={"permission": "review"})
            if attempt.is_preview:
                raise PreviewAttemptError(params={"attempt_id": str(attempt_id)})
            if not attempt.is_submitted:
                raise AttemptNotSubmittedError(params={"attempt_id": str(attempt_id)})
            value = _score(score, attempt.max_score)
            revision = await load_revision(uow, attempt.revision_id)
            test = find_test_block(revision.content, attempt.block_id)
            was_passed = bool(attempt.passed)
            attempt.override_score = value
            attempt.override_comment = comment.strip()
            attempt.reviewed_by = actor.user_id
            attempt.reviewed_at = now
            attempt.passed = is_passed(
                value, attempt.max_score, test.config.passing_score_pct
            )
            await uow.attempts.save(attempt)
            await self.completion.after_override(
                uow, attempt, was_passed=was_passed, now=now
            )
            await uow.commit()
        return await review_view(self.identity, attempt, test, with_review=True)


def _score(value: float, max_score: Decimal) -> Decimal:
    """Return the score as a decimal within 0..max_score or raise ScoreInvalidError."""
    try:
        score = Decimal(str(value))
    except InvalidOperation as error:
        raise ScoreInvalidError(params={"max_score": float(max_score)}) from error
    if not score.is_finite() or score < 0 or score > max_score:
        raise ScoreInvalidError(params={"max_score": float(max_score)})
    return score
