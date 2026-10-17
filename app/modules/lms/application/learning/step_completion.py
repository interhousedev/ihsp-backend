"""Step completion after a test is graded or a score is overridden (LMS-19, LMS-20)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.progress_service import (
    refresh_user_progress,
)
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import (
    StepContext,
    load_live_step,
)
from app.modules.lms.domain.learning.block_results import passed_block_ids
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
        passed = await self._passed(uow, attempt.user_id, attempt.step_id)
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
        passed = await self._passed(uow, attempt.user_id, attempt.step_id)
        if all_tests_passed(test_ids, passed):
            await uow.states.set_completed(attempt.user_id, attempt.step_id, now=now)
        elif was_passed and not attempt.passed and test_ids:
            await uow.states.clear_completed(attempt.user_id, attempt.step_id)
        await refresh_user_progress(uow, attempt.user_id, context.course, now)

    async def after_block_result(
        self, uow: LearningUnitOfWork, user_id: UUID, step_id: UUID, now: datetime
    ) -> None:
        """Complete the step when an H5P or video result finished its last block."""
        try:
            context = await load_live_step(uow, step_id)
        except StepNotFoundError:
            return
        rendered = await load_rendered(uow, self.cache, context.live_step.revision_id)
        passed = await self._passed(uow, user_id, step_id)
        if all_tests_passed(rendered.gradable_block_ids, passed):
            await uow.states.set_completed(user_id, step_id, now=now)
            await refresh_user_progress(uow, user_id, context.course, now)

    @staticmethod
    async def _passed(
        uow: LearningUnitOfWork, user_id: UUID, step_id: UUID
    ) -> set[str]:
        """Return the passed tests plus the finished H5P and video blocks."""
        passed = await uow.attempts.passed_block_ids(user_id, step_id)
        state = await uow.states.get(user_id, step_id)
        return passed | passed_block_ids(state.cards if state else {})

    async def _live(
        self, uow: LearningUnitOfWork, attempt: Attempt
    ) -> tuple[StepContext, tuple[str, ...]] | None:
        """Return the live context of the attempt's step and its test block ids."""
        try:
            context = await load_live_step(uow, attempt.step_id)
        except StepNotFoundError:
            return None
        rendered = await load_rendered(uow, self.cache, context.live_step.revision_id)
        return context, rendered.gradable_block_ids
