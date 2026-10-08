"""Step completion after a test is graded or a score is overridden (LMS-19, LMS-20)."""

from datetime import datetime

from app.modules.lms.application.learning.progress_service import (
    refresh_user_progress,
)
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import (
    StepContext,
    load_live_step,
)
from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.errors import StepNotFoundError
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.domain.learning.progress import all_tests_passed
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


class StepCompletion:
    """Keeps StepState completion and the enrollment progress in step with attempts."""

    def __init__(self, cache: RenderCache) -> None:
        """Store the render cache used to find the tests of the live revision."""
        self.cache = cache

    async def after_graded(
        self, uow: LearningUnitOfWork, attempt: Attempt, now: datetime
    ) -> None:
        """Complete the step when every test block of it has a passed attempt."""
        loaded = await self._live(uow, attempt)
        if loaded is None:
            return
        context, test_ids = loaded
        passed = await uow.attempts.passed_block_ids(attempt.user_id, attempt.step_id)
        if all_tests_passed(test_ids, passed):
            await uow.states.set_completed(attempt.user_id, attempt.step_id, now=now)
            await refresh_user_progress(uow, attempt.user_id, context.course, now)

    async def after_override(
        self,
        uow: LearningUnitOfWork,
        attempt: Attempt,
        *,
        was_passed: bool,
        now: datetime,
    ) -> None:
        """Recompute completion after a reviewer changed the score of an attempt.

        Only a real flip of ``passed`` can take completion away; a step that
        stayed completed through a content change is left alone otherwise.
        """
        loaded = await self._live(uow, attempt)
        if loaded is None:
            return
        context, test_ids = loaded
        passed = await uow.attempts.passed_block_ids(attempt.user_id, attempt.step_id)
        if all_tests_passed(test_ids, passed):
            await uow.states.set_completed(attempt.user_id, attempt.step_id, now=now)
        elif was_passed and not attempt.passed and test_ids:
            await uow.states.clear_completed(attempt.user_id, attempt.step_id)
        await refresh_user_progress(uow, attempt.user_id, context.course, now)

    async def _live(
        self, uow: LearningUnitOfWork, attempt: Attempt
    ) -> tuple[StepContext, tuple[str, ...]] | None:
        """Return the live context of the attempt's step and its test block ids."""
        try:
            context = await load_live_step(uow, attempt.step_id)
        except StepNotFoundError:
            return None
        rendered = await load_rendered(uow, self.cache, context.live_step.revision_id)
        return context, rendered.test_block_ids
