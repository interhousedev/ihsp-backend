"""Port: stored summaries of long chats."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredSummary:
    """A summary of messages 1..upto_seq of a chat."""

    text: str
    upto_seq: int


class SummaryStore(Protocol):
    """Summaries in Redis (`ai:summary:{chat_id}`, 30 days)."""

    async def get(self, chat_id: UUID) -> StoredSummary | None:
        """Return the stored summary."""
        ...

    async def put(self, chat_id: UUID, summary: StoredSummary) -> None:
        """Store or replace the summary."""
        ...
