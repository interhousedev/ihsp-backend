"""Sync everything of one student from EMIS: curriculum, terms, timetable, marks.

Kicked after a registration and by the settings button. The order matters: the
curriculum creates the terms, and the timetable sync gives up without a current term
(this used to happen on a fresh lyceum, where both tasks were kicked side by side).
Teachers the timetable names are found or created through the identity module.
"""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.curriculum.sync_group_curriculum import (
    SyncGroupCurriculum,
)
from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.student_sync_state import (
    SyncState,
    SyncStateStore,
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
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

_EMIS_ERRORS = (EmisAuthFailed, EmisCredentialsMissing, EmisUnavailable)


class SyncStudentAll:
    """Curriculum (and terms) first, then the group timetable, then the marks."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        curriculum: SyncGroupCurriculum,
        timetable: SyncGroupTimetable,
        state: SyncStateStore,
        kicker: TaskKicker,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._curriculum = curriculum
        self._timetable = timetable
        self._state = state
        self._kicker = kicker
        self._clock = clock

    async def execute(self, user_id: UUID, *, with_marks: bool) -> str:
        """Run the sync and record how it ended; return the timetable status."""
        previous = await self._state.get(user_id)
        requested = previous.requested_at if previous else self._clock.now()
        await self._state.put(user_id, SyncState("running", requested_at=requested))
        try:
            status = await self._run(user_id, with_marks=with_marks)
        except _EMIS_ERRORS:
            await self._finish(user_id, requested, "emis_unavailable")
            raise
        await self._finish(user_id, requested, status)
        return status

    async def _run(self, user_id: UUID, *, with_marks: bool) -> str:
        async with self._uow_factory() as uow:
            student = await uow.students.get(user_id)
        if student is None or student.status != "active":
            return "no_student"
        await self._ensure_curriculum(student.group_id)
        result = await self._timetable.execute(
            group_id=student.group_id, user_id=user_id
        )
        if with_marks:
            await self._kicker.kick(
                "academic.sync_student", user_id=str(user_id), mode="profile"
            )
        return result.status

    async def _ensure_curriculum(self, group_id: UUID) -> None:
        """A failure here is logged: a term made by Administration still works."""
        try:
            await self._curriculum.ensure(group_id)
        except _EMIS_ERRORS as exc:
            log.warning("student_sync_curriculum_failed", error=exc.support_details)

    async def _finish(self, user_id: UUID, requested: dt.datetime, detail: str) -> None:
        await self._state.put(
            user_id,
            SyncState(
                "done" if detail == "synced" else "failed",
                requested_at=requested,
                finished_at=self._clock.now(),
                detail=detail,
            ),
        )
