"""Use case: submit an attempt and grade it on the server (UF-LMS-04 steps 4-5)."""

from uuid import UUID

from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.attempt_presenter import (
    attempt_result,
    review_allowed,
)
from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_revision,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningAttemptResultView
from app.modules.lms.domain.learning.errors import AttemptNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock


class SubmitAttempt:
    """Grade the saved answers against the revision the attempt was taken on."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, finisher: AttemptFinisher
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.finisher = finisher

    async def execute(
        self, actor: Actor, attempt_id: UUID
    ) -> LearningAttemptResultView:
        """Return the result; submitting twice returns the same result.

        Correct answers and explanations are included only as the test's
        `show_answers` setting allows.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            attempt = await uow.attempts.get(attempt_id, for_update=True)
            if attempt is None or attempt.user_id != actor.user_id:
                raise AttemptNotFoundError(params={"attempt_id": str(attempt_id)})
            if not attempt.is_submitted:
                at = min(now, attempt.deadline_at) if attempt.deadline_at else now
                await self.finisher.finish(uow, attempt, at=at, now=now)
            revision = await load_revision(uow, attempt.revision_id)
            test = find_test_block(revision.content, attempt.block_id)
            show = await review_allowed(uow, attempt, test)
            await uow.commit()
        return attempt_result(attempt, test, with_review=show)
