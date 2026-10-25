"""Port: feedback items and their responses."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.feedback.domain.feedback import (
    Feedback,
    FeedbackArea,
    FeedbackKind,
    FeedbackResponse,
    FeedbackStatus,
)


@dataclass(frozen=True, slots=True)
class FeedbackFilter:
    """Optional filters of the administrators' list."""

    status: FeedbackStatus | None = None
    kind: FeedbackKind | None = None
    area: FeedbackArea | None = None


@dataclass(frozen=True, slots=True)
class PageAfter:
    """Keyset position: items strictly older than (created_at, id)."""

    created_at: datetime
    id: UUID


class FeedbackRepository(Protocol):
    """Feedback with ``response_count`` filled on every read."""

    async def add(self, item: Feedback) -> None:
        """Insert an item."""
        ...

    async def get(self, feedback_id: UUID) -> Feedback | None:
        """Return the item or None."""
        ...

    async def set_status(
        self, feedback_id: UUID, status: FeedbackStatus, now: datetime
    ) -> None:
        """Change the status."""
        ...

    async def list_for_reporter(self, reporter_id: UUID) -> list[Feedback]:
        """The reporter's items, newest first."""
        ...

    async def list_page(
        self, flt: FeedbackFilter, after: PageAfter | None, limit: int
    ) -> list[Feedback]:
        """Items matching the filter, newest first, after the position."""
        ...

    async def add_response(self, response: FeedbackResponse) -> None:
        """Insert a response."""
        ...

    async def responses(self, feedback_id: UUID) -> list[FeedbackResponse]:
        """Responses of an item, oldest first."""
        ...
