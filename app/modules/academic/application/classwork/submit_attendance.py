"""Use case: submit exactly who was absent from a lesson (ACA-11, UF-STF-06)."""

from collections.abc import Callable, Sequence
from typing import Any, Literal
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
from app.modules.academic.domain.classwork.attendance_rules import (
    build_snapshot,
    ensure_attendance_editable,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.notifications import AuditDraft

Source = Literal["bot", "staff", "admin"]


def effective_source(source: Source, lesson: Lesson, actor: Actor) -> Source:
    """Web edits by Administration of someone else's lesson are recorded as admin."""
    if (
        source == "staff"
        and actor.has(Role.ADMIN)
        and not lesson.is_taught_by(actor.user_id)
    ):
        return "admin"
    return source


class SubmitAttendance:
    """Check permission, window and version, then save the absent list."""

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
        actor: Actor,
        absent: Sequence[UUID],
        present_unassigned: Sequence[UUID] = (),
        base_version: int,
        source: Source,
    ) -> dict[str, Any]:
        """Save the list and return the new ``AttendanceSheet``.

        Raises:
            AttendanceConflictError: the version moved on; params hold the sheet.
        """
        today = local_today(self.clock)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            late = ensure_attendance_editable(lesson, actor, today, self.edit_days)
            roster = await self.roster_loader.load(uow, lesson)
            if base_version != lesson.attendance_version:
                sheet = await self.sheets.build(lesson, roster, actor, today)
                raise conflict_with(sheet)
            snapshot = build_snapshot(roster, absent, present_unassigned)
            version = await uow.lessons.save_attendance(
                lesson_id,
                base_version=base_version,
                roster=snapshot,
                absent=list(absent),
                source=effective_source(source, lesson, actor),
                by=actor.user_id,
                at=self.clock.now(),
            )
            if version is None:  # someone saved between our read and write
                fresh = await require_lesson(uow, lesson_id)
                sheet = await self.sheets.build(fresh, roster, actor, today)
                raise conflict_with(sheet)
            if late:
                uow.audit(
                    AuditDraft(
                        type="attendance.late_edit",
                        actor_id=actor.user_id,
                        metadata={"lesson_id": str(lesson_id), "version": version},
                    )
                )
            await uow.commit()
            fresh = await require_lesson(uow, lesson_id)
            return await self.sheets.build(fresh, roster, actor, today)
