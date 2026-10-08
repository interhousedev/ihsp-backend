"""Start an EMIS sync by hand (ADM-14)."""

from datetime import timedelta
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.marks.errors import (
    StudentNotFoundError,
    SyncAlreadyRunningError,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.contracts.academic import ScheduleQueries
from app.shared.notifications import AuditDraft
from app.shared.tasks import TaskKicker

STALE_RUN = timedelta(hours=3)


class RunManualSync:
    """Kicks one student's sync or a whole run on request of an administrator."""

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        schedule: ScheduleQueries,
        kicker: TaskKicker,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._schedule = schedule
        self._kicker = kicker
        self._clock = clock

    async def execute(self, actor: Actor, user_id: UUID | None = None) -> None:
        """Kick `academic.sync_student` for one student or `academic.sync_all`."""
        actor.require(Role.ADMIN)
        if user_id is not None:
            await self._one(actor, user_id)
            return
        await self._all(actor)

    async def _one(self, actor: Actor, user_id: UUID) -> None:
        if await self._schedule.get_student(user_id) is None:
            raise StudentNotFoundError(params={"user_id": str(user_id)})
        await self._audit(actor, user_id)
        await self._kicker.kick(
            "academic.sync_student", user_id=str(user_id), mode="profile"
        )

    async def _all(self, actor: Actor) -> None:
        async with self._uow_factory() as uow:
            cutoff = self._clock.now() - STALE_RUN
            if await uow.sync_runs.running_since(cutoff):
                raise SyncAlreadyRunningError()
        await self._audit(actor, None)
        await self._kicker.kick("academic.sync_all", slot="manual")

    async def _audit(self, actor: Actor, user_id: UUID | None) -> None:
        async with self._uow_factory() as uow:
            uow.audit(
                AuditDraft(
                    type="sync.manual_run",
                    actor_id=actor.user_id,
                    user_id=user_id,
                )
            )
            await uow.commit()
