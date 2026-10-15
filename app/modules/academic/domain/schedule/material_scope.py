"""Which lessons an admin EMIS materials pull touches (one subject, maybe a teacher)."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.schedule.lesson import Lesson

PullMode = Literal["full", "soft"]


@dataclass(frozen=True, slots=True)
class MaterialScope:
    """Lessons of ``subject_id`` (and ``teacher_id`` when set).

    ``full`` replaces the EMIS materials of those lessons; ``soft`` only fills the
    lessons that have no materials at all and never deletes anything.
    """

    subject_id: UUID
    teacher_id: UUID | None = None
    mode: PullMode = "full"

    @property
    def soft(self) -> bool:
        """Only fill empty lessons, delete nothing."""
        return self.mode == "soft"

    def matches(self, lesson: Lesson) -> bool:
        """Whether the pull touches the lesson."""
        if lesson.subject_id != self.subject_id:
            return False
        return self.teacher_id is None or lesson.teacher_id == self.teacher_id
