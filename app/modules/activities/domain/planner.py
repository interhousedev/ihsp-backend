"""Club planner board."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

__all__ = ["PlannerItem", "PlannerStatus", "completion_ratio"]


class PlannerStatus(StrEnum):
    """Board columns."""

    BACKLOG = "backlog"
    PLANNED = "planned"
    DOING = "doing"
    DONE = "done"


@dataclass(slots=True)
class PlannerItem:
    """A task or idea on the board."""

    club_id: UUID
    kind: str
    title: str
    body: str
    assignee_id: UUID | None
    due_at: datetime | None
    status: PlannerStatus
    event_id: UUID | None
    term: str
    id: UUID = field(default_factory=uuid4)

    def move(self, status: PlannerStatus) -> None:
        """A finished item can only be reopened to `doing`."""
        if self.status == PlannerStatus.DONE and status != PlannerStatus.DOING:
            raise ValueError("a done item can only be reopened to doing")
        self.status = status


def completion_ratio(items: list[PlannerItem]) -> float:
    """Share of done items."""
    if not items:
        return 0.0
    return sum(i.status == PlannerStatus.DONE for i in items) / len(items)
