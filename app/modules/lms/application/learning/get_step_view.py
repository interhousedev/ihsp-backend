"""Use case: open a step as a student sees it (UF-LMS-03)."""

from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.attempt_finisher import AttemptFinisher
from app.modules.lms.application.learning.attempt_presenter import (
    attempt_result,
    number,
)
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
    LearningBlockResultView,
    LearningFlashcardsBlockView,
    LearningH5PBlockView,
    LearningInteractiveVideoBlockView,
    LearningQuizBlockView,
    LearningQuizRulesView,
    LearningStepView,
    LearningTextBlockView,
    LearningVideoBlockView,
    StepBlockView,
)
from app.modules.lms.domain.learning.block_results import stored_result
from app.modules.lms.domain.learning.cards import select_next
from app.modules.lms.domain.learning.entities import Attempt, StepState
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.learning.grading import review_visible
from app.modules.lms.domain.learning.live import RenderCache, RenderedRevision
from app.modules.lms.domain.learning.points import earned_points, scored_earned_points
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
            state = await uow.states.get(actor.user_id, step_id)
            blocks = await self._blocks(uow, actor, step_id, rendered, state)
            await uow.commit()
        return LearningStepView(
            step_id=step_id,
            revision_id=rendered.revision_id,
            title=rendered.title,
            blocks=blocks,
            completed=state is not None and state.completed_at is not None,
            preview=False,
            blocks_total=len(blocks),
            blocks_passed=sum(1 for block in blocks if block.passed),
            points_total=number(rendered.points_total),
            points_earned=sum(
                block.points_earned
                for block in blocks
                if isinstance(block, LearningQuizBlockView)
            )
            + _scored_earned(rendered, state.cards if state else {}),
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
        state: StepState | None,
    ) -> list[StepBlockView]:
        """Fill the cached render with the student's attempts, cards and passes."""
        by_block: dict[str, list[Attempt]] = defaultdict(list)
        for attempt in await uow.attempts.list_for_step(actor.user_id, step_id):
            by_block[attempt.block_id].append(attempt)
        best_scores = await uow.attempts.best_scores(actor.user_id, [step_id])
        cards = state.cards if state else {}
        views: list[StepBlockView] = []
        for block in deepcopy(rendered.blocks):
            if block["type"] == "test":
                total = rendered.test_points.get(block["id"], Decimal(0))
                earned = earned_points(best_scores.get((step_id, block["id"])), total)
                views.append(
                    await self._quiz(uow, block, by_block[block["id"]], (total, earned))
                )
            elif block["type"] == "flashcards":
                views.append(await self._cards(actor, block, rendered, cards))
            elif block["type"] in ("h5p", "interactive_video"):
                views.append(_scored(block, stored_result(cards, block["id"])))
            elif block["type"] == "video":
                views.append(LearningVideoBlockView(**block, passed=state is not None))
            else:
                views.append(LearningTextBlockView(**block, passed=state is not None))
        return views

    async def _quiz(
        self,
        uow: LearningUnitOfWork,
        block: dict[str, Any],
        attempts: list[Attempt],
        points: tuple[Decimal, Decimal],
    ) -> LearningQuizBlockView:
        """Fill the attempts left, the best result, the open attempt and points."""
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
            passed=any(a.passed for a in attempts if a.is_submitted),
            points_total=number(points[0]),
            points_earned=number(points[1]),
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
            passed=all(
                card_id in states for card_id in rendered.card_ids.get(block["id"], ())
            ),
        )


def _scored(
    block: dict[str, Any], stored: Mapping[str, Any] | None
) -> LearningH5PBlockView | LearningInteractiveVideoBlockView:
    """Fill an H5P or interactive video block with my stored result."""
    result = (
        LearningBlockResultView(
            score=float(stored.get("score", 0)),
            max_score=float(stored.get("max_score", 0)),
            completed=bool(stored.get("completed")),
        )
        if stored
        else None
    )
    if block["type"] == "h5p":
        return LearningH5PBlockView(
            **block, result=result, passed=bool(stored and stored.get("passed"))
        )
    return LearningInteractiveVideoBlockView(
        **block,
        answers=dict((stored or {}).get("answers", {})),
        result=result,
        passed=result is not None and result.completed,
    )


def _scored_earned(rendered: RenderedRevision, cards: Mapping[str, Any]) -> float:
    """Return the points earned in the H5P and interactive video blocks."""
    return sum(
        float(scored_earned_points(stored_result(cards, block_id), total))
        for block_id, total in rendered.scored_points.items()
    )
