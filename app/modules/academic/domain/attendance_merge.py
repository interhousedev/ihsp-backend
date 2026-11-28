"""Merge the absences the platform recorded with those EMIS reported.

The platform marks attendance per lesson; EMIS reports absent dates per subject.
An absence both sources know about counts once: for every (subject, date) the
merged count is the larger of the two counts, so two missed lessons of one subject
on one day stay two, and an EMIS date that matches a platform absence adds nothing.
Every place that counts a student's absences (admin reports, the curator's view,
the overall student rating) must count them through :func:`merged_absences`.
"""

import datetime as dt
from collections import Counter
from collections.abc import Iterable
from uuid import UUID

AbsenceKey = tuple[UUID, dt.date]
"""(subject_id, date) of one missed lesson."""


def merged_absences(
    platform: Iterable[AbsenceKey], emis: Iterable[AbsenceKey]
) -> Counter[AbsenceKey]:
    """Return missed lessons per (subject, date), each absence counted once.

    ``platform`` holds one key per lesson the platform marked absent (repeat a key
    for several lessons of a subject on one day); ``emis`` holds the absent dates
    EMIS reported per subject (repeats are ignored: EMIS has no lesson number).
    """
    merged = Counter(platform)
    for key in set(emis):
        merged[key] = max(merged[key], 1)
    return merged


def merged_absence_count(
    platform: Iterable[AbsenceKey], emis: Iterable[AbsenceKey]
) -> int:
    """Return the number of missed lessons, each absence counted once."""
    return sum(merged_absences(platform, emis).values())
