"""Port: storage of the review log."""

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.modules.flashcards.domain.review_log import ReviewLogEntry


class ReviewLogRepository(Protocol):
    """Every rating a student gave, newest data last."""

    async def add(self, entry: ReviewLogEntry) -> None:
        """Insert one log row."""
        ...

    async def daily_counts(
        self, user_id: UUID, *, set_id: UUID | None
    ) -> dict[date, int]:
        """Return reviews per Tashkent day; one set, or all of the user's sets."""
        ...

    async def duration_ms_between(
        self,
        user_id: UUID,
        *,
        set_id: UUID | None,
        start: datetime,
        end: datetime,
    ) -> int:
        """Return the time spent on cards reviewed in [start, end), in milliseconds."""
        ...
