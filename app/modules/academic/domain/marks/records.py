"""Plain records of the marks module: stored marks and result snapshots."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.academic.domain.marks.diff import MarkKey


@dataclass(frozen=True, slots=True)
class StoredMark:
    """A mark row as stored, removed or not."""

    id: UUID
    key: MarkKey
    removed: bool
    lesson_id: UUID | None


@dataclass(frozen=True, slots=True)
class NewMark:
    """A mark about to be inserted."""

    student_id: UUID
    subject_id: UUID
    semester: int
    key: MarkKey
    lesson_id: UUID | None


@dataclass(frozen=True, slots=True)
class ResultSnapshot:
    """The current result of a subject (or the semester GPA when ``value`` only)."""

    value: Decimal | None
    lesson_avg: Decimal | None = None
    midterm_avg: Decimal | None = None
    final_avg: Decimal | None = None
    emis_rating: int | None = None
    marks_count: int = 0
    emis_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SyncRunRecord:
    """A sync run as stored."""

    id: UUID
    started_at: datetime
    finished_at: datetime | None
    status: str
    stats: dict[str, int]
