"""Use case: record that a student opened a step (UF-LMS-03, LMS-19)."""

from uuid import UUID

from app.modules.lms.application.learning.progress_service import (
    refresh_user_progress,
)
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import load_live_step
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningStepProgressView
from app.modules.lms.domain.learning.errors import NotEnrolledError
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.domain.learning.progress import completes_on_view
from app.shared.actor import Actor
from app.shared.clock import Clock


class MarkStepViewed:
    """Store the view and complete steps that have no tests."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, cache: RenderCache
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.cache = cache

    async def execute(self, actor: Actor, step_id: UUID) -> LearningStepProgressView:
        """Mark the step viewed; a step without tests is completed by opening it."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            enrollment = await uow.enrollments.get(context.course.id, actor.user_id)
            if enrollment is None:
                raise NotEnrolledError(params={"course_id": str(context.course.id)})
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
            complete = completes_on_view(rendered.gradable_block_ids)
            state = await uow.states.touch_viewed(
                actor.user_id, step_id, now=now, complete=complete
            )
            if complete:
                await refresh_user_progress(uow, actor.user_id, context.course, now)
            await uow.commit()
        return LearningStepProgressView(
            step_id=step_id,
            viewed_at=state.viewed_at,
            completed=state.completed_at is not None,
        )
