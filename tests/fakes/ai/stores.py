"""In-memory budget store, summary store and turn lock."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from uuid import UUID

from app.modules.ai.domain.errors import TurnInProgressError
from app.modules.ai.ports.budget_store import SessionWindow
from app.modules.ai.ports.summary_store import StoredSummary


class InMemoryBudgetStore:
    """BudgetStore without Redis."""

    def __init__(self) -> None:
        """Start empty."""
        self.windows: dict[UUID, SessionWindow] = {}
        self.days: dict[tuple[UUID, date], int] = {}

    async def session(self, user_id: UUID) -> SessionWindow | None:
        """Return the stored window (expiry is decided by the service)."""
        return self.windows.get(user_id)

    async def open_session(self, user_id: UUID, ends_at: datetime) -> None:
        """Start a window with zero tokens."""
        self.windows[user_id] = SessionWindow(used=0, ends_at=ends_at)

    async def add_session(self, user_id: UUID, tokens: int) -> None:
        """Add tokens to the window."""
        window = self.windows[user_id]
        self.windows[user_id] = SessionWindow(window.used + tokens, window.ends_at)

    async def day_used(self, user_id: UUID, day: date) -> int:
        """Return a day's tokens."""
        return self.days.get((user_id, day), 0)

    async def add_day(self, user_id: UUID, day: date, tokens: int) -> None:
        """Add tokens to a day."""
        self.days[(user_id, day)] = self.days.get((user_id, day), 0) + tokens


class InMemorySummaryStore:
    """SummaryStore without Redis."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: dict[UUID, StoredSummary] = {}

    async def get(self, chat_id: UUID) -> StoredSummary | None:
        """Return the summary."""
        return self.items.get(chat_id)

    async def put(self, chat_id: UUID, summary: StoredSummary) -> None:
        """Store the summary."""
        self.items[chat_id] = summary


class InMemoryTurnLock:
    """TurnLock for one process."""

    def __init__(self) -> None:
        """Start with no held locks."""
        self.held: set[UUID] = set()

    @asynccontextmanager
    async def hold(self, chat_id: UUID) -> AsyncIterator[None]:
        """Hold the lock or raise TurnInProgressError."""
        if chat_id in self.held:
            raise TurnInProgressError()
        self.held.add(chat_id)
        try:
            yield
        finally:
            self.held.discard(chat_id)


class NoTurnLock:
    """A lock that never blocks (to test the claim step on its own)."""

    @asynccontextmanager
    async def hold(self, chat_id: UUID) -> AsyncIterator[None]:
        """Do nothing."""
        yield


class InMemorySearchQuotaStore:
    """SearchQuotaStore without Redis."""

    def __init__(self) -> None:
        """Start empty."""
        self.days: dict[tuple[UUID, date], int] = {}

    async def used(self, user_id: UUID, day: date) -> int:
        """Return a day's searches."""
        return self.days.get((user_id, day), 0)

    async def add(self, user_id: UUID, day: date, units: int) -> int:
        """Count searches and return the total."""
        total = self.days.get((user_id, day), 0) + units
        self.days[(user_id, day)] = total
        return total

    async def remove(self, user_id: UUID, day: date, units: int) -> None:
        """Give searches back."""
        self.days[(user_id, day)] = max(self.days.get((user_id, day), 0) - units, 0)
