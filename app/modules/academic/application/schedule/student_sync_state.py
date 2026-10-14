"""The state of a student's full EMIS sync and the port that keeps it."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

SyncStatus = Literal["queued", "running", "done", "failed"]
SYNC_WINDOW_SECONDS = 600  # one sync per student every ten minutes


@dataclass(frozen=True, slots=True)
class SyncState:
    """Where the student's last sync is; ``detail`` is the timetable outcome."""

    status: SyncStatus
    requested_at: dt.datetime
    finished_at: dt.datetime | None = None
    detail: str | None = None


class SyncStateStore(Protocol):
    """Keeps the last sync of each student and the once-per-window claim."""

    async def get(self, user_id: UUID) -> SyncState | None:
        """Return the last sync, or None if there was none."""
        ...

    async def put(self, user_id: UUID, state: SyncState) -> None:
        """Replace the last sync."""
        ...

    async def claim(self, user_id: UUID, *, seconds: int) -> int | None:
        """Take the window; None when taken now, else the seconds still left."""
        ...
