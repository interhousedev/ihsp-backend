"""Lessons as the schedule sees them (ACA-7)."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from app.shared.lesson_kind import LessonKind

LessonStatus = Literal["scheduled", "cancelled"]


@dataclass(slots=True)
class Lesson:
    """A lesson row without attendance and homework details.

    ``has_content`` is True when homework, attendance, a topic or marks exist, so
    the lesson must be cancelled instead of deleted.
    """

    id: UUID
    term_id: UUID
    date: dt.date
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    teacher_id: UUID | None
    room_id: UUID | None
    audience: list[str] = field(default_factory=list)
    status: LessonStatus = "scheduled"
    is_overridden: bool = False
    timetable_entry_id: UUID | None = None
    origin_date: dt.date | None = None
    topic: str | None = None
    changes: dict[str, Any] | None = None
    has_content: bool = False
    kind: LessonKind = "other"
    # The EMIS class this lesson mirrors; None for hand-made or hand-edited lessons.
    emis_class_id: int | None = None
    # The topic EMIS last sent; ``topic`` follows it until a teacher writes their own.
    emis_topic: str | None = None

    def starts_after(self, now: dt.datetime) -> bool:
        """Return True if the lesson has not started yet."""
        return self.starts_at > now
