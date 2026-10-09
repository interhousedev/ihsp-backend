"""Conflict detection for timetable entries and lessons (ACA-8)."""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.timetable_entry import (
    TimetableEntry,
    WeekParity,
)

ConflictKind = Literal["teacher", "room", "audience"]

_DESCRIPTIONS: dict[str, str] = {
    "teacher": "The teacher already has a lesson at this time.",
    "room": "The room is already used at this time.",
    "audience": "The group or subgroup already has a lesson at this time.",
}


@dataclass(frozen=True, slots=True)
class Conflict:
    """One clash between a candidate and an existing entry or lesson."""

    kind: ConflictKind
    with_entry_id: UUID | None
    with_lesson_id: UUID | None
    description: str
    # Which weeks the other entry runs in; None when it is a lesson.
    week_parity: WeekParity | None = None

    def to_json(self) -> dict[str, Any]:
        """Return the API shape of a Conflict."""
        return {
            "kind": self.kind,
            "with_entry_id": str(self.with_entry_id) if self.with_entry_id else None,
            "with_lesson_id": (
                str(self.with_lesson_id) if self.with_lesson_id else None
            ),
            "description": self.description,
            "week_parity": self.week_parity,
        }


def parities_overlap(first: str, second: str) -> bool:
    """Return True if two week parities can fall on the same week."""
    return first == "every" or second == "every" or first == second


def validity_overlaps(
    first_from: dt.date,
    first_to: dt.date | None,
    second_from: dt.date,
    second_to: dt.date | None,
) -> bool:
    """Return True if two inclusive date ranges (open end = None) intersect."""
    first_ends_before = first_to is not None and first_to < second_from
    second_ends_before = second_to is not None and second_to < first_from
    return not (first_ends_before or second_ends_before)


def audiences_overlap(first: Iterable[str], second: Iterable[str]) -> bool:
    """Return True if any key is shared, or a group key meets its subgroup key.

    Subgroup 1 and subgroup 2 of one group never overlap.
    """
    parsed_second = [audience_keys.parse(key) for key in second]
    for key in first:
        group, subgroup = audience_keys.parse(key)
        for other_group, other_subgroup in parsed_second:
            if group != other_group:
                continue
            if subgroup is None or other_subgroup is None or subgroup == other_subgroup:
                return True
    return False


def _kinds(
    *,
    same_teacher: bool,
    same_room: bool,
    shared_audience: bool,
) -> list[ConflictKind]:
    kinds: list[ConflictKind] = []
    if same_teacher:
        kinds.append("teacher")
    if same_room:
        kinds.append("room")
    if shared_audience:
        kinds.append("audience")
    return kinds


def entry_conflicts(
    candidate: TimetableEntry, others: Iterable[TimetableEntry]
) -> list[Conflict]:
    """Return the conflicts of the candidate with other entries of the same term."""
    found: list[Conflict] = []
    for other in others:
        if other.id == candidate.id or not _same_slot(candidate, other):
            continue
        kinds = _kinds(
            same_teacher=_same(candidate.teacher_id, other.teacher_id),
            same_room=_same(candidate.room_id, other.room_id),
            shared_audience=audiences_overlap(candidate.audience, other.audience),
        )
        found.extend(
            Conflict(kind, other.id, None, _DESCRIPTIONS[kind], other.week_parity)
            for kind in kinds
        )
    return found


def _same_slot(first: TimetableEntry, second: TimetableEntry) -> bool:
    return (
        first.term_id == second.term_id
        and first.weekday == second.weekday
        and first.period == second.period
        and parities_overlap(first.week_parity, second.week_parity)
        and validity_overlaps(
            first.valid_from, first.valid_to, second.valid_from, second.valid_to
        )
    )


def _same(first: UUID | None, second: UUID | None) -> bool:
    return first is not None and first == second


@dataclass(frozen=True, slots=True)
class LessonSlot:
    """The fields of a lesson that matter for conflicts."""

    id: UUID
    starts_at: dt.datetime
    ends_at: dt.datetime
    teacher_id: UUID | None
    room_id: UUID | None
    audience: Sequence[str]


def lesson_conflicts(candidate: LessonSlot, others: Iterable[Lesson]) -> list[Conflict]:
    """Return the conflicts of a lesson with other scheduled lessons in time."""
    found: list[Conflict] = []
    for other in others:
        if other.id == candidate.id or other.status != "scheduled":
            continue
        if not (
            candidate.starts_at < other.ends_at and other.starts_at < candidate.ends_at
        ):
            continue
        kinds = _kinds(
            same_teacher=_same(candidate.teacher_id, other.teacher_id),
            same_room=_same(candidate.room_id, other.room_id),
            shared_audience=audiences_overlap(candidate.audience, other.audience),
        )
        found.extend(
            Conflict(kind, other.timetable_entry_id, other.id, _DESCRIPTIONS[kind])
            for kind in kinds
        )
    return found
