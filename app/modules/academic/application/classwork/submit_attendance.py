"""Use case: submit exactly who was absent from a lesson (ACA-11, UF-STF-06)."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal
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
from app.modules.academic.domain.classwork.attendance_rules import (
    build_snapshot,
    ensure_attendance_editable,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.work_off import (
    WorkOffChoice,
    WorkOffEntry,
    WorkOffMode,
    as_choice,
    as_entry,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today

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
    """Check permission and version, then save the absent list."""

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
        actor: Actor,
        absent: Sequence[UUID],
        late: Sequence[UUID] = (),
        present_unassigned: Sequence[UUID] = (),
        base_version: int,
        source: Source,
        work_off_mode: WorkOffMode = "per_student",
        work_offs: Sequence[WorkOffEntry | Mapping[str, Any]] = (),
        common_work_off: WorkOffChoice | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save the list and the work-offs (WO-3) and return the new sheet.

        Raises:
            AttendanceConflictError: the version moved on; params hold the sheet.
            WorkOffNotAbsentError: a work-off entry names a student who is present.
            WorkOffTextRequiredError: common mode without a template or text.
            WorkOffTemplateNotFoundError: a template is unknown or not the actor's.
        """
        today = local_today(self.clock)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_attendance_editable(lesson, actor)
            roster = await self.roster_loader.load(uow, lesson)
            if base_version != lesson.attendance_version:
                sheet = await self.sheets.build(lesson, roster, actor, today)
                raise conflict_with(sheet)
            snapshot = build_snapshot(roster, absent, present_unassigned, late)
            version = await uow.lessons.save_attendance(
                lesson_id,
                base_version=base_version,
                roster=snapshot,
                absent=list(absent),
                late=list(late),
                source=effective_source(source, lesson, actor),
                by=actor.user_id,
                at=self.clock.now(),
            )
            if version is None:  # someone saved between our read and write
                fresh = await require_lesson(uow, lesson_id)
                sheet = await self.sheets.build(fresh, roster, actor, today)
                raise conflict_with(sheet)
            await self.work_offs_after_save(
                uow,
                lesson,
                actor,
                absent,
                version,
                work_off_mode,
                [as_entry(w) for w in work_offs],
                as_choice(common_work_off),
            )
            await uow.commit()
            fresh = await require_lesson(uow, lesson_id)
            return await self.sheets.build(
                fresh,
                roster,
                actor,
                today,
                work_offs=await uow.work_offs.for_lesson(lesson_id),
            )

    async def work_offs_after_save(
        self,
        uow: AttendanceUnitOfWork,
        lesson: Lesson,
        actor: Actor,
        absent: Sequence[UUID],
        version: int,
        mode: WorkOffMode,
        entries: Sequence[WorkOffEntry],
        common: WorkOffChoice | None,
    ) -> None:
        """Write work-offs and notices in the same transaction as the list."""
        await self.work_offs.after_submit(
            uow,
            lesson,
            actor_id=actor.user_id,
            absent=absent,
            version=version,
            mode=mode,
            entries=entries,
            common=common,
            now=self.clock.now(),
        )
