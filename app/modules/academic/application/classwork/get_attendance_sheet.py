"""Use case: open the attendance sheet of a lesson (STF-8, ACA-11)."""

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
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today


class GetAttendanceSheet:
    """Return the sheet for the lesson's teacher or Administration."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        clock: Clock,
        roster_loader: RosterLoader,
        sheets: AttendanceSheetBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.roster_loader = roster_loader
        self.sheets = sheets

    async def execute(self, lesson_id: UUID, actor: Actor) -> dict[str, Any]:
        """Build the ``AttendanceSheet`` JSON."""
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_lesson_staff(lesson, actor)
            roster = await self.roster_loader.load(uow, lesson)
            work_offs = await uow.work_offs.for_lesson(lesson_id)
            return await self.sheets.build(
                lesson, roster, actor, local_today(self.clock), work_offs=work_offs
            )
