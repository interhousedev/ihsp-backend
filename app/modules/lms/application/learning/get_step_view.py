"""Use case: open a step as a student sees it (UF-LMS-03)."""

from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.attempt_presenter import attempt_result
from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_rendered,
    load_revision,
)
from app.modules.lms.application.learning.step_context import (
    StepContext,
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningAttemptResultView,
    LearningFlashcardsBlockView,
    LearningQuizBlockView,
    LearningQuizRulesView,
    LearningStepView,
    LearningTextBlockView,
    StepBlockView,
)
from app.modules.lms.domain.learning.cards import select_next
from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.learning.grading import review_visible
from app.modules.lms.domain.learning.live import RenderCache, RenderedRevision
from app.modules.lms.ports.learning.daily_counters import DailyCounters
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today


class GetStepView:
    """Return the live revision of a step with the student's own state."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        cache: RenderCache,
        finisher: AttemptFinisher,
        counters: DailyCounters,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.cache = cache
        self.finisher = finisher
        self.counters = counters

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> LearningStepView:
        """Return the step; attempts whose time ran out are submitted on the way."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            if context.course.id != course_id:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            await self._check_access(uow, actor, context)
            await self.finisher.finish_expired(
                uow, actor.user_id, step_id, preview=False, now=now
            )
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
            blocks = await self._blocks(uow, actor, step_id, rendered)
            state = await uow.states.get(actor.user_id, step_id)
            await uow.commit()
        return LearningStepView(
            step_id=step_id,
            revision_id=rendered.revision_id,
            title=rendered.title,
            blocks=blocks,
            completed=state is not None and state.completed_at is not None,
            preview=False,
        )

    async def _check_access(
        self, uow: LearningUnitOfWork, actor: Actor, context: StepContext
    ) -> None:
        """Allow enrolled students and course staff."""
        if await uow.enrollments.get(context.course.id, actor.user_id) is not None:
            return
        if not (await staff_access(uow, actor, context.course.id)).is_staff:
            raise NotEnrolledError(params={"course_id": str(context.course.id)})

    async def _blocks(
        self,
        uow: LearningUnitOfWork,
        actor: Actor,
        step_id: UUID,
        rendered: RenderedRevision,
    ) -> list[StepBlockView]:
        """Fill the cached render with the student's attempts and card counts."""
        by_block: dict[str, list[Attempt]] = defaultdict(list)
        for attempt in await uow.attempts.list_for_step(actor.user_id, step_id):
            by_block[attempt.block_id].append(attempt)
        state = await uow.states.get(actor.user_id, step_id)
        views: list[StepBlockView] = []
        for block in deepcopy(rendered.blocks):
            if block["type"] == "test":
                views.append(await self._quiz(uow, block, by_block[block["id"]]))
            elif block["type"] == "flashcards":
                cards = state.cards if state else {}
                views.append(await self._cards(actor, block, rendered, cards))
            else:
                views.append(LearningTextBlockView(**block))
        return views

    async def _quiz(
        self, uow: LearningUnitOfWork, block: dict[str, Any], attempts: list[Attempt]
    ) -> LearningQuizBlockView:
        """Fill the attempts left, the best result and the open attempt."""
        rules = block["rules"]
        limit: int | None = rules["attempts_left"]  # the cached render holds the limit
        left = None if limit is None else max(0, limit - len(attempts))
        open_attempt = next((a for a in reversed(attempts) if not a.is_submitted), None)
        return LearningQuizBlockView(
            id=block["id"],
            type="test",
            rules=LearningQuizRulesView(**{**rules, "attempts_left": left}),
            best=await self._best(uow, attempts, left),
            open_attempt_id=open_attempt.id if open_attempt else None,
        )

    async def _best(
        self, uow: LearningUnitOfWork, attempts: list[Attempt], left: int | None
    ) -> LearningAttemptResultView | None:
        """Return the best submitted attempt (ties go to the later one)."""
        submitted = [a for a in attempts if a.is_submitted]
        if not submitted:
            return None
        best = max(submitted, key=lambda a: (a.effective_score or 0, a.attempt_no))
        revision = await load_revision(uow, best.revision_id)
        test = find_test_block(revision.content, best.block_id)
        show = review_visible(
            test.config.show_answers, passed=bool(best.passed), attempts_left=left
        )
        return attempt_result(best, test, with_review=show)

    async def _cards(
        self,
        actor: Actor,
        block: dict[str, Any],
        rendered: RenderedRevision,
        states: Mapping[str, Mapping[str, Any]],
    ) -> LearningFlashcardsBlockView:
        """Count the cards a session of the block offers today."""
        usage = await self.counters.get(
            actor.user_id, block["id"], local_today(self.clock)
        )
        _, counts = select_next(
            rendered.card_ids.get(block["id"], ()), states, self.clock.now(), usage
        )
        return LearningFlashcardsBlockView(
            id=block["id"],
            type="flashcards",
            cards_count=block["cards_count"],
            due=counts.total,
        )
