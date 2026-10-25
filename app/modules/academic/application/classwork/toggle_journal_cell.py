"""Use case: toggle one student's absence from the journal grid (UF-STF-07)."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.apply_work_offs import WorkOffApplier
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


class ToggleJournalCell:
    """Mark or unmark one student with a single versioned statement."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        clock: Clock,
        roster_loader: RosterLoader,
        sheets: AttendanceSheetBuilder,
        work_offs: WorkOffApplier,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.roster_loader = roster_loader
        self.sheets = sheets
        self.work_offs = work_offs

    async def execute(
        self,
        *,
        lesson_id: UUID,
        student_id: UUID,
        absent: bool,
        late: bool = False,
        base_version: int,
        actor: Actor,
    ) -> int:
        """Toggle the cell and return the new ``attendance_version``.

        A newly absent student gets a ``lesson_absence`` notice; an un-marked
        student loses the work-off of this lesson (WO-3, WO-4).
        """
        today = local_today(self.clock)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_attendance_editable(lesson, actor)
            if absent and late:
                raise AbsentOutsideRosterError(params={"user_ids": [str(student_id)]})
            roster = await self.roster_loader.load(uow, lesson)
            expected, unassigned = roster.expected_ids(), roster.unassigned_ids()
            if student_id not in expected | unassigned:
                raise AbsentOutsideRosterError(params={"user_ids": [str(student_id)]})
            initial = [s.user_id for s in roster.expected]
            if (absent or late) and student_id in unassigned:
                initial.append(student_id)
            version = await uow.lessons.toggle_absent(
                lesson_id,
                student_id=student_id,
                absent=absent,
                late=late,
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
            await self.work_offs.after_toggle(
                uow, lesson, student_id, absent=absent, version=version
            )
            await uow.commit()
            return version
