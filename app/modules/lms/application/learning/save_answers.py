"""Use case: save the answers of an attempt as the student goes (UF-LMS-04 step 3)."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.attempt_presenter import attempt_view
from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_revision,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningAttemptView
from app.modules.lms.domain.learning.answers import normalize_answers
from app.modules.lms.domain.learning.errors import (
    AttemptClosedError,
    AttemptNotFoundError,
)
from app.shared.actor import Actor
from app.shared.clock import Clock


class SaveAnswers:
    """Store answers before the attempt is submitted and before its deadline."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, finisher: AttemptFinisher
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.finisher = finisher

    async def execute(
        self,
        actor: Actor,
        attempt_id: UUID,
        answers: Mapping[str, Mapping[str, Any]],
    ) -> LearningAttemptView:
        """Merge the answers into the attempt (per question) and return it.

        After the deadline the attempt is submitted with what was saved earlier,
        and the late answers are refused.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            attempt = await uow.attempts.get(attempt_id, for_update=True)
            if attempt is None or attempt.user_id != actor.user_id:
                raise AttemptNotFoundError(params={"attempt_id": str(attempt_id)})
            closed = attempt.is_submitted
            if attempt.is_expired(now) and attempt.deadline_at is not None:
                await self.finisher.finish(
                    uow, attempt, at=attempt.deadline_at, now=now
                )
                closed = True
            revision = await load_revision(uow, attempt.revision_id)
            test = find_test_block(revision.content, attempt.block_id)
            if not closed:
                attempt.answers = {
                    **attempt.answers,
                    **normalize_answers(test, attempt.variant, answers),
                }
                await uow.attempts.save(attempt)
            await uow.commit()
        if closed:
            raise AttemptClosedError(params={"attempt_id": str(attempt_id)})
        return attempt_view(attempt, test)
