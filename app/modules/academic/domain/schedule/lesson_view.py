"""Read model of a lesson with names, used by queries and HTTP lists."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.shared.contracts.academic import LessonRef


@dataclass(frozen=True, slots=True)
class LessonView:
    """A LessonRef plus what the web needs to draw a LessonItem."""

    ref: LessonRef
    subject_short: str | None
    is_overridden: bool
    changes: dict[str, Any] | None
    attendance_submitted: bool
    absent_count: int | None = None
    late_count: int | None = None
    term_id: UUID | None = None
    audience_groups: dict[UUID, str] = field(default_factory=dict)
    persisted: bool = True

    @property
    def has_homework(self) -> bool:
        """Return True if the teacher set homework."""
        return self.ref.homework_text is not None
