"""Read models of work-offs: a task with its lesson, and statistics (WO-6, WO-8)."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.work_off import WorkOff

GroupBy = Literal["subject", "teacher", "group", "student"]
StatusFilter = Literal["open", "done", "all"]


@dataclass(frozen=True, slots=True)
class WorkOffView:
    """A work-off with the facts of its lesson and the student's group."""

    work_off: WorkOff
    lesson_date: dt.date
    period: int
    subject_names: dict[str, str]
    lesson_teacher_id: UUID | None
    group_id: UUID
    group_name: str

    def subject_name(self, locale: str) -> str:
        """Subject name in the locale with the usual fallback."""
        return localized(self.subject_names, locale)


@dataclass(frozen=True, slots=True)
class WorkOffFilter:
    """Filters of the administrator's list."""

    start: dt.date | None = None
    end: dt.date | None = None
    subject_id: UUID | None = None
    teacher_id: UUID | None = None
    group_id: UUID | None = None
    student_id: UUID | None = None
    status: StatusFilter = "all"


@dataclass(frozen=True, slots=True)
class StatRow:
    """Open and done counts for one key; ``label`` is None for people."""

    key: UUID
    label: str | None
    open_count: int
    done_count: int
