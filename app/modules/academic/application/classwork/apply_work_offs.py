"""Applies the work-off part of an attendance save or toggle (WO-3, WO-4)."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.classwork.absence_notices import AbsenceNotices
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.work_off import (
    WorkOff,
    WorkOffChoice,
    WorkOffEntry,
    WorkOffMode,
    changed_students,
    notification_targets,
    plan_work_offs,
    referenced_template_ids,
)


class WorkOffApplier:
    """Writes work-offs next to the absent list and queues the student notices."""

    def __init__(self, notices: AbsenceNotices) -> None:
        """Store the notice builder."""
        self.notices = notices

    async def after_submit(
        self,
        uow: AttendanceUnitOfWork,
        lesson: Lesson,
        *,
        actor_id: UUID,
        absent: Sequence[UUID],
        version: int,
        mode: WorkOffMode,
        entries: Sequence[WorkOffEntry],
        common: WorkOffChoice | None,
        now: dt.datetime,
    ) -> None:
        """Plan and write the work-offs, drop stale ones, queue the notices."""
        absent_set = set(absent)
        templates = await uow.work_off_templates.get_many(
            referenced_template_ids(entries, common), actor_id
        )
        plan = plan_work_offs(
            mode, absent_set, entries, common, {t.id: t.text for t in templates}
        )
        existing = {w.student_id: w for w in await uow.work_offs.for_lesson(lesson.id)}
        await uow.work_offs.delete_unless_absent(lesson.id, absent_set)
        await uow.work_offs.delete_for_students(lesson.id, plan.deletes)
        saved: dict[UUID, WorkOff] = {
            sid: w for sid, w in existing.items() if sid in absent_set - plan.deletes
        }
        for student_id, resolved in plan.upserts.items():
            saved[student_id] = await uow.work_offs.upsert(
                lesson_id=lesson.id,
                student_id=student_id,
                assigned_by=actor_id,
                resolved=resolved,
                at=now,
            )
        targets = notification_targets(
            lesson.attendance_absent or (),
            absent_set,
            changed_students(existing, plan.upserts),
        )
        uow.notify(*await self.notices.drafts(lesson, targets, saved, version=version))

    async def after_toggle(
        self,
        uow: AttendanceUnitOfWork,
        lesson: Lesson,
        student_id: UUID,
        *,
        absent: bool,
        version: int,
    ) -> None:
        """Notify a newly absent student; drop the work-off of an un-marked one."""
        was_absent = student_id in (lesson.attendance_absent or ())
        if not absent:
            await uow.work_offs.delete_for_students(lesson.id, [student_id])
            return
        if was_absent:
            return
        uow.notify(
            *await self.notices.drafts(lesson, {student_id: False}, {}, version=version)
        )
