"""Port: token counters of the session window and the day."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """An open usage session: tokens used and when it ends."""

    used: int
    ends_at: datetime


class BudgetStore(Protocol):
    """Counters in Redis (`ai:session:{user}` and `ai:day:{user}:{date}`)."""

    async def session(self, user_id: UUID) -> SessionWindow | None:
        """Return the open session window, if there is one."""
        ...

    async def open_session(self, user_id: UUID, ends_at: datetime) -> None:
        """Start a new window with zero tokens used; it expires at `ends_at`."""
        ...

    async def add_session(self, user_id: UUID, tokens: int) -> None:
        """Add tokens to the open window."""
        ...

    async def day_used(self, user_id: UUID, day: date) -> int:
        """Return the tokens used on a Tashkent day."""
        ...

    async def add_day(self, user_id: UUID, day: date, tokens: int) -> None:
        """Add tokens to a day's counter (kept for 48 hours)."""
        ...
