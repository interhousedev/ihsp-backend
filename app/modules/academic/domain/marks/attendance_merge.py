"""Merge EMIS attendance with the platform's lesson rosters; EMIS has priority.

Per lesson: a date EMIS marks absent is an absence whatever the roster says; other
lessons keep the roster's state. A subject total from EMIS replaces the absence count.
The source is ``emis`` when every counted value comes from EMIS, ``platform`` when
none does and ``mixed`` otherwise.
"""

import datetime as dt
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Literal

from app.modules.academic.domain.marks.read_models import AttendanceCount

AttendanceSource = Literal["emis", "platform", "mixed"]


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """The student's state on one lesson with submitted attendance."""

    date: dt.date
    absent: bool
    late: bool = False


@dataclass(frozen=True, slots=True)
class EmisAttendanceReport:
    """What EMIS reported for one subject and semester (None: not reported)."""

    absent_dates: frozenset[dt.date] | None = None
    absence_total: int | None = None

    @property
    def empty(self) -> bool:
        """Return True when EMIS reported nothing usable."""
        return self.absence_total is None and not self.absent_dates

    def within(
        self, start: dt.date | None, end: dt.date | None
    ) -> "EmisAttendanceReport":
        """Return the report with absent dates limited to start..end."""
        if self.absent_dates is None:
            return self
        dates = frozenset(
            d
            for d in self.absent_dates
            if (start is None or d >= start) and (end is None or d <= end)
        )
        return EmisAttendanceReport(dates, self.absence_total)


def merge_attendance(
    roster: Collection[RosterEntry], emis: EmisAttendanceReport | None
) -> AttendanceCount:
    """Return one subject's count: EMIS values first, the roster fills the gaps."""
    if emis is None or emis.empty:
        return _platform(roster)
    if emis.absence_total is not None:
        total = emis.absence_total
        lessons = max(len(roster), total)
        lates = sum(1 for e in roster if e.late and not e.absent)
        source: AttendanceSource = "emis" if len(roster) <= total else "mixed"
        return AttendanceCount(total, lessons, lates, source)
    dates = emis.absent_dates or frozenset()
    platform_only = [e for e in roster if e.date not in dates]
    covered = len(roster) - len(platform_only)  # lessons on EMIS absent dates
    unmatched = len(dates - {e.date for e in roster})  # EMIS-only absences
    absences = covered + unmatched + sum(1 for e in platform_only if e.absent)
    lessons = len(roster) + unmatched
    lates = sum(1 for e in platform_only if e.late and not e.absent)
    return AttendanceCount(
        absences, lessons, lates, "mixed" if platform_only else "emis"
    )


def combined_source(sources: Iterable[AttendanceSource]) -> AttendanceSource:
    """Return the source of a sum of counts."""
    seen = set(sources)
    if not seen:
        return "platform"
    if len(seen) == 1:
        return next(iter(seen))
    return "mixed"


def _platform(roster: Collection[RosterEntry]) -> AttendanceCount:
    return AttendanceCount(
        absences=sum(1 for e in roster if e.absent),
        with_attendance=len(roster),
        lates=sum(1 for e in roster if e.late and not e.absent),
    )
