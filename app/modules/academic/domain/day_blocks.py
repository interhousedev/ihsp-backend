"""Non-lesson blocks of the school day: lunch, second lunch, a break, an assembly.

A block has a time of day, the weekdays it happens on (Monday 1 … Friday 5) and a
scope: the whole lyceum, one course (year of study), or a list of groups. Two blocks
with the same name may have different times on different days or for different
groups; each is its own row.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.shared.base_error import NotFoundError, ValidationFailedError

DayBlockKind = Literal["lunch", "second_lunch", "break", "assembly", "other"]
DayBlockScope = Literal["all", "course", "groups"]

DAY_BLOCK_KINDS: tuple[DayBlockKind, ...] = (
    "lunch",
    "second_lunch",
    "break",
    "assembly",
    "other",
)
DAY_BLOCK_SCOPES: tuple[DayBlockScope, ...] = ("all", "course", "groups")
SCHOOL_WEEKDAYS = frozenset({1, 2, 3, 4, 5})
NAME_MAX = 120


class DayBlockNotFoundError(NotFoundError):
    """The non-lesson block does not exist."""

    code = "academic/day-block-not-found"
    message_key = "academic-day-block-not-found"


class DayBlockInvalidError(ValidationFailedError):
    """The block's time, weekdays or scope do not fit together."""

    code = "academic/day-block-invalid"
    message_key = "academic-day-block-invalid"


@dataclass(slots=True)
class DayBlock:
    """One non-lesson block."""

    id: UUID
    name: str
    kind: DayBlockKind
    starts_at: dt.time
    ends_at: dt.time
    weekdays: list[int]
    scope: DayBlockScope
    course: int | None = None
    group_ids: list[UUID] = field(default_factory=list)

    def validate(self) -> None:
        """Raise DayBlockInvalidError for an impossible block; normalise the rest."""
        self.name = self.name.strip()
        days = sorted(set(self.weekdays))
        if (
            not self.name
            or len(self.name) > NAME_MAX
            or self.ends_at <= self.starts_at
            or not days
            or not set(days) <= SCHOOL_WEEKDAYS
        ):
            raise DayBlockInvalidError()
        if self.scope == "course" and (self.course is None or self.course < 1):
            raise DayBlockInvalidError()
        if self.scope == "groups" and not self.group_ids:
            raise DayBlockInvalidError()
        self.weekdays = days
        if self.scope != "course":
            self.course = None
        unique = list(dict.fromkeys(self.group_ids))
        self.group_ids = unique if self.scope == "groups" else []

    def applies(self, weekday: int, group_id: UUID, course: int | None) -> bool:
        """Whether the block is on this ISO weekday for a student of this group."""
        if weekday not in self.weekdays:
            return False
        if self.scope == "course":
            return course is not None and course == self.course
        if self.scope == "groups":
            return group_id in self.group_ids
        return True


@dataclass(frozen=True, slots=True)
class DayBlockOccurrence:
    """A block on one date (what the student's timetable shows)."""

    id: UUID
    date: dt.date
    name: str
    kind: DayBlockKind
    starts_at: dt.time
    ends_at: dt.time


def occurrences(
    blocks: list[DayBlock],
    start: dt.date,
    end: dt.date,
    group_id: UUID,
    course: int | None,
) -> list[DayBlockOccurrence]:
    """The blocks of a student's group on every date from start to end, in order."""
    found: list[DayBlockOccurrence] = []
    day = start
    while day <= end:
        for block in blocks:
            if block.applies(day.isoweekday(), group_id, course):
                found.append(
                    DayBlockOccurrence(
                        block.id,
                        day,
                        block.name,
                        block.kind,
                        block.starts_at,
                        block.ends_at,
                    )
                )
        day += dt.timedelta(days=1)
    found.sort(key=lambda item: (item.date, item.starts_at, item.name))
    return found
