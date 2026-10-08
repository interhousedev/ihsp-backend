"""The lesson as classwork sees it: content, homework and attendance."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.domain.classwork.names import localized
from app.shared.contracts.academic import LessonRef


@dataclass(slots=True)
class Lesson:
    """One lesson row with the names needed to show it."""

    id: UUID
    term_id: UUID
    date: dt.date
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    subject_names: dict[str, str]
    subject_short: str | None
    teacher_id: UUID | None
    room_id: UUID | None
    room_slug: str | None
    room_name: str | None
    room_pin: str | None
    audience: tuple[str, ...]
    groups: dict[UUID, str]  # group id -> name, in audience order
    status: Literal["scheduled", "cancelled"]
    topic: str | None
    is_overridden: bool
    changes: dict[str, Any] | None
    homework_text: str | None
    homework_due_date: dt.date | None
    homework_due_auto: bool
    homework_updated_at: dt.datetime | None
    attendance_roster: tuple[UUID, ...] | None
    attendance_absent: tuple[UUID, ...] | None
    # {student_id: {"by": ..., "at": ..., "comment": ...}}, a subset of absent
    attendance_excused: dict[str, dict[str, Any]] | None
    attendance_version: int
    attendance_by: UUID | None
    attendance_at: dt.datetime | None
    attendance_source: str | None

    @property
    def group_names(self) -> tuple[str, ...]:
        """Names of the groups in the audience."""
        return tuple(self.groups.values())

    @property
    def submitted(self) -> bool:
        """True once the teacher saved a list ("not submitted" != "all present")."""
        return self.attendance_absent is not None

    @property
    def scheduled(self) -> bool:
        """True unless the lesson was cancelled."""
        return self.status == "scheduled"

    @property
    def has_homework(self) -> bool:
        """True if the lesson has homework text."""
        return self.homework_text is not None

    def is_taught_by(self, user_id: UUID) -> bool:
        """True if the user is the lesson's teacher."""
        return self.teacher_id is not None and self.teacher_id == user_id

    def subject_name(self, locale: str) -> str:
        """Subject name in the locale with the uz, ru, en fallback."""
        return localized(self.subject_names, locale)

    def excused_ids(self) -> set[str]:
        """Student ids (as text) whose absence is excused."""
        return set(self.attendance_excused or {})

    def to_ref(self, locale: str) -> LessonRef:
        """Return the cross-module view of the lesson."""
        return LessonRef(
            id=self.id,
            date=self.date,
            period=self.period,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            subject_id=self.subject_id,
            subject_name=self.subject_name(locale),
            teacher_id=self.teacher_id,
            room_id=self.room_id,
            room_slug=self.room_slug,
            room_name=self.room_name,
            audience=self.audience,
            group_names=self.group_names,
            status=self.status,
            topic=self.topic,
            homework_text=self.homework_text,
            homework_due_date=self.homework_due_date,
        )
