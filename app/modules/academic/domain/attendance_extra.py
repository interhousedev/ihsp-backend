"""Absences EMIS reported that the platform's own attendance does not show.

Reports count platform absences in SQL; this adds what EMIS knows on top, using the
frozen :func:`merged_absences` so a (subject, date) both sources know counts once.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.domain.attendance_merge import merged_absences


@dataclass(frozen=True, slots=True)
class EmisAbsentDate:
    """One EMIS absent date of a student and the platform absences of that day."""

    student_id: UUID
    group_id: UUID | None
    subject_id: UUID
    date: dt.date
    platform: int  # lessons of the subject that day the platform marked absent


def emis_extra(row: EmisAbsentDate) -> int:
    """Return the missed lessons EMIS adds on top of the platform for this date."""
    key = (row.subject_id, row.date)
    merged = merged_absences([key] * row.platform, [key])
    return merged[key] - row.platform


def extras_by_key(rows: Iterable[EmisAbsentDate], view: str) -> Mapping[str, int]:
    """Return the extra absences per report key of ``view``.

    Views without an EMIS counterpart (lesson, teacher) get nothing.
    """
    extras: dict[str, int] = defaultdict(int)
    for row in rows:
        extra = emis_extra(row)
        if extra == 0:
            continue
        if view == "student":
            extras[str(row.student_id)] += extra
        elif view == "subject":
            extras[str(row.subject_id)] += extra
        elif view == "day":
            extras[row.date.isoformat()] += extra
        elif view == "group" and row.group_id is not None:
            extras[str(row.group_id)] += extra
    return extras
