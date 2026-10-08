"""ACA-6: one lesson taught to several groups is a merged entry, not a conflict."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.entry_merge import merge_target
from app.modules.academic.domain.schedule.timetable_entry import (
    TimetableEntry,
    WeekParity,
)
from app.shared.ids import new_id

GROUP_A = new_id()
GROUP_B = new_id()
SUBJECT = new_id()
TEACHER = new_id()
ROOM = new_id()


def entry(
    group: UUID,
    *,
    subject: UUID = SUBJECT,
    teacher: UUID | None = TEACHER,
    room: UUID | None = ROOM,
    subgroup: int | None = None,
    parity: WeekParity = "every",
) -> TimetableEntry:
    return TimetableEntry(
        id=new_id(),
        term_id=UUID(int=1),
        weekday=2,
        period=3,
        week_parity=parity,
        subject_id=subject,
        teacher_id=teacher,
        room_id=room,
        audience=[audience_keys.key(group, subgroup)],
        valid_from=dt.date(2026, 9, 1),
    )


def test_the_same_lesson_of_another_group_joins_the_existing_entry() -> None:
    """ACA-6: same subject, teacher and room at one time."""
    first = entry(GROUP_A)

    assert merge_target(entry(GROUP_B), [first]) is first


def test_another_subject_is_a_real_conflict() -> None:
    """ACA-8: the teacher cannot teach two subjects at once."""
    first = entry(GROUP_A)

    assert merge_target(entry(GROUP_B, subject=new_id()), [first]) is None


def test_the_same_group_twice_is_a_duplicate_not_a_merge() -> None:
    """ACA-8: a repeated row of one group's own timetable is skipped."""
    first = entry(GROUP_A)

    assert merge_target(entry(GROUP_A), [first]) is None


def test_two_clashing_entries_are_not_merged() -> None:
    """ACA-8: the candidate would have to join two lessons at once."""
    teacher_lesson = entry(GROUP_A, room=new_id())
    room_lesson = entry(new_id(), teacher=new_id())

    assert merge_target(entry(GROUP_B), [teacher_lesson, room_lesson]) is None


def test_odd_and_even_weeks_do_not_merge_into_each_other() -> None:
    """ACA-5: the parity must be the same for one lesson."""
    odd = entry(GROUP_A, parity="odd")

    assert merge_target(entry(GROUP_B, parity="even"), [odd]) is None


def test_no_clash_means_no_merge_target() -> None:
    """ACA-8: an entry that fits needs no merging."""
    other = entry(GROUP_A, teacher=new_id(), room=new_id())

    assert merge_target(entry(GROUP_B), [other]) is None
