"""Port: refresh a group's EMIS timetable (implemented by the schedule)."""

from typing import Protocol
from uuid import UUID


class TimetableOutcome(Protocol):
    """How a timetable sync ended."""

    @property
    def status(self) -> str:
        """One of the sync's statuses, e.g. synced or emis_unavailable."""
        ...


class TimetableSync(Protocol):
    """Reads a group's classes through one student's EMIS link and applies them."""

    async def execute(
        self, *, group_id: UUID, user_id: UUID, refresh_bells: bool = True
    ) -> TimetableOutcome:
        """Apply the timetable; EMIS errors come back as a status, not an exception."""
        ...
