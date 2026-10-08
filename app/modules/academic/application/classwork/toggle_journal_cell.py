"""Use case: toggle one student's absence from the journal grid (UF-STF-07)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.attendance_sheet import (
    AttendanceSheetBuilder,
)
from app.modules.academic.application.classwork.lookup import (
    conflict_with,
    require_lesson,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.application.classwork.submit_attendance import (
    effective_source,
)
from app.modules.academic.domain.classwork.attendance_rules import (
    ensure_attendance_editable,
)
from app.modules.academic.domain.classwork.errors import AbsentOutsideRosterError
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.notifications import AuditDraft


class ToggleJournalCell:
    """Mark or unmark one student with a single versioned statement."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        clock: Clock,
        roster_loader: RosterLoader,
        sheets: AttendanceSheetBuilder,
        edit_days: int,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.roster_loader = roster_loader
        self.sheets = sheets
        self.edit_days = edit_days

    async def execute(
        self,
        *,
        lesson_id: UUID,
        student_id: UUID,
        absent: bool,
        base_version: int,
        actor: Actor,
    ) -> int:
        """Toggle the cell and return the new ``attendance_version``."""
        today = local_today(self.clock)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            late = ensure_attendance_editable(lesson, actor, today, self.edit_days)
            roster = await self.roster_loader.load(uow, lesson)
            expected, unassigned = roster.expected_ids(), roster.unassigned_ids()
            if student_id not in expected | unassigned:
                raise AbsentOutsideRosterError(params={"user_ids": [str(student_id)]})
            initial = [s.user_id for s in roster.expected]
            if absent and student_id in unassigned:
                initial.append(student_id)
            version = await uow.lessons.toggle_absent(
                lesson_id,
                student_id=student_id,
                absent=absent,
                base_version=base_version,
                initial_roster=initial,
                source=effective_source("staff", lesson, actor),
                by=actor.user_id,
                at=self.clock.now(),
            )
            if version is None:
                fresh = await require_lesson(uow, lesson_id)
                raise conflict_with(
                    await self.sheets.build(fresh, roster, actor, today)
                )
            if late:
                uow.audit(
                    AuditDraft(
                        type="attendance.late_edit",
                        actor_id=actor.user_id,
                        metadata={"lesson_id": str(lesson_id), "version": version},
                    )
                )
            await uow.commit()
            return version
