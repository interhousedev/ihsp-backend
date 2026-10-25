"""Which lessons of a divided group a student sees, and whose subgroup each is.

A student sees whole-group lessons and their own subgroup's lessons. Where only
the other subgroup has a lesson in a slot (or theirs is another subject), they
see it too, marked as the other subgroup's. A student without a subgroup yet
matches both subgroups, so every lesson is their own.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.shared.contracts.academic import LessonRef


@dataclass(frozen=True, slots=True)
class SubgroupMark:
    """The subgroup a lesson is for, from the student's point of view."""

    subgroup_id: int
    subgroup_name: str
    is_own_subgroup: bool


def lesson_subgroups(audience: Sequence[str], group_id: UUID) -> set[int] | None:
    """Subgroups of the group a lesson is for; None for the whole group."""
    subs: set[int] = set()
    for key in audience:
        group, sub = audience_keys.parse(key)
        if group != group_id:
            continue
        if sub is None:
            return None
        subs.add(sub)
    return subs


def _mark(
    subs: set[int] | None, group_name: str, subgroup: int | None
) -> SubgroupMark | None:
    if not subs:
        return None  # the whole group (or a lesson of another group)
    own = subgroup is None or subgroup in subs
    shown = subgroup if subgroup is not None and subgroup in subs else min(subs)
    return SubgroupMark(shown, f"{group_name}/{shown}", own)


def place_lessons(
    lessons: Sequence[LessonRef],
    group_id: UUID,
    group_name: str,
    subgroup: int | None,
) -> list[tuple[LessonRef, SubgroupMark | None]]:
    """Return the lessons the student sees, each with its subgroup mark.

    `lessons` are all lessons of the group (both subgroups), in any order.
    """
    marked = [
        (ref, _mark(lesson_subgroups(ref.audience, group_id), group_name, subgroup))
        for ref in lessons
    ]
    own_slots: dict[tuple[dt.date, int], set[UUID]] = {}
    for ref, mark in marked:
        if mark is None or mark.is_own_subgroup:
            own_slots.setdefault((ref.date, ref.period), set()).add(ref.subject_id)
    return [
        (ref, mark)
        for ref, mark in marked
        if mark is None
        or mark.is_own_subgroup
        or ref.subject_id not in own_slots.get((ref.date, ref.period), set())
    ]
