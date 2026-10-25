"""Use case: read a graded attempt as its owner or as a reviewer (UF-LMS-15 step 2)."""

from uuid import UUID

from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.attempt_presenter import (
    attempt_result,
    number,
    review_allowed,
)
from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_revision,
)
from app.modules.lms.application.learning.step_context import staff_access
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningAttemptReviewView,
    LearningPersonRefView,
)
from app.modules.lms.domain.learning.access import REVIEW
from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.errors import (
    AttemptNotFoundError,
    AttemptNotSubmittedError,
)
from app.modules.lms.domain.step_content import TestBlock
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


async def review_view(
    identity: IdentityDirectory,
    attempt: Attempt,
    test: TestBlock,
    *,
    with_review: bool,
) -> LearningAttemptReviewView:
    """Return an attempt with its variant, answers and review fields."""
    result = attempt_result(attempt, test, with_review=with_review)
    users = await identity.get_users([attempt.user_id])
    user = users.get(attempt.user_id)
    person = (
        LearningPersonRefView(
            id=user.id, first_name=user.first_name, last_name=user.last_name
        )
        if user
        else LearningPersonRefView(id=attempt.user_id, first_name="", last_name="")
    )
    return LearningAttemptReviewView(
        **result.model_dump(),
        user=person,
        variant=attempt.variant.to_json(),
        answers=attempt.answers,
        revision_id=attempt.revision_id,
        override_score=(
            None if attempt.override_score is None else number(attempt.override_score)
        ),
        override_comment=attempt.override_comment,
    )


async def can_review(uow: LearningUnitOfWork, actor: Actor, attempt: Attempt) -> bool:
    """Return True if the actor holds `review` in the course of the attempt's step."""
    step = await uow.steps.get(attempt.step_id)
    if step is None:
        return False
    return (await staff_access(uow, actor, step.course_id)).can(REVIEW)


class GetAttempt:
    """Show an attempt to its owner (as `show_answers` allows) or to a reviewer."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        finisher: AttemptFinisher,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.finisher = finisher

    async def execute(
        self, actor: Actor, attempt_id: UUID
    ) -> LearningAttemptReviewView:
        """Return the graded attempt; an attempt whose time ran out is graded first."""
        now = self.clock.now()
        problem: AttemptNotSubmittedError | None = None
        async with self.uow_factory() as uow:
            attempt = await uow.attempts.get(attempt_id)
            reviewer = attempt is not None and await can_review(uow, actor, attempt)
            if attempt is None or not (reviewer or attempt.user_id == actor.user_id):
                raise AttemptNotFoundError(params={"attempt_id": str(attempt_id)})
            if attempt.is_expired(now) and attempt.deadline_at is not None:
                await self.finisher.finish(
                    uow, attempt, at=attempt.deadline_at, now=now
                )
            revision = await load_revision(uow, attempt.revision_id)
            test = find_test_block(revision.content, attempt.block_id)
            show = reviewer or await review_allowed(uow, attempt, test)
            problem = None if attempt.is_submitted else AttemptNotSubmittedError()
            await uow.commit()
        if problem is not None:
            raise problem
        return await review_view(self.identity, attempt, test, with_review=show)
