"""Event report shown on the club timeline."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.activities.domain.errors import Conflict

__all__ = ["EventReport", "ReportStateError", "in_timeline"]


class ReportStateError(Conflict):
    """Only a finished event's report is published."""


@dataclass(slots=True)
class EventReport:
    """What happened at an event."""

    event_id: UUID
    attendance_count: int
    summary: str = ""
    media_file_ids: list[UUID] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    published: bool = False

    @classmethod
    def draft(cls, event: Any, checked_in_count: int) -> "EventReport":
        """Attendance comes from check-ins, never typed in."""
        return cls(event.id, checked_in_count)

    def publish(self, event: Any) -> None:
        """Publish once the event is done."""
        if str(event.status) != "done":
            raise ReportStateError()
        self.published = True


def in_timeline(event: Any, report: EventReport) -> bool:
    """Done events with a published report."""
    return str(event.status) == "done" and report.published
