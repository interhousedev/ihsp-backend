"""Collaborators of the Coach built on the learning unit of work.

The gate, the daily limiter, the reader of the learner's last attempt, the outbox
events and the solution-key editing of course staff.
"""

from dataclasses import dataclass
from datetime import datetime
from json import dumps
from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.step_context import (
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.coach import SolutionKey
from app.modules.lms.domain.learning.errors import (
    NotEnrolledError,
    StepNotFoundError,
)
from app.modules.lms.domain.learning.tutor_errors import (
    TutorDailyLimitError,
    TutorDisabledError,
)
from app.modules.lms.domain.step_content import TestBlock
from app.modules.lms.ports.coach import (
    AttemptSnapshot,
    CoachInsightRow,
    CoachInsights,
    SolutionKeyStore,
)
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock, local_today
from app.shared.limits import LimitsProvider
from app.shared.notifications import AuditDraft
from app.shared.rate_limit import RateLimiter

DAY_SECONDS = 86_400
ANSWER_CHARS = 500


class LearningCoachGate:
    """A learner may use the Coach where they may read the step."""

    def __init__(self, uow_factory: UowFactory, gate: AudienceGate) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.gate = gate

    async def require(self, actor: Actor, step_id: UUID) -> UUID:
        """Raise unless the actor may use the Coach; return the live revision id."""
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            course = context.course
            if await uow.enrollments.get(course.id, actor.user_id) is None:
                raise NotEnrolledError(params={"course_id": str(course.id)})
            if not course.tutor_enabled:
                raise TutorDisabledError(params={"course_id": str(course.id)})
            await self.gate.require_step(uow, actor, course.id, step_id)
            return context.live_step.revision_id


class DailyCoachLimiter:
    """The daily cap of the Coach shares the tutor's per-student limit."""

    def __init__(
        self, limits: LimitsProvider, limiter: RateLimiter, clock: Clock
    ) -> None:
        """Store collaborators."""
        self.limits = limits
        self.limiter = limiter
        self.clock = clock

    async def hit(self, actor: Actor) -> None:
        """Count one model call; raise TutorDailyLimitError over the cap."""
        limit = (await self.limits.for_actor(actor)).ai_lms_tutor_per_day_student
        if limit is None:
            return
        key = f"lms_coach:{actor.user_id}:{local_today(self.clock).isoformat()}"
        try:
            await self.limiter.hit(key, limit=limit, window_seconds=DAY_SECONDS)
        except RateLimitedError as error:
            raise TutorDailyLimitError(params=error.params) from error


class AttemptsOfLearner:
    """Reads the learner's last attempt at a block of a step."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the factory."""
        self.uow_factory = uow_factory

    async def last_attempt(
        self, user_id: UUID, step_id: UUID, block_id: str | None
    ) -> AttemptSnapshot:
        """Return the snapshot (made 0 when the learner has not tried)."""
        async with self.uow_factory() as uow:
            attempts = [
                a
                for a in await uow.attempts.list_for_step(user_id, step_id)
                if a.is_submitted and (block_id is None or a.block_id == block_id)
            ]
            if not attempts:
                return AttemptSnapshot(0, None, False, None)
            last = attempts[-1]
            revision = await uow.revisions.get(last.revision_id)
        limit: int | None = None
        if revision is not None:
            for block in revision.content.blocks:
                if isinstance(block, TestBlock) and block.id == last.block_id:
                    limit = block.config.max_attempts
        made = len([a for a in attempts if a.block_id == last.block_id])
        left = None if limit is None else max(limit - made, 0)
        answer = dumps(last.answers, ensure_ascii=False)[:ANSWER_CHARS]
        return AttemptSnapshot(made, left, last.passed is False, answer)


class AuditCoachEvents:
    """Coach events of the lms are written to the audit log in one transaction."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the factory."""
        self.uow_factory = uow_factory

    async def publish(self, name: str, payload: dict[str, object]) -> None:
        """Queue an event for the log."""
        async with self.uow_factory() as uow:
            uow.audit(AuditDraft(type=name, metadata=dict(payload)))
            await uow.commit()


@dataclass(frozen=True, slots=True)
class SolutionKeyList:
    """The keys of one step revision."""

    keys: list[SolutionKey]


class SolutionKeys:
    """Read and replace the solution keys of a live step (course staff)."""

    def __init__(self, uow_factory: UowFactory, store: SolutionKeyStore) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.store = store

    async def read(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> SolutionKeyList:
        """Return the keys of the live revision (needs `edit`)."""
        revision_id = await self._revision(actor, course_id, step_id)
        return SolutionKeyList(await self.store.for_revision(revision_id))

    async def replace(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        keys: list[SolutionKey],
    ) -> SolutionKeyList:
        """Replace the keys of the live revision (needs `edit`)."""
        revision_id = await self._revision(actor, course_id, step_id)
        await self.store.replace(revision_id, keys)
        return SolutionKeyList(keys)

    async def _revision(self, actor: Actor, course_id: UUID, step_id: UUID) -> UUID:
        async with self.uow_factory() as uow:
            (await staff_access(uow, actor, course_id)).require("edit")
            context = await load_live_step(uow, step_id)
            if context.course.id != course_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            return context.live_step.revision_id


class CoachInsightsReport:
    """Sessions of a course by step (course staff with `review`)."""

    def __init__(self, uow_factory: UowFactory, insights: CoachInsights) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.insights = insights

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        start: datetime | None,
        end: datetime | None,
    ) -> list[CoachInsightRow]:
        """Return one row per step with sessions in the period."""
        async with self.uow_factory() as uow:
            (await staff_access(uow, actor, course_id)).require("review")
        return await self.insights.for_course(course_id, start, end)
