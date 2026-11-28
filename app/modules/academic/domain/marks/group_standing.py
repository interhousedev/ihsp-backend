"""Standings of students and groups for the "My group" page.

A student's GPA is the mean of their marks in the current term; attendance is
present / (present + absent) in percent, a late arrival counting as present. A
group's GPA is the mean of its members' GPAs; its attendance is the share over all
of its members' counted lessons. Equal values share a place (1, 1, 3); missing
values are unranked.
"""

import datetime as dt
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar
from uuid import UUID

Metric = Literal["gpa", "attendance"]
Scope = Literal["course", "lyceum"]
METRICS: tuple[Metric, ...] = ("gpa", "attendance")
SCOPES: tuple[Scope, ...] = ("course", "lyceum")

K = TypeVar("K", bound=Hashable)


@dataclass(frozen=True, slots=True)
class StudentStanding:
    """Term aggregates of one active student of an active group."""

    student_id: UUID
    group_id: UUID
    group_name: str
    course: int | None
    grade_sum: int
    grade_count: int
    present: int
    absent: int

    @property
    def gpa(self) -> float | None:
        """Mean mark, or None without marks."""
        return self.grade_sum / self.grade_count if self.grade_count else None

    @property
    def attendance(self) -> float | None:
        """Attendance percent, or None without counted lessons."""
        total = self.present + self.absent
        return 100 * self.present / total if total else None


@dataclass(frozen=True, slots=True)
class GroupStanding:
    """Aggregates of one group."""

    group_id: UUID
    group_name: str
    course: int | None
    members_count: int
    gpa: float | None
    attendance: float | None

    def value(self, metric: Metric) -> float | None:
        """The value of the metric."""
        return self.gpa if metric == "gpa" else self.attendance


def current_term(
    terms: Sequence[tuple[dt.date, dt.date]], today: dt.date
) -> tuple[dt.date, dt.date] | None:
    """The term containing today, else the latest started one, else the first."""
    for start, end in terms:
        if start <= today <= end:
            return start, end
    started = [t for t in terms if t[0] <= today]
    if started:
        return max(started)
    return min(terms) if terms else None


def places(values: Iterable[tuple[K, float | None]]) -> dict[K, int]:
    """Competition ranking, highest first; keys with None are left out."""
    ranked = sorted(
        ((k, round(v, 6)) for k, v in values if v is not None), key=lambda kv: -kv[1]
    )
    result: dict[K, int] = {}
    previous: float | None = None
    place = 0
    for position, (key, value) in enumerate(ranked, start=1):
        if value != previous:
            place, previous = position, value
        result[key] = place
    return result


def group_standings(students: Iterable[StudentStanding]) -> list[GroupStanding]:
    """Aggregate students per group."""
    by_group: dict[UUID, list[StudentStanding]] = {}
    for s in students:
        by_group.setdefault(s.group_id, []).append(s)
    groups = []
    for group_id, members in by_group.items():
        gpas = [g for g in (m.gpa for m in members) if g is not None]
        present = sum(m.present for m in members)
        total = present + sum(m.absent for m in members)
        first = members[0]
        groups.append(
            GroupStanding(
                group_id=group_id,
                group_name=first.group_name,
                course=first.course,
                members_count=len(members),
                gpa=sum(gpas) / len(gpas) if gpas else None,
                attendance=100 * present / total if total else None,
            )
        )
    return groups


def in_scope(
    groups: Iterable[GroupStanding], scope: Scope, course: int | None
) -> list[GroupStanding]:
    """The groups compared in the scope: the same course, or the whole lyceum."""
    if scope == "lyceum":
        return list(groups)
    return [g for g in groups if g.course == course]


def group_rankings(
    groups: Sequence[GroupStanding], metric: Metric
) -> list[tuple[int | None, GroupStanding]]:
    """Groups with their place, ranked first, then unranked by name."""
    ranks = places((g.group_id, g.value(metric)) for g in groups)

    def order(g: GroupStanding) -> tuple[int, str]:
        return ranks.get(g.group_id, len(groups) + 1), g.group_name.casefold()

    return [(ranks.get(g.group_id), g) for g in sorted(groups, key=order)]
