"""Builds the end-of-lesson prompt state for the bot (UF-BOT-08)."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.ports.draft_store import (
    AttendanceDraft,
    AttendanceDraftStore,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.domain.classwork.errors import LessonReassignedError
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.roster import Roster
from app.shared.clock import TASHKENT, Clock, local_today

MIN_DRAFT_TTL = 60


def draft_ttl_seconds(lesson: Lesson, now: dt.datetime) -> int:
    """Seconds until 23:59:59 Tashkent of the lesson's date (BOT-16)."""
    end = dt.datetime.combine(
        lesson.date + dt.timedelta(days=1), dt.time.min, tzinfo=TASHKENT
    )
    return max(MIN_DRAFT_TTL, int((end - now).total_seconds()))


def ensure_prompt_teacher(lesson: Lesson, teacher_id: UUID) -> None:
    """The prompt belongs to the lesson's current teacher (UF-BOT-08)."""
    if not lesson.is_taught_by(teacher_id):
        raise LessonReassignedError(params={"lesson_id": str(lesson.id)})


class PromptStateBuilder:
    """Combines the lesson, the roster and the server-side draft."""

    def __init__(
        self,
        clock: Clock,
        roster_loader: RosterLoader,
        drafts: AttendanceDraftStore,
    ) -> None:
        """Initialize the builder."""
        self.clock = clock
        self.roster_loader = roster_loader
        self.drafts = drafts

    async def roster_for(self, uow: AttendanceUnitOfWork, lesson: Lesson) -> Roster:
        """Load the roster of the lesson."""
        return await self.roster_loader.load(uow, lesson)

    def expired(self, lesson: Lesson) -> bool:
        """True once the lesson's day is over (Tashkent)."""
        return local_today(self.clock) > lesson.date

    def build(
        self,
        lesson: Lesson,
        roster: Roster,
        locale: str,
        draft: AttendanceDraft | None,
    ) -> dict[str, Any]:
        """Return the ``ClassworkCommands.prompt_state`` dict."""
        absent = set(draft.absent if draft else (lesson.attendance_absent or ()))
        unassigned = roster.unassigned_ids()
        return {
            "lesson": lesson.to_ref(locale),
            "roster": [
                {
                    "position": position,
                    "user_id": student.user_id,
                    "name": f"{student.last_name} {student.first_name}",
                    "group_name": student.group_name,
                    "subgroup_unset": student.user_id in unassigned,
                    "absent": student.user_id in absent,
                }
                for position, student in enumerate(roster.entries)
            ],
            "attendance_submitted": lesson.submitted,
            "attendance_version": (
                draft.base_version if draft else lesson.attendance_version
            ),
            "homework_text": lesson.homework_text,
            "expired": self.expired(lesson),
        }
