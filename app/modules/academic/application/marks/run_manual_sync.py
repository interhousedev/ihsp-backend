"""Start an EMIS sync by hand (ADM-14)."""

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.marks.errors import (
    StudentNotFoundError,
    SubjectNotFoundError,
    SyncAlreadyRunningError,
)
from app.modules.academic.domain.schedule.material_scope import PullMode
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

    async def resync_materials(
        self,
        actor: Actor,
        terms: Sequence[tuple[str, int]],
        *,
        job_id: str | None = None,
    ) -> None:
        """Kick `academic.resync_materials` for the terms (academic year, half).

        ``job_id`` is the queued job admins see in the process list (optional).
        """
        actor.require(Role.ADMIN)
        chosen = sorted(set(terms))
        async with self._uow_factory() as uow:
            uow.audit(
                AuditDraft(
                    type="sync.materials_resync",
                    actor_id=actor.user_id,
                    metadata={"terms": [f"{year}/{half}" for year, half in chosen]},
                )
            )
            await uow.commit()
        await self._kicker.kick(
            "academic.resync_materials",
            terms=[[year, half] for year, half in chosen],
            **({"job_id": job_id} if job_id else {}),
        )

    async def pull_subject(
        self,
        actor: Actor,
        subject_id: UUID,
        *,
        mode: PullMode = "full",
        teacher_id: UUID | None = None,
        group_id: UUID | None = None,
        terms: Sequence[tuple[str, int]] | None = None,
        job_id: str | None = None,
    ) -> None:
        """Kick `academic.pull_subject_materials`; ``terms`` None = current term."""
        actor.require(Role.ADMIN)
        if await self._schedule.subject_title(subject_id) is None:
            raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
        chosen = None if terms is None else sorted(set(terms))
        async with self._uow_factory() as uow:
            uow.audit(
                AuditDraft(
                    type="sync.subject_materials_pull",
                    actor_id=actor.user_id,
                    metadata={
                        "subject_id": str(subject_id),
                        "mode": mode,
                        "teacher_id": str(teacher_id) if teacher_id else None,
                        "group_id": str(group_id) if group_id else None,
                        "terms": (
                            None
                            if chosen is None
                            else [f"{year}/{half}" for year, half in chosen]
                        ),
                    },
                )
            )
            await uow.commit()
        await self._kicker.kick(
            "academic.pull_subject_materials",
            subject_id=str(subject_id),
            mode=mode,
            teacher_id=str(teacher_id) if teacher_id else None,
            group_id=str(group_id) if group_id else None,
            terms=None if chosen is None else [[year, half] for year, half in chosen],
            **({"job_id": job_id} if job_id else {}),
        )

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
