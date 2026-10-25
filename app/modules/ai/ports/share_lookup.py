"""Port: does a chat have an active share link (answered by the links module)."""

from typing import Protocol
from uuid import UUID


class ChatShareLookup(Protocol):
    """Used for `ChatDetail.shared`."""

    async def is_shared(self, chat_id: UUID) -> bool:
        """Return True if the chat has a live share link."""
        ...
