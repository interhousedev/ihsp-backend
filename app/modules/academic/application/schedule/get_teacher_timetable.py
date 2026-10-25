"""A teacher's timetable for a student: every group of the teacher, no student data."""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.application.schedule.common import (
    caller_locale,
    today,
)
from app.modules.academic.application.schedule.date_range import resolve_range
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.domain.schedule.audience_display import group_label
from app.modules.academic.domain.schedule.errors import TeacherNotFoundError
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.modules.academic.domain.schedule.school_days import SCHOOL_DAYS
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


@dataclass(frozen=True, slots=True)
class TeacherSlot:
    """One lesson of a teacher. Nothing about students: only when, what, where."""

    id: UUID
    date: dt.date
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    subject_name: str
    room: str | None
    group: str | None
    mine: bool
    status: str
    lesson_id: UUID | None = None


def _slot(view: LessonView, student_keys: frozenset[str]) -> TeacherSlot:
    ref = view.ref
    mine = not student_keys.isdisjoint(ref.audience)
    return TeacherSlot(
        id=ref.id,
        date=ref.date,
        starts_at=ref.starts_at,
        ends_at=ref.ends_at,
        subject_id=ref.subject_id,
        subject_name=ref.subject_name,
        room=ref.room_name,
        group=group_label(ref.audience, view.audience_groups),
        mine=mine,
        status=ref.status,
        lesson_id=ref.id if mine and view.persisted else None,
    )


class GetTeacherTimetable:
    """The timetable of a teacher who teaches the student, across all their groups."""

    def __init__(
        self, reader: ScheduleReader, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.reader = reader
        self.identity = identity
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        teacher_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[TeacherSlot]:
        """Return the teacher's Monday-Friday lessons between two dates by start.

        Cancelled lessons stay, with their status. `mine` marks the lessons of the
        caller's own group or subgroup.

        Raises:
            TeacherNotFoundError: The teacher does not teach the student.
        """
        if not await self.reader.teaches_student(teacher_id, actor.user_id):
            raise TeacherNotFoundError(params={"teacher_id": str(teacher_id)})
        first, last = resolve_range(start, end, today(self.clock))
        locale = await caller_locale(self.identity, actor)
        keys = frozenset(await self.reader.student_keys(actor.user_id) or ())
        views = await self.reader.projected_for_teacher(teacher_id, first, last, locale)
        slots = [
            _slot(view, keys)
            for view in views
            if view.ref.date.isoweekday() in SCHOOL_DAYS
        ]
        slots.sort(key=lambda slot: (slot.starts_at, str(slot.id)))
        return slots
