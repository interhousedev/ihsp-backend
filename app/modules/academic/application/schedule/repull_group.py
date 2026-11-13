"""Re-pull a group's EMIS data after the group got its EMIS id for the first time.

A group may exist for a while without an EMIS id (added by hand, students pending).
When the first student registers, the group is linked, and everything it holds from
EMIS is read afresh: the curriculum, the timetable (including the term's earlier
weeks) and, through their own sync jobs, every other member with a working EMIS link.
"""

from uuid import UUID

from app.modules.academic.application.curriculum.sync_group_curriculum import (
    SyncGroupCurriculum,
)
from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.run_student_sync import TASK_NAME
from app.modules.academic.application.schedule.student_sync_jobs import (
    StudentSyncJobs,
)
from app.modules.academic.application.schedule.sync_group_timetable import (
    SyncGroupTimetable,
)
from app.shared.clock import Clock
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisCredentialsMissing,
    EmisUnavailable,
)
from app.shared.contracts.identity import IdentityDirectory, UserStatus
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

_EMIS_ERRORS = (EmisAuthFailed, EmisCredentialsMissing, EmisUnavailable)


class RepullGroup:
    """Force the curriculum and the timetable, then sync the other members."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        curriculum: SyncGroupCurriculum,
        timetable: SyncGroupTimetable,
        identity: IdentityDirectory,
        jobs: StudentSyncJobs,
        kicker: TaskKicker,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._curriculum = curriculum
        self._timetable = timetable
        self._identity = identity
        self._jobs = jobs
        self._kicker = kicker
        self._clock = clock

    async def execute(self, *, group_id: UUID, user_id: UUID) -> str:
        """Re-pull through the registrant ``user_id``; return the timetable status.

        The members are queued even when EMIS fails for the group, as their own links
        may still work; the EMIS error is re-raised after that so the task is seen.
        """
        error: Exception | None = None
        status = "skipped"
        try:
            await self._curriculum.ensure(group_id, force=True)
            result = await self._timetable.execute(
                group_id=group_id,
                user_id=user_id,
                full_term=True,
                force_backfill=True,
            )
            status = result.status
        except _EMIS_ERRORS as exc:
            log.warning("group_repull_emis_failed", group_id=str(group_id))
            error = exc
        await self._sync_members(group_id, user_id)
        if error is not None:
            raise error
        return status

    async def _sync_members(self, group_id: UUID, registrant: UUID) -> None:
        """Queue a student sync for each other active member with a working link."""
        async with self._uow_factory() as uow:
            students = await uow.students.list_filtered(
                group_id=group_id, status="active"
            )
        ids = [s.user_id for s in students if s.user_id != registrant]
        users = await self._identity.get_users(ids) if ids else {}
        for member in ids:
            user = users.get(member)
            if (
                user is None
                or user.status != UserStatus.ACTIVE
                or user.emis_status != "active"
            ):
                continue
            _, queued = await self._jobs.request_refresh(member, self._clock.now())
            if not queued:
                continue
            try:
                await self._kicker.kick(TASK_NAME, user_id=str(member))
            except Exception:
                log.warning("group_repull_kick_failed", user_id=str(member))
