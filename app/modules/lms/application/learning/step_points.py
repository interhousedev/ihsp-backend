"""Points of the steps of a live version, for the course page and its sidebar."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.lms.application.learning.revision_loading import load_rendered_many
from app.modules.lms.domain.learning.block_results import stored_result
from app.modules.lms.domain.learning.entities import LiveVersion
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.domain.learning.points import (
    earned_points,
    scored_earned_points,
    sum_points,
)
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


@dataclass(frozen=True, slots=True)
class StepPoints:
    """Points one step is worth and what a student has earned in it."""

    total: Decimal
    earned: Decimal


@dataclass(frozen=True, slots=True)
class CoursePoints:
    """Points of every step of a version (earned is zero without a result)."""

    steps: dict[UUID, StepPoints]

    @property
    def total(self) -> Decimal:
        """Return the points of the whole course."""
        return sum_points(item.total for item in self.steps.values())

    @property
    def earned(self) -> Decimal:
        """Return the points the student has earned in the whole course."""
        return sum_points(item.earned for item in self.steps.values())


async def load_course_points(
    uow: LearningUnitOfWork,
    cache: RenderCache,
    version: LiveVersion,
    user_id: UUID | None,
) -> CoursePoints:
    """Return the points of every step of the version.

    With ``user_id`` the student's best score per test block counts as earned,
    capped at the block's points; without it nothing is earned.
    """
    steps = version.manifest.steps()
    renders = await load_rendered_many(uow, cache, [s.revision_id for s in steps])
    best = (
        await uow.attempts.best_scores(user_id, [s.step_id for s in steps])
        if user_id is not None
        else {}
    )
    cards = (
        await uow.states.cards_by_step(user_id, [s.step_id for s in steps])
        if user_id is not None
        else {}
    )
    result: dict[UUID, StepPoints] = {}
    for step in steps:
        render = renders.get(step.revision_id)
        blocks = render.test_points if render is not None else {}
        scored = render.scored_points if render is not None else {}
        step_cards = cards.get(step.step_id, {})
        result[step.step_id] = StepPoints(
            total=sum_points((*blocks.values(), *scored.values())),
            earned=sum_points(
                (
                    *(
                        earned_points(best.get((step.step_id, block_id)), total)
                        for block_id, total in blocks.items()
                    ),
                    *(
                        scored_earned_points(stored_result(step_cards, block_id), total)
                        for block_id, total in scored.items()
                    ),
                )
            ),
        )
    return CoursePoints(steps=result)
