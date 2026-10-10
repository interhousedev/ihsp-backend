"""Which semester a group is in, from the semester dates of its curriculum."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class SemesterDates(Protocol):
    """A semester with its 1-based number and school dates (EmisSemesterDates too)."""

    @property
    def number(self) -> int:
        """The 1-based semester number."""
        ...

    @property
    def starts_on(self) -> dt.date:
        """The first day of the semester."""
        ...

    @property
    def ends_on(self) -> dt.date:
        """The last day of the semester."""
        ...


@dataclass(frozen=True, slots=True)
class SemesterTerm:
    """The academic year and half a semester is stored under as a term."""

    number: int
    academic_year: str
    half: int
    starts_on: dt.date
    ends_on: dt.date


# The school year starts in autumn: from August on a semester is the first half.
FIRST_HALF_MONTH = 8


def current_semester(semesters: Sequence[SemesterDates], today: dt.date) -> int | None:
    """Return the number of the semester that holds today.

    Between two semesters (or after the last one) it is the latest semester that
    has started; before the first one there is none.
    """
    holding = [s for s in semesters if s.starts_on <= today <= s.ends_on]
    if holding:
        return max(holding, key=lambda s: (s.starts_on, s.number)).number
    started = [s for s in semesters if s.starts_on < today]
    if started:
        return max(started, key=lambda s: (s.starts_on, s.number)).number
    return None


def term_for_semester(
    starts_on: dt.date, ends_on: dt.date, number: int
) -> SemesterTerm:
    """Name the term of a semester: "2025-2026" and half 1 (autumn) or 2 (spring)."""
    autumn = starts_on.month >= FIRST_HALF_MONTH
    first_year = starts_on.year if autumn else starts_on.year - 1
    return SemesterTerm(
        number=number,
        academic_year=f"{first_year}-{first_year + 1}",
        half=1 if autumn else 2,
        starts_on=starts_on,
        ends_on=ends_on,
    )
