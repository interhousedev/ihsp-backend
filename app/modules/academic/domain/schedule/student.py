"""Students of a group and their subgroup (ACA-2, ACA-3, ACA-19)."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

StudentStatus = Literal["active", "left"]
LEFT_REASONS = ("graduated", "expelled", "transferred", "other")
LEFT_REASON_ALIASES = {"institution": "transferred", "deleted": "other"}
CLOSING_GRACE_DAYS = 30


@dataclass(slots=True)
class Student:
    """The academic profile of a user; names live in the identity module."""

    user_id: UUID
    group_id: UUID
    subgroup: int | None = None
    subgroup_set_by: UUID | None = None
    subgroup_set_at: dt.datetime | None = None
    status: StudentStatus = "active"
    left_at: dt.date | None = None
    left_reason: str | None = None
    synced_at: dt.datetime | None = None

    def assign_subgroup(
        self, subgroup: int | None, *, by: UUID, now: dt.datetime
    ) -> None:
        """Set the subgroup and remember who did it."""
        self.subgroup = subgroup
        self.subgroup_set_by = by
        self.subgroup_set_at = now

    def move_to(self, group_id: UUID) -> None:
        """Move to another group; the new curator sets the subgroup (ACA-3)."""
        if group_id == self.group_id:
            return
        self.group_id = group_id
        self.subgroup = None
        self.subgroup_set_by = None
        self.subgroup_set_at = None

    def leave(self, *, today: dt.date, reason: str) -> None:
        """Mark the student as left with a reason from the allowed list."""
        self.status = "left"
        self.left_at = today
        self.left_reason = normalize_left_reason(reason)


def normalize_left_reason(reason: str) -> str:
    """Map a caller's reason onto the stored enum (unknown values become "other")."""
    mapped = LEFT_REASON_ALIASES.get(reason, reason)
    return mapped if mapped in LEFT_REASONS else "other"
