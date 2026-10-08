"""Turning attempts into the JSON shapes of the API contract."""

from decimal import Decimal

from app.modules.lms.application.learning.views import (
    LearningAttemptQuestionView,
    LearningAttemptResultView,
    LearningAttemptView,
    LearningReviewItemView,
)
from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.errors import AttemptNotSubmittedError
from app.modules.lms.domain.learning.grading import (
    build_review,
    grade_attempt,
    review_visible,
)
from app.modules.lms.domain.step_content import TestBlock
from app.modules.lms.domain.student_render import render_questions
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


def number(value: Decimal | None) -> float:
    """Return a stored decimal as a float for JSON; 0.0 when missing."""
    return float(value) if value is not None else 0.0


def attempt_view(attempt: Attempt, test: TestBlock) -> LearningAttemptView:
    """Return an attempt in progress: its variant without correctness data."""
    questions = render_questions(
        test, list(attempt.variant.question_ids), attempt.variant.option_order
    )
    return LearningAttemptView(
        id=attempt.id,
        block_id=attempt.block_id,
        attempt_no=attempt.attempt_no,
        started_at=attempt.started_at,
        deadline_at=attempt.deadline_at,
        questions=[LearningAttemptQuestionView(**question) for question in questions],
        answers=attempt.answers,
        submitted_at=attempt.submitted_at,
    )


async def attempts_left(
    uow: LearningUnitOfWork, attempt: Attempt, test: TestBlock
) -> int | None:
    """Return attempts left in the block; None when unlimited or a preview."""
    limit = test.config.max_attempts
    if attempt.is_preview or limit is None:
        return None
    used = await uow.attempts.count(attempt.user_id, attempt.step_id, attempt.block_id)
    return max(0, limit - used)


async def review_allowed(
    uow: LearningUnitOfWork, attempt: Attempt, test: TestBlock
) -> bool:
    """Return True if ``show_answers`` lets the owner see the correct answers now."""
    return review_visible(
        test.config.show_answers,
        passed=bool(attempt.passed),
        attempts_left=await attempts_left(uow, attempt, test),
    )


def attempt_result(
    attempt: Attempt, test: TestBlock, *, with_review: bool
) -> LearningAttemptResultView:
    """Return the graded attempt; the review (correct answers) only if allowed."""
    if attempt.submitted_at is None:
        raise AttemptNotSubmittedError(params={"attempt_id": str(attempt.id)})
    review = None
    if with_review:
        grade = grade_attempt(test, attempt.variant, attempt.answers)
        review = [
            LearningReviewItemView(**item)
            for item in build_review(test, attempt.variant, grade.correct)
        ]
    return LearningAttemptResultView(
        id=attempt.id,
        score=number(attempt.effective_score),
        max_score=number(attempt.max_score),
        passed=bool(attempt.passed),
        submitted_at=attempt.submitted_at,
        review=review,
    )
