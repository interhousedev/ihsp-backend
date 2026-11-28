"""Edges of the level schemes: the course edit gate, the audit log, level-up events."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.engagement.service import (
    EngagementUowFactory,
    LevelHook,
)
from app.modules.lms.application.learning.step_context import staff_access
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.ports.coach import LmsEvents
from app.shared.actor import Actor
from app.shared.clock import Clock, to_local
from app.shared.notifications import AuditDraft


class CourseEditGate:
    """Course staff with `edit` (LMS admins always) may change a course scheme."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the factory."""
        self.uow_factory = uow_factory

    async def require_edit(self, actor: Actor, course_id: UUID) -> None:
        """Raise unless the actor may edit the course."""
        async with self.uow_factory() as uow:
            (await staff_access(uow, actor, course_id)).require("edit")


class AuditLevelEvents:
    """Writes level audit entries and level-up events to the audit log."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the factory."""
        self.uow_factory = uow_factory

    async def write(self, type: str, **metadata: Any) -> None:
        """Record an entry with the metadata."""
        actor_id = metadata.pop("actor_id", None)
        async with self.uow_factory() as uow:
            uow.audit(
                AuditDraft(
                    type=type,
                    actor_id=None if actor_id is None else UUID(str(actor_id)),
                    metadata=metadata,
                )
            )
            await uow.commit()

    async def publish(self, name: str, payload: dict[str, Any]) -> None:
        """Record a level-up."""
        await self.write(name, **payload)


class AwardCoachXp:
    """Gives the learner the XP of a resolved Coach session, then logs the event.

    The ledger row is keyed by the session id, so a repeat never pays twice.
    """

    def __init__(
        self,
        inner: LmsEvents,
        uow_factory: EngagementUowFactory,
        clock: Clock,
        levels: LevelHook,
    ) -> None:
        """Store collaborators."""
        self.inner = inner
        self.uow_factory = uow_factory
        self.clock = clock
        self.levels = levels

    async def publish(self, name: str, payload: dict[str, Any]) -> None:
        """Pay the XP of `lms.coach.session_closed`, then pass the event on."""
        await self.inner.publish(name, payload)
        xp = int(payload.get("xp", 0) or 0)
        if name != "lms.coach.session_closed" or xp <= 0:
            return
        user_id = UUID(str(payload["user_id"]))
        async with self.uow_factory() as uow:
            courses = await uow.engagement.course_of_steps(
                [UUID(str(payload["step_id"]))]
            )
            course_id = next(iter(courses.values()), None)
            added = await uow.engagement.add_xp(
                user_id,
                course_id,
                "coach",
                str(payload["session_id"]),
                xp,
                to_local(self.clock.now()).date(),
            )
            await uow.commit()
        if added:
            await self.levels.after_xp(user_id, {course_id})
