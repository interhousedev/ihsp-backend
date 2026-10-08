"""Typed view of ``ClassworkCommands.prompt_state`` (FINAL_PLAN § 3.6)."""

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any
from uuid import UUID

from app.shared.contracts.academic import LessonRef


@dataclass(frozen=True, slots=True)
class RosterItem:
    """One student of the lesson's audience."""

    position: int
    user_id: UUID
    name: str
    group_name: str
    subgroup_unset: bool
    absent: bool


@dataclass(frozen=True, slots=True)
class PromptState:
    """The end-of-lesson prompt as the server sees it."""

    lesson: LessonRef
    roster: tuple[RosterItem, ...]
    attendance_submitted: bool
    attendance_version: int
    homework_text: str | None
    expired: bool

    @property
    def absent_count(self) -> int:
        """Number of students marked absent."""
        return sum(1 for item in self.roster if item.absent)

    def minutes_left(self, now: datetime) -> int:
        """Whole minutes until the lesson ends (0 or less when it has ended)."""
        return ceil((self.lesson.ends_at - now).total_seconds() / 60)


def _roster_item(raw: dict[str, Any]) -> RosterItem:
    return RosterItem(
        position=int(raw["position"]),
        user_id=raw["user_id"],
        name=str(raw["name"]),
        group_name=str(raw.get("group_name", "")),
        subgroup_unset=bool(raw.get("subgroup_unset", False)),
        absent=bool(raw.get("absent", False)),
    )


def parse_prompt_state(raw: dict[str, Any]) -> PromptState:
    """Convert the dict returned by the classwork commands into a PromptState."""
    return PromptState(
        lesson=raw["lesson"],
        roster=tuple(_roster_item(item) for item in raw.get("roster", [])),
        attendance_submitted=bool(raw.get("attendance_submitted", False)),
        attendance_version=int(raw.get("attendance_version", 0)),
        homework_text=raw.get("homework_text"),
        expired=bool(raw.get("expired", False)),
    )
