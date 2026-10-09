"""Weekly timetable entries (ACA-5, ACA-6)."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.schedule.errors import EntryInvalidError

WeekParity = Literal["every", "odd", "even"]
EntrySource = Literal["manual", "emis"]
WEEKDAYS = (1, 2, 3, 4, 5, 6)


@dataclass(slots=True)
class TimetableEntry:
    """One cell of the weekly timetable of a term."""

    id: UUID
    term_id: UUID
    weekday: int
    period: int
    week_parity: WeekParity
    subject_id: UUID
    teacher_id: UUID | None
    room_id: UUID | None
    audience: list[str] = field(default_factory=list)
    valid_from: dt.date = dt.date.min
    valid_to: dt.date | None = None
    source: EntrySource = "manual"  # "emis": made by an EMIS import, EMIS decides

    def valid_on(self, day: dt.date) -> bool:
        """Return True if the entry applies on the date."""
        return self.valid_from <= day and (
            self.valid_to is None or day <= self.valid_to
        )


def validate_entry(entry: TimetableEntry) -> None:
    """Check ranges and that the entry has an audience."""
    if entry.weekday not in WEEKDAYS or entry.period < 1:
        raise EntryInvalidError(params={"reason": "slot"})
    if not entry.audience:
        raise EntryInvalidError(params={"reason": "audience"})
    if entry.valid_to is not None and entry.valid_to < entry.valid_from:
        raise EntryInvalidError(params={"reason": "validity"})
