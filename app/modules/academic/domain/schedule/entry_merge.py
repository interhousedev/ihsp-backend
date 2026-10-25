"""Joining a group to an existing timetable entry as one merged lesson (ACA-6)."""

from collections.abc import Iterable

from app.modules.academic.domain.schedule.conflicts import (
    audiences_overlap,
    entry_conflicts,
)
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry


def merge_target(
    candidate: TimetableEntry, others: Iterable[TimetableEntry]
) -> TimetableEntry | None:
    """Return the entry the candidate can join, or None.

    One lesson taught to several groups shows up in each group's EMIS timetable, so
    the second group clashes with the first on teacher and room. That is a merged
    lesson, not a conflict, when exactly one entry clashes, it is the same lesson
    (subject, teacher, room, week parity, validity) and its audience is other groups.
    """
    clashing = [o for o in others if entry_conflicts(candidate, [o])]
    if len(clashing) != 1:
        return None
    other = clashing[0]
    same_lesson = (
        other.subject_id,
        other.teacher_id,
        other.room_id,
        other.week_parity,
        other.valid_from,
        other.valid_to,
    ) == (
        candidate.subject_id,
        candidate.teacher_id,
        candidate.room_id,
        candidate.week_parity,
        candidate.valid_from,
        candidate.valid_to,
    )
    if same_lesson and not audiences_overlap(candidate.audience, other.audience):
        return other
    return None
