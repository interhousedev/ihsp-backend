"""Excuses contract: is a student officially excused right now (provider: academic)."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExcuseStatus:
    """The student's excuse state at one moment."""

    student_id: UUID
    excused_now: bool
    excuse_id: UUID | None
    until: date | None
    in_lesson_time: bool  # a scheduled lesson of the student is running now
    curator_id: UUID | None
    group_id: UUID | None


class ExcuseStatusReader(Protocol):
    """Read access to the excuse state of a student."""

    async def status(self, student_id: UUID, at: datetime) -> ExcuseStatus:
        """Return the state at ``at`` (a student without a group has no curator)."""
        ...
