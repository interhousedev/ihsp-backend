"""Use case: mark an absence as excused (ACA-20, UF-STF-11)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.attendance_sheet import (
    AttendanceSheetBuilder,
)
from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.domain.classwork.errors import (
    ExcuseNotAbsentError,
    NotCuratorError,
    StudentNotFoundError,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries

COMMENT_MAX = 500


class SetExcuse:
    """The curator of the student's group, or Administration, excuses an absence."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        clock: Clock,
        roster_loader: RosterLoader,
        sheets: AttendanceSheetBuilder,
        schedule: ScheduleQueries,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.roster_loader = roster_loader
        self.sheets = sheets
        self.schedule = schedule

    async def _curated(self, student_id: UUID, actor: Actor) -> set[UUID] | None:
        """Groups the actor curates, or None for Administration."""
        if actor.has(Role.ADMIN):
            return None
        student = await self.schedule.get_student(student_id)
        if student is None:
            raise StudentNotFoundError(params={"student_id": str(student_id)})
        groups = set(await self.schedule.curated_group_ids(actor.user_id))
        if student.group_id not in groups:
            raise NotCuratorError(params={"group_id": str(student.group_id)})
        return groups

    async def execute(
        self,
        *,
        lesson_id: UUID,
        student_id: UUID,
        excused: bool,
        comment: str | None,
        actor: Actor,
    ) -> dict[str, Any]:
        """Excuse or un-excuse and return the updated sheet."""
        curated = await self._curated(student_id, actor)
        text = (comment or "").strip()[:COMMENT_MAX] or None
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            if excused and student_id not in (lesson.attendance_absent or ()):
                raise ExcuseNotAbsentError(params={"student_id": str(student_id)})
            version = await uow.lessons.set_excuse(
                lesson_id,
                student_id=student_id,
                excused=excused,
                comment=text,
                by=actor.user_id,
                at=self.clock.now(),
            )
            if version is None:
                raise ExcuseNotAbsentError(params={"student_id": str(student_id)})
            await uow.commit()
            fresh = await require_lesson(uow, lesson_id)
            roster = await self.roster_loader.load(uow, fresh)
            return await self.sheets.build(
                fresh,
                roster,
                actor,
                local_today(self.clock),
                visible_groups=curated,
            )
