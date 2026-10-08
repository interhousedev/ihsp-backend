"""Conflict detection for timetable entries and lessons (ACA-8)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.conflicts import (
    LessonSlot,
    audiences_overlap,
    entry_conflicts,
    lesson_conflicts,
    parities_overlap,
    validity_overlaps,
)
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.ids import new_id

import pytest

TERM = new_id()
GROUP_A = new_id()
GROUP_B = new_id()
TEACHER = new_id()
OTHER_TEACHER = new_id()
ROOM = new_id()
TERM_FROM = dt.date(2026, 9, 1)
OTHER_ROOM = new_id()


def entry(
    *,
    audience: list[str] | None = None,
    teacher: UUID | None = None,
    room: UUID | None = None,
    parity: str = "every",
    weekday: int = 1,
    period: int = 2,
    term: UUID = TERM,
    valid_from: dt.date = TERM_FROM,
    valid_to: dt.date | None = None,
) -> TimetableEntry:
    """A timetable entry with test defaults."""
    return TimetableEntry(
        id=new_id(),
        term_id=term,
        weekday=weekday,
        period=period,
        week_parity=parity,  # type: ignore[arg-type]
        subject_id=new_id(),
        teacher_id=teacher,
        room_id=room,
        audience=(
            audience if audience is not None else [audience_keys.key(GROUP_A, None)]
        ),
        valid_from=valid_from,
        valid_to=valid_to,
    )


def kinds(candidate: TimetableEntry, other: TimetableEntry) -> list[str]:
    """Return the kinds of conflict between two entries."""
    return [c.kind for c in entry_conflicts(candidate, [other])]


def whole(group: UUID) -> list[str]:
    """Audience of a whole group."""
    return [audience_keys.key(group, None)]


def sub(group: UUID, number: int) -> list[str]:
    """Audience of one subgroup."""
    return [audience_keys.key(group, number)]


def test_the_same_teacher_in_the_same_slot_conflicts() -> None:
    """ACA-8: a teacher cannot be in two places."""
    first = entry(teacher=TEACHER, audience=whole(GROUP_A))
    second = entry(teacher=TEACHER, audience=whole(GROUP_B))

    assert kinds(first, second) == ["teacher"]


def test_the_same_room_in_the_same_slot_conflicts() -> None:
    """ACA-8: a room hosts one lesson at a time."""
    first = entry(room=ROOM, audience=whole(GROUP_A))
    second = entry(room=ROOM, audience=whole(GROUP_B))

    assert kinds(first, second) == ["room"]


def test_the_same_group_in_the_same_slot_conflicts() -> None:
    """ACA-8: a group has one lesson at a time."""
    first = entry(teacher=TEACHER, room=ROOM)
    second = entry(teacher=OTHER_TEACHER, room=OTHER_ROOM)

    assert kinds(first, second) == ["audience"]


def test_one_pair_can_conflict_in_several_ways() -> None:
    """ACA-8: every clash is reported, not only the first."""
    first = entry(teacher=TEACHER, room=ROOM)
    second = entry(teacher=TEACHER, room=ROOM)

    assert kinds(first, second) == ["teacher", "room", "audience"]


def test_odd_and_even_weeks_do_not_conflict() -> None:
    """ACA-5: alternating weeks can share a slot."""
    odd = entry(teacher=TEACHER, parity="odd")
    even = entry(teacher=TEACHER, parity="even")

    assert entry_conflicts(odd, [even]) == []


@pytest.mark.parametrize("parity", ["odd", "even"])
def test_every_week_conflicts_with_an_alternating_week(parity: str) -> None:
    """ACA-5: 'every' overlaps both parities."""
    every = entry(teacher=TEACHER, parity="every")
    other = entry(teacher=TEACHER, parity=parity)

    assert kinds(every, other) == ["teacher", "audience"]


def test_a_whole_group_conflicts_with_its_subgroup() -> None:
    """ACA-6: the whole group includes both subgroups."""
    group = entry(audience=whole(GROUP_A))
    subgroup = entry(audience=sub(GROUP_A, 1))

    assert kinds(group, subgroup) == ["audience"]
    assert kinds(subgroup, group) == ["audience"]


def test_subgroup_one_and_subgroup_two_do_not_conflict() -> None:
    """ACA-2: the two halves of a group can have different lessons."""
    first = entry(audience=sub(GROUP_A, 1))
    second = entry(audience=sub(GROUP_A, 2))

    assert entry_conflicts(first, [second]) == []


def test_a_merged_audience_conflicts_when_any_key_is_shared() -> None:
    """ACA-6: 2TN1/2 + 2TN2/2 clashes with 2TN2 as a whole."""
    merged = entry(audience=[*sub(GROUP_A, 2), *sub(GROUP_B, 2)])
    group_b = entry(audience=whole(GROUP_B))

    assert kinds(merged, group_b) == ["audience"]


def test_subgroups_of_different_groups_do_not_conflict() -> None:
    """ACA-6: subgroup numbers only compare inside one group."""
    first = entry(audience=sub(GROUP_A, 1))
    second = entry(audience=sub(GROUP_B, 1))

    assert entry_conflicts(first, [second]) == []


def test_different_terms_do_not_conflict() -> None:
    """ACA-8: only entries of the same term clash."""
    first = entry(teacher=TEACHER)
    second = entry(teacher=TEACHER, term=new_id())

    assert entry_conflicts(first, [second]) == []


@pytest.mark.parametrize("other", [{"weekday": 2}, {"period": 3}])
def test_a_different_slot_does_not_conflict(other: dict[str, int]) -> None:
    """ACA-8: weekday and period must both match."""
    first = entry(teacher=TEACHER)
    second = entry(teacher=TEACHER, **other)  # type: ignore[arg-type]

    assert entry_conflicts(first, [second]) == []


def test_entries_valid_in_different_periods_of_time_do_not_conflict() -> None:
    """ACA-5: a replaced entry and its replacement share the slot in turn."""
    old = entry(teacher=TEACHER, valid_to=dt.date(2026, 10, 31))
    new = entry(teacher=TEACHER, valid_from=dt.date(2026, 11, 1))

    assert entry_conflicts(old, [new]) == []


def test_an_entry_does_not_conflict_with_itself() -> None:
    """Editing an entry must ignore its stored version."""
    stored = entry(teacher=TEACHER)

    assert entry_conflicts(stored, [stored]) == []


def test_an_entry_without_teacher_or_room_cannot_clash_on_them() -> None:
    """ACA-7: 'teacher needed' entries do not conflict with each other."""
    first = entry(audience=whole(GROUP_A))
    second = entry(audience=whole(GROUP_B))

    assert entry_conflicts(first, [second]) == []


def test_conflicts_serialize_to_the_api_shape() -> None:
    """API: Conflict = {kind, with_entry_id, with_lesson_id, description}."""
    other = entry(teacher=TEACHER)
    found = entry_conflicts(entry(teacher=TEACHER, audience=whole(GROUP_B)), [other])

    assert found[0].to_json() == {
        "kind": "teacher",
        "with_entry_id": str(other.id),
        "with_lesson_id": None,
        "description": found[0].description,
    }


def test_parities_overlap_table() -> None:
    """ACA-5: every overlaps all; odd and even only themselves."""
    assert parities_overlap("every", "odd")
    assert parities_overlap("even", "every")
    assert parities_overlap("odd", "odd")
    assert not parities_overlap("odd", "even")


def test_validity_ranges_with_an_open_end() -> None:
    """ACA-5: valid_to None means "until the end"."""
    assert validity_overlaps(dt.date(2026, 9, 1), None, dt.date(2027, 1, 1), None)
    assert not validity_overlaps(
        dt.date(2026, 9, 1), dt.date(2026, 9, 30), dt.date(2026, 10, 1), None
    )


def test_audiences_overlap_on_the_same_key() -> None:
    """ACA-6: identical keys overlap."""
    assert audiences_overlap(sub(GROUP_A, 1), sub(GROUP_A, 1))


def lesson(
    starts: dt.datetime, *, teacher: UUID | None = None, room: UUID | None = None
) -> Lesson:
    """A scheduled 45-minute lesson."""
    return Lesson(
        id=new_id(),
        term_id=TERM,
        date=starts.date(),
        period=1,
        starts_at=starts,
        ends_at=starts + dt.timedelta(minutes=45),
        subject_id=new_id(),
        teacher_id=teacher,
        room_id=room,
        audience=whole(GROUP_A),
    )


def test_a_lesson_overlapping_in_time_with_the_same_teacher_conflicts() -> None:
    """ACA-8: extra lessons are checked against existing ones."""
    start = dt.datetime(2026, 10, 7, 4, 0, tzinfo=dt.UTC)
    existing = lesson(start, teacher=TEACHER)
    candidate = LessonSlot(
        new_id(),
        start + dt.timedelta(minutes=30),
        start + dt.timedelta(minutes=75),
        TEACHER,
        None,
        whole(GROUP_B),
    )

    assert [c.kind for c in lesson_conflicts(candidate, [existing])] == ["teacher"]
    assert lesson_conflicts(candidate, [existing])[0].with_lesson_id == existing.id


def test_back_to_back_lessons_do_not_conflict() -> None:
    """ACA-8: a lesson that starts when the other ends is fine."""
    start = dt.datetime(2026, 10, 7, 4, 0, tzinfo=dt.UTC)
    existing = lesson(start, teacher=TEACHER)
    candidate = LessonSlot(
        new_id(),
        existing.ends_at,
        existing.ends_at + dt.timedelta(minutes=45),
        TEACHER,
        None,
        whole(GROUP_A),
    )

    assert lesson_conflicts(candidate, [existing]) == []


def test_cancelled_lessons_are_ignored() -> None:
    """ACA-8: a cancelled lesson frees its teacher and room."""
    start = dt.datetime(2026, 10, 7, 4, 0, tzinfo=dt.UTC)
    cancelled = lesson(start, teacher=TEACHER)
    cancelled.status = "cancelled"
    candidate = LessonSlot(
        new_id(), start, start + dt.timedelta(minutes=45), TEACHER, None, whole(GROUP_A)
    )

    assert lesson_conflicts(candidate, [cancelled]) == []
