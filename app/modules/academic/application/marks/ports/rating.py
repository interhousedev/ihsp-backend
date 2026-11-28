"""Port: the inputs of the overall student rating."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.attendance_merge import AbsenceKey


@dataclass(frozen=True, slots=True)
class AcademicYear:
    """An academic year: its label and the span of its terms."""

    label: str
    starts_on: dt.date
    ends_on: dt.date


@dataclass(frozen=True, slots=True)
class StudentYearFacts:
    """One rated student's marks, absences and work-offs in the year."""

    student_id: UUID
    group_name: str
    mark_sum: int
    mark_count: int
    platform_absences: Sequence[AbsenceKey]
    emis_absences: Sequence[AbsenceKey]
    work_offs: int


class RatingSource(Protocol):
    """Read the academic facts of the rating."""

    async def academic_year(self, today: dt.date) -> AcademicYear | None:
        """Return the year of the term containing today.

        Falls back to the latest started term, else the first; None when no term
        exists.
        """
        ...

    async def year_facts(self, start: dt.date, end: dt.date) -> list[StudentYearFacts]:
        """Facts of every active student of an active, visible group.

        Marks are lesson marks (not controls); platform absences repeat a key per
        missed lesson; EMIS absences are its absent dates within the span.
        """
        ...
